"""Abuse controls and invalid-input regressions for the wallet audit."""
from unittest.mock import Mock
import pytest
import app as application
from app import app, db
from sqlalchemy import event as sql_event
from test_interface_contracts import ready_event, player, client, token, event


def test_withdrawal_throttle_runs_before_provider_and_persists(monkeypatch):
    with app.app_context():
        owner=player('limited_wallet');browser=client(owner)
        headers={'X-CSRFToken':token(browser.get('/wallet')),'Accept':'application/json'}
        monkeypatch.setitem(application.RATE_LIMITS,'wallet_withdraw_user',(1,60))
        transfer=Mock(return_value={'status':'test-no-money-moved'})
        monkeypatch.setattr(application,'request_wallet_withdrawal',transfer)
        assert browser.post('/wallet/withdraw',json={'amount':100},headers=headers).status_code==200
        denied=browser.post('/wallet/withdraw',json={'amount':100},headers=dict(headers,**{'X-Forwarded-For':'198.51.100.20'}))
        assert denied.status_code==429 and denied.headers.get('Retry-After') and transfer.call_count==1
        assert browser.post('/wallet/withdraw',json={'amount':100}).status_code==400


def test_withdraw_limits_do_not_block_other_accounts_behind_shared_proxy(monkeypatch):
    with app.app_context():
        first,second=player('first_wallet'),player('second_wallet')
        browsers=[client(first),client(second)]
        headers=[{'X-CSRFToken':token(b.get('/wallet')),'Accept':'application/json'} for b in browsers]
    monkeypatch.setitem(application.RATE_LIMITS,'wallet_withdraw_user',(1,60))
    transfer=Mock(return_value={'status':'test-no-money-moved'})
    monkeypatch.setattr(application,'request_wallet_withdrawal',transfer)
    assert browsers[0].post('/wallet/withdraw',json={'amount':100},headers=headers[0]).status_code==200
    assert browsers[0].post('/wallet/withdraw',json={'amount':100},headers=headers[0]).status_code==429
    assert browsers[1].post('/wallet/withdraw',json={'amount':100},headers=headers[1]).status_code==200
    assert transfer.call_count==2

@pytest.mark.parametrize('body',[[1],True,False,0,None,'not-an-object'])
def test_financial_routes_reject_non_object_json(body):
    with app.app_context():
        browser=client(player('invalid_json'));headers={'X-CSRFToken':token(browser.get('/wallet'))}
        for url in ['/wallet/withdraw','/wallet/initialize-deposit','/wallet/resolve-account','/tournaments/999999/pay-gp']:
            assert browser.post(url,json=body,headers=headers).status_code==400


def test_oversized_body_is_rejected_before_financial_processing(monkeypatch):
    with app.app_context():
        browser=client(player('bounded_body'));headers={'X-CSRFToken':token(browser.get('/wallet'))}
        transfer=Mock();monkeypatch.setattr(application,'request_wallet_withdrawal',transfer)
        response=browser.post('/wallet/withdraw',data='x'*(app.config['MAX_CONTENT_LENGTH']+1),content_type='application/json',headers=headers)
        assert response.status_code==413 and not transfer.called


def test_reading_free_join_confirmation_does_not_lock_event():
    with app.app_context():
        owner=player('read_only_join');browser=client(owner);cup=ready_event(event(fee=0),owner);statements=[]
        def collect(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
        sql_event.listen(db.engine,'before_cursor_execute',collect)
        try:
            assert browser.get(f'/join-tournament/{cup.id}').status_code==200
            assert not any('FOR UPDATE' in sql.upper() for sql in statements)
        finally:sql_event.remove(db.engine,'before_cursor_execute',collect)


def test_untrusted_receipt_text_is_html_escaped():
    from gamearena.models import WalletTransaction
    with app.app_context():
        owner=player('receipt_escape');browser=client(owner)
        row=WalletTransaction(user_id=owner.id,type='withdrawal',amount=100,status='completed',transaction_ref='test-escape-only',account_name='<script>alert(1)</script>')
        db.session.add(row);db.session.commit()
        response=browser.get(f'/wallet/transactions/{row.id}')
        assert response.status_code==200 and '<script>alert(1)</script>' not in response.text
        assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text


def test_legacy_amount_input_is_bounded_before_provider(monkeypatch):
    from test_wallet_updates import setup,payload
    with app.app_context():
        owner,browser,headers=setup(monkeypatch)
        provider=Mock();monkeypatch.setattr(application.requests,'post',provider)
        assert browser.post('/wallet/initialize-deposit',json={'amount':'9'*5000},headers=headers).status_code==400
        data=payload(owner);data['amount']='9'*5000
        assert browser.post('/wallet/withdraw',json=data,headers=headers).status_code==400
        assert not provider.called
