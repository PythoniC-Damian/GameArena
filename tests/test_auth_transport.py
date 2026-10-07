"""Transport checks run without an application or database fixture."""
from unittest.mock import Mock
from gamearena.services import auth


def test_publishable_key_is_not_sent_as_bearer(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://test.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test')
    request = Mock(return_value=Mock(ok=True, json=lambda: {'user': {}}))
    monkeypatch.setattr(auth.requests, 'request', request)
    auth.signin('player@example.com', 'password')
    assert request.call_args.kwargs['headers'] == {'apikey': 'sb_publishable_test'}
    auth.call('PUT', 'user', {'password': 'new'}, 'user-jwt')
    assert request.call_args.kwargs['headers'] == {
        'apikey': 'sb_publishable_test', 'Authorization': 'Bearer user-jwt'}
