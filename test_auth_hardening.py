from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
import re

import pytest
import requests

import app as application
from app import app, db, User, RateLimitBucket
from gamearena.services import auth
from werkzeug.security import generate_password_hash


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', False)
    monkeypatch.setenv('AUTH_PROVIDER', 'local')
    return app.test_client()


def player(verified=False):
    with app.app_context():
        user = User(username='auth_player', email='auth_player@example.com',
            password=generate_password_hash('secret123'), email_verified=verified)
        db.session.add(user)
        db.session.commit()
        return user.id


def identity(user_id='00000000-0000-0000-0000-000000000001'):
    return {'user': {'id': user_id, 'email': 'auth_player@example.com',
        'email_confirmed_at': '2026-10-06T00:00:00Z'}}


def test_simultaneous_code_requests_send_one_email(client, monkeypatch):
    user_id = player()
    send = Mock(return_value=True)
    monkeypatch.setattr(application, 'send_email', send)
    monkeypatch.setattr(application, 'create_and_emit_notification', lambda *args: None)
    monkeypatch.setattr(application, 'queue_account_email', lambda *args: False)
    def request_code(_):
        with app.test_request_context('/verify-email'):
            user = db.session.get(User, user_id)
            return application.send_verification_code(user)
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert all(executor.map(request_code, range(4)))
    assert send.call_count == 1
    with app.app_context():
        assert db.session.get(User, user_id).verification_code


def test_login_and_resend_share_cooldown(client, monkeypatch):
    user_id = player()
    send = Mock(return_value=True)
    monkeypatch.setattr(application, 'send_email', send)
    client.post('/login', data={'email': 'auth_player@example.com', 'password': 'secret123'})
    with app.app_context():
        first = db.session.get(User, user_id).verification_code
    response = client.post('/verify-email', data={'email': 'auth_player@example.com', 'action': 'resend'}, follow_redirects=True)
    assert send.call_count == 1
    wait = re.search(rb'data-cooldown="(\d+)"', response.data)
    assert wait and 0 < int(wait.group(1)) <= 60
    with app.app_context():
        assert db.session.get(User, user_id).verification_code == first


def test_rate_limit_keeps_browser_form_and_json_api(client, monkeypatch):
    monkeypatch.setitem(application.RATE_LIMITS, 'login_account', (1, 60))
    data = {'email': 'missing@example.com', 'password': 'wrong'}
    client.post('/login', data=data)
    browser = client.post('/login', data=data)
    assert browser.status_code == 429
    assert browser.mimetype == 'text/html'
    assert b'data-auth-form' in browser.data
    assert b'Please try again in' in browser.data
    assert browser.headers['Retry-After']
    api = client.post('/login', data=data, headers={'Accept': 'application/json'})
    assert api.status_code == 429
    assert api.json['status'] == 'error'


def test_google_callback_uses_canonical_domain(client, monkeypatch):
    monkeypatch.setattr(application, 'is_production', True)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'test-client')
    monkeypatch.setenv('GOOGLE_REDIRECT_URI', 'https://gamearena.onrender.com/auth/google/callback')
    response = client.get('/login/google', base_url='https://gamearena01.com')
    assert parse_qs(urlparse(response.location).query)['redirect_uri'] == ['https://gamearena01.com/auth/google/callback']


@pytest.mark.parametrize('verified,suspended', [(False, False), (True, True)])
def test_google_rejects_unverified_or_suspended(client, monkeypatch, verified, suspended):
    user_id = player(True)
    with app.app_context():
        db.session.get(User, user_id).suspended = suspended
        db.session.commit()
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'client')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'secret')
    state = parse_qs(urlparse(client.get('/login/google').location).query)['state'][0]
    monkeypatch.setattr(application.requests, 'post', lambda *a, **kw: Mock(ok=True, json=lambda: {'access_token': 'token'}))
    monkeypatch.setattr(application.requests, 'get', lambda *a, **kw: Mock(ok=True, json=lambda: {
        'email': 'auth_player@example.com', 'verified_email': verified}))
    assert client.get('/auth/google/callback?code=x&state=' + state).location.endswith('/login')
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_google_timeout_returns_login(client, monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'client')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET', 'secret')
    state = parse_qs(urlparse(client.get('/login/google').location).query)['state'][0]
    monkeypatch.setattr(application.requests, 'post', Mock(side_effect=requests.Timeout()))
    assert client.get('/auth/google/callback?code=x&state=' + state).location.endswith('/login')


def test_managed_signin_preserves_business_account(client, monkeypatch):
    user_id = player(True)
    with app.app_context():
        db.session.get(User, user_id).wallet_balance = 5000
        db.session.commit()
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    monkeypatch.setattr(auth, 'signin', lambda *args: identity())
    monkeypatch.setattr(application, 'check_password_hash', Mock(side_effect=AssertionError('local password used')))
    response = client.post('/login', data={'email': 'auth_player@example.com', 'password': 'managed-secret'})
    assert response.location.endswith('/dashboard')
    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.wallet_balance == 5000
        assert user.supabase_auth_id == identity()['user']['id']
        assert User.query.count() == 1


