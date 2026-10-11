"""Public help pages and performance/privacy boundaries."""
from app import app
import app as application

def test_policy_pages_public_links_and_aliases():
    visitor = app.test_client()
    for path, title in [('/privacy','Privacy Policy'),('/privacy-policy','Privacy Policy'),('/terms','Terms of Use'),('/terms-of-use','Terms of Use'),('/faq','Frequently Asked Questions')]:
        response = visitor.get(path)
        assert response.status_code == 200
        assert title in response.text
        assert 'aria-label="Footer"' in response.text
        assert 'no-store' in response.headers['Cache-Control']
    assert '<details' in visitor.get('/faq').text
    assert 'not end-to-end encrypted' in visitor.get('/privacy').text
    assert 'Grandmaster and Legendary are planned tiers' in visitor.get('/terms').text
    registration = visitor.get('/register')
    assert 'By creating an account' in registration.text
    assert '/privacy-policy' in registration.text and '/terms-of-use' in registration.text

def test_non_home_pages_do_not_prepare_hero_catalogue(monkeypatch):
    def unexpected(): raise AssertionError('Homepage image work on another page')
    monkeypatch.setattr(application, 'hero_image_catalog', unexpected)
    visitor = app.test_client()
    for path in ['/privacy','/terms','/faq','/login','/register']:
        assert visitor.get(path).status_code == 200

def test_policy_contact_override_is_escaped(monkeypatch):
    monkeypatch.setenv('GAMEARENA_SUPPORT_EMAIL','support@example.com')
    assert 'mailto:support@example.com' in app.test_client().get('/privacy').text
