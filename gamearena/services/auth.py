"""Supabase Auth over its HTTPS API; never use an admin key for user login."""
import os
import requests


class AuthError(Exception):
    def __init__(self, message='Authentication is temporarily unavailable. Please try again.', status=503):
        super().__init__(message)
        self.status = status


def enabled():
    return os.environ.get('AUTH_PROVIDER', 'local').strip().lower() == 'supabase'


def configuration():
    url = (os.environ.get('SUPABASE_URL') or '').rstrip('/')
    key = os.environ.get('SUPABASE_PUBLISHABLE_KEY') or os.environ.get('SUPABASE_ANON_KEY')
    if not url.startswith('https://') or not key:
        raise AuthError()
    return url, key


def call(method, path, payload=None, access_token=None):
    url, key = configuration()
    headers = {'apikey': key}
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    try:
        response = requests.request(method, url + '/auth/v1/' + path,
            headers=headers,
            json=payload, timeout=(5, 15))
        data = response.json()
    except (requests.RequestException, ValueError):
        raise AuthError() from None
    if not isinstance(data, dict):
        raise AuthError()
    if not response.ok:
        if response.status_code == 429:
            raise AuthError('Please wait before trying again.', 429)
        if data.get('error_code') == 'email_not_confirmed':
            raise AuthError('Verify your email before signing in. You can request another code below.', 400)
        if response.status_code < 500:
            raise AuthError('Unable to complete authentication. Check your details or request a new code.', 400)
        raise AuthError()
    return data


def close_session(data):
    if data.get('access_token'):
        try:
            call('POST', 'logout', access_token=data['access_token'])
        except AuthError:
            pass


def signup(email, password, username):
    return call('POST', 'signup', {'email': email, 'password': password,
        'data': {'username': username}})


def signin(email, password):
    return call('POST', 'token?grant_type=password', {'email': email, 'password': password})


def resend(email):
    return call('POST', 'resend', {'type': 'signup', 'email': email})


def verify(email, code, purpose='signup'):
    return call('POST', 'verify', {'email': email, 'token': code, 'type': purpose})


def recover(email):
    return call('POST', 'recover', {'email': email})


def reset_password(email, code, password):
    data = verify(email, code, 'recovery')
    if not data.get('access_token'):
        raise AuthError('Invalid or expired reset code.', 400)
    try:
        return call('PUT', 'user', {'password': password}, data['access_token'])
    finally:
        # Recovery grants must not leave a provider session active.
        try:
            call('POST', 'logout', access_token=data['access_token'])
        except AuthError:
            pass
