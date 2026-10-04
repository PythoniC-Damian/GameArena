"""Email-only checks with mocked providers; no messages leave the test environment."""
import json
import socket
from unittest.mock import MagicMock
import pytest
import app as application
from app import app, db, User, send_email
from test_interface_contracts import token

@pytest.fixture
def mail(monkeypatch):
    for key in ('RESEND_API_KEY','EMAIL_FROM','EMAIL_PROVIDER','SMTP_SERVER','SMTP_PORT','SMTP_USERNAME','SMTP_PASSWORD','RENDER'):
        monkeypatch.delenv(key,raising=False)
    connection=MagicMock();response=connection.getresponse.return_value
    response.status=200;response.getheader.return_value='safe-request';response.read.return_value=b'{"id":"test-email-id"}'
    monkeypatch.setattr(application.http.client,'HTTPSConnection',MagicMock(return_value=connection))
    smtp=MagicMock();smtp.__enter__.return_value.send_message.return_value={}
    factory=MagicMock(return_value=smtp);monkeypatch.setattr(application.smtplib,'SMTP',factory);monkeypatch.setattr(application.smtplib,'SMTP_SSL',factory)
    return connection,response,factory


def test_resend_domain_timeout_and_duplicate_protection(mail,monkeypatch):
    connection,_,smtp=mail;monkeypatch.setenv('RESEND_API_KEY','test-only-key');monkeypatch.setenv('EMAIL_PROVIDER','resend')
    with app.test_request_context('/'):
        assert send_email('Verify','recipient@example.test','Code 123456')
        assert send_email('Verify','recipient@example.test','Code 123456')
    payload=json.loads(connection.request.call_args.kwargs['body'])
    assert payload['from']=='GameArena <noreply@gamearena01.com>'
    calls=connection.request.call_args_list
    assert calls[0].kwargs['headers']['Idempotency-Key']==calls[1].kwargs['headers']['Idempotency-Key']
    assert connection.close.call_count==2 and not smtp.called
    application.http.client.HTTPSConnection.assert_called_with('api.resend.com',timeout=8)


def test_configured_sender_is_preserved(mail,monkeypatch):
    connection,_,_=mail;monkeypatch.setenv('RESEND_API_KEY','test-only-key');monkeypatch.setenv('EMAIL_FROM','GameArena <accounts@gamearena01.com>')
    with app.test_request_context('/'):assert send_email('Verify','recipient@example.test','Test')
    assert json.loads(connection.request.call_args.kwargs['body'])['from']=='GameArena <accounts@gamearena01.com>'


def test_render_missing_key_skips_blocked_smtp(mail,monkeypatch):
    connection,_,smtp=mail;monkeypatch.setenv('RENDER','true')
    for key,value in {'SMTP_SERVER':'smtp.example.test','SMTP_PORT':'587','SMTP_USERNAME':'local@example.test','SMTP_PASSWORD':'test-password'}.items():monkeypatch.setenv(key,value)
    with app.test_request_context('/'):assert not send_email('Verify','recipient@example.test','Test')
    assert not connection.request.called and not smtp.called


@pytest.mark.parametrize('status',[401,403,422,429,500])
def test_resend_errors_do_not_log_addresses_codes_or_keys(mail,monkeypatch,caplog,status):
    _,response,smtp=mail;response.status=status
    response.read.return_value=b'{"message":"secret-recipient@example.test 789012 test-only-key"}'
    monkeypatch.setenv('RESEND_API_KEY','test-only-key');monkeypatch.setenv('EMAIL_PROVIDER','resend')
    with app.test_request_context('/'):assert not send_email('Verify','secret-recipient@example.test','789012')
    assert not smtp.called
    assert all(value not in caplog.text for value in ('secret-recipient','789012','test-only-key'))


def test_malformed_success_does_not_claim_delivery(mail,monkeypatch):
    _,response,_=mail;response.read.return_value=b'<!DOCTYPE html><h1>Proxy</h1>'
    monkeypatch.setenv('RESEND_API_KEY','test-only-key');monkeypatch.setenv('EMAIL_PROVIDER','resend')
    with app.test_request_context('/'):assert not send_email('Verify','recipient@example.test','Test')


def test_timeout_closes_connection_without_smtp_delay(mail,monkeypatch):
    connection,_,smtp=mail;connection.getresponse.side_effect=socket.timeout()
    monkeypatch.setenv('RESEND_API_KEY','test-only-key');monkeypatch.setenv('EMAIL_PROVIDER','resend')
    with app.test_request_context('/'):assert not send_email('Verify','recipient@example.test','Test')
    assert connection.close.called and not smtp.called


def test_local_auto_smtp_fallback_is_preserved(mail,monkeypatch):
    _,response,smtp=mail;response.status=403
    for key,value in {'EMAIL_PROVIDER':'auto','RESEND_API_KEY':'test-only-key','SMTP_SERVER':'smtp.example.test','SMTP_PORT':'587','SMTP_USERNAME':'local@example.test','SMTP_PASSWORD':'test-password'}.items():monkeypatch.setenv(key,value)
    with app.test_request_context('/'):assert send_email('Verify','recipient@example.test','Test')
    assert smtp.called


def test_registration_code_arrives_in_provider_payload_and_verifies(mail,monkeypatch):
    connection,_,_=mail;monkeypatch.setenv('RESEND_API_KEY','test-only-key');monkeypatch.setenv('EMAIL_PROVIDER','resend')
    viewer=app.test_client();csrf=token(viewer.get('/register'))
    response=viewer.post('/register',data={'csrf_token':csrf,'username':'email_contract_player','email':'email-contract@example.com','password':'Only-Test-42!'})
    assert response.status_code==302 and '/verify-email' in response.location
    with app.app_context():
        user=User.query.filter_by(email='email-contract@example.com').one();code=user.verification_code
        assert len(code)==6 and not user.email_verified
        assert code in json.loads(connection.request.call_args.kwargs['body'])['text']
    page=viewer.get(response.location);csrf=token(page)
    verified=viewer.post('/verify-email',data={'csrf_token':csrf,'email':'email-contract@example.com','code':code})
    assert verified.status_code==302 and verified.location.endswith('/login')
    login=viewer.get(verified.location)
    assert b'Email verified! Log in below to enter your arena.' in login.data
    assert b'role="status"' in login.data
    with app.app_context():
        user=User.query.filter_by(email='email-contract@example.com').one();assert user.email_verified and user.verification_code is None
