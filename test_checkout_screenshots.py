from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import app as application
from app import app, db, UserTournament
from test_interface_contracts import player, client, token, event

@pytest.mark.parametrize('payload,status,expected',[
 ({'status':True,'data':{'authorization_url':'https://checkout.paystack.com/test-checkout'}},200,200),
 ({'status':True,'data':{}},200,502),
 ({'status':True,'data':{'authorization_url':'not a url'}},200,502),
 ({'status':False},401,502),
])
def test_checkout_only_creates_pending_entry_for_valid_provider_link(monkeypatch,payload,status,expected):
    response=SimpleNamespace(status_code=status,json=lambda:payload)
    monkeypatch.setattr(application.requests,'post',Mock(return_value=response))
    with app.app_context():
        owner=player('checkout_owner');tournament=event(fee=3500);viewer=client(owner)
        csrf=token(viewer.get('/profile'))
        result=viewer.post(f'/initialize-payment/{tournament.id}',data={'csrf_token':csrf},headers={'Accept':'application/json'})
        assert result.status_code==expected
        if expected==200:
            entry=UserTournament.query.one()
            assert entry.payment_status=='pending' and entry.amount_paid==3500
            assert result.json['authorization_url'].startswith('https://checkout.paystack.com/')
            assert application.requests.post.call_args.kwargs['json']['amount']==350000
        else: assert UserTournament.query.count()==0
        assert owner.wallet_balance==0


def test_failed_retry_preserves_existing_payment_reference(monkeypatch):
    monkeypatch.setattr(application.requests,'post',Mock(return_value=SimpleNamespace(status_code=200,json=lambda:{'status':True,'data':{}})))
    with app.app_context():
        owner=player('checkout_retry');tournament=event(fee=2500);viewer=client(owner)
        db.session.add(UserTournament(user_id=owner.id,tournament_id=tournament.id,payment_status='pending',amount_paid=2500,transaction_ref='previous-reference'));db.session.commit()
        csrf=token(viewer.get('/profile'))
        result=viewer.post(f'/initialize-payment/{tournament.id}',data={'csrf_token':csrf},headers={'Accept':'application/json'})
        assert result.status_code==502
        db.session.expire_all()
        assert UserTournament.query.one().transaction_ref=='previous-reference'
