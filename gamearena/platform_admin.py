"""Bounded, server-owned platform configuration; never edit secrets or ledger data."""
import os
import re
from datetime import datetime
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from sqlalchemy.dialects.postgresql import insert
from gamearena.extensions import db
from gamearena.models import PlatformSetting

platform_admin = Blueprint('platform_admin', __name__)


def setting(key):
    cache = g.setdefault('platform_settings', {})
    if key not in cache:
        row = db.session.get(PlatformSetting, key)
        cache[key] = row.value if row else {}
    return cache[key]


def catalogue(lock=False):
    from gamearena.market import CATALOG
    if lock:
        row = PlatformSetting.query.filter_by(key='shop_catalog').with_for_update().populate_existing().first()
        overrides = row.value if row else {}
    else:
        overrides = setting('shop_catalog')
    return {key: dict(item, **{field: value for field, value in overrides.get(key, {}).items()
        if field in {'price', 'name', 'description'}}) for key, item in CATALOG.items()}


def save_setting(key, value):
    db.session.execute(insert(PlatformSetting).values(key=key, value=value,
        updated_by=current_user.id, updated_at=datetime.utcnow()).on_conflict_do_update(
        index_elements=['key'], set_=dict(value=value, updated_by=current_user.id, updated_at=datetime.utcnow())))
    g.pop('platform_settings', None)


@platform_admin.app_context_processor
def basics():
    values = setting('basics')
    return dict(platform_basics=values, support_email=values.get('support_email') or
        os.environ.get('GAMEARENA_SUPPORT_EMAIL', 'jegzdami@gmail.com'))


@platform_admin.route('/admin/platform', methods=['GET', 'POST'])
@login_required
def dashboard():
    if not current_user.is_admin or current_user.suspended:
        abort(403)
    from gamearena.market import CATALOG
    errors = []
    if request.method == 'POST':
        if request.form.get('section') == 'shop':
            values = {}
            for key in CATALOG:
                price = request.form.get('price__' + key, '')
                name = request.form.get('name__' + key, '').strip()
                description = request.form.get('description__' + key, '').strip()
                if not re.fullmatch(r'\d{1,7}', price) or not 0 <= int(price) <= 1000000 or not 2 <= len(name) <= 100 or not 5 <= len(description) <= 500:
                    errors.append('Check the name, description and whole GP price for ' + CATALOG[key]['name'] + '.')
                else:
                    values[key] = dict(price=int(price), name=name, description=description)
            if not errors:
                save_setting('shop_catalog', values)
        elif request.form.get('section') == 'basics':
            email = request.form.get('support_email', '').strip()
            announcement = request.form.get('announcement', '').strip()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 150 or len(announcement) > 500:
                errors.append('Enter a valid support email and an announcement of at most 500 characters.')
            if not errors:
                save_setting('basics', dict(support_email=email, announcement=announcement,
                    pro_promotion=request.form.get('pro_promotion') == 'yes'))
        else:
            abort(400)
        if not errors:
            db.session.commit()
            flash('Platform settings saved. Existing purchases and balances are unchanged.', 'success')
            return redirect(url_for('.dashboard'))
        db.session.rollback()
    return render_template('admin_platform.html', catalog=catalogue(), errors=errors, payouts_enabled=current_app.config.get('WITHDRAWALS_ENABLED',False), paystack_configured=bool(os.environ.get('PAYSTACK_SECRET_KEY'))), 400 if errors else 200


@platform_admin.app_template_filter('clean_currency_text')
def clean_currency_text(text):
    value = str(text or '')
    for _ in range(2):
        value = value.replace('\u00e2\u201a\u00a6', '\u20a6').replace('\u00e2\x82\u00a6', '\u20a6')
    return value
