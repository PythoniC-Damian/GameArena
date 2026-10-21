"""Real ownership, exact ledger deductions and independent equipped cosmetics."""
from concurrent.futures import ThreadPoolExecutor
import importlib
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
import pytest
from app import app, db
from gamearena.market import CATALOG, purchase_price
from gamearena.models import User, CosmeticOwnership, WalletTransaction
from test_interface_contracts import player, client, token


def post(browser, path, data):
    return browser.post(path, data=dict(data, csrf_token=token(browser.get('/shop'))))


def buy(browser, key, price=None):
    return post(browser, f'/shop/{key}/buy', {'confirm':'yes','price_gp':str(CATALOG[key]['price'] if price is None else price)})


def test_bundle_deducts_once_grants_components_and_equips_separate_slots():
    with app.app_context():
        user=player('bundle_player');user.wallet_balance=1200;user.wallet_winnings_balance=300;user.wallet_bonus_balance=200;db.session.commit()
        browser=client(user)
        assert buy(browser,'emerald-bundle').status_code==302
        db.session.refresh(user)
        assert (user.wallet_balance,user.wallet_winnings_balance,user.wallet_bonus_balance)==(500,300,0)
        keys={row.item_key for row in CosmeticOwnership.query.filter_by(user_id=user.id)}
        assert keys=={'emerald-bundle',*CATALOG['emerald-bundle']['components']}
        ledger=WalletTransaction.query.filter_by(user_id=user.id,type='cosmetic_purchase').one()
        assert ledger.amount==900 and ledger.bonus_spent==200 and ledger.winnings_spent==0
        assert ledger.status=='completed' and ledger.public_transaction_id
        assert buy(browser,'emerald-bundle').status_code==302
        assert WalletTransaction.query.filter_by(user_id=user.id).count()==1
        assert post(browser,'/shop/equip',{'item_key':'emerald-bundle'}).status_code==302
        db.session.refresh(user)
        assert (user.cosmetic_card,user.cosmetic_nameplate,user.cosmetic_frame)==('emerald-card','emerald-nameplate','vanguard-frame')
        assert post(browser,'/shop/equip',{'slot':'card'}).status_code==302
        db.session.refresh(user)
        assert user.cosmetic_card is None and user.cosmetic_frame=='vanguard-frame' and user.cosmetic_nameplate=='emerald-nameplate'


def test_legacy_frame_and_bundle_completion_price_preserve_existing_purchase():
    with app.app_context():
        user=player('legacy_collection');user.wallet_balance=1000;db.session.commit();browser=client(user)
        assert buy(browser,'neon-circuit').status_code==302
        old=CosmeticOwnership.query.filter_by(user_id=user.id,item_key='neon-circuit').one();old_payment=old.transaction_id
        assert post(browser,'/shop/equip',{'item_key':'neon-circuit'}).status_code==302
        assert purchase_price('neon-bundle',{'neon-circuit'})==700
        # A stale quote cannot debit or grant anything.
        assert buy(browser,'neon-bundle',850).status_code==400
        assert buy(browser,'neon-bundle',700).status_code==302
        db.session.refresh(user);assert user.wallet_balance==100 and user.cosmetic_frame=='neon-circuit'
        assert CosmeticOwnership.query.filter_by(user_id=user.id,item_key='neon-circuit').one().transaction_id==old_payment


def test_purchase_requires_confirmation_funds_and_owned_equipment():
    with app.app_context():
        user=player('shop_guard');browser=client(user)
        assert post(browser,'/shop/solar-nameplate/buy',{'price_gp':'250'}).status_code==400
        assert buy(browser,'solar-nameplate').status_code==302
        assert CosmeticOwnership.query.count()==0 and WalletTransaction.query.count()==0
        assert post(browser,'/shop/equip',{'item_key':'solar-nameplate'}).status_code==403
        assert post(browser,'/shop/equip',{'slot':'wallet_balance'}).status_code==400
        assert browser.post('/shop/arena-origin/buy',data={'confirm':'yes','price_gp':'0'}).status_code==400
        assert buy(browser,'arena-origin').status_code==302
        assert WalletTransaction.query.count()==0


def test_cosmetics_render_on_owner_public_profile_and_match(monkeypatch):
    from test_competition_flow import fixture,check_in,start
    from gamearena.models import TournamentMatch
    with app.app_context():
        admin,users,event=fixture(monkeypatch)
        user=users[0];user.wallet_balance=1000;db.session.commit();browser=client(user)
        buy(browser,'emerald-bundle');post(browser,'/shop/equip',{'item_key':'emerald-bundle'})
        for path in ('/profile',f'/players/{user.id}'):
            page=browser.get(path)
            assert page.status_code==200
            assert 'data-arena-card="emerald-card"' in page.text
            assert 'data-arena-nameplate="emerald-nameplate"' in page.text
        check_in(admin,users,event);start(admin,event)
        match=TournamentMatch.query.filter((TournamentMatch.player_one_user_id==user.id)|(TournamentMatch.player_two_user_id==user.id)).one()
        page=browser.get(f'/match/{match.id}/play')
        assert page.status_code==200 and 'data-arena-nameplate="emerald-nameplate"' in page.text


def test_two_simultaneous_bundle_requests_only_charge_once():
    with app.app_context():
        user=player('parallel_bundle');user.wallet_balance=2000;db.session.commit();uid=user.id
    def purchase(_):
        with app.app_context():
            browser=client(db.session.get(User,uid))
            return buy(browser,'emerald-bundle').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(purchase,range(2)))==[302,302]
    with app.app_context():
        assert db.session.get(User,uid).wallet_balance==1100
        assert CosmeticOwnership.query.filter_by(user_id=uid).count()==4
        assert WalletTransaction.query.filter_by(user_id=uid).count()==1


def test_slot_migration_is_idempotent_and_preserves_existing_frames():
    with app.app_context():
        user=player('migration_frame');user.cosmetic_frame='neon-circuit';user.wallet_balance=321;db.session.commit()
        revision=importlib.import_module('migrations.versions.20261021_shop_collections')
        with db.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade();revision.upgrade()
        assert {'cosmetic_card','cosmetic_nameplate'} <= {c['name'] for c in inspect(db.engine).get_columns('user')}
        db.session.refresh(user);assert user.cosmetic_frame=='neon-circuit' and user.wallet_balance==321


def test_other_players_ownership_never_authorizes_equipment():
    with app.app_context():
        first=player('owner_one');second=player('owner_two')
        db.session.add(CosmeticOwnership(user_id=first.id,item_key='solar-nameplate'));db.session.commit()
        assert post(client(second),'/shop/equip',{'item_key':'solar-nameplate'}).status_code==403
        db.session.refresh(second);assert second.cosmetic_nameplate is None
