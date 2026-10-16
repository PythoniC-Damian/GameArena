"""Ownership, wallet source accounting, organiser authorization and saved locale."""
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import app, db, User, WalletTransaction
from gamearena.models import CosmeticOwnership, OrganizerDraft, UserSettings, Tournament
from gamearena.economy import spend_cash, refund_cash
from gamearena.gp import gp_to_naira
from test_interface_contracts import player, client, token


def post(browser, url, data, page='/shop'):
    return browser.post(url, data=dict(data, csrf_token=token(browser.get(page))))


def test_shop_atomic_owned_equipped_and_bonus_first():
    with app.app_context():
        owner=player('shop_owner');owner.wallet_balance=gp_to_naira('1000');owner.wallet_bonus_balance=gp_to_naira('100');db.session.commit()
        browser=client(owner)
        amount=gp_to_naira('200')
        assert post(browser,'/shop/neon-circuit/buy',{'price_gp':'200','confirm':'yes'}).status_code==302
        db.session.refresh(owner)
        assert owner.wallet_balance==gp_to_naira('900') and owner.wallet_bonus_balance==0
        payment=WalletTransaction.query.filter_by(type='cosmetic_purchase').one()
        assert payment.amount==amount and payment.bonus_spent==gp_to_naira('100')
        assert payment.transaction_ref.startswith('shop_')
        assert post(browser,'/shop/neon-circuit/buy',{'price_gp':'200','confirm':'yes'}).status_code==302
        assert WalletTransaction.query.count()==1 and CosmeticOwnership.query.count()==1
        assert post(browser,'/shop/equip',{'item_key':'solar-crown'}).status_code==403
        assert post(browser,'/shop/equip',{'item_key':'neon-circuit'}).status_code==302
        db.session.refresh(owner);assert owner.profile_frame=='neon-circuit' and not owner.master_active
        assert 'neon-circuit' in browser.get('/profile').text
        assert 'Cosmetic purchase' in browser.get(f'/wallet/transactions/{payment.id}').text
        assert browser.get('/wallet/transactions?category=cosmetic_purchase').status_code==200


def test_shop_tamper_and_insufficient_funds_and_csrf():
    with app.app_context():
        owner=player('shop_poor');browser=client(owner)
        assert browser.post('/shop/arena-origin/buy',data={'price_gp':'0','confirm':'yes'}).status_code==400
        assert post(browser,'/shop/neon-circuit/buy',{'price_gp':'0','confirm':'yes'}).status_code==400
        assert post(browser,'/shop/neon-circuit/buy',{'price_gp':'200','confirm':'yes'}).status_code==302
        assert CosmeticOwnership.query.count()==0 and WalletTransaction.query.count()==0
        assert post(browser,'/shop/arena-origin/buy',{'price_gp':'0','confirm':'yes'}).status_code==302
        assert CosmeticOwnership.query.count()==1 and WalletTransaction.query.count()==0


def test_cash_sources_and_refund_do_not_convert_bonus():
    with app.app_context():
        owner=player('source_owner');owner.wallet_balance=1000;owner.wallet_winnings_balance=600;owner.wallet_bonus_balance=900
        used=spend_cash(owner,700)
        assert used==300 and owner.wallet_balance==300 and owner.wallet_winnings_balance==300
        transaction=WalletTransaction(amount=700,winnings_spent=used)
        refund_cash(owner,transaction)
        assert owner.wallet_balance==1000 and owner.wallet_winnings_balance==600 and owner.wallet_bonus_balance==900
        with pytest.raises(ValueError):spend_cash(owner,1001)


