from datetime import datetime,timedelta
from urllib.parse import urlparse,parse_qs
from unittest.mock import Mock
import app as application
from app import app,db
from gamearena.models import User,UserSettings,Tournament,TournamentInterest,UserTournament,WalletTransaction
from test_interface_contracts import player,client,token


def post(viewer,path,data,source):
    return viewer.post(path,data=dict(data,csrf_token=token(viewer.get(source))))


def test_google_signup_and_login_use_same_verified_provider_identity(monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER','local');monkeypatch.setenv('GOOGLE_CLIENT_ID','public-test-client');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','test-only-secret')
    viewer=app.test_client();page=viewer.get('/register');assert 'Sign up with Google' in page.text
    assert viewer.post('/register/google',data={'accept_terms':'on'}).status_code==400
    assert post(viewer,'/register/google',{},'/register').location.endswith('/register')
    assert post(viewer,'/register/google',{'accept_terms':'on','date_of_birth':'1995-01-01'},'/register').location.endswith('/login/google')
    monkeypatch.setattr(application.requests,'post',lambda *a,**kw:Mock(ok=True,json=lambda:{'access_token':'synthetic-token'}))
    monkeypatch.setattr(application.requests,'get',lambda *a,**kw:Mock(ok=True,json=lambda:{'email':'google_new@example.test','verified_email':True,'name':'Google Player'}))
    for browser in (viewer,app.test_client()):
        redirect=browser.get('/login/google');assert urlparse(redirect.location).hostname=='accounts.google.com'
        query=parse_qs(urlparse(redirect.location).query);assert query['scope']==['openid email profile']
        response=browser.get('/auth/google/callback?code=synthetic&state='+query['state'][0]);assert response.status_code==302
        with browser.session_transaction() as session:assert session.get('_user_id')
    with app.app_context():assert User.query.count()==1 and User.query.one().email_verified


def test_google_signup_reuses_managed_provider_pkce(monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER','supabase');monkeypatch.setenv('SUPABASE_URL','https://preview.supabase.co');monkeypatch.setenv('SUPABASE_ANON_KEY','synthetic-public-key')
    viewer=app.test_client();assert post(viewer,'/register/google',{'accept_terms':'on','date_of_birth':'1995-01-01'},'/register').status_code==302
    response=viewer.get('/login/google');url=urlparse(response.location);query=parse_qs(url.query)
    assert url.hostname=='preview.supabase.co' and url.path=='/auth/v1/authorize'
    assert query['provider']==['google'] and query['code_challenge_method']==['s256']
    with viewer.session_transaction() as session:assert session['supabase_pkce_verifier']


def test_settings_categories_save_only_the_fields_in_that_category():
    with app.app_context():
        owner=player('hub_owner');viewer=client(owner);viewer.get('/settings')
        preferences=UserSettings.query.filter_by(user_id=owner.id).one();preferences.wallet_notifications=False;preferences.profile_public=False;preferences.preferred_games=['Free Fire'];db.session.commit()
        directory=viewer.get('/settings');assert directory.status_code==200 and '/settings/account' in directory.text
        assert 'name="username"' not in directory.text
        for section in ('account','notifications','privacy','gaming','appearance','language','data'):assert viewer.get('/settings/'+section).status_code==200
        assert viewer.get('/settings/unknown').status_code==404
        assert post(viewer,'/settings/account',{'username':'hub_updated','bio':'My profile'},'/settings/account').status_code==302
        db.session.refresh(owner);db.session.refresh(preferences)
        assert owner.username=='hub_updated' and owner.bio=='My profile' and not preferences.wallet_notifications and not preferences.profile_public and preferences.preferred_games==['Free Fire']
        assert post(viewer,'/settings/notifications',{'chat_notifications':'on'},'/settings/notifications').status_code==302
        db.session.refresh(preferences);assert preferences.chat_notifications and not preferences.wallet_notifications and not preferences.profile_public
        assert post(viewer,'/settings/appearance',{'theme':'light','larger_text':'on'},'/settings/appearance').status_code==302
        db.session.refresh(preferences);assert preferences.theme=='light' and preferences.larger_text and preferences.preferred_games==['Free Fire']
        assert 'name="username"' not in viewer.get('/settings/notifications').text


def test_free_waiting_list_is_idempotent_private_and_never_takes_entry_money():
    with app.app_context():
        owner=player('waiting_owner');other=player('waiting_other');viewer=client(owner);owner.wallet_balance=500;db.session.commit()
        event=Tournament(name='Waiting cup',game='eFootball',status='open',entry_fee=200,prize=1000,max_participants=4)
        db.session.add(event);db.session.commit();url=f'/join-tournament/{event.id}';action=f'/tournament/{event.id}/waiting-list'
        assert 'Join tournament' in viewer.get(f'/tournament/{event.id}').text
        page=viewer.get(url);assert page.status_code==200 and 'No GP is charged' in page.text
        assert viewer.post(action,data={'action':'join'}).status_code==400
        for _ in range(2):assert post(viewer,action,{'action':'join','user_id':other.id},url).status_code==302
        row=TournamentInterest.query.one();assert row.user_id==owner.id
        assert UserTournament.query.count()==WalletTransaction.query.count()==0
        db.session.refresh(owner);assert owner.wallet_balance==500
        assert 'You’re on the waiting list' in viewer.get(url).text
        assert post(client(other),action,{'action':'leave'},url).status_code==302
        assert TournamentInterest.query.count()==1
        assert post(viewer,action,{'action':'leave'},url).status_code==302 and TournamentInterest.query.count()==0
        event.match_time=datetime.utcnow()+timedelta(days=2);event.entry_fee=0;db.session.commit()
        assert post(viewer,action,{'action':'join'},url).location.endswith(url)
        assert UserTournament.query.count()==0
        event.status='finished';db.session.commit()
        assert post(viewer,action,{'action':'join'},'/profile').status_code==409
