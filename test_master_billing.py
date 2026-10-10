"""Mocked Paystack tests; never contact Paystack or charge a card."""
import json, hashlib, hmac
from datetime import datetime, timedelta
import pytest
import app as application
from app import app, db
from gamearena import master_billing as billing
from gamearena.models import MasterPayment, MasterSubscription, WalletTransaction
from test_interface_contracts import player, client, token

@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv('MASTER_BILLING_ENABLED','1')
    monkeypatch.setenv('PAYSTACK_MASTER_PLAN_CODE','PLN_test_master')
    monkeypatch.setenv('PAYSTACK_SECRET_KEY','sk_test_mock_only')
    monkeypatch.setenv('PUBLIC_BASE_URL','http://127.0.0.1:5059')
    monkeypatch.setattr(application,'PAYSTACK_SECRET_KEY','sk_test_mock_only')

def subscription(user):
    item=MasterSubscription(user_id=user.id,plan_code='PLN_test_master',billing_email=user.email,status='pending')
    db.session.add(item);db.session.flush()
    db.session.add(MasterPayment(reference='master-initial',subscription_id=item.id));db.session.commit()
    return item

def charge(user,reference='master-initial',paid=None):
    return dict(reference=reference,status='success',amount=230000,currency='NGN',customer={'email':user.email,'customer_code':'CUS_master'},plan_object={'plan_code':'PLN_test_master'},paid_at=(paid or datetime.utcnow()).isoformat()+'Z')

def webhook(name,data,signature=True):
    raw=json.dumps({'event':name,'data':data}).encode()
    digest=hmac.new(b'sk_test_mock_only',raw,hashlib.sha512).hexdigest() if signature else 'bad'
    return app.test_client().post('/paystack/webhook',data=raw,content_type='application/json',headers={'x-paystack-signature':digest})

def test_checkout_price_consent_and_duplicate_click(settings,monkeypatch):
    calls=[]
    def provider(method,path,**kwargs):
        calls.append(path)
        if path.startswith('/plan/'):
            return dict(plan_code='PLN_test_master',amount=230000,currency='NGN',interval='monthly')
        assert kwargs['json']['amount']==230000 and kwargs['json']['channels']==['card']
        assert kwargs['json']['plan']=='PLN_test_master'
        return dict(reference=kwargs['json']['reference'],authorization_url='https://checkout.paystack.com/mock')
    monkeypatch.setattr(billing,'provider',provider)
    with app.app_context():
        owner=player('billing_owner'); viewer=client(owner); csrf=token(viewer.get('/pro'))
        assert viewer.post('/pro/checkout',data={'csrf_token':csrf}).status_code==302
        assert MasterSubscription.query.count()==0
        for _ in range(2):
            result=viewer.post('/pro/checkout',data={'csrf_token':csrf,'renewal_consent':'yes'})
            assert result.location=='https://checkout.paystack.com/mock'
        assert MasterSubscription.query.count()==1 and MasterPayment.query.count()==1
        assert calls.count('/transaction/initialize')==1
        assert viewer.post('/pro/checkout',data={'renewal_consent':'yes'}).status_code==400
        assert not owner.master_active

def test_signed_payment_and_invoice_are_idempotent(settings,monkeypatch):
    with app.app_context():
        owner=player('paid_master'); item=subscription(owner)
        assert webhook('charge.success',charge(owner),signature=False).status_code==401
        wrong=charge(owner);wrong['amount']=1000
        assert webhook('charge.success',wrong).status_code!=200
        db.session.rollback();db.session.refresh(owner);assert not owner.master_active
        assert webhook('charge.success',charge(owner)).status_code==200
        db.session.refresh(owner);original=owner.master_expires_at
        assert webhook('charge.success',charge(owner)).status_code==200
        db.session.refresh(owner);assert owner.master_expires_at==original
        assert WalletTransaction.query.count()==0
        data={'plan':{'plan_code':'PLN_test_master'},'amount':230000,'customer':{'email':owner.email,'customer_code':'CUS_master'},'subscription_code':'SUB_master','email_token':'private-cancel-token','next_payment_date':original.isoformat()+'Z'}
        assert webhook('subscription.create',data).status_code==200
        renewed=charge(owner,'master-renewal',original)
        monkeypatch.setattr(billing,'provider',lambda *a,**k:renewed)
        invoice={'subscription':{'subscription_code':'SUB_master'},'paid':True,'status':'success','transaction':{'reference':'master-renewal'},'period_end':billing.monthly_end(original).isoformat()+'Z'}
        assert webhook('invoice.update',invoice).status_code==200
        assert webhook('invoice.update',invoice).status_code==200
        db.session.refresh(owner);assert owner.master_expires_at>original
        assert MasterPayment.query.filter_by(status='success').count()==2
        assert webhook('invoice.payment_failed',{'subscription':{'subscription_code':'SUB_master'}}).status_code==200
        db.session.refresh(owner);assert owner.master_expires_at>original
        assert 'private-cancel-token' not in client(owner).get('/pro').text

def test_cancellation_retains_paid_access_and_is_owner_scoped(settings,monkeypatch):
    calls=[];monkeypatch.setattr(billing,'provider',lambda *a,**k:calls.append((a,k)) or {})
    with app.app_context():
        owner,other=player('cancel_master'),player('cancel_other');item=subscription(owner)
        item.status='active';item.subscription_code='SUB_master';item.email_token='server-secret';owner.master_expires_at=datetime.utcnow()+timedelta(days=10);db.session.commit()
        viewer=client(owner); csrf=token(viewer.get('/pro'))
        outsider=client(other); foreign_csrf=token(outsider.get('/pro'))
        assert outsider.post('/pro/cancel',data={'csrf_token':foreign_csrf,'confirmed':'yes'}).status_code==404
        viewer.post('/pro/cancel',data={'csrf_token':csrf});assert calls==[]
        for _ in range(2):viewer.post('/pro/cancel',data={'csrf_token':csrf,'confirmed':'yes'})
        db.session.refresh(owner);db.session.refresh(item)
        assert owner.master_active and item.status=='non-renewing' and len(calls)==1
        assert calls[0][0]==('POST','/subscription/disable')

def test_payment_callback_cannot_verify_another_account(settings,monkeypatch):
    with app.app_context():
        owner,other=player('verify_master'),player('verify_other');subscription(owner)
        viewer=client(other)
        assert viewer.get('/pro/verify?reference=master-initial').status_code==404
        assert viewer.get('/pro/verify?reference=bad%2Freference').status_code==404
        monkeypatch.setattr(billing,'provider',lambda *a,**k:charge(owner))
        assert client(owner).get('/pro/verify?reference=master-initial').status_code==302
        db.session.refresh(owner);assert owner.master_active

def test_monthly_billing_dates_and_wrong_plan(settings,monkeypatch):
    assert billing.monthly_end(datetime(2026,1,31)).date()==datetime(2026,2,28).date()
    assert billing.monthly_end(datetime(2026,12,10)).date()==datetime(2027,1,10).date()
    monkeypatch.setattr(billing,'provider',lambda *a,**k:dict(plan_code='PLN_test_master',amount=1000,currency='NGN',interval='monthly'))
    with app.app_context():
        owner=player('wrong_plan');viewer=client(owner);csrf=token(viewer.get('/pro'))
        viewer.post('/pro/checkout',data={'csrf_token':csrf,'renewal_consent':'yes'})
        assert MasterSubscription.query.count()==0