def test_organizer_draft_requires_owner_and_admin_review():
    with app.app_context():
        owner=player('creator');other=player('not_creator');admin=player('review_admin');admin.is_admin=True;db.session.commit()
        browser=client(owner)
        data=dict(name='Arena test cup',game='Free Fire',rules='First to the published score wins. No cheating.',entry_gp='100',prize_gp='1000',capacity='16',starts_at=(datetime.utcnow()+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'))
        assert post(browser,'/organizers',data,page='/organizers').status_code==302
        row=OrganizerDraft.query.one();assert row.status=='draft' and Tournament.query.count()==0
        stranger=client(other)
        assert stranger.get(f'/organizers/{row.id}/edit').status_code==404
        assert browser.get(f'/organizers/{row.id}/edit').status_code==200
        assert post(browser,f'/organizers/{row.id}/edit',dict(data,name='Updated arena cup'),page='/organizers').status_code==302
        db.session.refresh(row);assert row.name=='Updated arena cup'
        assert post(stranger,f'/organizers/{row.id}/submit',{},page='/organizers').status_code==404
        assert post(browser,f'/organizers/{row.id}/submit',{},page='/organizers').status_code==302
        assert post(browser,f'/organizers/{row.id}/review',{'action':'approve','checked':'yes'},page='/organizers').status_code==403
        reviewer=client(admin)
        assert post(reviewer,f'/organizers/{row.id}/review',{'action':'approve'},page='/organizers').status_code==400
        assert post(reviewer,f'/organizers/{row.id}/review',{'action':'approve','checked':'yes'},page='/organizers').status_code==302
        db.session.refresh(row);assert row.status=='published' and row.tournament_id
        assert post(reviewer,f'/organizers/{row.id}/review',{'action':'approve','checked':'yes'},page='/organizers').status_code==409
        assert Tournament.query.count()==1
        assert browser.get(f'/organizers/{row.id}/participants.csv').status_code==200
        assert stranger.get(f'/organizers/{row.id}/participants.csv').status_code==404


def test_language_persists_without_translating_user_content():
    with app.app_context():
        owner=player('Settings');browser=client(owner)
        assert post(browser,'/language',{'language':'es','next':'/shop'}).location=='/shop'
        html=browser.get('/shop').text
        assert 'lang="es"' in html and 'Tienda Arena' in html and '>Settings<' in html
        assert UserSettings.query.filter_by(user_id=owner.id).one().language=='es'
        assert post(browser,'/language',{'language':'es','next':'//evil.example'}).location=='/'
        assert post(browser,'/language',{'language':'zz'}).status_code==400
        assert client(owner).get('/shop').text.count('Tienda Arena')>0


@pytest.mark.parametrize('code,heading', [('en','Arena Shop'),('es','Tienda Arena'),('fr','Boutique Arena'),('pt','Loja Arena')])
def test_each_language_renders_core_flows(code, heading):
    with app.app_context():
        owner=player('locale_player');browser=client(owner)
        assert post(browser,'/language',{'language':code,'next':'/shop'}).status_code==302
        assert heading in browser.get('/shop').text
        for path in ['/wallet','/organizers','/settings','/tournaments']:
            response=browser.get(path)
            assert response.status_code==200 and f'lang="{code}"' in response.text
        guest=app.test_client()
        csrf=token(guest.get('/register'))
        assert guest.post('/language',data={'language':code,'csrf_token':csrf,'next':'/register'}).status_code==302
        assert f'lang="{code}"' in guest.get('/register').text


def test_concurrent_cosmetic_buy_charges_once():
    with app.app_context():
        owner=player('shop_concurrent');owner.wallet_balance=1000;db.session.commit()
        owner_id=owner.id
        clients=[client(owner),client(owner)];tokens=[token(c.get('/shop')) for c in clients]
        db.session.commit()
    def buy(index):
        return clients[index].post('/shop/neon-circuit/buy', data={'csrf_token':tokens[index],'price_gp':'200','confirm':'yes'})
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses=list(executor.map(buy,range(2)))
    assert all(response.status_code==302 for response in responses)
    with app.app_context():
        assert db.session.get(User,owner_id).wallet_balance==800
        assert CosmeticOwnership.query.count()==1 and WalletTransaction.query.count()==1
