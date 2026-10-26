"""Individual, server-resolved community mentions; never broadcast tags."""
import re
from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required
from markupsafe import Markup, escape
from sqlalchemy import func, select
from gamearena.extensions import db
from gamearena.models import User, UserBlock

chat_mentions = Blueprint('chat_mentions', __name__)
TOKEN = re.compile(r'(?<![A-Za-z0-9_@])@([A-Za-z0-9_]{1,150})(?![A-Za-z0-9_])')
RESERVED = {'all', 'everyone', 'here'}


def eligible_users(sender_id):
    blocked = select(UserBlock.blocked_id).where(UserBlock.blocker_id == sender_id)
    blockers = select(UserBlock.blocker_id).where(UserBlock.blocked_id == sender_id)
    return User.query.filter(User.suspended.is_(False), ~User.id.in_(blocked), ~User.id.in_(blockers))


@chat_mentions.get('/chat/mentions')
@login_required
def suggestions():
    if current_user.suspended: abort(403)
    from app import consume_rate_limit, rate_limit_response
    wait = consume_rate_limit(f'mention_lookup:{current_user.id}', 90, 60)
    if wait: return rate_limit_response(wait)
    prefix = request.args.get('q', '')
    if len(prefix) > 150 or (prefix and not re.fullmatch(r'[A-Za-z0-9_]+', prefix)):
        return jsonify(users=[])
    rows = eligible_users(current_user.id).filter(User.id != current_user.id,
        ~func.lower(User.username).in_(RESERVED), func.lower(User.username).startswith(prefix.lower(), autoescape=True)
    ).order_by(func.lower(User.username), User.id).limit(8).all()
    response = jsonify(users=[dict(id=row.id, username=row.username) for row in rows])
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def resolve_mentions(text, sender_id):
    matches = list(TOKEN.finditer(text))
    if len(matches) > 5: raise ValueError('Use at most 5 individual mentions per message.')
    names = {match.group(1).lower() for match in matches}
    if names & RESERVED: raise ValueError('Mention individual players; @all, @everyone and @here are unavailable.')
    if not names: return []
    rows = eligible_users(sender_id).filter(func.lower(User.username).in_(names)).all()
    result = []
    for match in matches:
        candidates = [row for row in rows if row.username.lower() == match.group(1).lower()]
        exact = next((row for row in candidates if row.username == match.group(1)), None)
        row = exact or (candidates[0] if len(candidates) == 1 else None)
        if row:
            result.append(dict(id=row.id, username=row.username, start=match.start(), end=match.end()))
    return result


@chat_mentions.app_template_filter('mention_text')
def mention_text(text, mentions):
    parts, cursor = [], 0
    for item in (mentions or [])[:5]:
        start, end, user_id = item.get('start'), item.get('end'), item.get('id')
        if not all(isinstance(n, int) for n in (start, end, user_id)) or not cursor <= start < end <= len(text): continue
        token = text[start:end]
        if not TOKEN.fullmatch(token): continue
        parts.extend([escape(text[cursor:start]), Markup('<a class="ga-chat-mention" href="/players/{}">{}</a>').format(user_id, token)])
        cursor = end
    parts.append(escape(text[cursor:]))
    return Markup('').join(parts)
