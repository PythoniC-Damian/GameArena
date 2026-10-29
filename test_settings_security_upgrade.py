import re,time
from datetime import datetime,timedelta
from unittest.mock import Mock
import pytest
import app as application
from app import app,db
from gamearena.models import User,AccountSecurity,EmailLoginChallenge,UserSettings,UserBlock,Notification,RateLimitBucket
from gamearena.i18n import LANGUAGES,CATALOGS
from test_interface_contracts import player,client,token
from test_signup_settings_waiting import post


def fresh_browser(user):
    user.set_password('a-long-testing-password');db.session.commit()
    viewer=client(user)
    with viewer.session_transaction() as session:
        session['auth_session_version']=user.auth_session_version
        session['security_primary_uid']=user.id;session['security_primary_at']=time.time()
    return viewer


def mail_capture(monkeypatch,accepted=True):
    codes=[]
    def send(subject,recipient,body):
        codes.append(re.search(r'\b[0-9]{8}\b',body)[0]);return accepted
    monkeypatch.setattr(application,'send_email',send)
    monkeypatch.setenv('AUTH_PROVIDER','local')
    return codes


def start_setting(viewer,action):
    start=post(viewer,'/account/two-step',{'action':action},'/settings/privacy')
    assert '/security/reauthenticate' in start.location
    result=post(viewer,start.location,{'password':'a-long-testing-password'},start.location)
    assert result.location.endswith('/account/two-step')
    return viewer.get(result.location)


def enroll(user,viewer,codes):
    start=start_setting(viewer,'enable')
    assert start.location.endswith('/account/two-step/challenge')
    row=EmailLoginChallenge.query.one()
    assert row.code_hash!=codes[-1] and len(row.code_hash)==64 and row.purpose=='enable'
    assert db.session.get(AccountSecurity,user.id).email_enabled_at is None
    result=post(viewer,'/account/two-step/challenge',{'code':codes[-1]},'/account/two-step/challenge')
    assert result.location.endswith('/settings/privacy')
    db.session.expire_all()
    assert db.session.get(AccountSecurity,user.id).email_enabled_at


def test_languages_are_searchable_persisted_and_only_completed_catalogs_are_selectable():
    with app.app_context():
        user=player('language_list');viewer=client(user)
        page=viewer.get('/settings/language')
        assert 'ga-language-row' in page.text and 'data-language-search' in page.text
        assert set(LANGUAGES)=={'en','es','fr','pt'}
        assert 'value="ar"' not in page.text
        for code,catalog in CATALOGS.items():
            for key in ('Two-step verification','Private chat notifications','Group and community notifications','Search languages'):
                assert catalog[key] and catalog[key]!=key,(code,key)
        assert post(viewer,'/language',{'language':'es','next':'/settings/privacy'},'/settings/language').status_code==302
        db.session.expire_all();assert UserSettings.query.filter_by(user_id=user.id).one().language=='es'
        assert 'Verificación en dos pasos' in viewer.get('/settings/privacy').text
        assert post(viewer,'/language',{'language':'ar'},'/settings/language').status_code==400
        assert post(app.test_client(),'/language',{'language':'fr','next':'//bad.example'},'/languages').location=='/'


def test_private_and_group_alerts_are_independent_and_worker_rechecks(monkeypatch):
    with app.app_context():
        user=player('split_alerts');viewer=client(user)
        data={'chat_controls':'split','group_chat_notifications':'on','wallet_notifications':'on'}
        assert post(viewer,'/settings/notifications',data,'/settings/notifications').status_code==302
        pref=UserSettings.query.filter_by(user_id=user.id).one()
        assert pref.group_chat_notifications and not pref.private_chat_notifications and pref.chat_notifications
        application.create_and_emit_notification(user.id,'Private alert','chat','/messages/2')
        application.create_and_emit_notification(user.id,'Group alert','chat','/chat#message-1')
        assert Notification.query.count()==1
        record=Notification.query.one();assert record.message=='Group alert'
        from gamearena.workers import deliver_notification_push
        import web_push
        deliver=Mock();monkeypatch.setattr(web_push,'deliver_push',deliver)
        pref.group_chat_notifications=False;pref.chat_notifications=False;db.session.commit()
        deliver_notification_push(record.id);deliver.assert_not_called()
        page=viewer.get('/settings/notifications').text
        assert page.count('role="switch"')==6 and 'chat_controls' in page


