"""First-party cosmetics with durable ownership and atomic GP purchases."""
from datetime import datetime
from uuid import uuid4
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user, login_required
from gamearena.extensions import db
from gamearena.models import User, CosmeticOwnership, WalletTransaction
from gamearena.economy import spend_cash
from gamearena.gp import gp_to_naira

market = Blueprint('market', __name__)
CATALOG = {
    'arena-origin': dict(name='Arena Origin', description='The original emerald GameArena frame.', price=0, slot='frame', color='#17d3a0', glow='#17d3a022', theme='emerald'),
    'neon-circuit': dict(name='Neon Circuit', description='Electric cyan with a violet outer glow.', price=200, slot='frame', color='#38dcff', glow='#8b5cf644', theme='neon'),
    'solar-crown': dict(name='Solar Crown', description='A warm gold finish for your player profile.', price=400, slot='frame', color='#ffd064', glow='#b97e2633', theme='solar'),
    'ember-core': dict(name='Ember Core', description='An orange and crimson arena signature.', price=600, slot='frame', color='#fa8050', glow='#e13b4c33', theme='solar'),
    'emerald-card': dict(name='Emerald Vanguard', description='The signature emerald player card.', price=450, slot='card', theme='emerald'),
    'midnight-card': dict(name='Midnight Circuit', description='A violet circuit backdrop for your player card.', price=450, slot='card', theme='neon'),
    'arctic-card': dict(name='Arctic Signal', description='A cool blue backdrop for your player card.', price=350, slot='card', theme='arctic'),
    'solar-nameplate': dict(name='Solar Flare', description='A warm highlight for your name.', price=250, slot='nameplate', theme='solar'),
    'emerald-nameplate': dict(name='Emerald Pulse', description='The signature emerald nameplate.', price=250, slot='nameplate', theme='emerald'),
    'neon-nameplate': dict(name='Neon Afterhours', description='A violet highlight for your name.', price=250, slot='nameplate', theme='neon'),
    'vanguard-frame': dict(name='Vanguard Crest', description='An angular emerald avatar frame.', price=350, slot='frame', color='#73edc0', glow='#20cea222', theme='emerald'),
    'emerald-bundle': dict(name='Emerald Vanguard', description='Player card, Vanguard Crest frame and Emerald Pulse nameplate.', price=900, slot='bundle', theme='emerald', components=('emerald-card','vanguard-frame','emerald-nameplate')),
    'neon-bundle': dict(name='Neon Afterhours', description='Midnight Circuit card, Neon Circuit frame and Neon Afterhours nameplate.', price=850, slot='bundle', theme='neon', components=('midnight-card','neon-circuit','neon-nameplate')),
}
SLOTS = {'frame':'cosmetic_frame', 'card':'cosmetic_card', 'nameplate':'cosmetic_nameplate'}


def purchase_price(key, owned):
    item = CATALOG[key]
    if item['slot'] == 'bundle':
        return min(item['price'], sum(CATALOG[part]['price'] for part in item['components'] if part not in owned))
    return item['price']


def equipped_items(owner):
    return {slot: getattr(owner, column) or '' for slot, column in SLOTS.items()}


def accessible_items(owner):
    if owner.is_admin and not owner.suspended:
        return set(CATALOG)
    return {row.item_key for row in CosmeticOwnership.query.filter_by(user_id=owner.id).all()}


@market.route('/shop')
@login_required
def shop():
    owned = accessible_items(current_user)
    items = {key: dict(item, current_price=purchase_price(key, owned)) for key, item in CATALOG.items()}
    selected = request.args.get('item') if request.args.get('item') in items else 'emerald-bundle'
    return render_template('shop.html', catalog=items, owned=owned, equipped=equipped_items(current_user),
        selected_key=selected, selected_item=items[selected],
        shop_catalog=items, shop_equipped=equipped_items(current_user))

@market.route('/shop/<item_key>/buy', methods=['POST'])
@login_required
def buy(item_key):
    item = CATALOG.get(item_key)
    if not item: abort(404)
    owner = User.query.filter_by(id=current_user.id).with_for_update().populate_existing().one()
    if owner.suspended:
        db.session.rollback()
        abort(403)
    if owner.is_admin:
        db.session.rollback()
        flash('Your administrator account includes every shop item. Choose Equip to use it.', 'info')
        return redirect(url_for('.shop', item=item_key))
    owned = CosmeticOwnership.query.filter_by(user_id=owner.id, item_key=item_key).first()
    if owned:
        db.session.rollback()
        flash('You already own this item.', 'info')
        return redirect(url_for('.shop'))
    owned_keys = {row.item_key for row in CosmeticOwnership.query.filter_by(user_id=owner.id).all()}
    price = purchase_price(item_key, owned_keys)
    if request.form.get('confirm') != 'yes' or request.form.get('price_gp') != str(price):
        db.session.rollback()
        abort(400, description='Confirm the current GP price before purchasing.')
    cost = gp_to_naira(price) if price else 0
    bonus = min(owner.wallet_bonus_balance or 0, cost)
    if (owner.wallet_balance or 0) + bonus < cost:
        db.session.rollback()
        flash('Not enough GP. Top up your wallet first.', 'error')
        return redirect(url_for('.shop'))
    winnings = spend_cash(owner, cost - bonus)
    owner.wallet_bonus_balance = (owner.wallet_bonus_balance or 0) - bonus
    payment = None
    if cost:
        payment = WalletTransaction(user_id=owner.id, type='cosmetic_purchase', amount=cost,
            status='completed', completed_at=datetime.utcnow(), transaction_ref='shop_'+uuid4().hex,
            account_name=item['name'], bonus_spent=bonus, winnings_spent=winnings)
        db.session.add(payment)
        db.session.flush()
    for granted_key in (item_key, *item.get('components', ())):
        if granted_key not in owned_keys:
            db.session.add(CosmeticOwnership(user_id=owner.id, item_key=granted_key,
                transaction_id=payment.id if payment else None))
    db.session.commit()
    flash('Added to your collection. You can equip it now.', 'success')
    return redirect(url_for('.shop', item=item_key))

@market.route('/shop/equip', methods=['POST'])
@login_required
def equip():
    key = request.form.get('item_key', '')
    owner = User.query.filter_by(id=current_user.id).with_for_update().populate_existing().one()
    if owner.suspended:
        db.session.rollback()
        abort(403)
    slot = request.form.get('slot', 'frame')
    if slot not in SLOTS:
        db.session.rollback(); abort(400)
    if not key:
        setattr(owner, SLOTS[slot], None)
    else:
        item = CATALOG.get(key)
        owned = accessible_items(owner)
        if not item or key not in owned:
            db.session.rollback(); abort(403)
        parts = item.get('components', (key,))
        if any(part not in owned for part in parts):
            db.session.rollback(); abort(403)
        for part in parts:
            component = CATALOG[part]
            setattr(owner, SLOTS[component['slot']], part)
    db.session.commit()
    flash('Profile appearance saved.', 'success')
    return redirect(url_for('.shop', item=key))
