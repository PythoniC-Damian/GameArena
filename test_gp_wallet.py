"""Exact GP conversion, persisted fees, webhook amounts and GP entry accounting."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import hashlib,hmac,json
import pytest
import app as application
from app import app,db,User,UserTournament,WalletTransaction
from gamearena.gp import gp_to_naira,gp_label,withdrawal_fee_kobo
from test_wallet_updates import setup,payload,provider
from test_interface_contracts import player,client,token,event

@pytest.mark.parametrize('naira,gp',[(1000,'1000'),(2500,'2500'),(150000,'150000'),(1001,'1001')])
def test_fixed_rate_is_exact(naira,gp):
    assert gp_to_naira(gp)==naira
    assert gp_label(naira).replace(',','')==gp+' GP'

@pytest.mark.parametrize('value',['0','-1','1.1','NaN','Infinity','1e3','1,000','2000000001'])
def test_invalid_gp_is_rejected(value):
    with pytest.raises(ValueError):gp_to_naira(value)

def test_fee_cap_and_precise_payout(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch);owner.wallet_balance=200000;db.session.commit()
        call=Mock(side_effect=provider());monkeypatch.setattr(application,'paystack_transfer_request',call)
        data=payload(owner);data.pop('amount');data.update(amount_gp='150000',fee_kobo=20000)
        response=browser.post('/wallet/withdraw',json=data,headers=headers)
        assert response.status_code==202 and response.json['withdrawal_status']=='completed'
        row=WalletTransaction.query.one();db.session.refresh(owner)
        assert row.amount==150000 and row.withdrawal_fee_kobo==20000 and row.payout_kobo==14980000
        assert owner.wallet_balance==50000
        transfer=next(call for call in call.call_args_list if call.args[1]=='/transfer')
        assert transfer.kwargs['json']['amount']==14980000
        receipt=browser.get(response.json['receipt_url'])
        assert '150,000 GP' in receipt.text and '149,800' in receipt.text and 'Withdrawal fee' in receipt.text

@pytest.mark.parametrize('change',[{'fee_kobo':0},{'fee_consent':False},{'fee_policy':'old'}])
def test_fee_cannot_be_hidden_or_tampered(monkeypatch,change):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        response=browser.post('/wallet/withdraw',json=payload(owner,**change),headers=headers)
        assert response.status_code==400
        db.session.refresh(owner);assert owner.wallet_balance==1000 and WalletTransaction.query.count()==0

def test_failed_fee_is_refunded_and_webhook_requires_net_amount(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        monkeypatch.setattr(application,'paystack_transfer_request',Mock(side_effect=provider('pending')))
        response=browser.post('/wallet/withdraw',json=payload(owner),headers=headers)
        row=WalletTransaction.query.one();assert row.status=='processing' and row.payout_kobo==29700
        def webhook(amount,event='transfer.failed'):
            body=json.dumps({'event':event,'data':{'reference':row.transaction_ref,'currency':'NGN','amount':amount,'transfer_code':'TRF_test'}}).encode()
            signature=hmac.new(b'sk_test_fake_only',body,hashlib.sha512).hexdigest()
            return browser.post('/paystack/webhook',data=body,headers={'Content-Type':'application/json','x-paystack-signature':signature})
        assert webhook(30000).status_code==400
        db.session.refresh(owner);assert owner.wallet_balance==700
        assert webhook(29700).status_code==200
        assert webhook(29700).status_code==200
        db.session.refresh(owner);assert owner.wallet_balance==1000
        db.session.refresh(row);assert row.status=='failed'
        assert 'refunded' in browser.get(response.json['receipt_url']).text

def test_gp_entry_debits_once_and_blocks_external_pending_checkout(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch);tournament=event(fee=500)
        monkeypatch.setattr(application,'award_achievements_for_user',lambda *a:None)
        url=f'/tournaments/{tournament.id}/pay-gp'
        assert browser.post(url,json={'amount_gp':'49'},headers=headers).status_code==409
        paid=browser.post(url,json={'amount_gp':'500'},headers=headers)
        assert paid.status_code==200 and paid.json['status']=='success'
        assert browser.post(url,json={'amount_gp':'500'},headers=headers).json['already_paid']
        db.session.refresh(owner);assert owner.wallet_balance==500
        assert UserTournament.query.one().payment_status=='paid'
        assert WalletTransaction.query.one().type=='tournament_entry'
        assert 'GameArena GP wallet' in browser.get(paid.json['redirect_url']).text
        other=event('External pending',fee=100)
        db.session.add(UserTournament(user_id=owner.id,tournament_id=other.id,payment_status='pending',transaction_ref='external_checkout',amount_paid=100));db.session.commit()
        assert browser.post(f'/tournaments/{other.id}/pay-gp',json={'amount_gp':'1000'},headers=headers).status_code==409
        db.session.refresh(owner);assert owner.wallet_balance==500

def test_gp_capacity_and_duplicate_entry_requests_are_atomic(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch);tournament=event(fee=100,capacity=1)
        monkeypatch.setattr(application,'award_achievements_for_user',lambda *a:None)
        clients=[client(owner),client(owner)]
        csrf=[token(c.get('/wallet')) for c in clients]
        url=f'/tournaments/{tournament.id}/pay-gp';owner_id=owner.id
    def enter(i):return clients[i].post(url,json={'amount_gp':'100'},headers={'X-CSRFToken':csrf[i]})
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(enter,range(2)))
    assert all(result.status_code==200 for result in results)
    with app.app_context():
        assert db.session.get(User,owner_id).wallet_balance==900
        assert WalletTransaction.query.count()==UserTournament.query.count()==1

def test_legacy_withdrawals_keep_zero_fee():
    row=WalletTransaction(type='withdrawal',amount=300,withdrawal_fee_kobo=0)
    assert row.payout_kobo==30000


def test_gp_topup_credits_only_after_verified_payment(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        response=Mock(status_code=200);response.json.return_value={'status':True,'data':{'authorization_url':'https://checkout.paystack.com/test-gp'}}
        initialize=Mock(return_value=response);monkeypatch.setattr(application.requests,'post',initialize)
        started=browser.post('/wallet/initialize-deposit',json={'amount_gp':'1000'},headers=headers)
        assert started.json['status']=='success'
        assert initialize.call_args.kwargs['json']['amount']==100000
        row=WalletTransaction.query.one();assert row.amount==1000 and row.status=='pending'
        db.session.refresh(owner);assert owner.wallet_balance==1000
        transaction={'reference':row.transaction_ref,'amount':100000,'currency':'NGN','metadata':{'user_id':owner.id,'type':'wallet_deposit'}}
        assert application.apply_wallet_deposit(row,transaction)==(True,'processed')
        db.session.refresh(row)
        assert application.apply_wallet_deposit(row,transaction)==(True,'already_processed')
        db.session.refresh(owner);assert owner.wallet_balance==2000 and gp_label(owner.wallet_balance)=='2,000 GP'


def test_last_gp_entry_slot_is_not_oversold(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch);other=player('last_slot_opponent');other.wallet_balance=1000;db.session.commit()
        tournament=event(fee=100,capacity=1);owner_ids=[owner.id,other.id]
        monkeypatch.setattr(application,'award_achievements_for_user',lambda *args:None)
        clients=[client(owner),client(other)];csrf=[token(c.get('/wallet')) for c in clients]
        url=f'/tournaments/{tournament.id}/pay-gp'
    def enter(i):return clients[i].post(url,json={'amount_gp':'100'},headers={'X-CSRFToken':csrf[i]})
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(enter,range(2)))
    assert sorted(result.status_code for result in results)==[200,409]
    with app.app_context():
        assert sorted(db.session.get(User,i).wallet_balance for i in owner_ids)==[900,1000]
        assert UserTournament.query.count()==WalletTransaction.query.count()==1
