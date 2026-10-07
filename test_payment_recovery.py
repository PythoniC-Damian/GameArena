import hashlib
import hmac
import json
from unittest.mock import Mock

import pytest
import app as application
from app import app, db, UserTournament
from test_interface_contracts import player, client, token, event


def setup_entry():
    owner = player('payment_recovery')
    tournament = event(fee=3000)
    entry = UserTournament(user_id=owner.id, tournament_id=tournament.id,
                           payment_status='pending', amount_paid=3000,
                           transaction_ref='new-checkout-reference')
    db.session.add(entry)
    db.session.commit()
    transaction = {'status': 'success', 'reference': 'earlier-paid-reference',
                   'amount': 314721, 'requested_amount': 300000, 'fees': 14721,
                   'currency': 'NGN',
                   'metadata': {'user_id': owner.id, 'tournament_id': tournament.id}}
    return owner, tournament, entry, transaction


def test_webhook_recovers_replaced_reference_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(application, 'PAYSTACK_SECRET_KEY', 'test-webhook-secret')
    monkeypatch.setattr(application, 'create_and_emit_notification', Mock())
    monkeypatch.setattr(application, 'award_achievements_for_user', Mock())
    with app.app_context():
        owner, tournament, entry, transaction = setup_entry()
        # Changing the advertised fee must not change an existing checkout amount.
        tournament.entry_fee = 4000
        db.session.commit()
        body = json.dumps({'event': 'charge.success', 'data': transaction}).encode()
        signature = hmac.new(b'test-webhook-secret', body, hashlib.sha512).hexdigest()
        viewer = app.test_client()
        for _ in range(2):
            response = viewer.post('/paystack/webhook', data=body,
                content_type='application/json', headers={'x-paystack-signature': signature})
            assert response.status_code == 200
        db.session.expire_all()
        assert db.session.get(UserTournament, entry.id).payment_status == 'paid'
        assert db.session.get(UserTournament, entry.id).transaction_ref == transaction['reference']
        assert application.create_and_emit_notification.call_count == 1
        assert owner.wallet_balance == 0


@pytest.mark.parametrize('change', [
    {'status': 'pending'}, {'amount': 1}, {'currency': 'USD'},
    {'requested_amount': 299999}, {'fees': 100},
    {'metadata': 'invalid'}, {'metadata': {'user_id': 999, 'tournament_id': 1}},
    {'metadata': {'type': 'wallet_deposit', 'user_id': 1, 'tournament_id': 1}},
])
def test_recovery_rejects_unmatched_or_unsuccessful_payment(change):
    with app.app_context():
        owner, tournament, entry, transaction = setup_entry()
        transaction.update(change)
        ok, _ = application.apply_tournament_payment(entry, transaction)
        assert not ok
        db.session.rollback()
        assert db.session.get(UserTournament, entry.id).payment_status == 'pending'


def test_callback_recovers_old_reference_only_for_its_owner(monkeypatch):
    monkeypatch.setattr(application, 'create_and_emit_notification', Mock())
    monkeypatch.setattr(application, 'award_achievements_for_user', Mock())
    with app.app_context():
        owner, tournament, entry, transaction = setup_entry()
        monkeypatch.setattr(application, 'verify_paystack_reference', lambda _: transaction)
        other = client(player('other_payment_player'))
        other.get('/verify-payment?reference=earlier-paid-reference')
        assert db.session.get(UserTournament, entry.id).payment_status == 'pending'
        response = client(owner).get('/verify-payment?reference=earlier-paid-reference')
        assert response.location.endswith('/dashboard')
        db.session.expire_all()
        assert db.session.get(UserTournament, entry.id).payment_status == 'paid'


def test_retry_confirms_existing_success_without_opening_checkout(monkeypatch):
    monkeypatch.setattr(application, 'create_and_emit_notification', Mock())
    monkeypatch.setattr(application, 'award_achievements_for_user', Mock())
    post = Mock(side_effect=AssertionError('Must not open another checkout'))
    monkeypatch.setattr(application.requests, 'post', post)
    with app.app_context():
        owner, tournament, entry, transaction = setup_entry()
        transaction['reference'] = entry.transaction_ref
        monkeypatch.setattr(application, 'verify_paystack_reference', lambda _: transaction)
        viewer = client(owner)
        csrf = token(viewer.get('/profile'))
        response = viewer.post(f'/initialize-payment/{tournament.id}', data={'csrf_token': csrf})
        assert response.json['already_paid'] is True
        assert post.call_count == 0
