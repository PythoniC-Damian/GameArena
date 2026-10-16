"""Saved interface languages. Player content is never sent to a translation service."""
import json
from pathlib import Path
from flask import Blueprint, session, request, redirect, abort
from flask_login import current_user
from gamearena.extensions import db
from gamearena.models import UserSettings, User
LANGUAGES = {'en':'English', 'es':'Español', 'fr':'Français', 'pt':'Português'}
CATALOGS = {code:json.loads((Path(__file__).parent/'locales'/(code+'.json')).read_text(encoding='utf-8')) for code in LANGUAGES if code != 'en'}
i18n = Blueprint('i18n', __name__)

def language():
    if current_user.is_authenticated and current_user.settings:
        value = current_user.settings.language
    else:
        value = session.get('language', 'en')
    return value if value in LANGUAGES else 'en'

def translate(message):
    return CATALOGS.get(language(), {}).get(str(message), message)

@i18n.app_context_processor
def locale_context():
    code = language()
    return dict(t=translate, current_language=code, languages=LANGUAGES,
        interface_catalog=CATALOGS.get(code, {}))

@i18n.route('/language', methods=['POST'])
def choose():
    code = request.form.get('language')
    if code not in LANGUAGES: abort(400)
    if current_user.is_authenticated:
        db.session.execute(db.select(User).where(User.id == current_user.id).with_for_update())
        row = UserSettings.query.filter_by(user_id=current_user.id).first()
        if not row:
            row = UserSettings(user_id=current_user.id)
            db.session.add(row)
        row.language = code
        db.session.commit()
    session['language'] = code
    target = request.form.get('next', '/')
    if not target.startswith('/') or target.startswith('//') or '\\' in target or any(ord(c)<32 for c in target):
        target = '/'
    return redirect(target)