def test_managed_provider_failure_has_no_local_fallback(client, monkeypatch):
    player(True)
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    monkeypatch.setattr(auth, 'signin', Mock(side_effect=auth.AuthError()))
    monkeypatch.setattr(application, 'check_password_hash', Mock(side_effect=AssertionError('local fallback')))
    response = client.post('/login', data={'email': 'auth_player@example.com', 'password': 'secret123'})
    assert response.status_code == 503
    assert response.mimetype == 'text/html'


def test_managed_signup_does_not_keep_password_or_trust_signup_id(client, monkeypatch):
    from werkzeug.security import check_password_hash
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    signup = Mock(return_value={'user': {'id': 'unconfirmed-response'}})
    monkeypatch.setattr(auth, 'signup', signup)
    response = client.post('/register', data={'email': 'new@example.com',
        'username': 'new_player', 'password': 'secret123'})
    assert '/verify-email' in response.location
    with app.app_context():
        user = User.query.filter_by(email='new@example.com').one()
        assert user.supabase_auth_id is None
        assert not check_password_hash(user.password, 'secret123')
        assert not user.email_verified
    assert signup.call_count == 1


def test_managed_recovery_requests_share_cooldown(client, monkeypatch):
    player(True)
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    recover = Mock(return_value={})
    monkeypatch.setattr(auth, 'recover', recover)
    for _ in range(2):
        response = client.post('/forgot-password', data={'email': 'auth_player@example.com'})
        assert '/reset-password' in response.location
    assert recover.call_count == 1


def test_managed_suspension_and_unconfirmed_identity(client, monkeypatch):
    user_id = player(True)
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    with app.test_request_context():
        with pytest.raises(auth.AuthError):
            application.managed_identity({'user': {'id': 'x', 'email': 'auth_player@example.com'}})
        db.session.get(User, user_id).suspended = True
        db.session.commit()
        with pytest.raises(auth.AuthError, match='suspended'):
            application.managed_identity(identity())


def test_managed_oauth_requires_pkce_session(client, monkeypatch):
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'test-key')
    call = Mock()
    monkeypatch.setattr(auth, 'call', call)
    assert client.get('/auth/supabase/callback?code=x').location.endswith('/login')
    call.assert_not_called()
    response = client.get('/login/google')
    params = parse_qs(urlparse(response.location).query)
    assert params['code_challenge_method'] == ['s256']
    call.return_value = identity()
    assert client.get('/auth/supabase/callback?code=x').location.endswith('/dashboard')
    assert call.call_args.args[1] == 'token?grant_type=pkce'


def test_password_reset_revokes_existing_application_session(client, monkeypatch):
    user_id = player(True)
    monkeypatch.setenv('AUTH_PROVIDER', 'supabase')
    monkeypatch.setattr(auth, 'signin', lambda *args: identity())
    monkeypatch.setattr(auth, 'reset_password', Mock())
    client.post('/login', data={'email': 'auth_player@example.com', 'password': 'secret123'})
    second = app.test_client()
    response = second.post('/reset-password', data={'email': 'auth_player@example.com',
        'code': '123456', 'new_password': 'new-secret123'})
    assert response.location.endswith('/login')
    assert client.get('/dashboard').status_code == 302
    with app.app_context():
        assert db.session.get(User, user_id).auth_session_version == 1


def test_reset_api_uses_verified_recovery_access_token(monkeypatch):
    call = Mock(side_effect=[{'access_token': 'recovery-token'}, {}, {}])
    monkeypatch.setattr(auth, 'call', call)
    auth.reset_password('player@example.com', '123456', 'new-secret')
    assert call.call_args_list[0].args == ('POST', 'verify', {
        'email': 'player@example.com', 'token': '123456', 'type': 'recovery'})
    assert call.call_args_list[1].args == ('PUT', 'user', {'password': 'new-secret'}, 'recovery-token')
    assert call.call_args_list[2].kwargs['access_token'] == 'recovery-token'


@pytest.mark.parametrize('problem', ['timeout', 'invalid_json', 'wrong_shape'])
def test_provider_errors_are_safe(monkeypatch, problem):
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'test-key')
    response = Mock(ok=True)
    response.json = Mock(side_effect=ValueError()) if problem == 'invalid_json' else Mock(return_value=[])
    monkeypatch.setattr(auth.requests, 'request', Mock(side_effect=requests.Timeout()) if problem == 'timeout' else Mock(return_value=response))
    with pytest.raises(auth.AuthError):
        auth.signin('player@example.com', 'secret')
