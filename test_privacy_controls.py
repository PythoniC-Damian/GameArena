from datetime import datetime, timedelta
from urllib.parse import urlparse,parse_qs
from unittest.mock import Mock
import pytest
import app as application
from app import app,db
from gamearena.models import User,UserActivityDay,TournamentVisit,Tournament
from gamearena.privacy_controls import age_error,serializer,choices,POLICY,purge_usage
from test_interface_contracts import player,client,token
from test_signup_settings_waiting import post


def test_birth_date_boundaries_and_email_signup(monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER','local')
    monkeypatch.setattr(application,'send_verification_code',lambda user:True)
    assert age_error('not-a-date') and age_error(datetime.utcnow().date().isoformat())
    assert age_error('1900-01-01') and age_error('2099-01-01')
    assert age_error('1990-01-01') is None
    browser=app.test_client()
    fields=dict(username='adult_signup',email='adult_signup@example.com',password='a-long-test-password',accept_terms='y')
    assert 'date_of_birth' in post(browser,'/register',dict(fields,date_of_birth='2018-01-01'),'/register').text
    with app.app_context(): assert User.query.count()==0
    response=post(browser,'/register',dict(fields,date_of_birth='1990-01-01'),'/register')
    assert response.status_code==302
    with app.app_context():
        user=User.query.one();assert user.adult_confirmed_at and user.adult_policy_version==POLICY
        assert not hasattr(user,'date_of_birth')


def test_existing_accounts_gate_including_admin_and_keep_support_export(monkeypatch):
    monkeypatch.setitem(app.config,'ADULT_ACCESS_REQUIRED',True)
    with app.app_context():
        owner=player('adult_gate');owner.is_admin=True;db.session.commit();browser=client(owner)
        assert browser.get('/dashboard').location.endswith('/account/eligibility')
        assert browser.post('/wallet/initialize-deposit',json={'amount':200},headers={'X-CSRFToken':token(browser.get('/account/eligibility'))}).status_code==403
        for path in ('/support','/privacy','/privacy/choices','/account/export','/settings/data'):
            assert browser.get(path).status_code==200,path
        assert 'adults' in browser.get('/account/eligibility').text.lower()
        response=post(browser,'/account/eligibility',{'date_of_birth':'2018-01-01','adult_confirm':'yes'},'/account/eligibility')
        assert '18 and over' in response.text
        db.session.refresh(owner);assert owner.adult_confirmed_at is None
        assert post(browser,'/account/eligibility',{'date_of_birth':'1990-01-01','adult_confirm':'yes'},'/account/eligibility').status_code==302
        db.session.refresh(owner);assert owner.adult_confirmed_at and browser.get('/dashboard').status_code==200
        from gamearena.account_security import socket_identity_allowed
        with app.test_request_context():
            from flask_login import login_user
            login_user(owner);assert socket_identity_allowed()
            owner.adult_confirmed_at=None;assert not socket_identity_allowed()


def test_google_and_managed_new_accounts_cannot_bypass_age_signup(monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER','local');monkeypatch.setenv('GOOGLE_CLIENT_ID','synthetic-client');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','synthetic-secret')
    monkeypatch.setattr(application.requests,'post',lambda *a,**k:Mock(ok=True,json=lambda:{'access_token':'synthetic'}))
    monkeypatch.setattr(application.requests,'get',lambda *a,**k:Mock(ok=True,json=lambda:{'email':'agegoogle@example.com','verified_email':True,'name':'Adult Google'}))
    browser=app.test_client()
    state=parse_qs(urlparse(browser.get('/login/google').location).query)['state'][0]
    assert browser.get('/auth/google/callback?code=x&state='+state).location.endswith('/register')
    with app.app_context():assert User.query.count()==0
    assert post(browser,'/register/google',{'accept_terms':'on','date_of_birth':'2018-01-01'},'/register').location.endswith('/register')
    assert post(browser,'/register/google',{'accept_terms':'on','date_of_birth':'1990-01-01'},'/register').location.endswith('/login/google')
    state=parse_qs(urlparse(browser.get('/login/google').location).query)['state'][0]
    browser.get('/auth/google/callback?code=x&state='+state)
    with app.app_context():assert User.query.one().adult_confirmed_at
    with app.test_request_context():
        managed_auth = application.managed_auth
        with pytest.raises(managed_auth.AuthError):
            application.managed_identity({'id':'synthetic-identity','email':'other@example.com','email_confirmed_at':'2026-10-27'})


def test_optional_tracking_requires_consent_and_withdrawal_removes_only_own_visits():
    with app.app_context():
        owner=player('consent_owner');other=player('consent_other');browser=client(owner)
        event=Tournament(name='Privacy cup',game='eFootball',status='open',entry_fee=0,prize=0,max_participants=4)
        db.session.add(event);db.session.commit();url=f'/tournament/{event.id}'
        browser.get(url,headers={'Accept':'text/html'})
        assert UserActivityDay.query.count()==TournamentVisit.query.count()==0
        assert browser.post('/privacy/choices',json={'choice':'accept'}).status_code==400
        cookie=serializer().dumps({'version':POLICY,'analytics':True})
        browser.set_cookie('ga_privacy',cookie+'tampered');browser.get(url,headers={'Accept':'text/html'})
        assert UserActivityDay.query.count()==TournamentVisit.query.count()==0
        response=post(browser,'/privacy/choices',{'choice':'accept'},'/privacy/choices')
        assert response.status_code==302 and 'HttpOnly' in response.headers['Set-Cookie'] and 'SameSite=Lax' in response.headers['Set-Cookie']
        browser.get(url,headers={'Accept':'text/html'})
        assert UserActivityDay.query.count()==TournamentVisit.query.count()==1
        db.session.add(TournamentVisit(user_id=other.id,tournament_id=event.id));db.session.commit()
        post(browser,'/privacy/choices',{'choice':'reject'},'/privacy/choices')
        browser.get(url,headers={'Accept':'text/html'})
        assert UserActivityDay.query.count()==0 and TournamentVisit.query.one().user_id==other.id
        db.session.refresh(owner);assert owner.wallet_balance==0
        assert post(browser,'/privacy/choices',{'choice':'invalid'},'/privacy/choices').status_code==400


def test_ninety_day_usage_retention_and_operator_disclosure():
    with app.app_context():
        owner=player('retention_owner');event=Tournament(name='Retention cup',game='eFootball',status='open')
        db.session.add(event);db.session.commit();now=datetime.utcnow()
        db.session.add_all([UserActivityDay(user_id=owner.id,activity_date=(now-timedelta(days=100)).date()),TournamentVisit(user_id=owner.id,tournament_id=event.id,viewed_at=now-timedelta(days=100))]);db.session.commit()
        purge_usage(now-timedelta(days=90));db.session.expire_all()
        assert UserActivityDay.query.count()==TournamentVisit.query.count()==0 and User.query.count()==1 and Tournament.query.count()==1
        page=app.test_client().get('/privacy').text
        assert 'GAMERENA NEXUS TECHNOLOGIES LTD' in page and 'wegamearena@gmail.com' in page and 'jegzdami@gmail.com' in page
        assert '90 days' in page and 'Cookie choices' in page
