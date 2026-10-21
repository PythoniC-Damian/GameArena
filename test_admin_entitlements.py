from datetime import datetime, timedelta
from app import app, db
from gamearena.models import CosmeticOwnership, WalletTransaction, MasterSubscription, MasterPayment
from gamearena.market import CATALOG
from gamearena.pro import deliver_due_reminders
from test_interface_contracts import player, client, token, event


def test_admin_collection_and_master_are_included_without_financial_records(monkeypatch):
    from gamearena import master_billing
    monkeypatch.setattr(master_billing, 'provider', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('No payment provider call expected')))
    with app.app_context():
        owner=player('included_admin'); owner.is_admin=True
        owner.wallet_balance=120; owner.wallet_bonus_balance=50; owner.wallet_winnings_balance=20
        db.session.commit(); viewer=client(owner)
        assert owner.master_active and owner.master_expires_at is None
        shop=viewer.get('/shop'); assert shop.status_code==200
        assert shop.text.count('data-owned="true"')==len(CATALOG)
        csrf=token(shop)
        for key in CATALOG:
            assert viewer.post('/shop/equip',data={'csrf_token':csrf,'item_key':key}).status_code==302
        assert viewer.post('/shop/emerald-bundle/buy',data={'csrf_token':csrf}).status_code==302
        membership=viewer.get('/pro'); assert membership.status_code==200
        assert 'Included with administrator access' in membership.text
        assert 'action="/pro/checkout"' not in membership.text
        assert viewer.post('/pro/checkout',data={'csrf_token':csrf},headers={'Accept':'application/json'}).json['checkout_url']=='/pro#appearance'
        assert viewer.post('/pro/appearance',json={'frame':'green','profile_theme':'forest'},headers={'X-CSRFToken':csrf}).status_code==200
        tournament=event('Admin included reminder'); now=datetime.utcnow()
        tournament.match_time=now+timedelta(minutes=20); db.session.commit()
        assert viewer.post(f'/pro/saved/{tournament.id}',json={'action':'reminder','enabled':True},headers={'X-CSRFToken':csrf}).status_code==200
        assert len(deliver_due_reminders(now))==1
        db.session.refresh(owner)
        assert (owner.wallet_balance,owner.wallet_bonus_balance,owner.wallet_winnings_balance)==(120,50,20)
        assert CosmeticOwnership.query.count()==WalletTransaction.query.count()==MasterSubscription.query.count()==MasterPayment.query.count()==0
        # Removing the role removes the free entitlement; nothing was recorded as purchased.
        owner.is_admin=False; db.session.commit()
        assert not owner.master_active
        assert viewer.post('/shop/equip',data={'csrf_token':csrf,'item_key':'emerald-bundle'}).status_code==403
        assert viewer.post('/pro/appearance',json={'frame':'green','profile_theme':'forest'},headers={'X-CSRFToken':csrf}).status_code==403


def test_regular_user_cannot_request_admin_entitlements():
    with app.app_context():
        owner=player('regular_no_included'); viewer=client(owner); csrf=token(viewer.get('/shop'))
        response=viewer.post('/shop/emerald-bundle/buy',data={'csrf_token':csrf,'confirm':'yes','price_gp':'0','is_admin':'true'})
        assert response.status_code==400
        assert viewer.post('/shop/equip',data={'csrf_token':csrf,'item_key':'emerald-bundle','is_admin':'true'}).status_code==403
        assert not owner.master_active
        owner.is_admin=True; owner.suspended=True; db.session.commit()
        assert not owner.master_active
