"""Scoped settings saves keep other categories unchanged."""
import re
from urllib.parse import urlparse
from flask import request, redirect, url_for, flash, abort
from flask_login import current_user
from gamearena.extensions import db
from gamearena.models import User

SECTIONS = {
 'account':('Account','Username, email, photo and bio','user'),
 'privacy':('Privacy & security','Profile visibility, messages and blocked players','shield'),
 'notifications':('Notifications','Tournament, payment and chat updates','bell'),
 'gaming':('Gaming','Preferred games and game IDs','trophy'),
 'appearance':('Appearance & accessibility','Light/dark theme, motion and text size','settings'),
 'language':('Language','English, Spanish, French and Portuguese','chat'),
 'data':('Account data & support','Export data, account requests and help','download'),
}


def save_section(section, preferences):
    if current_user.suspended: abort(403)
    def back(message, category='error'):
        flash(message,category);return redirect(url_for('settings',section=section))
    if section=='account':
        username=request.form.get('username','').strip();bio=request.form.get('bio','').strip()
        avatar=request.form.get('avatar_url',current_user.avatar_url or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{3,150}',username):return back('Username must be 3-150 letters, numbers, or underscores.')
        if User.query.filter(db.func.lower(User.username)==username.lower(),User.id!=current_user.id).first():return back('That username is already in use.')
        if len(bio)>500 or len(avatar)>500:return back('Profile information is too long.')
        if avatar and avatar!=current_user.avatar_url:
            parsed=urlparse(avatar)
            if not (avatar.startswith('/static/') and '..' not in parsed.path.split('/') or parsed.scheme=='https' and parsed.hostname=='images.unsplash.com' and not parsed.username and not parsed.password):
                return back('Choose a supported profile photo.')
        current_user.username=username;current_user.bio=bio or None;current_user.avatar_url=avatar or None
    elif section in {'notifications','privacy','appearance'}:
        fields={'notifications':('tournament_notifications','match_notifications','wallet_notifications','chat_notifications','marketing_notifications'),
                'privacy':('profile_public','allow_direct_messages'),'appearance':('reduce_motion','larger_text')}[section]
        if section=='appearance':
            theme=request.form.get('theme',preferences.theme)
            if theme not in {'dark','light'}:return back('Choose Dark or Light for your theme.')
            preferences.theme=theme
        for field in fields:setattr(preferences,field,request.form.get(field)=='on')
    elif section=='gaming':
        preferences.preferred_games=list(dict.fromkeys(value.strip() for value in request.form.getlist('preferred_games') if 0<len(value.strip())<=100))[:10]
        ids={}
        for line in request.form.get('game_ids','').splitlines()[:20]:
            if ':' not in line:continue
            game,value=(part.strip() for part in line.split(':',1))
            if 0<len(game)<=100 and 0<len(value)<=150:ids[game]=value
        preferences.game_ids=ids
    else:abort(405)
    db.session.commit()
    return back('Settings updated.','success')