def test_blocked_users_count_list_and_unblock_controls_are_visible():
    with app.app_context():
        user=player('block_owner');other=player('blocked_person')
        db.session.add(UserBlock(blocker_id=user.id,blocked_id=other.id));db.session.commit()
        viewer=client(user);page=viewer.get('/settings/privacy')
        assert 'Blocked users' in page.text and 'blocked_person' in page.text and 'Unblock' in page.text
        assert f'form="unblock-{other.id}"' in page.text
        assert page.text.count('role="switch"')==3


def test_email_enable_login_single_use_and_disable(monkeypatch):
    codes=mail_capture(monkeypatch)
    with app.app_context():
        user=player('email_factor');user.email='email_factor@example.com';user.set_password('a-long-testing-password');db.session.commit()
        old=client(user);viewer=fresh_browser(user);enroll(user,viewer,codes)
        assert old.get('/settings').status_code==302
        login=app.test_client()
        response=post(login,'/login',{'email':user.email,'password':'a-long-testing-password'},'/login')
        assert response.location.endswith('/account/two-step/challenge')
        with login.session_transaction() as session:assert '_user_id' not in session
        assert login.get('/settings').location.startswith('/login')
        login_code=codes[-1]
        challenge=EmailLoginChallenge.query.filter_by(purpose='login').one()
        assert post(login,'/account/two-step/challenge',{'code':login_code},'/account/two-step/challenge').status_code==302
        with login.session_transaction() as session:assert session['_user_id']==str(user.id)
        db.session.refresh(challenge);assert challenge.used_at
        assert login.get('/account/two-step/challenge').location.endswith('/login')
        response=start_setting(login,'disable')
        assert response.location.endswith('/account/two-step/challenge')
        assert db.session.get(AccountSecurity,user.id).email_enabled_at
        post(login,'/account/two-step/challenge',{'code':codes[-1]},'/account/two-step/challenge')
        db.session.expire_all();assert db.session.get(AccountSecurity,user.id).email_enabled_at is None
        assert viewer.get('/settings').status_code==302


@pytest.mark.parametrize('failure',['expired','attempts','password_changed'])
def test_email_codes_reject_expiry_attempt_limit_and_stale_primary(monkeypatch,failure):
    codes=mail_capture(monkeypatch)
    with app.app_context():
        user=player('email_reject');viewer=fresh_browser(user)
        start_setting(viewer,'enable')
        challenge=EmailLoginChallenge.query.one()
        if failure=='expired':challenge.expires_at=datetime.utcnow()-timedelta(seconds=1)
        elif failure=='attempts':challenge.attempts=5
        else:user.auth_session_version+=1
        db.session.commit()
        response=post(viewer,'/account/two-step/challenge',{'code':codes[-1]},'/account/two-step/challenge') if failure!='password_changed' else viewer.get('/account/two-step/challenge')
        db.session.expire_all();assert db.session.get(AccountSecurity,user.id).email_enabled_at is None
        if failure=='password_changed':assert response.status_code in {302,403}
        else:assert 'invalid, expired or already used' in response.text


def test_failed_email_delivery_and_missing_csrf_never_enable_or_login(monkeypatch):
    codes=mail_capture(monkeypatch,accepted=False)
    with app.app_context():
        user=player('email_failure');user.email='email_failure@example.com';user.set_password('a-long-testing-password');db.session.commit()
        viewer=fresh_browser(user)
        assert viewer.post('/account/two-step',data={'action':'enable'}).status_code==400
        response=start_setting(viewer,'enable')
        response=viewer.get(response.location)
        assert 'could not send the code' in response.text and db.session.get(AccountSecurity,user.id).email_enabled_at is None
        db.session.get(AccountSecurity,user.id).email_enabled_at=datetime.utcnow();db.session.commit()
        login=app.test_client();post(login,'/login',{'email':user.email,'password':'a-long-testing-password'},'/login')
        with login.session_transaction() as session:assert '_user_id' not in session
        assert EmailLoginChallenge.query.filter_by(used_at=None).count()==0


