"""Saved interface languages. Player content is never sent to a translation service."""
import json
from pathlib import Path
from flask import Blueprint, session, request, redirect, abort
from flask_login import current_user
from gamearena.extensions import db
from gamearena.models import UserSettings, User
REQUESTED_LANGUAGES = {'en': 'English', 'ar': 'العربية', 'be': 'Беларуская', 'ca': 'Català', 'zh-Hans': '简体中文', 'zh-Hant': '繁體中文', 'hr': 'Hrvatski', 'cs': 'Čeština', 'nl': 'Nederlands', 'fi': 'Suomi', 'fr': 'Français', 'de': 'Deutsch', 'he': 'עברית', 'id': 'Bahasa Indonesia', 'it': 'Italiano', 'kk': 'Қазақша', 'ko': '한국어', 'ms': 'Bahasa Melayu', 'nb': 'Norsk (Bokmål)', 'fa': 'فارسی', 'pl': 'Polski', 'pt-BR': 'Português (Brasil)', 'pt': 'Português', 'ro': 'Română', 'ru': 'Русский', 'sr': 'Српски', 'sk': 'Slovenčina', 'es': 'Español'}
LANGUAGES = {code:REQUESTED_LANGUAGES[code] for code in ('en','es','fr','pt')}

LANGUAGE_NAMES_EN = {'en': 'English', 'ar': 'Arabic', 'be': 'Belarusian', 'ca': 'Catalan', 'zh-Hans': 'Chinese (Simplified)', 'zh-Hant': 'Chinese (Traditional)', 'hr': 'Croatian', 'cs': 'Czech', 'nl': 'Dutch', 'fi': 'Finnish', 'fr': 'French', 'de': 'German', 'he': 'Hebrew', 'id': 'Indonesian', 'it': 'Italian', 'kk': 'Kazakh', 'ko': 'Korean', 'ms': 'Malay', 'nb': 'Norwegian (Bokmål)', 'fa': 'Persian', 'pl': 'Polish', 'pt-BR': 'Portuguese (Brazil)', 'pt': 'Portuguese', 'ro': 'Romanian', 'ru': 'Russian', 'sr': 'Serbian', 'sk': 'Slovak', 'es': 'Spanish'}
CATALOGS = {code:json.loads((Path(__file__).parent/'locales'/(code+'.json')).read_text(encoding='utf-8')) for code in LANGUAGES if code != 'en' and (Path(__file__).parent/'locales'/(code+'.json')).exists()}

i18n = Blueprint('i18n', __name__)

def language():
    override=request.args.get('lang')
    if (request.endpoint or '').startswith('legal.') and override in LANGUAGES:return override
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
    return dict(t=translate, current_language=code, languages=LANGUAGES, language_names_en=LANGUAGE_NAMES_EN, language_direction='rtl' if code in {'ar','he','fa'} else 'ltr',
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

@i18n.get('/languages')
def listing():
    from flask import render_template
    return render_template('languages.html')
