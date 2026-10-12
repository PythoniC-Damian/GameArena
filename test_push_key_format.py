import base64
from web_push import public_key_configuration

# Standard public P-256 generator point: public test data, no private key.
PUBLIC_POINT = bytes.fromhex('04' +
    '6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296' +
    '4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5')
PUBLIC = base64.urlsafe_b64encode(PUBLIC_POINT).decode().rstrip('=')


def test_valid_public_encoding_and_copy_format_normalization():
    for value in (PUBLIC, PUBLIC+'=', '\n"'+PUBLIC+'"\r\n', PUBLIC[:40]+'\n'+PUBLIC[40:]):
        key, status = public_key_configuration(value)
        assert key == PUBLIC and status['valid']
        assert status['decoded_bytes'] == 65


def test_invalid_public_setting_diagnostics_do_not_disclose_value():
    for value in ('', 'not-a-key!', 'VAPID_PUBLIC_KEY='+PUBLIC,
        base64.urlsafe_b64encode(b'x'*32).decode().rstrip('='),
        base64.urlsafe_b64encode(b'\x04'+b'\x00'*64).decode().rstrip('=')):
        key, status = public_key_configuration(value)
        assert key == '' and not status['valid']
        assert 'error' in status
        if value:
            assert value not in str(status)


def test_config_response_does_not_return_malformed_key(monkeypatch):
    from app import app
    from test_interface_contracts import player, client
    with app.app_context():
        owner=player('key_diagnostic')
        for name in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'):
            monkeypatch.setenv(name,'invalid-test-only')
        result=client(owner).get('/notifications/push').json
        assert result['public_key']==''
        assert not result['public_key_status']['valid']
        assert 'invalid-test-only' not in str(result)
