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
    'arena-origin': dict(name='Arena Origin', description='The original emerald GameArena frame.', price=0),
    'neon-circuit': dict(name='Neon Circuit', description='Electric cyan with a violet outer glow.', price=200),
    'solar-crown': dict(name='Solar Crown', description='A warm gold finish for your player profile.', price=400),
    'ember-core': dict(name='Ember Core', description='An orange and crimson arena signature.', price=600),
}

@market.route('/shop')
@login_required
def shop():
    owned = {row.item_key for row in CosmeticOwnership.query.filter_by(user_id=current_user.id).all()}
    return render_template('shop.html', catalog=CATALOG, owned=owned)

@market.route('/shop/<item_key>/buy', methods=['POST'])
@login_required
def buy(item_key):
    item = CATALOG.get(item_key)
    if not item: abort(404)
    owner = User.query.filter_by(id=current_user.id).with_for_update().populate_existing().one()
    if owner.suspended:
        db.session.rollback()
        abort(403)
    owned = CosmeticOwnership.query.filter_by(user_id=owner.id, item_key=item_key).first()
    if owned:
        db.session.rollback()
        flash('You already own this item.', 'info')
        return redirect(url_for('.shop'))
    if request.form.get('confirm') != 'yes' or request.form.get('price_gp') != str(item['price']):
        db.session.rollback()
        abort(400, description='Confirm the current GP price before purchasing.')
    cost = gp_to_naira(item['price']) if item['price'] else 0
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
    db.session.add(CosmeticOwnership(user_id=owner.id, item_key=item_key,
        transaction_id=payment.id if payment else None))
    db.session.commit()
    flash('Added to your collection. You can equip it now.', 'success')
    return redirect(url_for('.shop'))

@market.route('/shop/equip', methods=['POST'])
@login_required
def equip():
    key = request.form.get('item_key', '')
    owner = User.query.filter_by(id=current_user.id).with_for_update().populate_existing().one()
    if owner.suspended:
        db.session.rollback()
        abort(403)
    if key and (key not in CATALOG or not CosmeticOwnership.query.filter_by(user_id=owner.id, item_key=key).first()):
        db.session.rollback()
        abort(403)
    owner.cosmetic_frame = key or None
    db.session.commit()
    flash('Profile appearance saved.', 'success')
    return redirect(url_for('.shop'))
