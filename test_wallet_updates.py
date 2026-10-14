"""Wallet accounting, account resolution and receipt privacy regressions."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import app as application
from app import app, db, WalletTransaction
from test_interface_contracts import player, client, token

BANKS = [{'name': 'Test Bank', 'code': '999'}]


def setup(monkeypatch):
    monkeypatch.setattr(application, 'PAYSTACK_SECRET_KEY', 'sk_test_fake_only')
    monkeypatch.setattr(application, 'create_and_emit_notification', lambda *a, **kw: None)
    monkeypatch.setattr(application, '_supported_banks_cache', {'expires': float('inf'), 'banks': BANKS})
    owner = player('wallet_owner'); owner.wallet_balance = 1000; db.session.commit()
    browser = client(owner)
    return owner, browser, {'X-CSRFToken': token(browser.get('/wallet'))}


def verified(owner, **changes):
    details = {'user_id': owner.id, 'bank_code': '999', 'bank_name': 'Test Bank', 'account_number': '0000000000', 'account_name': 'TEST RECIPIENT'}
    details.update(changes)
    return application.wallet_account_signer().dumps(details)


def payload(owner, **changes):
    data = {'amount': 300, 'bank_name': 'Untrusted browser name', 'bank_code': '999', 'account_number': '0000000000', 'idempotency_key': 'test_request_123456789', 'verification_token': verified(owner)}
    data.update(changes)
    return data


def provider(status='success'):
    def call(method, path, **kwargs):
        if path == '/bank/resolve': return {'account_number':'0000000000','account_name':'TEST RECIPIENT'}
        if path == '/transferrecipient': return {'recipient_code':'RCP_test'}
        if path == '/transfer': return {'status':status,'transfer_code':'TRF_test'}
        raise AssertionError(path)
    return call


def test_history_is_bounded_and_receipts_are_owner_only(monkeypatch):
    with app.app_context():
        owner, browser, headers = setup(monkeypatch)
        for i in range(26): db.session.add(WalletTransaction(user_id=owner.id,type='deposit',amount=i+100,status='pending',transaction_ref=f'dep_test_{i:016}'))
        db.session.commit()
        home=browser.get('/wallet'); history=browser.get('/wallet/transactions'); page2=browser.get('/wallet/transactions?page=2')
        assert home.status_code == history.status_code == page2.status_code == 200
        assert home.text.count('data-wallet-transaction') == 5
        assert history.text.count('data-wallet-transaction') == 20
        assert page2.text.count('data-wallet-transaction') == 6
        assert 'View all transaction history' in home.text
        row=WalletTransaction.query.first(); receipt=browser.get(f'/wallet/transactions/{row.id}')
        assert row.transaction_ref in receipt.text and 'GameArena transaction ID' in receipt.text and 'Pending' in receipt.text
        assert 'no-store' in receipt.headers['Cache-Control']
        other=player('wallet_other')
        assert client(other).get(f'/wallet/transactions/{row.id}').status_code == 404


def test_resolution_returns_provider_name_and_requires_csrf(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        call=Mock(side_effect=provider());monkeypatch.setattr(application,'paystack_transfer_request',call)
        data={'bank_code':'999','account_number':'0000000000'}
        assert browser.post('/wallet/resolve-account',json=data).status_code == 400
        response=browser.post('/wallet/resolve-account',json=data,headers=headers)
        assert response.status_code == 200 and response.json['account_name'] == 'TEST RECIPIENT'
        assert 'no-store' in response.headers['Cache-Control']
        assert application.wallet_account_signer().loads(response.json['verification_token'])['user_id'] == owner.id
        data['bank_code']='888'
        assert browser.post('/wallet/resolve-account',json=data,headers=headers).status_code == 400


@pytest.mark.parametrize('changes',[{'verification_token':'invalid'},{'account_number':'1111111111'},{'bank_code':'888'}])
def test_tampered_confirmation_cannot_debit(monkeypatch,changes):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        call=Mock();monkeypatch.setattr(application,'paystack_transfer_request',call)
        assert browser.post('/wallet/withdraw',json=payload(owner,**changes),headers=headers).status_code == 400
        db.session.refresh(owner);assert owner.wallet_balance == 1000 and WalletTransaction.query.count() == 0
        call.assert_not_called()


def test_success_is_idempotent_and_stores_real_recipient(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        call=Mock(side_effect=provider());monkeypatch.setattr(application,'paystack_transfer_request',call)
        data=payload(owner)
        response=browser.post('/wallet/withdraw',json=data,headers=headers)
        assert response.status_code == 202 and response.json['withdrawal_status']=='completed'
        again=browser.post('/wallet/withdraw',json=data,headers=headers)
        assert again.json['reference']==response.json['reference'] and call.call_count==3
        row=WalletTransaction.query.one();db.session.refresh(owner)
        assert owner.wallet_balance==700 and row.account_name=='TEST RECIPIENT' and row.bank_name=='Test Bank'
        receipt=browser.get(response.json['receipt_url'])
        assert 'TEST RECIPIENT' in receipt.text and 'TRF_test' in receipt.text and 'Successful' in receipt.text
        assert browser.post('/wallet/withdraw',json=payload(owner,amount=200),headers=headers).status_code==409


def test_conclusive_failure_refunds_once_and_explains_setup(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        monkeypatch.setattr(application,'paystack_transfer_request',Mock(side_effect=ValueError('Transfers are not enabled for starter businesses')))
        response=browser.post('/wallet/withdraw',json=payload(owner),headers=headers)
        assert response.json['withdrawal_status']=='failed' and 'not enabled' in response.json['message']
        row=WalletTransaction.query.one();application.release_failed_withdrawal(row.id,'duplicate event')
        db.session.refresh(owner);assert owner.wallet_balance==1000


def test_transfer_timeout_keeps_reservation_and_repeat_does_not_resend(monkeypatch):
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        regular=provider()
        def timeout(method,path,**kwargs):
            if path=='/transfer':raise TimeoutError('unknown response')
            return regular(method,path,**kwargs)
        call=Mock(side_effect=timeout);monkeypatch.setattr(application,'paystack_transfer_request',call)
        data=payload(owner);response=browser.post('/wallet/withdraw',json=data,headers=headers)
        assert response.json['withdrawal_status']=='processing'
        browser.post('/wallet/withdraw',json=data,headers=headers)
        assert call.call_count==3
        db.session.refresh(owner);assert owner.wallet_balance==700
        row=WalletTransaction.query.one();application.complete_withdrawal(row.id,'TRF_confirmed');application.complete_withdrawal(row.id,'TRF_confirmed')
        db.session.refresh(owner);assert owner.wallet_balance==700


def test_invalid_provider_json_is_not_conclusive_failure(monkeypatch):
    with app.app_context():
        monkeypatch.setattr(application,'PAYSTACK_SECRET_KEY','sk_test_fake_only')
        response=Mock(ok=True,status_code=200);response.json.side_effect=ValueError('bad json')
        monkeypatch.setattr(application.requests,'request',Mock(return_value=response))
        with pytest.raises(RuntimeError):application.paystack_transfer_request('POST','/transfer')


@pytest.mark.parametrize('code,message', [(503,'Service unavailable'), (400,'Duplicate transfer reference'), (409,'Conflict')])
def test_ambiguous_provider_errors_are_not_refunded(monkeypatch, code, message):
    with app.app_context():
        monkeypatch.setattr(application,'PAYSTACK_SECRET_KEY','sk_test_fake_only')
        response=Mock(ok=False,status_code=code)
        response.json.return_value={'status':False,'message':message}
        monkeypatch.setattr(application.requests,'request',Mock(return_value=response))
        with pytest.raises(RuntimeError):application.paystack_transfer_request('POST','/transfer')
