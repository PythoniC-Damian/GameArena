"""Paystack failures are reported safely without creating credits or pending deposits."""
from unittest.mock import Mock
import pytest
import app as application
from app import app, db
from gamearena.models import WalletTransaction
from test_interface_contracts import player, client, token


@pytest.mark.parametrize('provider_status',[401,403,500])
def test_rejected_deposit_is_not_recorded_or_credited(monkeypatch,provider_status):
    with app.app_context():
        user=player('reject_deposit');browser=client(user)
        response=Mock(status_code=provider_status)
        response.json.return_value={'status':False,'message':'Provider rejection'}
        monkeypatch.setattr(application,'PAYSTACK_SECRET_KEY','synthetic-secret')
        monkeypatch.setattr(application.requests,'post',Mock(return_value=response))
        result=browser.post('/wallet/initialize-deposit',json={'amount':200},headers={'X-CSRFToken':token(browser.get('/wallet'))})
        assert result.status_code==502
        assert result.json['code']=='payment_provider_rejected'
        assert ('temporarily unavailable' if provider_status in (401,403) else 'could not be opened') in result.json['message']
        assert 'synthetic-secret' not in result.text
        assert WalletTransaction.query.filter_by(user_id=user.id).count()==0
        db.session.refresh(user);assert not user.wallet_balance


def test_missing_secret_does_not_contact_provider(monkeypatch):
    with app.app_context():
        browser=client(player('missing_deposit_key'))
        monkeypatch.setattr(application,'PAYSTACK_SECRET_KEY','')
        send=Mock();monkeypatch.setattr(application.requests,'post',send)
        response=browser.post('/wallet/initialize-deposit',json={'amount':200},headers={'X-CSRFToken':token(browser.get('/wallet'))})
        assert response.status_code==503 and response.json['code']=='payment_configuration_missing'
        assert not send.called and WalletTransaction.query.count()==0


def test_successful_provider_response_still_returns_checkout(monkeypatch):
    with app.app_context():
        user=player('working_deposit');browser=client(user)
        response=Mock(status_code=200)
        response.json.return_value={'status':True,'data':{'authorization_url':'https://checkout.paystack.com/synthetic-checkout'}}
        monkeypatch.setattr(application,'PAYSTACK_SECRET_KEY','synthetic-secret')
        monkeypatch.setattr(application.requests,'post',Mock(return_value=response))
        result=browser.post('/wallet/initialize-deposit',json={'amount':200},headers={'X-CSRFToken':token(browser.get('/wallet'))})
        assert result.status_code==200 and result.json['authorization_url'].startswith('https://checkout.paystack.com/')
        row=WalletTransaction.query.filter_by(user_id=user.id).one()
        assert row.status=='pending' and row.amount==200
        assert not db.session.get(type(user),user.id).wallet_balance