@pytest.mark.parametrize('provider',['google','supabase'])
def test_oauth_callbacks_require_email_step_before_authentication(monkeypatch,provider):
    from urllib.parse import parse_qs,urlparse
    from gamearena.services import auth
    codes=mail_capture(monkeypatch)
    with app.app_context():
        user=player('oauth_factor');user.email='oauth_factor@example.com';db.session.commit()
        viewer=fresh_browser(user);enroll(user,viewer,codes)
        browser=app.test_client()
        if provider=='google':
            monkeypatch.setenv('GOOGLE_CLIENT_ID','synthetic-client');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','synthetic-secret')
            monkeypatch.setattr(application.requests,'post',lambda *a,**kw:Mock(ok=True,json=lambda:{'access_token':'synthetic-token'}))
            monkeypatch.setattr(application.requests,'get',lambda *a,**kw:Mock(ok=True,json=lambda:{'email':user.email,'verified_email':True}))
            query=parse_qs(urlparse(browser.get('/login/google').location).query)
            response=browser.get('/auth/google/callback?code=synthetic&state='+query['state'][0])
        else:
            monkeypatch.setenv('AUTH_PROVIDER','supabase');monkeypatch.setenv('SUPABASE_URL','https://preview.supabase.co');monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','synthetic-key')
            monkeypatch.setattr(auth,'call',Mock(return_value={'user':{'id':'00000000-0000-0000-0000-000000000001','email':user.email,'email_confirmed_at':'2026-10-29T00:00:00Z'}}))
            browser.get('/login/google')
            response=browser.get('/auth/supabase/callback?code=synthetic')
        assert response.location.endswith('/account/two-step/challenge')
        with browser.session_transaction() as state:assert '_user_id' not in state
        assert post(browser,'/account/two-step/challenge',{'code':codes[-1]},'/account/two-step/challenge').location.endswith('/dashboard')
        with browser.session_transaction() as state:assert state['_user_id']==str(user.id)


def test_toggle_requires_password_before_sending_code_even_after_recent_login(monkeypatch):
    codes=mail_capture(monkeypatch)
    with app.app_context():
        user=player('password_first');viewer=fresh_browser(user)
        response=post(viewer,'/account/two-step',{'action':'enable'},'/settings/privacy')
        assert '/security/reauthenticate' in response.location and not codes
        password_url=response.location
        assert viewer.get('/account/two-step').location==password_url
        wrong=post(viewer,password_url,{'password':'incorrect'},password_url)
        assert wrong.status_code==200 and not codes and EmailLoginChallenge.query.count()==0
        accepted=post(viewer,password_url,{'password':'a-long-testing-password'},password_url)
        assert viewer.get(accepted.location).location.endswith('/account/two-step/challenge')
        assert len(codes)==1 and not db.session.get(AccountSecurity,user.id).email_enabled_at


def test_signup_has_one_age_consent_step_and_distinct_email_steps():
    page=app.test_client().get('/register').text
    assert page.count('name="date_of_birth"')==1 and page.count('name="accept_terms"')==1
    assert page.count('<fieldset data-signup-step>')==3
    assert 'data-google-signup' in page and 'data-signup-next' in page


def test_google_only_account_can_reconfirm_provider_before_setup_code(monkeypatch):
    from urllib.parse import parse_qs,urlparse
    codes=mail_capture(monkeypatch)
    with app.app_context():
        user=player('google_setup');browser=client(user)
        post(browser,'/account/two-step',{'action':'enable'},'/settings/privacy')
        again='/security/sign-in-again?next=/account/two-step'
        post(browser,again,{},'/security/reauthenticate')
        monkeypatch.setenv('GOOGLE_CLIENT_ID','synthetic-client');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','synthetic-secret')
        monkeypatch.setattr(application.requests,'post',lambda *a,**kw:Mock(ok=True,json=lambda:{'access_token':'synthetic-token'}))
        monkeypatch.setattr(application.requests,'get',lambda *a,**kw:Mock(ok=True,json=lambda:{'email':user.email,'verified_email':True}))
        query=parse_qs(urlparse(browser.get('/login/google').location).query)
        response=browser.get('/auth/google/callback?code=synthetic&state='+query['state'][0])
        assert response.location.endswith('/account/two-step') and not codes
        assert browser.get(response.location).location.endswith('/account/two-step/challenge')
        assert len(codes)==1 and not db.session.get(AccountSecurity,user.id).email_enabled_at
