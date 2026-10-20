"""Exercise MFA, origin bypass, fresh sign-in, redacted auditing and strict scripts."""
import re
import time
from datetime import datetime
from unittest.mock import Mock
import pytest
import app as application
from app import app, db, socketio
from gamearena import account_security as security
from gamearena.models import AccountSecurity, SecurityAuditEvent, WalletTransaction
from test_interface_contracts import player,client,token


def account(name,admin=False):
    user=player(name);user.is_admin=admin;user.set_password('Correct test-only password!');db.session.commit()
    browser=client(user)
    with browser.session_transaction() as session:
        session['security_primary_at']=time.time();session['security_primary_uid']=user.id
    return user,browser


def post(browser,path,data=None):
    return browser.post(path,data=dict(data or {},csrf_token=token(browser.get('/security/reauthenticate'))))


def enroll(browser,user):
    page=browser.get('/security/enroll');assert page.status_code==200
    row=db.session.get(AccountSecurity,user.id)
    secret=security.cipher().decrypt(row.pending_secret.encode()).decode()
    response=post(browser,'/security/enroll',{'code':security.totp(secret,int(time.time())//30)})
    assert response.status_code==200 and 'shown once' in response.text
    codes=re.findall(r'<code[^>]*>([a-f0-9]{32})</code>',response.text)
    assert len(codes)==10
    return secret,codes


def test_rfc_totp_vectors_and_replay_window():
    secret='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'  # gitleaks:allow -- public RFC 6238 test vector
    assert security.totp(secret,1)=='287082'
    assert security.totp(secret,37037036)=='081804'


def test_admin_enrollment_encrypted_recovery_single_use_and_gate(monkeypatch):
    monkeypatch.setitem(app.config,'SECURITY_ENFORCE_ADMIN_MFA',True)
    with app.app_context():
        user,browser=account('mfa_owner',True)
        assert '/security/enroll' in browser.get('/admin').location
        assert '/security/enroll' in browser.get('/admin/security-events').location
        secret,codes=enroll(browser,user)
        row=db.session.get(AccountSecurity,user.id)
        assert row.totp_secret!=secret and secret not in row.totp_secret
        assert all(code not in str(row.recovery_hashes) for code in codes)
        assert browser.get('/admin').status_code==200
        with browser.session_transaction() as session:session.pop('security_mfa_at',None)
        assert '/security/challenge' in browser.get('/admin').location
        assert post(browser,'/security/challenge',{'code':codes[0]}).status_code==302
        assert len(db.session.get(AccountSecurity,user.id).recovery_hashes)==9
        with browser.session_transaction() as session:session.pop('security_mfa_at',None)
        response=post(browser,'/security/challenge',{'code':codes[0]})
        assert response.status_code==200 and 'already used' in response.text
        assert '/security/challenge' in browser.get('/admin').location


def test_totp_replay_and_wrong_account_recovery_rejected():
    with app.app_context():
        user,browser=account('factor_owner');secret,codes=enroll(browser,user)
        other,outsider=account('factor_other');enroll(outsider,other)
        response=post(browser,'/security/challenge',{'code':security.totp(secret,db.session.get(AccountSecurity,user.id).last_counter)})
        assert 'already used' in response.text
        response=post(outsider,'/security/challenge',{'code':codes[0]})
        assert 'invalid' in response.text


def test_sensitive_withdrawal_needs_fresh_password_without_debit(monkeypatch):
    monkeypatch.setitem(app.config,'SECURITY_REQUIRE_STEP_UP',True)
    with app.app_context():
        user,browser=account('fresh_wallet');user.wallet_balance=1000;db.session.commit()
        with browser.session_transaction() as session:session['security_primary_at']=time.time()-601
        response=browser.post('/wallet/withdraw',json={'amount':300},headers={'X-CSRFToken':token(browser.get('/wallet'))})
        assert response.status_code==403 and response.json['code']=='reauthentication_required'
        assert response.json['security_url'].startswith('/security/reauthenticate')
        db.session.refresh(user);assert user.wallet_balance==1000 and WalletTransaction.query.count()==0
        assert post(browser,'/security/reauthenticate',{'password':'incorrect'}).status_code==200
        assert post(browser,'/security/reauthenticate',{'password':'Correct test-only password!'}).status_code==302
        with browser.session_transaction() as session:assert session['security_primary_uid']==user.id


def test_optional_player_mfa_protects_new_http_and_socket_sessions():
    with app.app_context():
        user,browser=account('player_mfa');_,codes=enroll(browser,user)
        with browser.session_transaction() as session:session.pop('security_mfa_at',None)
        assert '/security/challenge' in browser.get('/wallet').location
        connection=socketio.test_client(app,flask_test_client=browser)
        assert not connection.is_connected()
        assert post(browser,'/security/challenge',{'code':codes[0]}).status_code==302
        assert browser.get('/wallet').status_code==200


def test_mfa_setup_requires_recent_primary_and_cannot_disable_admin_policy(monkeypatch):
    monkeypatch.setitem(app.config,'SECURITY_ENFORCE_ADMIN_MFA',True)
    with app.app_context():
        user,browser=account('setup_recent',True)
        with browser.session_transaction() as session:session.pop('security_primary_at',None)
        assert '/security/reauthenticate' in browser.get('/security/enroll').location
        assert db.session.get(AccountSecurity,user.id) is None
        assert browser.post('/security/enroll',data={'code':'000000'}).status_code==400


def test_origin_gate_covers_http_socket_and_webhook_without_disabling_health(monkeypatch):
    monkeypatch.setitem(app.config,'ORIGIN_PROTECTION_ENABLED',True)
    monkeypatch.setitem(app.config,'ORIGIN_SHARED_SECRET','owner-test-only-origin-secret-32-chars')
    browser=app.test_client();headers={'X-GameArena-Origin':app.config['ORIGIN_SHARED_SECRET']}
    for path in ('/','/login','/socket.io/?EIO=4&transport=polling','/paystack/webhook'):
        assert browser.get(path).status_code==403
    assert browser.get('/health').status_code==200
    assert browser.post('/health').status_code==403
    assert browser.get('/login',headers=headers).status_code==200
    assert browser.get('/login',headers={'X-GameArena-Origin':'é'}).status_code==403
    assert browser.get('/login',base_url='https://attacker.invalid',headers=headers).status_code==400


def test_untrusted_proxy_headers_cannot_bypass_ip_limits(monkeypatch):
    with app.test_request_context('/login',headers={'CF-Connecting-IP':'192.0.2.44'}):
        monkeypatch.setitem(app.config,'ORIGIN_PROTECTION_ENABLED',False)
        assert application.client_rate_limit_key()!='192.0.2.44'
        monkeypatch.setitem(app.config,'ORIGIN_PROTECTION_ENABLED',True)
        assert application.client_rate_limit_key()=='192.0.2.44'


def test_csp_nonce_matches_scripts_changes_per_request_and_no_inline_wallet_handlers():
    with app.app_context():
        user,browser=account('nonce_owner')
        page=browser.get('/wallet')
        csp=page.headers['Content-Security-Policy']
        assert "script-src 'self' 'nonce-" in csp
        assert "'unsafe-inline'" not in csp.split('script-src ')[1].split(';')[0]
        nonce=re.search(r"'nonce-([^']+)'",csp).group(1)
        assert nonce and all(value==nonce for value in re.findall(r'<script[^>]*nonce="([^"]+)"',page.text))
        assert 'onclick=' not in page.text and 'data-wallet-action="withdraw"' in page.text
        assert nonce not in browser.get('/wallet').headers['Content-Security-Policy']


def test_audit_has_action_metadata_but_not_body_or_codes():
    with app.app_context():
        user,browser=account('audit_admin',True)
        response=post(browser,'/support',{'reason':'PRIVATE_BANK_DETAIL_DO_NOT_LOG'})
        assert response.status_code==302
        rows=SecurityAuditEvent.query.filter_by(actor_id=user.id).all()
        assert any(row.event=='admin.action' and row.endpoint=='support' for row in rows)
        assert 'PRIVATE_BANK_DETAIL_DO_NOT_LOG' not in str([row.__dict__ for row in rows])
        assert browser.get('/admin/security-events').status_code==200
        other,outside=account('audit_other')
        assert outside.get('/admin/security-events').status_code==403


def test_emergency_withdrawal_pause_does_not_call_provider_or_debit(monkeypatch):
    monkeypatch.setitem(app.config,'WITHDRAWALS_ENABLED',False)
    call=Mock(side_effect=AssertionError('Provider must not be called'))
    monkeypatch.setattr(application,'paystack_transfer_request',call)
    with app.app_context():
        user,browser=account('pause_wallet');user.wallet_balance=1000;db.session.commit()
        response=browser.post('/wallet/withdraw',json={'amount':300},headers={'X-CSRFToken':token(browser.get('/wallet'))})
        assert response.status_code==503 and 'paused' in response.json['message']
        db.session.refresh(user);assert user.wallet_balance==1000 and WalletTransaction.query.count()==0
        assert not call.called


def test_socket_admin_cannot_connect_without_mfa(monkeypatch):
    monkeypatch.setitem(app.config,'SECURITY_ENFORCE_ADMIN_MFA',True)
    with app.app_context():user,browser=account('socket_mfa_admin',True)
    connection=socketio.test_client(app,flask_test_client=browser)
    assert not connection.is_connected()


def test_real_primary_login_stamps_session_and_discards_prior_factor():
    with app.app_context():
        user,_=account('primary_signal');user.email='primary_signal@example.com';db.session.commit();browser=app.test_client()
        response=browser.post('/login',data={'email':user.email,'password':'Correct test-only password!',
            'csrf_token':token(browser.get('/login'))})
        assert response.status_code==302
        with browser.session_transaction() as session:
            assert session['security_primary_uid']==user.id and 'security_mfa_at' not in session


def test_recovery_replacement_revokes_other_factor_sessions():
    with app.app_context():
        user,browser=account('replace_codes');secret,codes=enroll(browser,user)
        row=db.session.get(AccountSecurity,user.id);version=row.version
        response=post(browser,'/security/recovery-codes')
        assert response.status_code==200
        db.session.refresh(row);assert row.version==version+1 and len(row.recovery_hashes)==10
        assert security.recovery_hash(codes[0]) not in row.recovery_hashes
        assert 'shown once' in response.text


def test_missing_factor_key_fails_closed_without_disabling_protection(monkeypatch):
    from cryptography.fernet import Fernet
    with app.app_context():
        user,browser=account('wrong_mfa_key');_,codes=enroll(browser,user)
        monkeypatch.setitem(app.config,'SECURITY_ENCRYPTION_KEY',Fernet.generate_key())
        response=post(browser,'/security/challenge',{'code':codes[0]})
        assert response.status_code==503
        assert db.session.get(AccountSecurity,user.id).enabled_at


def test_managed_reauthentication_requires_matching_identity_and_closes_session(monkeypatch):
    from gamearena.services import auth as managed
    monkeypatch.setattr(managed,'enabled',lambda:True)
    with app.app_context():
        user,browser=account('managed_reauth');user.supabase_auth_id='synthetic-managed-id';db.session.commit()
        with browser.session_transaction() as session:session['auth_provider']='supabase'
        identity={'user':{'id':user.supabase_auth_id},'access_token':'synthetic-token'}
        monkeypatch.setattr(managed,'signin',lambda *args:identity)
        close=Mock();monkeypatch.setattr(managed,'close_session',close)
        assert post(browser,'/security/reauthenticate',{'password':'synthetic password'}).status_code==302
        close.assert_called_once_with(identity)
        monkeypatch.setattr(managed,'signin',lambda *args:{'user':{'id':'other-user'}})
        assert post(browser,'/security/reauthenticate',{'password':'synthetic password'}).status_code==200


def test_security_alert_email_is_optional_redacted_and_bounded(monkeypatch):
    from gamearena.services import email
    monkeypatch.setattr(security,'_metrics',{})
    monkeypatch.setattr(security,'_last_alert_email',0)
    monkeypatch.setitem(app.config,'SECURITY_ALERT_EMAIL','owner@example.test')
    send=Mock(return_value=True);monkeypatch.setattr(email,'send_email',send)
    monkeypatch.setattr(application.socketio,'start_background_task',lambda action:action())
    with app.app_context():
        for _ in range(3):security.metric('mfa_failures',3)
        for _ in range(5):security.metric('authentication_failures',5)
    assert send.call_count==1
    subject,recipient,body=send.call_args.args
    assert recipient=='owner@example.test' and 'mfa_failures' in body
    assert 'No credentials or player details' in body


def test_owner_recovery_tool_checks_identity_and_revokes_sessions(monkeypatch):
    import os,sys
    from scripts import security_admin
    with app.app_context():
        user,browser=account('owner_cli',True);_,codes=enroll(browser,user)
        original=user.auth_session_version
        monkeypatch.setenv('GAMEARENA_SECURITY_DATABASE_URL',os.environ['GAMEARENA_TEST_DATABASE_URL'])
        monkeypatch.setattr(sys,'argv',['security_admin.py','reset-mfa','--user-id',str(user.id),'--confirm-username','wrong'])
        with pytest.raises(SystemExit,match='confirmation did not match'):security_admin.main()
        db.session.refresh(user);assert user.auth_session_version==original
        monkeypatch.setattr(sys,'argv',['security_admin.py','reset-mfa','--user-id',str(user.id),'--confirm-username',user.username])
        security_admin.main();db.session.expire_all()
        assert db.session.get(type(user),user.id).auth_session_version==original+1
        row=db.session.get(AccountSecurity,user.id)
        assert not row.enabled_at and not row.totp_secret and not row.recovery_hashes
        assert '/login' in browser.get('/wallet').location
