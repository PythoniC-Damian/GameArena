import os
import http.client
import json
import hmac
import hashlib
import secrets
import re
import time
from functools import lru_cache
import urllib.parse
from collections import defaultdict, deque
from flask import Response, Flask, render_template, redirect, url_for, request, flash, abort, jsonify, session, g, send_from_directory, has_request_context
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO, join_room, leave_room, emit
from sqlalchemy.pool import NullPool
from sqlalchemy import or_, event as sqlalchemy_event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import selectinload, joinedload

from wtforms import StringField, PasswordField, SubmitField, SelectField, IntegerField, validators
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote_plus, urlparse
import random
import smtplib
import socket
import ssl
from gamearena.bootstrap import create_base_app
from gamearena.services.email import account_email_content
from gamearena.services.jobs import queue_account_email, queue_push
from gamearena.services.redis_support import shared_socket_allowed
from gamearena.assets import frontend_assets, is_built_asset
from user_media import store_avatar
from web_push import push_configured, valid_subscription, deliver_push
try:
    import requests
    REQUESTS_AVAILABLE = True 
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Warning: requests module not available, payment features will not work")
from dotenv import load_dotenv

base_dir = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from the project .env file first. Pytest supplies
# its isolated PostgreSQL URL before this module is imported.
test_mode = os.environ.get('GAMEARENA_TESTING') == '1'
load_dotenv(os.path.join(base_dir, '.env'), override=not test_mode)

app = create_base_app(base_dir, testing=test_mode)
app.config['TESTING'] = test_mode
app.jinja_env.globals['frontend_assets'] = frontend_assets

# Configuration
secret_key = (os.environ.get('SECRET_KEY') or '').strip()
environment = (os.environ.get('FLASK_ENV') or '').strip().lower()
is_production = environment == 'production' or bool(os.environ.get('RENDER'))
if not secret_key:
    if is_production:
        raise RuntimeError('SECRET_KEY must be configured in production.')
    # Keep local development usable, but never use this value in production.
    secret_key = secrets.token_hex(32)
    app.logger.warning('SECRET_KEY is not configured; using an ephemeral development key.')
elif secret_key == 'dev-secret-key-change-in-production' and is_production:
    raise RuntimeError('A non-default SECRET_KEY must be configured in production.')

app.config['SECRET_KEY'] = secret_key
app.config['SESSION_COOKIE_SECURE'] = is_production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Static filenames are not content-fingerprinted in the current Jinja setup.
# Keep their cache lifetime useful but bounded so a deployment that replaces an
# asset at the same URL can be picked up without a forced cache purge.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = timedelta(days=1)

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.socket.io https://js.paystack.co",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://images.unsplash.com https://lh3.googleusercontent.com",
    "connect-src 'self' https://api.paystack.co https://accounts.google.com https://oauth2.googleapis.com wss:",
    "frame-src https://checkout.paystack.com",
    "font-src 'self' data:",
])
supabase_media_origin = urlparse(os.environ.get('SUPABASE_URL', ''))
if supabase_media_origin.scheme == 'https' and supabase_media_origin.hostname:
    CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace('img-src \'self\' data:', f"img-src 'self' data: https://{supabase_media_origin.hostname}")
SENSITIVE_CACHE_PATHS = (
    '/dashboard',
    '/wallet',
    '/profile',
    '/notifications',
    '/chat',
    '/admin',
    '/pay/',
    '/verify-payment',
    '/wallet/verify-deposit',
)
database_url = (os.environ.get('DATABASE_URL') or '').strip()
if not database_url:
    raise RuntimeError('DATABASE_URL must be configured for local and production PostgreSQL use.')
if not database_url.lower().startswith(('postgresql://', 'postgres://', 'postgresql+')):
    raise RuntimeError('DATABASE_URL must point to PostgreSQL.')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
RATE_LIMITS = {
    'login_ip': (10, 15 * 60),
    'login_account': (5, 15 * 60),
    'register_ip': (8, 60 * 60),
    'password_reset_ip': (5, 60 * 60),
    'verification_ip': (10, 15 * 60),
    'verification_resend': (3, 15 * 60),
    'user_report': (5, 60 * 60),
    'global_search': (40, 60),
    'payment_user': (10, 10 * 60),
    'payment_verification': (20, 10 * 60),
}
RATE_LIMIT_CLEANUP_INTERVAL = 100
RATE_LIMIT_RETENTION_SECONDS = max(window for _, window in RATE_LIMITS.values()) + 60 * 60
EMAIL_NETWORK_TIMEOUT_SECONDS = 8
rate_limit_requests_since_cleanup = 0


@app.after_request
def add_response_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Content-Security-Policy', CONTENT_SECURITY_POLICY)
    response.headers.setdefault(
        'Permissions-Policy',
        'camera=(), microphone=(), geolocation=(), payment=(self "https://checkout.paystack.com")',
    )

    forwarded_proto = request.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
    if is_production and (request.is_secure or forwarded_proto == 'https'):
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')

    if request.endpoint in {'avatar_file', 'database_avatar'}:
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif request.endpoint == 'static':
        # The worker and manifest must be revalidated so PWA updates reach
        # clients promptly. Other static files are safe for a bounded shared
        # browser/CDN cache, but not immutable because URLs are unversioned.
        if request.path.endswith(('/sw.js', '/manifest.json')):
            response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        elif response.status_code == 200 and (is_built_asset((request.view_args or {}).get('filename', '')) or request.args.get('v') == asset_fingerprint((request.view_args or {}).get('filename', ''))):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        else:
            response.headers['Cache-Control'] = (
                'public, max-age=86400, s-maxage=86400, stale-while-revalidate=3600'
            )
    elif current_user.is_authenticated or request.path.startswith(SENSITIVE_CACHE_PATHS):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    elif 'Cache-Control' not in response.headers:
        # Dynamic pages can vary by session (for example their navigation and
        # tournament join state). Public JSON endpoints set their own short,
        # explicit CDN policy in public_api_response().
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
    return response


from gamearena.observability import init_observability
init_observability(app)


# Socket.IO (WebSockets)
# Note:bruv for production you may want a message queue (Redis) to support multi-worker.
socketio_cors_origins = [
    origin.strip()
    for origin in (os.environ.get('SOCKETIO_CORS_ALLOWED_ORIGINS') or '').split(',')
    if origin.strip()
]
# Optional shared pub/sub for multiple single-worker instances. Tests stay isolated.
socketio_message_queue = None if os.environ.get('GAMEARENA_TESTING') == '1' else (os.environ.get('SOCKETIO_MESSAGE_QUEUE') or None)
socketio = SocketIO(app, cors_allowed_origins=socketio_cors_origins or None,
    message_queue=socketio_message_queue, channel='gamearena-socketio')

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Use NullPool so SQLAlchemy does not rely on a queue-based connection pool.
# The gunicorn/eventlet worker monkey-patches Python's threading, which breaks
# QueuePool's condition lock at runtime ("cannot wait on un-acquired lock"),
# causing a 500 on every DB query. NullPool opens a fresh connection per check
# out and avoids the threading lock entirely.
# Pool options are validated in gamearena.database; NullPool remains default.

# Paystack Configuration
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY')
PAYSTACK_BASE_URL = 'https://api.paystack.co'
PAYSTACK_CURRENCY = 'NGN'
PAYSTACK_REFERENCE_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/google/callback')
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USER_INFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'


def get_google_oauth_config():
    return {
        'client_id': os.environ.get('GOOGLE_CLIENT_ID') or GOOGLE_CLIENT_ID,
        'client_secret': os.environ.get('GOOGLE_CLIENT_SECRET') or GOOGLE_CLIENT_SECRET,
        'redirect_uri': os.environ.get('GOOGLE_REDIRECT_URI') or GOOGLE_REDIRECT_URI,
    }


def is_safe_local_redirect(target):
    """Allow only relative redirects or URLs on this application's host."""
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc and target.startswith('/') and not target.startswith('//')


def safe_next_url(target):
    return target if is_safe_local_redirect(target) else None


from gamearena.constants import MAX_CHAT_MESSAGE_LENGTH
MAX_MATCH_PROOF_LENGTH = 2000

# Socket events are authenticated, but a connected browser can otherwise send
# mutation events as quickly as its network allows. This lightweight guard is
# deliberately process-local: it protects a single worker without making Redis
# a required development dependency. A future Redis adapter can replace this
# implementation when Socket.IO is deployed across multiple workers.
SOCKET_EVENT_LIMITS = {
    'join_user': (12, 60),
    'join_tournament': (20, 60),
    'join_global_chat': (12, 60),
    'send_global_chat_message': (6, 10),
    'send_chat_message': (6, 10),
    'mark_notification_read': (15, 10),
    'send_direct_message': (8, 10),
    'chat_typing': (12, 10),
}
socket_event_windows = defaultdict(deque)


def socket_event_allowed(event_name):
    """Return whether the current Socket.IO connection may emit an event."""
    limit, window_seconds = SOCKET_EVENT_LIMITS.get(event_name, (20, 60))
    shared = shared_socket_allowed(current_user.get_id(), event_name, limit, window_seconds)
    if shared is not None:
        return shared
    key = (getattr(request, 'sid', f'http:{current_user.get_id()}'), event_name)
    now = time.monotonic()
    events = socket_event_windows[key]
    cutoff = now - window_seconds
    while events and events[0] <= cutoff:
        events.popleft()
    if len(events) >= limit:
        return False
    events.append(now)
    return True


def socket_rate_limit_error():
    if current_user.is_authenticated:
        socketio.emit('socket_error', {'message': 'Too many requests. Please wait and try again.'}, room=f'user:{current_user.id}')
    return {'status':'error', 'message':'Too many requests. Please wait and try again.'}


def is_admin_user(user=None):
    user = user or current_user
    return bool(user and user.is_authenticated and user.is_admin and not user.suspended)


def get_tournament_membership(user_id, tournament_id):
    return UserTournament.query.filter_by(
        user_id=user_id,
        tournament_id=tournament_id,
    ).first()


def can_access_tournament_chat(user_id, tournament_id):
    if is_admin_user():
        return True
    membership = get_tournament_membership(user_id, tournament_id)
    return bool(membership and membership.payment_status in {'paid', 'free'})


def can_access_match(user_id, match):
    return bool(
        match and (
            is_admin_user() or
            user_id in {match.player_one_user_id, match.player_two_user_id}
        )
    )


def active_participant_count(tournament):
    """Count only memberships that represent an actual participant."""
    if hasattr(tournament, '_active_count'):
        return tournament._active_count
    return sum(
        1 for membership in tournament.participants
        if membership.payment_status in {'paid', 'free'}
    )

from gamearena.extensions import db
db.init_app(app)
from gamearena.models import (User, UserSettings, Achievement, UserAchievement, Tournament, TournamentStat, UserTournament, WalletTransaction, RateLimitBucket, Notification, TournamentChatMessage, GlobalChatMessage, DirectMessage, ProfilePhoto, PushSubscription, UserBlock, UserReport, TournamentMatch, TournamentMatchChatMessage, TournamentMatchDispute)
from gamearena.forms import (RegistrationForm, LoginForm, EmailVerificationForm, ForgotPasswordForm, ResetPasswordForm, TournamentForm, TournamentSetupForm, LeaderboardEntryForm)


login_manager = LoginManager()
login_manager.init_app(app)

# -------------------------
# NOTIFICATIONS (SocketIO)
# -------------------------

def get_unread_notification_count(user_id: int):
    """Return the number of unread notifications for a user."""
    if not user_id:
        return 0
    return Notification.query.filter(
        Notification.user_id == int(user_id),
        Notification.read_at.is_(None)
    ).count()


def mark_notifications_read_for_user(user_id: int, only_count: bool = False):
    """Mark notifications as read for a user unless only_count is requested."""
    if not user_id:
        return 0

    if not only_count:
        now = datetime.utcnow()
        (Notification.query
            .filter(Notification.user_id == int(user_id), Notification.read_at.is_(None))
            .update({"read_at": now}, synchronize_session=False))
        db.session.commit()

    return get_unread_notification_count(user_id)


def create_and_emit_notification(user_id: int, message: str, category='system', target_url=None):
    """Create one preference-aware notification and emit it to the user's room."""
    if not user_id or not message:
        return
    category = category if category in {
        'tournament', 'match', 'wallet', 'chat', 'achievement', 'system', 'marketing',
    } else 'system'
    settings = UserSettings.query.filter_by(user_id=int(user_id)).first()
    preference_name = {
        'tournament': 'tournament_notifications',
        'match': 'match_notifications',
        'wallet': 'wallet_notifications',
        'chat': 'chat_notifications',
        'marketing': 'marketing_notifications',
    }.get(category)
    if settings and preference_name and not getattr(settings, preference_name):
        return
    if target_url and (not target_url.startswith('/') or target_url.startswith('//')):
        target_url = None
    notif = Notification(
        user_id=int(user_id), message=message, category=category, target_url=target_url,
    )
    db.session.add(notif)
    db.session.commit()

    # Emit to the specific user room.
    # Dashboard client listens for event name: 'notification'
    socketio.emit(
        'notification',
        {
            'id': notif.id,
            'message': message,
            'category': category,
            'target_url': target_url,
            'created_at': notif.created_at.isoformat() if notif.created_at else None,
        },
        room=f'user:{int(user_id)}'
    )
    if push_configured() and not queue_push(notif.id):
        subscriptions = [record.subscription for record in PushSubscription.query.filter_by(user_id=int(user_id)).all()]
        if subscriptions:
            socketio.start_background_task(deliver_push, subscriptions,
                {'title':'GameArena', 'body':message, 'url':target_url or '/notifications', 'id':notif.id}, app.logger)

login_manager.login_view = "login"
@login_manager.unauthorized_handler
def unauthorized_response():
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'message':'Your session has expired. Log in again to continue.'}), 401
    return redirect(url_for('login', next=request.full_path))


csrf = CSRFProtect(app)


@app.errorhandler(403)
def forbidden_page(error):
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': {'message': 'Access denied.', 'status': 403}}), 403
    return render_template(
        'error.html', code=403, title='Access denied',
        message='You do not have permission to view this page.',
    ), 403


@app.errorhandler(404)
def not_found_page(error):
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': {'message': 'The requested resource was not found.', 'status': 404}}), 404
    return render_template(
        'error.html', code=404, title='Page not found',
        message='We could not find the page you requested.',
    ), 404


@app.errorhandler(500)
def internal_error_page(error):
    db.session.rollback()
    app.logger.error('Unhandled application error request_id=%s', getattr(g, 'request_id', '-'))
    if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
        return jsonify({'error': {'message': 'The request could not be completed.', 'status': 500}}), 500
    return render_template(
        'error.html', code=500, title='Something went wrong',
        message='GameArena could not complete that request. Please try again.',
    ), 500

# Tournament images keyed by normalized game name
@lru_cache(maxsize=256)
def asset_fingerprint(filename):
    path = os.path.join(app.static_folder, filename)
    try:
        with open(path, 'rb') as asset:
            return hashlib.sha256(asset.read()).hexdigest()[:12]
    except OSError:
        return 'missing'


def asset_url(filename):
    return url_for('static', filename=filename, v=asset_fingerprint(filename))


def optimized_image(filename, width=960):
    stem = os.path.splitext(os.path.basename(filename))[0].replace(' ', '_')
    optimized = f'images/optimized/{stem}-{width}.webp'
    return optimized if os.path.isfile(os.path.join(app.static_folder, optimized)) else filename


@app.context_processor
def application_navigation():
    preferences = current_user.settings if current_user.is_authenticated else None
    return {
        'asset_url': asset_url,
        'nav_unread_count': get_unread_notification_count(current_user.id) if current_user.is_authenticated else 0,
        'nav_preferences': preferences,
    }


@app.template_filter('naira')
def format_naira(value):
    try:
        return f'â‚¦{int(value or 0):,}'
    except (TypeError, ValueError):
        return 'Not specified'


GAME_IMAGE_MAP = {
    'call of duty mobile': 'images/call of duty 2.webp',
    'call of duty': 'images/call of duty 2.webp',
    'free fire': 'images/free fire 2.webp',
    'pubg mobile': 'images/PUBG.jpg',
    'pubg': 'images/PUBG.jpg',
    'efootball': 'images/efootball_2.jpg',
    'fifa': 'images/efootball_2.jpg',
}

GAME_IMAGE_CAROUSEL_MAP = {
    'call of duty mobile': ['images/call of duty 2.webp', 'images/call_of_duty.jpg', 'images/call of duty 3.jpg'],
    'call of duty': ['images/call of duty 2.webp', 'images/call_of_duty.jpg', 'images/call of duty 3.jpg'],
    'free fire': ['images/free fire 2.webp', 'images/free fire.jpg', 'images/free fire 3.jpg'],
    'pubg mobile': ['images/PUBG.jpg', 'images/PUBG 2.jpg'],
    'pubg': ['images/PUBG.jpg', 'images/PUBG 2.jpg'],
    'efootball': ['images/efootball_2.jpg', 'images/efootball-messi.jpg', 'images/efootball_3.jpg'],
    'fifa': ['images/efootball_2.jpg', 'images/efootball-messi.jpg', 'images/efootball_3.jpg'],
}

FEATURED_GAME_PRIORITY = ['pubg', 'free fire', 'call of duty mobile', 'efootball']
HERO_IMAGE_FILENAMES = [
    'images/free fire 2.webp',
    'images/efootball_2.jpg',
    'images/call of duty 2.webp',
    'images/free fire 3.jpg',
    'images/PUBG.jpg',
]


@lru_cache(maxsize=1)
def hero_image_catalog():
    return tuple(f'images/{entry.name}' for entry in os.scandir(os.path.join(app.static_folder, 'images'))
        if entry.is_file() and os.path.splitext(entry.name)[1].lower() in {'.png','.jpg','.jpeg','.webp'})


@app.context_processor
def utility_processor():
    def normalize_game_key(game_name):
        if not game_name:
            return ''
        return game_name.strip().lower()

    def featured_tournaments(tournaments):
        if not tournaments:
            return []

        featured = []
        seen = set()

        for tournament in tournaments:
            if tournament is None:
                continue
            normalized = normalize_game_key(getattr(tournament, 'game', ''))
            if normalized in FEATURED_GAME_PRIORITY and normalized not in seen:
                featured.append(tournament)
                seen.add(normalized)

        ordered = []
        for game_key in FEATURED_GAME_PRIORITY:
            for tournament in featured:
                if normalize_game_key(getattr(tournament, 'game', '')) == game_key:
                    ordered.append(tournament)
                    break
        return ordered

    def tournament_image(game_name):
        if not game_name:
            return asset_url('images/gaming-fallback.svg')
        key = normalize_game_key(game_name)
        if key in GAME_IMAGE_MAP:
            value = GAME_IMAGE_MAP[key]
            return value if value.startswith('http') else asset_url(optimized_image(value))
        return asset_url('images/gaming-fallback.svg')

    def game_image_carousel(game_name):
        if not game_name:
            return []
        key = normalize_game_key(game_name)
        if key in GAME_IMAGE_CAROUSEL_MAP:
            return [asset_url(optimized_image(image)) for image in GAME_IMAGE_CAROUSEL_MAP[key]]
        fallback = tournament_image(game_name)
        return [fallback]

    def carousel_images():
        # Use every game image, randomized per request; serve optimized variants.
        filenames = sorted({filename for images in GAME_IMAGE_CAROUSEL_MAP.values() for filename in images})
        filenames += [filename for filename in HERO_IMAGE_FILENAMES if filename not in filenames]
        filenames += [filename for filename in hero_image_catalog() if filename not in filenames]
        random.shuffle(filenames)
        return [asset_url(optimized_image(filename, 1440)) for filename in filenames
            if os.path.isfile(os.path.join(app.static_folder, filename))]

    return dict(
        tournament_image=tournament_image,
        game_image_carousel=game_image_carousel,
        carousel_images=carousel_images(),
        featured_tournaments=featured_tournaments,
        active_participant_count=active_participant_count,
        tournament_image_small=lambda game: asset_url(optimized_image(GAME_IMAGE_MAP.get(normalize_game_key(game), 'images/gaming-fallback.svg'), 480)),
        tournament_image_large=lambda game: asset_url(optimized_image(GAME_IMAGE_MAP.get(normalize_game_key(game), 'images/gaming-fallback.svg'), 1440)),
    )


def generate_code(length=6):
    return ''.join(secrets.choice('0123456789') for _ in range(length))


def send_email(subject, recipient, body):
    # Compatibility entry point used by existing callers and provider tests.
    from gamearena.services.email import send_email as deliver_email
    return deliver_email(subject, recipient, body)


def send_verification_code(user):
    """Generate verification code and send email"""
    # Create an in-app notification for the user
    # (the dashboard socket will display it)
    create_and_emit_notification(user.id, 'Email verification code generated.')
    user.verification_code = generate_code(6)
    user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
    db.session.commit()

    verification_url = url_for('verify_email', email=user.email, _external=True)
    subject, body = account_email_content(user, 'verification', verification_url)
    if queue_account_email(user, 'verification'):
        return True  # Accepted into a durable queue; provider delivery follows.
    return send_email(subject, user.email, body)


def send_password_reset_code(user):
    create_and_emit_notification(user.id, 'Password reset code generated.')
    user.reset_code = generate_code(6)
    user.reset_expires_at = datetime.utcnow() + timedelta(minutes=15)
    db.session.commit()
    subject, body = account_email_content(user, 'reset')
    if queue_account_email(user, 'reset'):
        return True
    return send_email(subject, user.email, body)


# Form Classes


# -------------------------
# USER MODEL
# -------------------------


# -------------------------
# TOURNAMENT MODEL
# -------------------------


# -------------------------
# LEADERBOARD MODEL
# -------------------------


# -------------------------
# USER-TOURNAMENT MODEL
# -------------------------


# -------------------------
# WALLET TRANSACTIONS MODEL
# -------------------------


def client_rate_limit_key():
    return request.remote_addr or 'unknown-client'


def rate_limit_response(retry_after):
    message = 'Too many requests. Please try again later.'
    if request.path == '/verify-email' and request.method == 'POST' and request.form.get('action') == 'resend':
        message = 'Please wait before requesting another verification code.'
        form = EmailVerificationForm()
        form.email.data = (request.form.get('email') or '').strip()
        flash(message, 'error')
        response = app.make_response(render_template('verify_email.html', form=form))
    else:
        response = jsonify({'status': 'error', 'message': message})
    response.status_code = 429
    response.headers['Retry-After'] = str(max(1, int(retry_after)))
    return response


def consume_rate_limit(bucket_key, limit, window_seconds):
    global rate_limit_requests_since_cleanup
    rate_limit_requests_since_cleanup += 1
    if rate_limit_requests_since_cleanup >= RATE_LIMIT_CLEANUP_INTERVAL:
        cleanup_rate_limit_buckets()
        rate_limit_requests_since_cleanup = 0

    now = datetime.utcnow()
    bucket = RateLimitBucket.query.filter_by(bucket_key=bucket_key).with_for_update().first()
    if bucket is None:
        bucket = RateLimitBucket(bucket_key=bucket_key, window_started=now, count=1)
        db.session.add(bucket)
        try:
            db.session.commit()
            return None
        except Exception:
            db.session.rollback()
            bucket = RateLimitBucket.query.filter_by(bucket_key=bucket_key).with_for_update().first()
            if bucket is None:
                return window_seconds

    elapsed = (now - bucket.window_started).total_seconds()
    if elapsed >= window_seconds:
        bucket.window_started = now
        bucket.count = 1
        db.session.commit()
        return None
    if bucket.count >= limit:
        db.session.rollback()
        return max(1, int(window_seconds - elapsed))

    bucket.count += 1
    db.session.commit()
    return None


def cleanup_rate_limit_buckets():
    cutoff = datetime.utcnow() - timedelta(seconds=RATE_LIMIT_RETENTION_SECONDS)
    RateLimitBucket.query.filter(RateLimitBucket.window_started < cutoff).delete(synchronize_session=False)
    db.session.commit()


def enforce_rate_limits():
    if request.method not in {'POST', 'GET'}:
        return None

    path = request.path
    client_key = client_rate_limit_key()
    checks = []
    if path == '/login' and request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        checks = [('login_ip:' + client_key, 'login_ip'),
                  ('login_account:' + (email or 'unknown'), 'login_account')]
    elif path == '/register' and request.method == 'POST':
        checks = [('register_ip:' + client_key, 'register_ip')]
    elif path == '/forgot-password' and request.method == 'POST':
        checks = [('password_reset_ip:' + client_key, 'password_reset_ip')]
    elif path == '/verify-email' and request.method == 'POST':
        if request.form.get('action') == 'resend':
            email = (request.form.get('email') or '').strip().lower()
            checks = [
                ('verification_resend_ip:' + client_key, 'verification_resend'),
                ('verification_resend_email:' + (email or 'unknown'), 'verification_resend'),
            ]
        else:
            checks = [('verification_ip:' + client_key, 'verification_ip')]
    elif path.startswith('/users/') and path.endswith('/report') and request.method == 'POST':
        checks = [('user_report_ip:' + client_key, 'user_report')]
    elif (path == '/support' or path.startswith('/chat/messages/')) and request.method == 'POST':
        checks = [('user_report_ip:' + client_key, 'user_report')]
    elif path == '/search' and request.method == 'GET':
        checks = [('global_search_ip:' + client_key, 'global_search')]
    elif (path.startswith('/initialize-payment/') or path == '/wallet/initialize-deposit'):
        checks = [('payment_user:' + str(current_user.get_id()), 'payment_user')]
    elif path in {'/verify-payment', '/wallet/verify-deposit'}:
        checks = [('payment_verification:' + str(current_user.get_id()), 'payment_verification')]

    for bucket_key, limit_name in checks:
        limit, window = RATE_LIMITS[limit_name]
        retry_after = consume_rate_limit(bucket_key, limit, window)
        if retry_after is not None:
            return rate_limit_response(retry_after)
    return None


@app.before_request
def apply_rate_limits():
    return enforce_rate_limits()


# -------------------------
# NOTIFICATIONS (Phase 1)
# -------------------------


# -------------------------
# TOURNAMENT CHAT (Phase 1)
# -------------------------


def get_or_create_user_settings(user_id):
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    if settings:
        return settings
    db.session.execute(
        postgresql_insert(UserSettings).values(user_id=user_id).on_conflict_do_nothing(
            index_elements=['user_id'],
        )
    )
    db.session.commit()
    return UserSettings.query.filter_by(user_id=user_id).first()


def users_have_block(user_one_id, user_two_id):
    if not user_one_id or not user_two_id or user_one_id == user_two_id:
        return False
    return UserBlock.query.filter(
        or_(
            db.and_(UserBlock.blocker_id == user_one_id, UserBlock.blocked_id == user_two_id),
            db.and_(UserBlock.blocker_id == user_two_id, UserBlock.blocked_id == user_one_id),
        )
    ).first() is not None


def can_direct_message(sender, recipient):
    if not sender or not recipient or sender.id == recipient.id:
        return False
    if sender.suspended or recipient.suspended or users_have_block(sender.id, recipient.id):
        return False
    recipient_settings = recipient.settings
    return recipient_settings is None or recipient_settings.allow_direct_messages


def achievement_progress_for_user(user_id):
    memberships = UserTournament.query.filter(
        UserTournament.user_id == user_id,
        UserTournament.payment_status.in_(['paid', 'free']),
    )
    tournament_count = memberships.count()
    confirmed_matches = TournamentMatch.query.filter(
        TournamentMatch.status == 'confirmed',
        TournamentMatch.winner_user_id.isnot(None),
        or_(
            TournamentMatch.player_one_user_id == user_id,
            TournamentMatch.player_two_user_id == user_id,
        ),
    )
    wins = confirmed_matches.filter(TournamentMatch.winner_user_id == user_id).count()
    win_streak = 0
    for match in confirmed_matches.order_by(
        TournamentMatch.updated_at.desc(), TournamentMatch.id.desc(),
    ).limit(1000).yield_per(100):
        if match.winner_user_id != user_id:
            break
        win_streak += 1
    champion_tournament_ids = {
        row[0] for row in TournamentStat.query.filter_by(
            user_id=user_id, rank=1,
        ).with_entities(TournamentStat.tournament_id).all()
    }
    final_rounds = db.session.query(
        TournamentMatch.tournament_id.label('tournament_id'),
        db.func.max(TournamentMatch.round_number).label('final_round'),
    ).filter(TournamentMatch.round_number.isnot(None)).group_by(
        TournamentMatch.tournament_id,
    ).subquery()
    bracket_champions = db.session.query(TournamentMatch.tournament_id).join(
        Tournament, Tournament.id == TournamentMatch.tournament_id,
    ).join(
        final_rounds,
        db.and_(
            final_rounds.c.tournament_id == TournamentMatch.tournament_id,
            final_rounds.c.final_round == TournamentMatch.round_number,
        ),
    ).filter(
        Tournament.status == 'finished',
        TournamentMatch.status == 'confirmed',
        TournamentMatch.winner_user_id == user_id,
    ).all()
    champion_count = len(champion_tournament_ids | {row[0] for row in bracket_champions})
    best_rank = db.session.query(db.func.min(TournamentStat.rank)).filter(
        TournamentStat.user_id == user_id,
        TournamentStat.rank > 0,
    ).scalar()
    return {
        'tournaments': tournament_count,
        'wins': wins,
        'win_streak': win_streak,
        'champions': champion_count,
        'top_rank': best_rank,
    }


def award_achievements_for_user(user_id):
    progress = achievement_progress_for_user(user_id)
    definitions = Achievement.query.filter_by(enabled=True).all()
    for achievement in definitions:
        value = progress.get(achievement.rule_type, 0) or 0
        db.session.execute(
            postgresql_insert(UserAchievement).values(
                user_id=user_id, achievement_id=achievement.id,
                progress=0, unlocked_at=None,
            ).on_conflict_do_nothing(constraint='unique_user_achievement')
        )
        record = UserAchievement.query.filter_by(
            user_id=user_id, achievement_id=achievement.id,
        ).with_for_update().first()
        if achievement.rule_type == 'top_rank':
            record.progress = achievement.threshold if value and value <= achievement.threshold else 0
            unlocked = bool(value and value <= achievement.threshold)
        else:
            record.progress = min(value, achievement.threshold)
            unlocked = value >= achievement.threshold
        if unlocked and record.unlocked_at is None:
            record.unlocked_at = datetime.utcnow()
            db.session.add(Notification(
                user_id=user_id,
                message=f'You unlocked {achievement.name}.',
                category='achievement',
                target_url='/profile#achievements',
            ))
    db.session.commit()


def create_tournament_matches(tournament):
    if not tournament or tournament.status == 'finished':
        return []

    existing_matches = TournamentMatch.query.filter_by(tournament_id=tournament.id).all()
    if existing_matches:
        return existing_matches

    participants = [
        entry.user_id for entry in sorted(
            tournament.participants,
            key=lambda item: (item.joined_at or datetime.min, item.user_id),
        )
        if entry.payment_status in {'paid', 'free'}
    ]
    if len(participants) < 2 or len(participants) & (len(participants) - 1):
        return []

    random.shuffle(participants)
    matches = []
    for index in range(0, len(participants), 2):
        pair = participants[index:index + 2]
        match = TournamentMatch(
            tournament_id=tournament.id,
            player_one_user_id=pair[0],
            player_two_user_id=pair[1],
            status='scheduled',
            round_number=1,
            match_order=index // 2 + 1,
        )
        db.session.add(match)
        matches.append(match)

    tournament.status = 'live'
    db.session.commit()
    return matches


def advance_tournament_bracket(match):
    if not match or not match.round_number:
        return False

    tournament = Tournament.query.filter_by(id=match.tournament_id).with_for_update().first()
    if not tournament:
        return False
    if tournament.status == 'finished':
        return False
    round_matches = TournamentMatch.query.filter_by(
        tournament_id=tournament.id, round_number=match.round_number,
    ).order_by(TournamentMatch.match_order.asc()).all()
    if not round_matches or any(
        round_match.status != 'confirmed' or round_match.winner_user_id is None
        for round_match in round_matches
    ):
        return False

    winners = [round_match.winner_user_id for round_match in round_matches]
    next_round = match.round_number + 1
    if len(winners) == 1:
        champion = db.session.get(User, winners[0])
        tournament.status = 'finished'
        db.session.commit()
        if champion:
            award_achievements_for_user(champion.id)
            create_and_emit_notification(
                champion.id, f'You won {tournament.name}.', 'tournament',
                f'/tournament/{tournament.id}',
            )
        return True

    existing_next_round = TournamentMatch.query.filter_by(
        tournament_id=tournament.id, round_number=next_round,
    ).first()
    if existing_next_round:
        return False

    for index in range(0, len(winners), 2):
        db.session.add(TournamentMatch(
            tournament_id=tournament.id,
            player_one_user_id=winners[index],
            player_two_user_id=winners[index + 1],
            status='scheduled',
            round_number=next_round,
            match_order=index // 2 + 1,
        ))
    db.session.commit()
    for winner_id in winners:
        create_and_emit_notification(
            winner_id, f'You advanced to round {next_round} of {tournament.name}.',
            'tournament', f'/tournament/{tournament.id}',
        )
    return True


def submit_match_result(match, user, room_code, room_password, player_profile_id, opponent_profile_id, winner_user_id, proof_note):
    if not match or not user:
        return None

    match.room_code = room_code
    match.room_password = room_password
    match.player_one_profile_id = player_profile_id
    match.player_two_profile_id = opponent_profile_id
    match.winner_user_id = winner_user_id
    match.proof_note = proof_note
    match.submitted_by_user_id = user.id
    match.status = 'pending_confirmation'
    db.session.commit()
    return match


# -------------------------
# LOGIN MANAGER
# -------------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.options(joinedload(User.settings)).filter_by(id=int(user_id)).first()
    except Exception as exc:
        app.logger.warning(f"Unable to load user {user_id}: {exc}")
        return None


# -------------------------
# HOME
# -------------------------
@app.route("/")
def home():
    tournaments = Tournament.query.filter(Tournament.status.in_(['open', 'ongoing', 'live'])).order_by(
        Tournament.match_time.asc().nullslast(), Tournament.id.desc(),
    ).limit(6).all()
    memberships = prepare_tournament_cards(tournaments)
    return render_template("index.html", tournaments=tournaments, memberships=memberships)


def prepare_tournament_cards(tournaments):
    """Aggregate counts instead of loading every participant for a listing."""
    ids = [tournament.id for tournament in tournaments]
    if not ids:
        return {}
    counts = dict(db.session.query(UserTournament.tournament_id, db.func.count(UserTournament.id)).filter(
        UserTournament.tournament_id.in_(ids), UserTournament.payment_status.in_(['paid', 'free']),
    ).group_by(UserTournament.tournament_id).all())
    for tournament in tournaments:
        tournament._active_count = counts.get(tournament.id, 0)
    if not current_user.is_authenticated:
        return {}
    return {membership.tournament_id: membership for membership in UserTournament.query.filter(
        UserTournament.user_id == current_user.id, UserTournament.tournament_id.in_(ids),
    ).all()}


@app.route('/sw.js')
def service_worker():
    from flask import send_from_directory
    response = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


@app.route('/health')
def health():
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok'}), 200
    except Exception:
        db.session.rollback()
        app.logger.exception('Health check database query failed')
        return jsonify({'status': 'unavailable'}), 503


# -------------------------
# PUBLIC JSON API (migration-ready frontend boundary)
# -------------------------
from gamearena.public_api import (
    API_MAX_PAGE_SIZE, PUBLIC_TOURNAMENT_STATUSES, api_error, api_pagination,
    serialize_tournament, public_api_response, api_tournaments,
    api_tournament_detail, api_leaderboard, register_public_api,
)
register_public_api(app, Tournament, TournamentStat, TournamentMatch, GAME_IMAGE_MAP)


# -------------------------
# PUBLIC LEADERBOARD
# -------------------------
@app.route("/leaderboard")
def leaderboard():
    available_games = [row[0] for row in db.session.query(Tournament.game).distinct().order_by(Tournament.game).all()]
    selected_game = (request.args.get('game') or '').strip()
    if selected_game not in available_games:
        selected_game = ''
    try:
        selected_tournament_id = int(request.args.get('tournament', ''))
    except (TypeError, ValueError):
        selected_tournament_id = None

    tournaments_query = Tournament.query.options(
        selectinload(Tournament.leaderboard).joinedload(TournamentStat.user),
    )
    if selected_game:
        tournaments_query = tournaments_query.filter(Tournament.game == selected_game)
    if selected_tournament_id:
        tournaments_query = tournaments_query.filter(Tournament.id == selected_tournament_id)
    tournaments = tournaments_query.order_by(Tournament.match_time.desc()).limit(50).all()
    rankings_query = TournamentStat.query.join(Tournament).options(
        joinedload(TournamentStat.user), joinedload(TournamentStat.tournament),
    )
    if selected_game:
        rankings_query = rankings_query.filter(Tournament.game == selected_game)
    if selected_tournament_id:
        rankings_query = rankings_query.filter(TournamentStat.tournament_id == selected_tournament_id)
    pagination = rankings_query.order_by(
        TournamentStat.tournament_id.desc(), TournamentStat.rank.asc(), TournamentStat.points.desc(),
    ).paginate(page=max(request.args.get('page', 1, type=int) or 1, 1), per_page=30, error_out=False)
    own_placements = []
    if current_user.is_authenticated:
        placements_query = (
            TournamentStat.query
            .options(joinedload(TournamentStat.tournament))
            .filter_by(user_id=current_user.id)
        )
        if selected_game:
            placements_query = placements_query.join(Tournament).filter(Tournament.game == selected_game)
        if selected_tournament_id:
            placements_query = placements_query.filter(TournamentStat.tournament_id == selected_tournament_id)
        own_placements = placements_query.order_by(
            TournamentStat.rank.asc(), TournamentStat.points.desc(),
        ).limit(20).all()
    return render_template(
        "leaderboard.html", tournaments=tournaments, own_placements=own_placements,
        available_games=available_games, selected_game=selected_game,
        selected_tournament_id=selected_tournament_id,
        filter_tournaments=tournaments, rankings=pagination.items, pagination=pagination,
    )


# -------------------------
# TOURNAMENTS PAGE (dedicated listing)
# -------------------------
@app.route("/tournaments")
def tournaments_page():
    selected_game = (request.args.get('game') or '').strip()[:100]
    selected_status = (request.args.get('status') or '').strip().lower()
    search_query = (request.args.get('q') or '').strip()[:100]
    query = Tournament.query
    if selected_game:
        query = query.filter(Tournament.game == selected_game)
    if selected_status in PUBLIC_TOURNAMENT_STATUSES:
        query = query.filter(Tournament.status == selected_status)
    else:
        selected_status = ''
    if search_query:
        query = query.filter(or_(Tournament.name.ilike(f'%{search_query}%'), Tournament.game.ilike(f'%{search_query}%')))
    pagination = query.order_by(Tournament.match_time.asc().nullslast(), Tournament.id.desc()).paginate(
        page=max(request.args.get('page', 1, type=int) or 1, 1), per_page=12, error_out=False,
    )
    games = [row[0] for row in db.session.query(Tournament.game).distinct().order_by(Tournament.game).all()]
    memberships = prepare_tournament_cards(pagination.items)
    return render_template('tournaments.html', tournaments=pagination.items, pagination=pagination,
        available_games=games, selected_game=selected_game, selected_status=selected_status,
        search_query=search_query, memberships=memberships)


# -------------------------
# WALLET PAGE
# -------------------------
@app.route("/wallet")
@login_required
def wallet():
    joins = UserTournament.query.filter_by(user_id=current_user.id)
    all_joins = joins.options(joinedload(UserTournament.tournament)).order_by(UserTournament.joined_at.desc()).limit(20).all()
    total_spent = db.session.query(db.func.coalesce(db.func.sum(UserTournament.amount_paid), 0)).filter(UserTournament.user_id == current_user.id, UserTournament.payment_status == 'paid').scalar()
    pending_count = joins.filter_by(payment_status='pending').count()
    pagination = WalletTransaction.query.filter_by(user_id=current_user.id).order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=30, error_out=False)
    wallet_transactions = pagination.items
    wallet_balance = current_user.wallet_balance or 0
    return render_template("wallet.html", transactions=all_joins, total_spent=total_spent, pending_count=pending_count, wallet_transactions=wallet_transactions, pagination=pagination, wallet_balance=wallet_balance, paystack_public_key=PAYSTACK_PUBLIC_KEY)


@app.route('/chat')
@login_required
def chat():
    latest_messages = GlobalChatMessage.query.options(joinedload(GlobalChatMessage.user)).order_by(
        GlobalChatMessage.created_at.desc(), GlobalChatMessage.id.desc(),
    ).limit(50).all()
    all_messages = list(reversed(latest_messages))

    # Defensively drop any messages whose user relationship is missing (orphaned
    # rows, e.g. a chat message referencing a user that no longer exists). This
    # prevents an AttributeError -> HTTP 500 when rendering the template.
    messages = [m for m in all_messages if m.user is not None]

    # Most recent 10 distinct chatting users.
    # Use a grouped aggregate query so the ordering is valid on PostgreSQL.
    from sqlalchemy import func
    # Select user_id first, then the aggregated last_seen (row[0] = user_id).
    distinct_user_ids = [
        row[0] for row in db.session.query(
            GlobalChatMessage.user_id,
            func.max(GlobalChatMessage.created_at).label('last_seen'),
        )
        .filter(GlobalChatMessage.user_id != current_user.id)
        .group_by(GlobalChatMessage.user_id)
        .order_by(func.max(GlobalChatMessage.created_at).desc())
        .limit(10).all()
    ]
    # Preserve order of most-recent first
    chat_partners = []
    if distinct_user_ids:
        partners = User.query.filter(User.id.in_(distinct_user_ids)).all()
        partner_map = {u.id: u for u in partners}
        chat_partners = [partner_map[uid] for uid in distinct_user_ids
            if uid in partner_map and can_direct_message(current_user, partner_map[uid])]

    return render_template(
        'chat.html', messages=messages, chat_partners=chat_partners,
        dm_unread_count=DirectMessage.query.filter_by(
            recipient_id=current_user.id, read_at=None,
        ).count(),
    )


@app.route('/chat/history')
@login_required
def chat_history():
    after = max(request.args.get('after', 0, type=int) or 0, 0)
    partner_id = request.args.get('partner', type=int)
    if partner_id:
        partner = db.session.get(User, partner_id)
        if not can_direct_message(current_user, partner):
            return jsonify({'error': 'This conversation is unavailable.'}), 403
        rows = DirectMessage.query.options(joinedload(DirectMessage.sender)).filter(
            DirectMessage.id > after,
            or_(db.and_(DirectMessage.sender_id == current_user.id, DirectMessage.recipient_id == partner_id),
                db.and_(DirectMessage.sender_id == partner_id, DirectMessage.recipient_id == current_user.id)),
        ).order_by(DirectMessage.id).limit(51).all()
        data = [{'id': row.id, 'sender_id': row.sender_id, 'username': row.sender.username if row.sender else 'Player',
            'message': row.message, 'deleted':bool(row.deleted_at), 'client_message_id':row.client_message_id, 'reply':quoted_message(row.reply_to), 'created_at': row.created_at.isoformat() if row.created_at else None} for row in rows[:50]]
    else:
        rows = GlobalChatMessage.query.options(joinedload(GlobalChatMessage.user)).filter(
            GlobalChatMessage.id > after,
        ).order_by(GlobalChatMessage.id).limit(51).all()
        data = [{'id': row.id, 'user_id': row.user_id, 'username': row.user.username if row.user else 'Player',
            'message': row.message, 'deleted':bool(row.deleted_at), 'client_message_id':row.client_message_id, 'reply':quoted_message(row.reply_to), 'created_at': row.created_at.isoformat() if row.created_at else None} for row in rows[:50]]
    model = DirectMessage if partner_id else GlobalChatMessage
    removed = model.query.filter(model.deleted_at.isnot(None))
    if partner_id:
        removed = removed.filter(or_(db.and_(DirectMessage.sender_id == current_user.id, DirectMessage.recipient_id == partner_id), db.and_(DirectMessage.sender_id == partner_id, DirectMessage.recipient_id == current_user.id)))
    return jsonify({'messages': data, 'has_more': len(rows) > 50, 'deleted_ids':[row.id for row in removed.order_by(model.deleted_at.desc()).limit(200)]})


# -------------------------
# PROFILE PAGE
# -------------------------
@app.route("/profile")
@login_required
def profile():
    joined_count = UserTournament.query.filter(
        UserTournament.user_id == current_user.id,
        UserTournament.payment_status.in_(['paid', 'free']),
    ).count()
    stats = TournamentStat.query.options(
        joinedload(TournamentStat.tournament),
    ).filter_by(user_id=current_user.id).order_by(
        TournamentStat.rank.asc(), TournamentStat.points.desc(),
    ).all()
    settings = get_or_create_user_settings(current_user.id)
    award_achievements_for_user(current_user.id)
    achievements = UserAchievement.query.options(
        joinedload(UserAchievement.achievement),
    ).filter(
        UserAchievement.user_id == current_user.id,
        or_(
            UserAchievement.unlocked_at.isnot(None),
            UserAchievement.achievement.has(Achievement.hidden.is_(False)),
        ),
    ).order_by(UserAchievement.unlocked_at.desc().nullslast()).all()
    progress = achievement_progress_for_user(current_user.id)
    confirmed_matches = TournamentMatch.query.filter(
        TournamentMatch.status == 'confirmed',
        TournamentMatch.winner_user_id.isnot(None),
        or_(
            TournamentMatch.player_one_user_id == current_user.id,
            TournamentMatch.player_two_user_id == current_user.id,
        ),
    )
    matches_played = confirmed_matches.count()
    wins = confirmed_matches.filter(TournamentMatch.winner_user_id == current_user.id).count()
    recent_activity = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc(), Notification.id.desc(),
    ).limit(5).all()
    profile_tournaments = UserTournament.query.options(joinedload(UserTournament.tournament)).filter(
        UserTournament.user_id == current_user.id, UserTournament.payment_status.in_(['paid', 'free', 'pending']),
    ).order_by(UserTournament.joined_at.desc()).limit(8).all()
    match_history = confirmed_matches.options(
        joinedload(TournamentMatch.tournament), joinedload(TournamentMatch.player_one), joinedload(TournamentMatch.player_two),
    ).order_by(TournamentMatch.updated_at.desc()).limit(8).all()
    return render_template(
        "profile.html", joined_count=joined_count, stats=stats,
        settings=settings, achievements=achievements, achievement_progress=progress,
        matches_played=matches_played, wins=wins, losses=matches_played - wins,
        win_rate=round((wins / matches_played) * 100) if matches_played else 0,
        recent_activity=recent_activity,
        profile_tournaments=profile_tournaments, match_history=match_history,
    )


@app.route('/players/<int:user_id>')
def public_profile(user_id):
    player = User.query.get_or_404(user_id)
    if player.suspended and not is_admin_user():
        abort(404)
    settings = UserSettings.query.filter_by(user_id=player.id).first()
    if player.id != (current_user.id if current_user.is_authenticated else None):
        if settings and not settings.profile_public:
            abort(404)

    matches = TournamentMatch.query.filter(
        TournamentMatch.status == 'confirmed',
        TournamentMatch.winner_user_id.isnot(None),
        or_(
            TournamentMatch.player_one_user_id == player.id,
            TournamentMatch.player_two_user_id == player.id,
        ),
    )
    matches_played = matches.count()
    wins = matches.filter(TournamentMatch.winner_user_id == player.id).count()
    losses = matches_played - wins
    placements = TournamentStat.query.options(
        joinedload(TournamentStat.tournament),
    ).filter_by(user_id=player.id).order_by(
        TournamentStat.rank.asc(), TournamentStat.points.desc(),
    ).limit(20).all()
    joined_tournaments = UserTournament.query.options(
        joinedload(UserTournament.tournament),
    ).filter(
        UserTournament.user_id == player.id,
        UserTournament.payment_status.in_(['paid', 'free']),
    ).order_by(UserTournament.joined_at.desc()).limit(10).all()
    achievements = UserAchievement.query.options(
        joinedload(UserAchievement.achievement),
    ).filter(
        UserAchievement.user_id == player.id,
        or_(
            UserAchievement.unlocked_at.isnot(None),
            UserAchievement.achievement.has(Achievement.hidden.is_(False)),
        ),
    ).order_by(UserAchievement.unlocked_at.desc()).limit(12).all()
    return render_template(
        'public_profile.html', player=player, settings=settings,
        matches_played=matches_played, wins=wins, losses=losses,
        win_rate=round((wins / matches_played) * 100) if matches_played else 0,
        placements=placements, joined_tournaments=joined_tournaments,
        achievements=achievements,
        is_blocked=users_have_block(current_user.id, player.id) if current_user.is_authenticated else False,
    )


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    preferences = get_or_create_user_settings(current_user.id)
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        bio = (request.form.get('bio') or '').strip()
        avatar_url = (request.form.get('avatar_url') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{3,150}', username):
            flash('Username must be 3-150 letters, numbers, or underscores.', 'error')
            return redirect(url_for('settings'))
        username_owner = User.query.filter(
            db.func.lower(User.username) == username.lower(), User.id != current_user.id,
        ).first()
        if username_owner:
            flash('That username is already in use.', 'error')
            return redirect(url_for('settings'))
        if len(bio) > 500 or len(avatar_url) > 500:
            flash('Profile information is too long.', 'error')
            return redirect(url_for('settings'))
        if avatar_url and avatar_url != current_user.avatar_url:
            avatar_parts = urlparse(avatar_url)
            local_avatar = avatar_url.startswith('/static/') and '..' not in avatar_parts.path.split('/')
            hosted_avatar = (
                avatar_parts.scheme == 'https'
                and avatar_parts.hostname == 'images.unsplash.com'
                and not avatar_parts.username
                and not avatar_parts.password
            )
            if not (local_avatar or hosted_avatar):
                flash('Avatar must be a local static asset or hosted on images.unsplash.com.', 'error')
                return redirect(url_for('settings'))

        current_user.username = username
        current_user.bio = bio or None
        current_user.avatar_url = avatar_url or None
        preferences.tournament_notifications = request.form.get('tournament_notifications') == 'on'
        preferences.match_notifications = request.form.get('match_notifications') == 'on'
        preferences.wallet_notifications = request.form.get('wallet_notifications') == 'on'
        preferences.chat_notifications = request.form.get('chat_notifications') == 'on'
        preferences.marketing_notifications = request.form.get('marketing_notifications') == 'on'
        preferences.profile_public = request.form.get('profile_public') == 'on'
        preferences.allow_direct_messages = request.form.get('allow_direct_messages') == 'on'
        preferences.reduce_motion = request.form.get('reduce_motion') == 'on'
        preferences.larger_text = request.form.get('larger_text') == 'on'
        theme = request.form.get('theme', preferences.theme)
        if theme not in {'dark', 'light'}:
            db.session.rollback()
            flash('Choose Dark or Light for your theme.', 'error')
            return redirect(url_for('settings'))
        preferences.theme = theme
        preferred_games = [
            game.strip()[:100] for game in request.form.getlist('preferred_games')
            if game.strip() and len(game) <= 100
        ][:10]
        preferences.preferred_games = list(dict.fromkeys(preferred_games))
        game_ids = {}
        for line in (request.form.get('game_ids') or '').splitlines()[:20]:
            if ':' not in line:
                continue
            game, game_id = (value.strip() for value in line.split(':', 1))
            if game and game_id and len(game) <= 100 and len(game_id) <= 150:
                game_ids[game] = game_id
        preferences.game_ids = game_ids
        db.session.commit()
        flash('Settings updated.', 'success')
        return redirect(url_for('settings'))

    available_games = [row[0] for row in db.session.query(Tournament.game).distinct().order_by(Tournament.game).limit(50).all()]
    blocks = UserBlock.query.options(joinedload(UserBlock.blocked)).filter_by(blocker_id=current_user.id).order_by(UserBlock.created_at.desc()).all()
    return render_template(
        'settings.html', preferences=preferences, available_games=available_games,
        blocks=blocks, version=os.environ.get('GAMEARENA_VERSION', 'Flask V1'),
    )


@app.route('/search')
def search():
    query = (request.args.get('q') or '').strip()[:100]
    players = []
    tournaments = []
    games = []
    if len(query) >= 2:
        players = User.query.outerjoin(UserSettings, UserSettings.user_id == User.id).filter(
            User.suspended.is_(False),
            or_(UserSettings.id.is_(None), UserSettings.profile_public.is_(True)),
            User.username.ilike(f'%{query}%'),
        ).order_by(User.username.asc()).limit(8).all()
        tournaments = Tournament.query.filter(
            or_(Tournament.name.ilike(f'%{query}%'), Tournament.game.ilike(f'%{query}%')),
        ).order_by(Tournament.match_time.asc().nullslast(), Tournament.id.desc()).limit(8).all()
        games = [row[0] for row in db.session.query(Tournament.game).filter(
            Tournament.game.ilike(f'%{query}%'),
        ).distinct().order_by(Tournament.game.asc()).limit(8).all()]
    return render_template(
        'search.html', query=query, players=players, tournaments=tournaments, games=games,
    )


def persist_profile_photo(filename, image):
    # Store only one normalized, small photo per account in the existing DB.
    ProfilePhoto.query.filter_by(user_id=current_user.id).delete()
    db.session.add(ProfilePhoto(id=filename[:-5], user_id=current_user.id, image=image))
    return url_for('database_avatar', photo_id=filename[:-5])


@app.route('/media/profile/<photo_id>.webp')
def database_avatar(photo_id):
    if not re.fullmatch(r'[a-f0-9]{32}', photo_id):
        abort(404)
    photo = db.session.get(ProfilePhoto, photo_id)
    if not photo:
        abort(404)
    response = Response(photo.image, mimetype='image/webp')
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.route('/profile/photo', methods=['POST'])
@login_required
def upload_profile_photo():
    upload = request.files.get('avatar')
    if not upload or not upload.filename:
        flash('Choose a profile photo first.', 'error')
    else:
        try:
            photo_url = store_avatar(upload, app, persist=persist_profile_photo)
            current_user.avatar_url = photo_url
            db.session.commit()
            flash('Your profile photo was updated.', 'success')
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
    return redirect(url_for('profile'))


@app.route('/media/avatars/<filename>')
def avatar_file(filename):
    if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename):
        abort(404)
    folder = os.environ.get('AVATAR_UPLOAD_DIR') or os.path.join(app.instance_path, 'avatars')
    return send_from_directory(folder, filename, mimetype='image/webp', max_age=31536000)


@app.route('/notifications/preview')
@login_required
def notification_preview():
    records = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(6).all()
    return jsonify({'unread':get_unread_notification_count(current_user.id), 'notifications':[
        {'id':item.id, 'message':item.message, 'category':item.category, 'target_url':item.target_url,
         'unread':item.read_at is None, 'created_at':item.created_at.isoformat() if item.created_at else None,
         'read_url':url_for('mark_notification_read', notification_id=item.id)} for item in records]})


@app.route('/notifications/push', methods=['GET', 'POST', 'DELETE'])
@login_required
def push_subscription():
    if request.method == 'GET':
        return jsonify({'configured':push_configured(), 'public_key':os.environ.get('VAPID_PUBLIC_KEY', '') if push_configured() else ''})
    data = request.get_json(silent=True) or {}
    value = data.get('subscription')
    if not valid_subscription(value):
        return jsonify({'error':'This browser notification subscription is invalid.'}), 400
    digest = hashlib.sha256(value['endpoint'].encode()).hexdigest()
    if request.method == 'DELETE':
        PushSubscription.query.filter_by(user_id=current_user.id, endpoint_hash=digest).delete()
        db.session.commit(); session.pop('push_endpoint_hash', None)
        return jsonify({'status':'removed'})
    if not push_configured():
        return jsonify({'error':'Phone notifications are not configured yet.'}), 503
    existing = PushSubscription.query.filter_by(endpoint_hash=digest).first()
    if existing and existing.user_id != current_user.id:
        return jsonify({'error':'Sign out of the previous account on this browser first.'}), 409
    if existing:
        existing.subscription = value
    else:
        db.session.add(PushSubscription(user_id=current_user.id, endpoint_hash=digest, subscription=value))
    db.session.commit(); session['push_endpoint_hash'] = digest
    return jsonify({'status':'saved'})


@app.route('/users/<int:user_id>/block', methods=['POST'])
@login_required
def block_user(user_id):
    target = User.query.get_or_404(user_id)
    if target.id == current_user.id:
        abort(400)
    if not UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=target.id).first():
        db.session.add(UserBlock(blocker_id=current_user.id, blocked_id=target.id))
        db.session.commit()
    flash(f'{target.username} is blocked from direct messaging you.', 'success')
    return redirect(safe_next_url(request.referrer) or url_for('settings'))


@app.route('/users/<int:user_id>/unblock', methods=['POST'])
@login_required
def unblock_user(user_id):
    UserBlock.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).delete()
    db.session.commit()
    target = db.session.get(User, user_id)
    if target:
        remaining_block = users_have_block(current_user.id, target.id)
        settings = target.settings
        own_settings = current_user.settings
        if remaining_block:
            flash(f'You unblocked {target.username}. They still have you blocked.', 'success')
        elif own_settings and not own_settings.allow_direct_messages:
            flash(f'You unblocked {target.username}. Enable Allow direct messages in Settings to receive messages.', 'success')
        elif settings and not settings.allow_direct_messages:
            flash(f'You unblocked {target.username}. Their direct messages are disabled.', 'success')
        else:
            flash(f'{target.username} is unblocked. You can message each other again.', 'success')
        for owner_id, partner_id in [(current_user.id, target.id), (target.id, current_user.id)]:
            socketio.emit('conversation_access_changed', {'partner_id':partner_id}, room=f'user:{owner_id}')
    return redirect(safe_next_url(request.referrer) or url_for('settings'))


@app.route('/users/<int:user_id>/report', methods=['POST'])
@login_required
def report_user(user_id):
    target = User.query.get_or_404(user_id)
    if target.id == current_user.id:
        abort(400)
    reason = (request.form.get('reason') or '').strip()
    if not reason or len(reason) > 2000:
        flash('Add a short reason for the report.', 'error')
        return redirect(url_for('public_profile', user_id=target.id))
    db.session.add(UserReport(
        reporter_id=current_user.id, target_user_id=target.id,
        content_type='player', reason=reason,
    ))
    db.session.commit()
    flash('Report sent to the admin team.', 'success')
    return redirect(url_for('public_profile', user_id=target.id))


@app.route('/chat/messages/<int:message_id>/report', methods=['POST'])
@login_required
def report_chat_message(message_id):
    message = GlobalChatMessage.query.get_or_404(message_id)
    if message.user_id == current_user.id:
        abort(400)
    reason = (request.form.get('reason') or '').strip()
    if not reason or len(reason) > 2000:
        flash('Add a short reason for the report.', 'error')
    else:
        db.session.add(UserReport(
            reporter_id=current_user.id, target_user_id=message.user_id,
            content_type='global_chat', content_id=message.id, reason=reason,
        ))
        db.session.commit()
        flash('Message report sent to the admin team.', 'success')
    return redirect(url_for('chat'))


@app.route('/support', methods=['GET', 'POST'])
@login_required
def support():
    if request.method == 'POST':
        reason = (request.form.get('reason') or '').strip()
        if not reason or len(reason) > 2000:
            flash('Describe the issue in 2,000 characters or fewer.', 'error')
        else:
            db.session.add(UserReport(
                reporter_id=current_user.id, content_type='support', reason=reason,
            ))
            db.session.commit()
            flash('Your message was sent to the support team.', 'success')
            return redirect(url_for('support'))
    return render_template('support.html')


@app.route('/admin/reports')
@login_required
def admin_reports():
    if not is_admin_user():
        abort(403)
    reports = UserReport.query.options(
        joinedload(UserReport.reporter), joinedload(UserReport.target_user),
    ).order_by(UserReport.status.asc(), UserReport.created_at.asc()).limit(100).all()
    chat_message_ids = [
        report.content_id for report in reports
        if report.content_type == 'global_chat' and report.content_id
    ]
    reported_messages = {
        message.id: message for message in GlobalChatMessage.query.filter(
            GlobalChatMessage.id.in_(chat_message_ids),
        ).all()
    } if chat_message_ids else {}
    return render_template(
        'admin_reports.html', reports=reports,
        reported_messages=reported_messages,
    )


@app.route('/admin/reports/<int:report_id>/review', methods=['POST'])
@login_required
def review_report(report_id):
    if not is_admin_user():
        abort(403)
    report = UserReport.query.get_or_404(report_id)
    action = (request.form.get('action') or '').strip()
    if (report.status == 'pending' and action == 'resolve') or (
        report.status == 'resolved' and action == 'reopen'
    ):
        report.status = 'resolved' if action == 'resolve' else 'pending'
        report.reviewed_by_id = current_user.id
        report.reviewed_at = datetime.utcnow() if action == 'resolve' else None
        db.session.commit()
        flash('Report updated.', 'success')
    return redirect(url_for('admin_reports'))


def direct_message_room_key(user_one_id, user_two_id):
    lower_id, higher_id = sorted((int(user_one_id), int(user_two_id)))
    return f'direct:{lower_id}:{higher_id}'


def quoted_message(parent):
    if not parent:
        return None
    owner = parent.sender if isinstance(parent, DirectMessage) else parent.user
    return {'id':parent.id, 'username':owner.username if owner else 'Player', 'message':parent.message[:200], 'deleted':bool(parent.deleted_at)}


@app.route('/messages/<int:user_id>')
@login_required
def direct_message(user_id):
    recipient = User.query.get_or_404(user_id)
    if not can_direct_message(current_user, recipient):
        flash('This conversation is unavailable due to account privacy or blocking.', 'error')
        return redirect(url_for('chat'))
    conversation_filter = db.or_(
        db.and_(DirectMessage.sender_id == current_user.id, DirectMessage.recipient_id == recipient.id),
        db.and_(DirectMessage.sender_id == recipient.id, DirectMessage.recipient_id == current_user.id),
    )
    recent_messages = DirectMessage.query.filter(conversation_filter).order_by(
        DirectMessage.created_at.desc(), DirectMessage.id.desc(),
    ).limit(100).all()
    messages = list(reversed(recent_messages))
    DirectMessage.query.filter_by(
        sender_id=recipient.id, recipient_id=current_user.id, read_at=None,
    ).update({'read_at': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    unread_count = DirectMessage.query.filter_by(
        recipient_id=current_user.id, read_at=None,
    ).count()
    socketio.emit('unread_count', {'unread': unread_count}, room=f'user:{current_user.id}')
    return render_template(
        'chat.html', messages=[], chat_partners=[], conversation_user=recipient,
        direct_messages=messages,
        is_blocked=users_have_block(current_user.id, recipient.id),
        dm_unread_count=DirectMessage.query.filter_by(
            recipient_id=current_user.id, read_at=None,
        ).count(),
    )


@app.route('/messages/<int:user_id>/read', methods=['POST'])
@login_required
def read_direct_messages(user_id):
    partner = db.session.get(User, user_id)
    if not can_direct_message(current_user, partner):
        return jsonify({'error':'Conversation unavailable.'}), 403
    DirectMessage.query.filter_by(sender_id=user_id, recipient_id=current_user.id, read_at=None).update({'read_at':datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    unread = DirectMessage.query.filter_by(recipient_id=current_user.id, read_at=None).count()
    socketio.emit('unread_count', {'unread':unread}, room=f'user:{current_user.id}')
    return jsonify({'unread':unread})


# -------------------------
# NEW: TOURNAMENT DETAILS PAGE ðŸ”¥
# -------------------------
@app.route("/tournament/<int:tournament_id>")
def tournament_details(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    joined_participant = False
    can_matchmake = False
    can_view_match_rooms = is_admin_user()
    pending_payment = False

    if current_user.is_authenticated:
        join = UserTournament.query.filter_by(
            user_id=current_user.id,
            tournament_id=tournament_id
        ).first()
        pending_payment = bool(join and join.payment_status == 'pending')
        if join and join.payment_status in {'paid', 'free'}:
            joined_participant = True
            can_view_match_rooms = True
            active_match = TournamentMatch.query.filter(
                TournamentMatch.tournament_id == tournament_id,
                TournamentMatch.status.in_({'scheduled', 'ongoing', 'pending_confirmation', 'disputed'}),
                or_(
                    TournamentMatch.player_one_user_id == current_user.id,
                    TournamentMatch.player_two_user_id == current_user.id,
                ),
            ).first()
            can_matchmake = tournament.status in {'live', 'ongoing'} and active_match is None

    matches = []
    if tournament.id:
        matches = TournamentMatch.query.options(
            joinedload(TournamentMatch.player_one), joinedload(TournamentMatch.player_two),
            joinedload(TournamentMatch.winner), joinedload(TournamentMatch.submitted_by),
            selectinload(TournamentMatch.disputes),
        ).filter_by(tournament_id=tournament.id).order_by(
            TournamentMatch.round_number.asc().nullslast(),
            TournamentMatch.match_order.asc().nullslast(),
            TournamentMatch.created_at.asc(),
        ).all()

    return render_template(
        "tournament_details.html",
        tournament=tournament,
        joined_participant=joined_participant,
        can_matchmake=can_matchmake,
        matches=matches,
        can_view_match_rooms=can_view_match_rooms,
        pending_payment=pending_payment,
    )


# -------------------------
# REGISTER
# -------------------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = RegistrationForm()

    if form.validate_on_submit():

        existing_user = User.query.filter_by(email=form.email.data.lower().strip()).first() or User.query.filter_by(username=form.username.data).first()

        if existing_user:
            if existing_user.email == form.email.data:
                flash("Email already registered", "error")
            else:
                flash("Username already taken", "error")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(form.password.data)

        new_user = User(
            username=form.username.data,
            email=form.email.data.lower().strip(),
            password=hashed_password,
            email_verified=False
        )

        try:
            db.session.add(new_user)
            db.session.commit()
            if send_verification_code(new_user):
                flash('Verification email requested. Please check your inbox and spam folder.', 'success')
            else:
                flash("Your account was created, but we couldn't send the verification email right now. Please try again shortly.", 'error')
            return redirect(url_for("verify_email", email=new_user.email))
        except Exception as e:
            db.session.rollback()
            flash("An error occurred. Please try again.", "error")
            app.logger.error(f"Registration error: {e}")

    return render_template("register.html", form=form)


# -------------------------
# LOGIN
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        if user and check_password_hash(user.password, form.password.data):
            if user.suspended:
                flash("This account has been suspended.", "error")
                return redirect(url_for("login"))

            if not user.email_verified and not getattr(user, "is_admin", False):
                if send_verification_code(user):
                    flash('Verification email requested. Please check your inbox and spam folder.', 'success')
                else:
                    flash("Your email isn't verified, and we couldn't send a new code right now. Please try again shortly.", 'error')
                return redirect(url_for("verify_email", email=user.email))

            if getattr(user, "is_admin", False) and not user.email_verified:
                user.email_verified = True
                db.session.commit()

            login_user(user)
            next_page = safe_next_url(request.args.get('next'))
            return redirect(next_page or url_for("dashboard"))

        flash("Invalid email or password", "error")

    return render_template("login.html", form=form)


@app.route('/login/google')
def login_google():
    google_config = get_google_oauth_config()
    client_id = google_config['client_id']

    if not client_id:
        flash('Google sign-in is not configured yet.', 'error')
        return redirect(url_for('login'))

    params = {
        'client_id': client_id,
        'redirect_uri': google_config['redirect_uri'],
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'offline',
        'prompt': 'consent',
    }
    oauth_state = secrets.token_urlsafe(32)
    session['google_oauth_state'] = oauth_state
    params['state'] = oauth_state
    auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)


@app.route('/auth/google/callback')
def google_callback():
    google_config = get_google_oauth_config()
    client_id = google_config['client_id']
    client_secret = google_config['client_secret']

    if not client_id or not client_secret:
        flash('Google sign-in is not configured yet.', 'error')
        return redirect(url_for('login'))

    code = request.args.get('code')
    if not code:
        flash('Google sign-in was cancelled.', 'error')
        return redirect(url_for('login'))

    returned_state = request.args.get('state')
    expected_state = session.pop('google_oauth_state', None)
    if not expected_state or not returned_state or not hmac.compare_digest(expected_state, returned_state):
        flash('Google sign-in could not be verified. Please try again.', 'error')
        return redirect(url_for('login'))

    token_response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': google_config['redirect_uri'],
            'grant_type': 'authorization_code',
        },
        timeout=15,
    )
    token_data = token_response.json() if token_response.ok else {}
    access_token = token_data.get('access_token')
    if not access_token:
        flash('Google sign-in failed. Please try again.', 'error')
        return redirect(url_for('login'))

    user_info_response = requests.get(
        GOOGLE_USER_INFO_URL,
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=15,
    )
    user_info = user_info_response.json() if user_info_response.ok else {}
    email = (user_info.get('email') or '').strip().lower()
    name = (user_info.get('name') or email.split('@', 1)[0]).strip()
    picture = user_info.get('picture')

    if not email:
        flash('Google sign-in did not return an email address.', 'error')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        base_username = ''.join(char for char in name.replace(' ', '_') if char.isalnum() or char == '_') or 'google_user'
        candidate = base_username[:150]
        counter = 1
        while User.query.filter_by(username=candidate).first():
            suffix = f'_{counter}'
            candidate = f'{base_username[:150 - len(suffix)]}{suffix}'
            counter += 1
        user = User(
            username=candidate,
            email=email,
            password=generate_password_hash(os.urandom(24).hex()),
            email_verified=True,
            avatar_url=picture,
        )
        db.session.add(user)
        db.session.commit()

    if not user.email_verified:
        user.email_verified = True
        user.avatar_url = picture or user.avatar_url
        db.session.commit()

    login_user(user)
    flash('Signed in successfully with Google.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    form = EmailVerificationForm()
    email = request.args.get('email', '')
    if request.method == 'POST' and request.form.get('action') != 'resend':
        email = form.email.data.lower().strip()

    if request.method == 'POST' and request.form.get('action') == 'resend':
        email = (request.form.get('email') or '').strip().lower()
        user = User.query.filter_by(email=email).first() if email else None
        if user and not user.email_verified:
            if send_verification_code(user):
                flash('Verification email requested. Please check your inbox and spam folder.', 'success')
            else:
                flash("We couldn't send the verification email right now. Please try again shortly.", 'error')
        else:
            flash('Unable to resend code. Please register first.', 'error')
        return redirect(url_for('verify_email', email=email))

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if not user:
            flash('No account found for that email.', 'error')
            return redirect(url_for('register'))

        if user.email_verified:
            flash('Email already verified. Please login.', 'success')
            return redirect(url_for('login'))

        if (
            not user.verification_code
            or not hmac.compare_digest(user.verification_code, form.code.data)
        ):
            flash('This verification code is invalid or has expired. Please request a new code.', 'error')
            return render_template('verify_email.html', form=form)

        if not user.verification_expires_at or user.verification_expires_at < datetime.utcnow():
            flash('This verification code is invalid or has expired. Please request a new code.', 'error')
            return render_template('verify_email.html', form=form)

        user.email_verified = True
        user.verification_code = None
        user.verification_expires_at = None
        db.session.commit()

        flash('Email verified! Log in below to enter your arena.', 'success')
        return redirect(url_for('login'))

    if email:
        form.email.data = email

    return render_template('verify_email.html', form=form)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user:
            send_password_reset_code(user)
        flash('If that email exists, a reset code will be sent if email delivery is available.', 'success')
        return redirect(url_for('reset_password', email=form.email.data.lower().strip()))

    return render_template('forgot_password.html', form=form)


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    form = ResetPasswordForm()
    email = request.args.get('email', '')

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if not user or not user.reset_code or user.reset_code != form.code.data:
            flash('Invalid email or reset code.', 'error')
            return render_template('reset_password.html', form=form)

        if not user.reset_expires_at or user.reset_expires_at < datetime.utcnow():
            flash('Reset code expired. Please request a new one.', 'error')
            return redirect(url_for('forgot_password'))

        user.password = generate_password_hash(form.new_password.data)
        user.reset_code = None
        user.reset_expires_at = None
        db.session.commit()
        flash('Password reset successful. Please log in.', 'success')
        return redirect(url_for('login'))

    if email:
        form.email.data = email

    return render_template('reset_password.html', form=form)


# -------------------------
# DASHBOARD
# -------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    all_joins = UserTournament.query.options(joinedload(UserTournament.tournament)).filter_by(user_id=current_user.id).order_by(UserTournament.joined_at.desc()).limit(50).all()

    # Deduplicate: show only one entry per tournament (latest join)
    seen_tournaments = set()
    joined_tournaments = []
    for ut in all_joins:
        if ut.tournament_id not in seen_tournaments:
            joined_tournaments.append(ut)
            seen_tournaments.add(ut.tournament_id)

    match_players = or_(
        TournamentMatch.player_one_user_id == current_user.id,
        TournamentMatch.player_two_user_id == current_user.id,
    )
    upcoming_matches = (
        TournamentMatch.query
        .join(Tournament)
        .options(
            joinedload(TournamentMatch.tournament),
            joinedload(TournamentMatch.player_one),
            joinedload(TournamentMatch.player_two),
        )
        .filter(
            match_players,
            TournamentMatch.status.in_(['scheduled', 'ongoing']),
            Tournament.status.notin_(['finished', 'cancelled']),
        )
        .order_by(Tournament.match_time.asc().nullslast(), TournamentMatch.created_at.asc())
        .limit(5)
        .all()
    )
    recent_matches = (
        TournamentMatch.query
        .options(
            joinedload(TournamentMatch.tournament),
            joinedload(TournamentMatch.player_one),
            joinedload(TournamentMatch.player_two),
            joinedload(TournamentMatch.winner),
        )
        .filter(
            match_players,
            TournamentMatch.status.in_(['pending_confirmation', 'disputed']),
        )
        .order_by(TournamentMatch.updated_at.desc(), TournamentMatch.id.desc())
        .limit(5)
        .all()
    )
    confirmed_matches = TournamentMatch.query.filter(
        match_players,
        TournamentMatch.status == 'confirmed',
        TournamentMatch.winner_user_id.isnot(None),
    )
    matches_played = confirmed_matches.count()
    wins = confirmed_matches.filter(TournamentMatch.winner_user_id == current_user.id).count()
    losses = matches_played - wins
    win_rate = round((wins / matches_played) * 100) if matches_played else 0

    tournament_stats = TournamentStat.query.options(
        joinedload(TournamentStat.tournament),
    ).filter_by(user_id=current_user.id).order_by(
        TournamentStat.rank.asc(), TournamentStat.points.desc(),
    ).all()

    recent_notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )
    recent_achievements = UserAchievement.query.options(
        joinedload(UserAchievement.achievement),
    ).filter(
        UserAchievement.user_id == current_user.id,
        UserAchievement.unlocked_at.isnot(None),
    ).order_by(UserAchievement.unlocked_at.desc()).limit(3).all()

    total_paid = db.session.query(db.func.coalesce(db.func.sum(UserTournament.amount_paid), 0)).filter(UserTournament.user_id == current_user.id, UserTournament.payment_status == 'paid').scalar()

    return render_template(
        "dashboard.html",
        joined_tournaments=joined_tournaments,
        upcoming_matches=upcoming_matches,
        tournament_stats=tournament_stats,
        recent_notifications=recent_notifications,
        total_paid=total_paid,
        recent_matches=recent_matches,
        matches_played=matches_played,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        unread_notification_count=get_unread_notification_count(current_user.id),
        recent_achievements=recent_achievements,
    )


@app.route("/notifications")
@login_required
def notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc(), Notification.id.desc(),
    ).limit(100).all()
    unread_count = get_unread_notification_count(current_user.id)
    return render_template("notifications.html", notifications=notifications, unread_count=unread_count)


@app.route('/notifications/count')
@login_required
def notification_count():
    return jsonify({'unread': get_unread_notification_count(current_user.id)})


@app.route('/notifications/read-all', methods=['POST'])
@login_required
def read_all_notifications():
    unread = mark_notifications_read_for_user(current_user.id)
    socketio.emit('notification_unread_count', {'unread': unread}, room=f'user:{current_user.id}')
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'unread':unread})
    flash('All notifications marked as read.', 'success')
    return redirect(url_for('notifications'))


@app.route('/notifications/<int:notification_id>/unread', methods=['POST'])
@login_required
def mark_notification_unread(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    notification.read_at = None
    db.session.commit()
    socketio.emit('notification_unread_count', {'unread': get_unread_notification_count(current_user.id)}, room=f'user:{current_user.id}')
    return redirect(url_for('notifications'))


@app.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id, user_id=current_user.id,
    ).first_or_404()
    if notification.read_at is None:
        notification.read_at = datetime.utcnow()
        db.session.commit()
    socketio.emit('notification_unread_count', {'unread': get_unread_notification_count(current_user.id)}, room=f'user:{current_user.id}')
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'unread':get_unread_notification_count(current_user.id)})
    return redirect(safe_next_url(request.form.get('next')) or url_for('notifications'))


# -------------------------# ADMIN PANEL
# -------------------------
@app.route("/admin")
@login_required
def admin():
    if not current_user.is_admin:
        abort(403)  # Forbidden
    
    tournaments = Tournament.query.all()
    return render_template("admin.html", tournaments=tournaments)

@app.route("/admin/stats")
@login_required
def admin_stats():
    if not current_user.is_admin:
        abort(403)
    
    total_users = User.query.count()
    total_tournaments = Tournament.query.count()
    total_revenue = db.session.query(db.func.sum(UserTournament.amount_paid)).filter(UserTournament.payment_status == 'paid').scalar() or 0
    
    return render_template("admin_stats.html", total_users=total_users, total_tournaments=total_tournaments, total_revenue=total_revenue)

@app.route("/admin/users")
@login_required
def admin_users():
    if not current_user.is_admin:
        abort(403)
    
    users = User.query.all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/users/suspend/<int:user_id>", methods=['POST'])
@login_required
def suspend_user(user_id):
    if not current_user.is_admin:
        abort(403)
    
    user = User.query.get_or_404(user_id)
    user.suspended = True
    db.session.commit()
    flash(f"User {user.username} suspended.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/unsuspend/<int:user_id>", methods=['POST'])
@login_required
def unsuspend_user(user_id):
    if not current_user.is_admin:
        abort(403)
    
    user = User.query.get_or_404(user_id)
    user.suspended = False
    db.session.commit()
    flash(f"User {user.username} unsuspended.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/delete/<int:user_id>", methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} deleted.", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/tournaments/start/<int:tournament_id>", methods=['POST'])
@login_required
def start_tournament(tournament_id):
    if not current_user.is_admin:
        abort(403)
    
    tournament = Tournament.query.get_or_404(tournament_id)
    tournament.status = 'ongoing'
    db.session.commit()
    flash(f"Tournament {tournament.name} started.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/tournaments/end/<int:tournament_id>", methods=['POST'])
@login_required
def end_tournament(tournament_id):
    if not current_user.is_admin:
        abort(403)
    
    tournament = Tournament.query.get_or_404(tournament_id)
    tournament.status = 'finished'
    db.session.commit()
    flash(f"Tournament {tournament.name} finished.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/tournaments/cancel/<int:tournament_id>", methods=['POST'])
@login_required
def cancel_tournament(tournament_id):
    if not current_user.is_admin:
        abort(403)
    
    tournament = Tournament.query.get_or_404(tournament_id)
    tournament.status = 'cancelled'
    db.session.commit()
    flash(f"Tournament {tournament.name} cancelled.", "success")
    return redirect(url_for("admin"))

@app.route('/admin/tournaments/<int:tournament_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_tournament(tournament_id):
    if not current_user.is_admin:
        abort(403)

    tournament = Tournament.query.get_or_404(tournament_id)
    form = TournamentSetupForm(obj=tournament)
    if request.method == 'POST' and form.validate_on_submit():
        tournament.entry_fee = int(form.entry_fee.data)
        tournament.prize = int(form.prize_pool.data)
        tournament.max_participants = int(form.max_participants.data)
        tournament.room_id = form.room_id.data
        tournament.room_password = form.room_password.data
        tournament.status = form.status.data
        tournament.first_place = form.first_place.data
        tournament.second_place = form.second_place.data
        tournament.third_place = form.third_place.data

        if form.match_time.data:
            try:
                tournament.match_time = datetime.strptime(form.match_time.data, '%Y-%m-%d %H:%M')
            except ValueError:
                flash('Match time must be in YYYY-MM-DD HH:MM format.', 'error')
                return render_template('admin_tournament_edit.html', tournament=tournament, form=form)
        else:
            tournament.match_time = None

        db.session.commit()
        flash(f"Tournament '{tournament.name}' updated successfully!", 'success')
        return redirect(url_for('admin'))

    if tournament.match_time:
        form.match_time.data = tournament.match_time.strftime('%Y-%m-%d %H:%M')
    form.prize_pool.data = tournament.prize

    return render_template('admin_tournament_edit.html', tournament=tournament, form=form)


@app.route('/admin/tournaments/<int:tournament_id>/leaderboard', methods=['GET', 'POST'])
@login_required
def admin_tournament_leaderboard(tournament_id):
    if not current_user.is_admin:
        abort(403)

    tournament = Tournament.query.get_or_404(tournament_id)
    form = LeaderboardEntryForm()
    choices = []
    seen = set()
    for ut in tournament.participants:
        if ut.user and ut.user.id not in seen:
            choices.append((ut.user.id, ut.user.username))
            seen.add(ut.user.id)
    form.user_id.choices = choices

    if form.validate_on_submit():
        stat = TournamentStat.query.filter_by(user_id=form.user_id.data, tournament_id=tournament_id).first()
        if not stat:
            stat = TournamentStat(user_id=form.user_id.data, tournament_id=tournament_id)
        stat.wins = form.wins.data
        stat.kills = form.kills.data
        stat.points = form.points.data
        stat.rank = form.rank.data
        db.session.add(stat)
        db.session.commit()
        flash('Leaderboard entry saved.', 'success')
        return redirect(url_for('admin_tournament_leaderboard', tournament_id=tournament_id))

    leaderboard = TournamentStat.query.filter_by(tournament_id=tournament_id).order_by(TournamentStat.rank).all()
    return render_template('admin_leaderboard.html', tournament=tournament, form=form, leaderboard=leaderboard)


@app.route('/admin/tournaments/<int:tournament_id>/leaderboard/delete/<int:stat_id>', methods=['POST'])
@login_required
def delete_leaderboard_entry(tournament_id, stat_id):
    if not current_user.is_admin:
        abort(403)

    stat = TournamentStat.query.get_or_404(stat_id)
    db.session.delete(stat)
    db.session.commit()
    flash('Leaderboard entry removed.', 'success')
    return redirect(url_for('admin_tournament_leaderboard', tournament_id=tournament_id))


@app.route("/admin/create-tournament", methods=["GET", "POST"])
@login_required
def create_tournament():
    if not current_user.is_admin:
        abort(403)  # Forbidden
    
    form = TournamentForm()
    if form.validate_on_submit():
        # Check if tournament with this game name already exists
        existing_tournament = Tournament.query.filter_by(game=form.game.data).first()
        if existing_tournament:
            flash("A tournament with this game name already exists!", "error")
            return redirect(url_for("create_tournament"))
        
        try:
            match_time = None
            if form.match_time.data:
                try:
                    match_time = datetime.strptime(form.match_time.data, '%Y-%m-%d %H:%M')
                except ValueError:
                    flash("Match time must be in YYYY-MM-DD HH:MM format.", "error")
                    return render_template("create_tournament.html", form=form)

            new_tournament = Tournament(
                name=form.game.data,  # Use game name as tournament name
                game=form.game.data,
                entry_fee=int(form.entry_fee.data),
                prize=int(form.prize_pool.data),  # Map prize_pool to prize field
                max_participants=int(form.max_participants.data),
                match_time=match_time
            )
            db.session.add(new_tournament)
            db.session.commit()
            flash(f"Tournament '{form.game.data}' created successfully!", "success")
            return redirect(url_for("admin"))
        except Exception as e:
            db.session.rollback()
            flash("An error occurred while creating the tournament.", "error")
            app.logger.error(f"Tournament creation error: {e}")
    
    return render_template("create_tournament.html", form=form)


# -------------------------  # JOIN TOURNAMENT
# ------------------
@app.route("/join-tournament/<int:tournament_id>", methods=['GET', 'POST'])
@login_required
def join_tournament(tournament_id):
    # Serialize the capacity check with other joins and payment confirmations.
    tournament = Tournament.query.filter_by(id=tournament_id).with_for_update().populate_existing().first_or_404()
    if tournament.status != 'open':
        flash('Registration is closed for this tournament.', 'warning')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    existing_join = UserTournament.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()

    if existing_join:
        if existing_join.payment_status == 'pending':
            return redirect(url_for('pay_for_tournament', tournament_id=tournament_id))
        flash(f"You've already joined {tournament.game}!", "warning")
        return redirect(url_for("dashboard"))

    entrant_count = UserTournament.query.filter(UserTournament.tournament_id == tournament_id, UserTournament.payment_status.in_(['paid', 'free'])).count()
    if entrant_count >= tournament.max_participants:
        flash(f"{tournament.game} is FULL!", "error")
        return redirect(url_for("home"))

    # If tournament has entry fee, redirect to payment
    if tournament.entry_fee > 0:
        return redirect(url_for('pay_for_tournament', tournament_id=tournament_id))

    if request.method == 'GET':
        return render_template('join_confirmation.html', tournament=tournament)

    # Free tournament - join directly
    join = UserTournament(
        user_id=current_user.id,
        tournament_id=tournament_id,
        payment_status='free',
        amount_paid=0
    )
    db.session.add(join)
    db.session.commit()
    award_achievements_for_user(current_user.id)
    create_and_emit_notification(
        current_user.id, f'You joined {tournament.name}.', 'tournament',
        f'/tournament/{tournament.id}',
    )

    flash(f"Joined {tournament.game} successfully!", "success")
    return redirect(url_for("dashboard"))


# MATCH ROUTES
# -------------------------
@app.route('/tournament/<int:tournament_id>/create-matches', methods=['POST'])
@login_required
def create_matches(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    if not is_admin_user():
        flash('Only admins can create match pairings.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    matches = create_tournament_matches(tournament)
    if not matches:
        participant_count = active_participant_count(tournament)
        if participant_count >= 2 and participant_count & (participant_count - 1):
            flash('Bracket tournaments require a power-of-two field so no entrants are silently dropped.', 'error')
        else:
            flash('Not enough eligible participants to create matches yet.', 'error')
    else:
        flash(f'{len(matches)} matches created for this tournament.', 'success')
    return redirect(url_for('tournament_details', tournament_id=tournament_id))


def _get_paid_participants_not_in_assigned_match(tournament_id: int, exclude_user_id: int | None = None):
    """Return paid user_ids in this tournament that are not already assigned to an active match.

    Active match statuses:
    - scheduled
    - ongoing
    - pending_confirmation
    - disputed
    """
    active_statuses = {'scheduled', 'ongoing', 'pending_confirmation', 'disputed'}

    assigned_rows = TournamentMatch.query.filter(
        TournamentMatch.tournament_id == tournament_id,
        TournamentMatch.status.in_(active_statuses)
    ).all()

    assigned_user_ids = set()
    for m in assigned_rows:
        assigned_user_ids.add(m.player_one_user_id)
        assigned_user_ids.add(m.player_two_user_id)

    q = UserTournament.query.filter(
        UserTournament.tournament_id == tournament_id,
        UserTournament.payment_status.in_(['paid', 'free'])
    )
    user_ids = [ut.user_id for ut in q.all()]


    filtered = []
    for uid in user_ids:
        if uid in assigned_user_ids:
            continue
        if exclude_user_id is not None and uid == exclude_user_id:
            continue
        filtered.append(uid)

    return filtered


@app.route('/tournament/<int:tournament_id>/matchmake', methods=['POST'])
@login_required
def matchmake_player_pair(tournament_id):


    """Player-initiated pairing (Option A).

    Clicking user is paired with the next available waiting opponent.
    Only paid users participate.
    """
    tournament = Tournament.query.get_or_404(tournament_id)

    if TournamentMatch.query.filter(
        TournamentMatch.tournament_id == tournament_id,
        TournamentMatch.round_number.isnot(None),
    ).first():
        flash('This tournament uses an admin-managed bracket; follow the match shown below.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    # Only registered paid/free participants can request matchmaking.
    join = UserTournament.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id,
    ).first()

    if not join or join.payment_status not in {'paid', 'free'}:
        flash('Only registered participants can matchmake.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    #This here is to prevent making multiple assignments for the same user
    active_statuses = {'scheduled', 'ongoing', 'pending_confirmation', 'disputed'}
    existing = TournamentMatch.query.filter(
        TournamentMatch.tournament_id == tournament_id,
        TournamentMatch.status.in_(active_statuses),
        (TournamentMatch.player_one_user_id == current_user.id) | (TournamentMatch.player_two_user_id == current_user.id)
    ).first()

    if existing:
        flash('You already have an active match in this tournament.', 'warning')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    waiting_opponents = _get_paid_participants_not_in_assigned_match(tournament_id, exclude_user_id=current_user.id)

    if not waiting_opponents:
        flash('No available opponent yet. Wait for another player to matchmake.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    opponent_id = random.choice(waiting_opponents)

    # Create match for the clicker and the selected opponent
    match = TournamentMatch(
        tournament_id=tournament.id,
        player_one_user_id=current_user.id,
        player_two_user_id=opponent_id,
        status='scheduled',
    )
    db.session.add(match)

    # Put tournament live once we start creating pairings
    if tournament.status != 'live':
        tournament.status = 'live'

    db.session.commit()

    flash('Match found! Your pairing is now available below.', 'success')
    return redirect(url_for('tournament_details', tournament_id=tournament_id))



@app.route('/match/<int:match_id>/submit-result', methods=['POST'])
@login_required
def submit_match_result_route(match_id):
    match = TournamentMatch.query.get_or_404(match_id)
    tournament = match.tournament

    if not can_access_match(current_user.id, match):
        flash('Only the assigned players or an admin can view this match.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if current_user.id not in {match.player_one_user_id, match.player_two_user_id}:
        flash('Only an assigned player can submit a match result.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if match.status not in {'scheduled', 'ongoing'}:
        flash('This match is not accepting result submissions right now.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    room_code = request.form.get('room_code', '').strip()
    room_password = request.form.get('room_password', '').strip()
    player_profile_id = request.form.get('player_profile_id', '').strip()
    opponent_profile_id = request.form.get('opponent_profile_id', '').strip()
    winner_user_id = request.form.get('winner_user_id', '').strip()
    proof_note = request.form.get('proof_note', '').strip()

    if len(room_code) > 100 or len(room_password) > 100 or len(player_profile_id) > 150 or len(opponent_profile_id) > 150 or len(proof_note) > MAX_MATCH_PROOF_LENGTH:
        flash('One or more match fields are too long.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    if not room_code or not player_profile_id or not opponent_profile_id or not winner_user_id:
        flash('Please fill in the room details, profile IDs and winner before submitting.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    try:
        winner_id = int(winner_user_id)
    except (TypeError, ValueError):
        flash('Invalid winner selected for this match.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    # IMPORTANT ANTI-LIE VALIDATION:
    #Note Winner must be one of the two assigned players for this match.
    if winner_id not in {match.player_one_user_id, match.player_two_user_id}:
        flash('Invalid winner selected for this match.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    # Mtach Submission Submit for confirmation
    submit_match_result(
        match=match,
        user=current_user,
        room_code=room_code,
        room_password=room_password,
        player_profile_id=player_profile_id,
        opponent_profile_id=opponent_profile_id,
        winner_user_id=winner_id,
        proof_note=proof_note,
    )
    opponent_id = match.player_two_user_id if current_user.id == match.player_one_user_id else match.player_one_user_id
    create_and_emit_notification(
        opponent_id, f'{current_user.username} submitted a result for your match.',
        'match', f'/tournament/{tournament.id}',
    )
    flash('Match result submitted and waiting for confirmation.', 'success')
    return redirect(url_for('tournament_details', tournament_id=tournament.id))



@app.route('/match/<int:match_id>/confirm-result', methods=['POST'])
@login_required
def confirm_match_result(match_id):
    match = TournamentMatch.query.get_or_404(match_id)
    tournament = match.tournament

    if not can_access_match(current_user.id, match):
        flash('Only the assigned players or an admin can view this match.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if current_user.id not in {match.player_one_user_id, match.player_two_user_id}:
        flash('Only an assigned player can confirm a match result.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if match.status != 'pending_confirmation':
        flash('There is no submitted result waiting for confirmation.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if current_user.id == match.submitted_by_user_id:
        flash('The other player must confirm the submitted result.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if is_admin_user():
        flash('Admins can review disputed results only.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    match.status = 'confirmed'
    db.session.commit()
    for player_id in {match.player_one_user_id, match.player_two_user_id}:
        award_achievements_for_user(player_id)
    create_and_emit_notification(
        match.submitted_by_user_id,
        f'{current_user.username} confirmed your match result.',
        'match', f'/tournament/{tournament.id}',
    )
    advance_tournament_bracket(match)
    flash('Match result confirmed.', 'success')
    return redirect(url_for('tournament_details', tournament_id=tournament.id))


@app.route('/match/<int:match_id>/chat', methods=['POST'])
@login_required
def send_match_chat_message(match_id):
    match = TournamentMatch.query.get_or_404(match_id)
    tournament = match.tournament

    if not can_access_match(current_user.id, match):
        flash('Only the assigned players or an admin can chat in this match.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    message = request.form.get('message', '').strip()
    if len(message) > MAX_CHAT_MESSAGE_LENGTH:
        flash('Message is too long.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if message:
        chat_message = TournamentMatchChatMessage(match_id=match.id, user_id=current_user.id, message=message)
        db.session.add(chat_message)
        db.session.commit()
        flash('Message sent.', 'success')
    else:
        flash('Message cannot be empty.', 'error')
    return redirect(url_for('tournament_details', tournament_id=tournament.id))


@app.route('/match/<int:match_id>/dispute', methods=['POST'])
@login_required
def dispute_match_result(match_id):
    match = TournamentMatch.query.get_or_404(match_id)
    tournament = match.tournament

    if not can_access_match(current_user.id, match):
        flash('Only the assigned players or an admin can view this match.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if current_user.id not in {match.player_one_user_id, match.player_two_user_id}:
        flash('Only an assigned player can dispute a match result.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if match.status != 'pending_confirmation':
        flash('Only a submitted result can be disputed.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if current_user.id == match.submitted_by_user_id:
        flash('The other player must raise a dispute.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    reason = request.form.get('reason', '').strip()
    if len(reason) > MAX_MATCH_PROOF_LENGTH:
        flash('Dispute reason is too long.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if reason:
        dispute = TournamentMatchDispute(match_id=match.id, user_id=current_user.id, reason=reason)
        db.session.add(dispute)
        match.status = 'disputed'
        db.session.commit()
        create_and_emit_notification(
            match.submitted_by_user_id,
            f'{current_user.username} disputed your match result.',
            'match', f'/tournament/{tournament.id}',
        )
        flash('Dispute submitted for review.', 'success')
    else:
        flash('Please describe the issue before submitting a dispute.', 'error')
    return redirect(url_for('tournament_details', tournament_id=tournament.id))


@app.route('/admin/matches/<int:match_id>/review-dispute', methods=['POST'])
@login_required
def review_match_dispute(match_id):
    match = TournamentMatch.query.get_or_404(match_id)
    if not is_admin_user():
        abort(403)

    dispute = TournamentMatchDispute.query.filter_by(
        match_id=match.id, status='pending',
    ).order_by(TournamentMatchDispute.created_at.desc()).first()
    decision = (request.form.get('decision') or '').strip().lower()
    if match.status != 'disputed' or not dispute or decision not in {'confirm', 'reopen'}:
        flash('This dispute is not available for review.', 'error')
        return redirect(url_for('tournament_details', tournament_id=match.tournament_id))

    dispute.status = 'resolved'
    if decision == 'confirm':
        match.status = 'confirmed'
        flash('Disputed result confirmed after review.', 'success')
    else:
        match.status = 'ongoing'
        match.winner_user_id = None
        match.submitted_by_user_id = None
        match.proof_note = None
        match.player_one_profile_id = None
        match.player_two_profile_id = None
        flash('Match reopened for a new result submission.', 'success')
    db.session.commit()
    if decision == 'confirm':
        for player_id in {match.player_one_user_id, match.player_two_user_id}:
            award_achievements_for_user(player_id)
        advance_tournament_bracket(match)
    return redirect(url_for('tournament_details', tournament_id=match.tournament_id))


# PAYMENT ROUTES
# -------------------------
def is_valid_paystack_reference(reference):
    return bool(reference and PAYSTACK_REFERENCE_PATTERN.fullmatch(reference))


def paystack_transaction_matches(transaction, expected_amount, expected_reference,
                                 expected_user_id=None, expected_tournament_id=None,
                                 expected_type=None):
    if not isinstance(transaction, dict):
        return False
    if transaction.get('reference') != expected_reference:
        return False
    try:
        if int(transaction.get('amount')) != int(expected_amount) * 100:
            return False
    except (TypeError, ValueError):
        return False
    if str(transaction.get('currency', '')).upper() != PAYSTACK_CURRENCY:
        return False

    metadata = transaction.get('metadata') or {}
    if expected_user_id is not None and str(metadata.get('user_id')) != str(expected_user_id):
        return False
    if expected_tournament_id is not None and str(metadata.get('tournament_id')) != str(expected_tournament_id):
        return False
    if expected_type is not None and metadata.get('type') != expected_type:
        return False
    return True


def verify_paystack_reference(reference):
    if not REQUESTS_AVAILABLE or not PAYSTACK_SECRET_KEY:
        return None
    try:
        response = requests.get(
            f'{PAYSTACK_BASE_URL}/transaction/verify/{urllib.parse.quote(reference, safe="")}',
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}'},
            timeout=15,
        )
        response_data = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return None
    if not response_data.get('status') or not isinstance(response_data.get('data'), dict):
        return None
    return response_data['data']


def apply_tournament_payment(user_tournament, transaction):
    tournament = Tournament.query.filter_by(id=user_tournament.tournament_id).with_for_update().populate_existing().one()
    if not paystack_transaction_matches(
        transaction,
        tournament.entry_fee,
        user_tournament.transaction_ref,
        expected_user_id=user_tournament.user_id,
        expected_tournament_id=tournament.id,
    ):
        return False, 'Payment details could not be verified.'

    if user_tournament.payment_status == 'paid':
        return True, 'already_processed'
    if user_tournament.payment_status != 'pending':
        return False, 'This payment is no longer pending.'

    updated = UserTournament.query.filter_by(
        id=user_tournament.id,
        payment_status='pending',
    ).update({'payment_status': 'paid'}, synchronize_session=False)
    if not updated:
        db.session.rollback()
        return True, 'already_processed'
    db.session.commit()
    award_achievements_for_user(user_tournament.user_id)
    create_and_emit_notification(
        user_tournament.user_id, f'Your entry for {tournament.name} is confirmed.',
        'tournament', f'/tournament/{tournament.id}',
    )
    return True, 'processed'


def apply_wallet_deposit(wallet_transaction, transaction):
    if not paystack_transaction_matches(
        transaction,
        wallet_transaction.amount,
        wallet_transaction.transaction_ref,
        expected_user_id=wallet_transaction.user_id,
        expected_type='wallet_deposit',
    ):
        return False, 'Payment details could not be verified.'

    if wallet_transaction.status == 'completed':
        return True, 'already_processed'
    if wallet_transaction.status != 'pending':
        return False, 'This deposit is no longer pending.'

    updated = WalletTransaction.query.filter_by(
        id=wallet_transaction.id,
        status='pending',
    ).update({'status': 'completed'}, synchronize_session=False)
    if not updated:
        db.session.rollback()
        return True, 'already_processed'
    User.query.filter_by(id=wallet_transaction.user_id).update(
        {User.wallet_balance: db.func.coalesce(User.wallet_balance, 0) + wallet_transaction.amount},
        synchronize_session=False,
    )
    db.session.commit()
    create_and_emit_notification(
        wallet_transaction.user_id,
        f'Your wallet deposit of â‚¦{wallet_transaction.amount:,} is complete.',
        'wallet', '/wallet',
    )
    return True, 'processed'


@app.route("/pay/<int:tournament_id>")
@login_required
def pay_for_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    if tournament.status != 'open':
        flash('Registration is closed for this tournament.', 'warning')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    # Check if already joined
    existing_join = UserTournament.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()

    if existing_join and existing_join.payment_status != 'pending':
        flash("You've already joined this tournament!", "warning")
        return redirect(url_for("dashboard"))

    if active_participant_count(tournament) >= tournament.max_participants:
        flash("Tournament is full!", "error")
        return redirect(url_for("home"))

    return render_template("payment.html", tournament=tournament, paystack_public_key=PAYSTACK_PUBLIC_KEY)


def validated_checkout_url(payload, status_code):
    if status_code != 200 or not isinstance(payload, dict) or payload.get('status') is not True:
        app.logger.warning('Checkout response rejected provider_status=%s reason=provider_rejection', status_code)
        return None
    data = payload.get('data')
    value = data.get('authorization_url') if isinstance(data, dict) else None
    if not isinstance(value, str):
        app.logger.warning('Checkout response rejected provider_status=%s reason=missing_checkout_url', status_code)
        return None
    parsed = urlparse(value)
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
        return value
    app.logger.warning('Checkout response rejected provider_status=%s reason=invalid_checkout_url', status_code)
    return None


def checkout_failure_message(status_code):
    if status_code in (401, 403):
        return 'Payments are temporarily unavailable. Please contact GameArena support.'
    return 'Checkout could not be opened. Please try again shortly.'


@app.route("/initialize-payment/<int:tournament_id>", methods=['POST'])
@login_required
def initialize_payment(tournament_id):
    if not REQUESTS_AVAILABLE:
        return jsonify({'status': 'error', 'message': 'Payment system not available'})
        
    try:
        tournament = Tournament.query.filter_by(id=tournament_id).with_for_update().populate_existing().first_or_404()
        if tournament.status != 'open':
            return jsonify({'status': 'error', 'message': 'Registration is closed.'}), 409
        if tournament.entry_fee <= 0:
            return jsonify({'status': 'error', 'message': 'This tournament has free entry.'}), 400
        
        # This line is to:
        # Check if the user already has a registration for this tournament.
        # Allow a retry if the prior join is still pending payment so the user can
        # continue the payment flow without getting stuck.
        existing_join = UserTournament.query.filter_by(
            user_id=current_user.id,
            tournament_id=tournament_id
        ).first()

        if existing_join and existing_join.payment_status in {'paid', 'free'}:
            return jsonify({'status': 'error', 'message': 'Already joined this tournament'})

        if existing_join and existing_join.payment_status == 'pending':
            # Reuse the pending registration and create a fresh Paystack reference.
            import uuid
            transaction_ref = str(uuid.uuid4())
            existing_join.transaction_ref = transaction_ref
            existing_join.amount_paid = tournament.entry_fee

            headers = {
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json'
            }

            data = {
                'email': current_user.email,
                'amount': tournament.entry_fee * 100,
                'currency': PAYSTACK_CURRENCY,
                'reference': transaction_ref,
                'callback_url': url_for('verify_payment', _external=True),
                'metadata': {
                    'tournament_id': tournament_id,
                    'user_id': current_user.id
                }
            }

            response = requests.post(f'{PAYSTACK_BASE_URL}/transaction/initialize', json=data, headers=headers, timeout=(5, 15))
            response_data = response.json()
            checkout_url = validated_checkout_url(response_data, response.status_code)

            if checkout_url:
                db.session.commit()
                return jsonify({
                    'status': 'success',
                    'authorization_url': checkout_url,
                    'reference': transaction_ref
                })
            db.session.rollback()
            return jsonify({'status': 'error', 'message': checkout_failure_message(response.status_code)}), 502

        if active_participant_count(tournament) >= tournament.max_participants:
            return jsonify({'status': 'error', 'message': 'Tournament is full'})

        # Generate unique transaction reference
        import uuid
        transaction_ref = str(uuid.uuid4())

        # Paystack expects amount in kobo (multiply by 100)
        amount_kobo = tournament.entry_fee * 100

        # Initialize payment with Paystack
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json'
        }

        data = {
            'email': current_user.email,
            'amount': amount_kobo,
            'currency': PAYSTACK_CURRENCY,
            'reference': transaction_ref,
            'callback_url': url_for('verify_payment', _external=True),
            'metadata': {
                'tournament_id': tournament_id,
                'user_id': current_user.id
            }
        }

        response = requests.post(f'{PAYSTACK_BASE_URL}/transaction/initialize', json=data, headers=headers, timeout=(5, 15))
        response_data = response.json()
        checkout_url = validated_checkout_url(response_data, response.status_code)

        if checkout_url:
            # Create pending UserTournament record
            join = UserTournament(
                user_id=current_user.id,
                tournament_id=tournament_id,
                payment_status='pending',
                transaction_ref=transaction_ref,
                amount_paid=tournament.entry_fee
            )
            db.session.add(join)
            db.session.commit()

            return jsonify({
                'status': 'success',
                'authorization_url': checkout_url,
                'reference': transaction_ref
            })
        else:
            db.session.rollback()
            return jsonify({'status': 'error', 'message': checkout_failure_message(response.status_code)}), 502

    except requests.Timeout:
        db.session.rollback()
        return jsonify({'status':'error','message':'Checkout timed out. Please check your entry and try again.'}), 504
    except ValueError:
        db.session.rollback()
        return jsonify({'status':'error','message':'The payment provider returned an invalid response. Please try again shortly.'}), 502
    except Exception:
        db.session.rollback()
        app.logger.exception('Payment initialization failed')
        return jsonify({'status': 'error', 'message': 'Unable to initialize payment.'}), 502


@app.route("/verify-payment")
@login_required
def verify_payment():
    if not REQUESTS_AVAILABLE:
        flash("Payment verification not available", "error")
        return redirect(url_for("home"))

    reference = (request.args.get('reference') or '').strip()
    if not is_valid_paystack_reference(reference):
        flash("Invalid payment reference", "error")
        return redirect(url_for("home"))

    if not reference:
        flash("Payment reference missing", "error")
        return redirect(url_for("home"))

    # Find the UserTournament record
    user_tournament = UserTournament.query.filter_by(
        transaction_ref=reference,
        user_id=current_user.id
    ).first()

    if not user_tournament:
        flash("Payment record not found", "error")
        return redirect(url_for("home"))

    # Verify payment with Paystack.
    transaction = verify_paystack_reference(reference)
    if not transaction or transaction.get('status') != 'success':
        flash("Payment verification failed. Please try again.", "error")
        return redirect(url_for("pay_for_tournament", tournament_id=user_tournament.tournament_id))

    try:
        verified, result = apply_tournament_payment(user_tournament, transaction)
    except Exception:
        db.session.rollback()
        app.logger.exception('Tournament payment application failed')
        verified, result = False, 'Payment could not be applied.'
    if not verified:
        flash(result, "error")
        return redirect(url_for("pay_for_tournament", tournament_id=user_tournament.tournament_id))

    flash(f"Payment successful! You've joined {user_tournament.tournament.game}", "success")
    return redirect(url_for("dashboard"))


@app.route('/paystack/webhook', methods=['POST'])
@csrf.exempt
def paystack_webhook():
    if not PAYSTACK_SECRET_KEY:
        return jsonify({'status': 'error', 'message': 'Webhook unavailable'}), 503

    payload = request.get_data()
    signature = request.headers.get('x-paystack-signature', '')
    expected_signature = hmac.new(PAYSTACK_SECRET_KEY.encode(), payload, hashlib.sha512).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected_signature):
        return jsonify({'status': 'error', 'message': 'Invalid webhook signature'}), 401

    try:
        event = request.get_json(silent=True) or {}
        transaction = event.get('data') or {}
        reference = transaction.get('reference')
        event_name = event.get('event')
        if not is_valid_paystack_reference(reference):
            return jsonify({'status': 'ignored'}), 200

        if event_name in {'transfer.success', 'transfer.failed', 'transfer.reversed'}:
            withdrawal = WalletTransaction.query.filter_by(
                type='withdrawal', transaction_ref=reference,
            ).with_for_update().first()
            if not withdrawal:
                return jsonify({'status': 'ignored'}), 200
            transfer_code = str(transaction.get('transfer_code') or '').strip() or None
            try:
                if int(transaction.get('amount')) != withdrawal.amount * 100:
                    return jsonify({'status': 'error', 'message': 'Transfer amount mismatch'}), 400
            except (TypeError, ValueError):
                return jsonify({'status': 'error', 'message': 'Invalid transfer amount'}), 400
            if str(transaction.get('currency', '')).upper() != PAYSTACK_CURRENCY:
                return jsonify({'status': 'error', 'message': 'Transfer currency mismatch'}), 400
            if event_name == 'transfer.success':
                complete_withdrawal(withdrawal.id, transfer_code)
            else:
                release_failed_withdrawal(
                    withdrawal.id,
                    'Paystack reported that the transfer was not completed.',
                    transfer_code,
                )
            return jsonify({'status': 'ok'}), 200

        if event_name != 'charge.success':
            return jsonify({'status': 'ignored'}), 200

        tournament_join = UserTournament.query.filter_by(transaction_ref=reference).first()
        wallet_deposit = WalletTransaction.query.filter_by(
            transaction_ref=reference,
            type='deposit',
        ).first()
        if tournament_join and wallet_deposit:
            app.logger.error('Paystack reference is assigned to multiple payment records: %s', reference)
            return jsonify({'status': 'error', 'message': 'Payment record conflict'}), 409
        if tournament_join:
            verified, result = apply_tournament_payment(tournament_join, transaction)
        elif wallet_deposit:
            verified, result = apply_wallet_deposit(wallet_deposit, transaction)
        else:
            return jsonify({'status': 'ignored'}), 200
        if not verified:
            return jsonify({'status': 'error', 'message': result}), 400
        return jsonify({'status': 'ok'}), 200
    except (TypeError, ValueError):
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Invalid webhook payload'}), 400
    except Exception:
        db.session.rollback()
        app.logger.exception('Paystack webhook processing failed')
        return jsonify({'status': 'error', 'message': 'Webhook processing failed'}), 500


# -------------------------
# WALLET DEPOSIT / WITHDRAWAL ROUTES (JSON API for frontend) AI did initialized this for me 
# -------------------------
@app.route("/wallet/initialize-deposit", methods=['POST'])
@login_required
def wallet_initialize_deposit():
    if not REQUESTS_AVAILABLE:
        return jsonify({'status': 'error', 'message': 'Payment system not available'})

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'status': 'error', 'message': 'Invalid request data'})

    amount = str(data.get('amount', '')).strip()
    if not amount or not amount.isdigit() or int(amount) <= 0:
        return jsonify({'status': 'error', 'message': 'Please enter a valid deposit amount.'})

    amount = int(amount)

    import uuid
    transaction_ref = str(uuid.uuid4())

    # Initialize Paystack transaction
    headers = {
        'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json'
    }

    payload = {
        'email': current_user.email,
        'amount': amount * 100,  # Paystack uses kobo
        'currency': PAYSTACK_CURRENCY,
        'reference': transaction_ref,
        'callback_url': url_for('wallet_verify_deposit', _external=True),
        'metadata': {
            'user_id': current_user.id,
            'type': 'wallet_deposit'
        }
    }

    try:
        response = requests.post(f'{PAYSTACK_BASE_URL}/transaction/initialize', json=payload, headers=headers, timeout=(5, 15))
        response_data = response.json()

        if response_data['status']:
            # Create pending wallet transaction
            wt = WalletTransaction(
                user_id=current_user.id,
                type='deposit',
                amount=amount,
                status='pending',
                transaction_ref=transaction_ref
            )
            db.session.add(wt)
            db.session.commit()

            return jsonify({
                'status': 'success',
                'authorization_url': response_data['data']['authorization_url'],
                'reference': transaction_ref
            })
        else:
            return jsonify({'status': 'error', 'message': 'Payment initialization failed.'})
    except Exception:
        db.session.rollback()
        app.logger.exception('Wallet deposit initialization failed')
        return jsonify({'status': 'error', 'message': 'Unable to initialize deposit.'}), 502


@app.route("/wallet/verify-deposit")
@login_required
def wallet_verify_deposit():
    if not REQUESTS_AVAILABLE:
        flash("Payment verification not available", "error")
        return redirect(url_for("wallet"))

    reference = (request.args.get('reference') or '').strip()
    if not is_valid_paystack_reference(reference):
        flash("Payment reference missing", "error")
        return redirect(url_for("wallet"))

    # Find the WalletTransaction record
    wt = WalletTransaction.query.filter_by(
        transaction_ref=reference,
        user_id=current_user.id,
        type='deposit'
    ).first()

    if not wt:
        flash("Deposit record not found", "error")
        return redirect(url_for("wallet"))

    if wt.status == 'completed':
        flash("This deposit has already been processed.", "success")
        return redirect(url_for("wallet"))

    transaction = verify_paystack_reference(reference)
    if not transaction or transaction.get('status') != 'success':
        flash('Deposit verification failed. Please try again.', 'error')
        return redirect(url_for('wallet'))

    try:
        verified, result = apply_wallet_deposit(wt, transaction)
    except Exception:
        db.session.rollback()
        app.logger.exception('Wallet deposit application failed')
        verified, result = False, 'Deposit could not be applied.'
    if not verified:
        flash(result, 'error')
        return redirect(url_for('wallet'))

    flash(f'â‚¦{wt.amount:,} deposited successfully!', 'success')
    return redirect(url_for('wallet'))


WITHDRAWAL_FINAL_STATUSES = {'completed', 'failed'}
_supported_banks_cache = {'expires': 0, 'banks': []}


@app.route('/wallet/banks')
@login_required
def wallet_banks():
    if not REQUESTS_AVAILABLE or not PAYSTACK_SECRET_KEY:
        return jsonify({'message': 'The bank list is temporarily unavailable. Please try again later.'}), 503
    if _supported_banks_cache['expires'] > time.monotonic():
        return jsonify({'banks': _supported_banks_cache['banks']})
    try:
        banks = paystack_transfer_request('GET', '/bank', params={'currency': PAYSTACK_CURRENCY, 'country': 'nigeria', 'perPage': 100})
        supported = [{'name': bank['name'], 'code': bank['code']} for bank in banks if bank.get('name') and bank.get('code') and bank.get('active', True)]
        _supported_banks_cache.update(expires=time.monotonic()+300, banks=supported)
        return jsonify({'banks': supported})
    except Exception:
        app.logger.exception('Unable to retrieve supported withdrawal banks')
        return jsonify({'message': 'Unable to load supported banks. Please try again.'}), 502


def withdrawal_response(withdrawal):
    return {
        'status': 'success' if withdrawal.status != 'failed' else 'error',
        'withdrawal_status': withdrawal.status,
        'reference': withdrawal.transaction_ref,
        'message': (
            'Withdrawal completed successfully.' if withdrawal.status == 'completed'
            else 'Withdrawal could not be completed; reserved funds have been returned.' if withdrawal.status == 'failed'
            else 'Withdrawal request received and is being processed.'
        ),
    }


def paystack_transfer_request(method, path, **kwargs):
    if not REQUESTS_AVAILABLE or not PAYSTACK_SECRET_KEY:
        raise RuntimeError('Paystack transfers are not configured.')
    headers = {'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'}
    response = requests.request(method, f'{PAYSTACK_BASE_URL}{path}', headers=headers, timeout=15, **kwargs)
    payload = response.json()
    if not response.ok or not payload.get('status'):
        raise ValueError((payload.get('message') if isinstance(payload, dict) else None) or 'Paystack request failed.')
    return payload.get('data') or {}


def release_failed_withdrawal(withdrawal_id, reason, provider_transfer_code=None):
    """Release a reserved balance exactly once after a conclusive payout failure."""
    withdrawal = WalletTransaction.query.filter_by(id=withdrawal_id, type='withdrawal').with_for_update().first()
    if not withdrawal or withdrawal.status in WITHDRAWAL_FINAL_STATUSES:
        db.session.commit()
        return withdrawal
    owner = User.query.filter_by(id=withdrawal.user_id).with_for_update().first()
    if not owner:
        raise RuntimeError('Withdrawal wallet owner was not found.')
    owner.wallet_balance = (owner.wallet_balance or 0) + withdrawal.amount
    withdrawal.status = 'failed'
    withdrawal.failure_reason = (reason or 'Transfer failed.')[:500]
    withdrawal.failed_at = datetime.utcnow()
    if provider_transfer_code:
        withdrawal.provider_transfer_code = provider_transfer_code[:100]
    db.session.commit()
    create_and_emit_notification(
        withdrawal.user_id,
        f'Your withdrawal of â‚¦{withdrawal.amount:,} failed and the funds were returned to your wallet.',
        'wallet', '/wallet',
    )
    return withdrawal


def complete_withdrawal(withdrawal_id, provider_transfer_code=None):
    withdrawal = WalletTransaction.query.filter_by(id=withdrawal_id, type='withdrawal').with_for_update().first()
    if not withdrawal or withdrawal.status in WITHDRAWAL_FINAL_STATUSES:
        db.session.commit()
        return withdrawal
    withdrawal.status = 'completed'
    withdrawal.completed_at = datetime.utcnow()
    withdrawal.failure_reason = None
    if provider_transfer_code:
        withdrawal.provider_transfer_code = provider_transfer_code[:100]
    db.session.commit()
    create_and_emit_notification(
        withdrawal.user_id,
        f'Your withdrawal of â‚¦{withdrawal.amount:,} is complete.',
        'wallet', '/wallet',
    )
    return withdrawal


def start_withdrawal_transfer(withdrawal_id):
    """Submit one reserved withdrawal using its stable Paystack reference.

    Network uncertainty deliberately leaves the reservation in ``processing``.
    Retrying the same Paystack reference is safe; creating a new debit is not.
    """
    withdrawal = WalletTransaction.query.filter_by(id=withdrawal_id, type='withdrawal').with_for_update().first()
    if not withdrawal or withdrawal.status in WITHDRAWAL_FINAL_STATUSES:
        db.session.commit()
        return withdrawal
    withdrawal.status = 'processing'
    withdrawal.processing_at = withdrawal.processing_at or datetime.utcnow()
    db.session.commit()

    try:
        account = paystack_transfer_request(
            'GET', '/bank/resolve', params={'account_number': withdrawal.account_number, 'bank_code': withdrawal.bank_code},
        )
        resolved_name = str(account.get('account_name') or '').strip()
        if not resolved_name:
            raise ValueError('Paystack could not verify the account details.')
        withdrawal = WalletTransaction.query.filter_by(id=withdrawal_id).with_for_update().first()
        withdrawal.account_name = resolved_name[:200]
        db.session.commit()

        recipient = paystack_transfer_request('POST', '/transferrecipient', json={
            'type': 'nuban', 'name': resolved_name, 'account_number': withdrawal.account_number,
            'bank_code': withdrawal.bank_code, 'currency': PAYSTACK_CURRENCY,
        })
        recipient_code = str(recipient.get('recipient_code') or '').strip()
        if not recipient_code:
            raise ValueError('Paystack did not return a transfer recipient.')
        withdrawal = WalletTransaction.query.filter_by(id=withdrawal_id).with_for_update().first()
        withdrawal.provider_recipient_code = recipient_code[:100]
        db.session.commit()

        transfer = paystack_transfer_request('POST', '/transfer', json={
            'source': 'balance', 'amount': withdrawal.amount * 100, 'reference': withdrawal.transaction_ref,
            'recipient': recipient_code, 'reason': f'GameArena wallet withdrawal {withdrawal.transaction_ref}',
            'currency': PAYSTACK_CURRENCY,
        })
        transfer_code = str(transfer.get('transfer_code') or '').strip() or None
        provider_status = str(transfer.get('status') or '').lower()
        if provider_status == 'success':
            return complete_withdrawal(withdrawal_id, transfer_code)
        if provider_status in {'failed', 'reversed', 'abandoned', 'rejected'}:
            return release_failed_withdrawal(withdrawal_id, 'Paystack declined the transfer.', transfer_code)
        withdrawal = WalletTransaction.query.filter_by(id=withdrawal_id).with_for_update().first()
        if withdrawal and withdrawal.status not in WITHDRAWAL_FINAL_STATUSES:
            withdrawal.provider_transfer_code = transfer_code[:100] if transfer_code else withdrawal.provider_transfer_code
            db.session.commit()
        return withdrawal
    except ValueError as error:
        return release_failed_withdrawal(withdrawal_id, str(error))
    except Exception:
        db.session.rollback()
        app.logger.exception('Withdrawal transfer submission is inconclusive reference=%s', withdrawal_id)
        # Do not refund on an unknown network outcome: Paystack may have queued
        # the transfer. The signed webhook is authoritative for final state.
        return WalletTransaction.query.get(withdrawal_id)


def request_wallet_withdrawal(req_data):
    if not REQUESTS_AVAILABLE or not PAYSTACK_SECRET_KEY:
        return jsonify({'status': 'error', 'message': 'Withdrawals are temporarily unavailable.'}), 503
    amount_raw = str(req_data.get('amount', '')).strip()
    bank_name = str(req_data.get('bank_name', '')).strip()
    bank_code = str(req_data.get('bank_code', '')).strip()
    account_number = str(req_data.get('account_number', '')).strip()
    idempotency_key = str(req_data.get('idempotency_key', '')).strip()
    if not amount_raw.isdigit() or int(amount_raw) <= 0:
        return jsonify({'status': 'error', 'message': 'Please enter a valid withdrawal amount.'}), 400
    if not bank_name or not re.fullmatch(r'[A-Za-z0-9_-]{2,20}', bank_code) or not re.fullmatch(r'\d{10}', account_number):
        return jsonify({'status': 'error', 'message': 'Please provide valid bank details.'}), 400
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', idempotency_key):
        return jsonify({'status': 'error', 'message': 'Invalid withdrawal request identifier.'}), 400

    existing = WalletTransaction.query.filter_by(user_id=current_user.id, type='withdrawal', idempotency_key=idempotency_key).with_for_update().first()
    if existing:
        db.session.commit()
        return jsonify(withdrawal_response(existing))
    amount = int(amount_raw)
    owner = User.query.filter_by(id=current_user.id).with_for_update().populate_existing().first()
    if not owner:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Wallet owner was not found.'}), 404
    if amount > (owner.wallet_balance or 0):
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Insufficient wallet balance.'}), 400
    import uuid
    withdrawal = WalletTransaction(
        user_id=owner.id, type='withdrawal', amount=amount, status='pending',
        transaction_ref=f'wd_{uuid.uuid4().hex}', idempotency_key=idempotency_key,
        bank_name=bank_name[:120], bank_code=bank_code, account_number=account_number,
    )
    owner.wallet_balance = (owner.wallet_balance or 0) - amount
    db.session.add(withdrawal)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        existing = WalletTransaction.query.filter_by(user_id=current_user.id, type='withdrawal', idempotency_key=idempotency_key).first()
        if existing:
            return jsonify(withdrawal_response(existing))
        app.logger.exception('Withdrawal reservation failed')
        return jsonify({'status': 'error', 'message': 'Unable to create withdrawal request.'}), 500
    start_withdrawal_transfer(withdrawal.id)
    return jsonify(withdrawal_response(WalletTransaction.query.get(withdrawal.id))), 202


@app.route("/wallet/withdraw", methods=['POST'])
@login_required
def wallet_withdraw():
    req_data = request.get_json(silent=True)
    if not req_data:
        return jsonify({'status': 'error', 'message': 'Invalid request data'})

    return request_wallet_withdrawal(req_data)

    amount = str(req_data.get('amount', '')).strip()
    bank_name = str(req_data.get('bank_name', '')).strip()
    account_number = str(req_data.get('account_number', '')).strip()
    account_name = str(req_data.get('account_name', '')).strip()

    if not amount or not amount.isdigit() or int(amount) <= 0:
        return jsonify({'status': 'error', 'message': 'Please enter a valid withdrawal amount.'})

    if not bank_name or not account_number or not account_name:
        return jsonify({'status': 'error', 'message': 'Please fill in all bank details.'})

    if len(bank_name) > 120 or len(account_number) > 40 or len(account_name) > 200:
        return jsonify({'status': 'error', 'message': 'One or more bank details are too long.'}), 400
    if not account_number.isdigit() or len(account_number) != 10:
        return jsonify({'status': 'error', 'message': 'Account number must contain exactly 10 digits.'}), 400

    amount = int(amount)
    # Lock and refresh the wallet owner before checking funds. This serialises
    # concurrent debit requests instead of trusting a potentially stale
    # ``current_user`` identity-map value.
    wallet_owner = User.query.filter_by(id=current_user.id).with_for_update().populate_existing().first()
    if wallet_owner is None:
        return jsonify({'status': 'error', 'message': 'Wallet owner was not found.'}), 404
    balance = wallet_owner.wallet_balance or 0

    if amount > balance:
        return jsonify({'status': 'error', 'message': f'Insufficient balance. You have â‚¦{balance:,} in your wallet.'})

    import uuid
    transaction_ref = str(uuid.uuid4())

    #Remember Jegede This code is to Deduct from wallet and create withdrawal record
    wallet_owner.wallet_balance = balance - amount

    wt = WalletTransaction(
        user_id=wallet_owner.id,
        type='withdrawal',
        amount=amount,
        status='completed',
        transaction_ref=transaction_ref,
        bank_name=bank_name,
        account_number=account_number,
        account_name=account_name
    )
    db.session.add(wt)
    db.session.commit()

    return jsonify({'status': 'success', 'message': f'â‚¦{amount:,} withdrawn successfully to {account_name} ({bank_name} - {account_number}).'})

# LOGOUT
@app.route("/logout", methods=['GET', 'POST'])
@login_required
def logout():
    digest = session.pop('push_endpoint_hash', None)
    if digest and current_user.is_authenticated:
        PushSubscription.query.filter_by(user_id=current_user.id, endpoint_hash=digest).delete()
        db.session.commit()
    logout_user()
    return redirect(url_for("home"))


# CREATE TEST DATA & ADMIN USER
with app.app_context():
    # Production schema ownership belongs to db_migrate.py. This escape hatch
    # exists only for that migration bootstrap and explicit local development.
    if os.environ.get('GAMEARENA_SCHEMA_BOOTSTRAP') == '1':
        db.create_all()

# Ensure explicitly configured admin credentials exist. This updates or creates
# only the admin identified by environment variables; it never changes an
# existing legitimate admin merely because configuration is absent.
    expected_admin_email = (os.environ.get('ADMIN_EMAIL', '') or '').strip().lower()
    expected_admin_password = os.environ.get('ADMIN_PASSWORD', '') or ''

    if expected_admin_email and expected_admin_password:
        admin_user = User.query.filter(db.func.lower(User.email) == expected_admin_email).first()
        if admin_user:
            admin_user.is_admin = True
            admin_user.email_verified = True
            admin_user.suspended = False
            admin_user.password = generate_password_hash(expected_admin_password)
            if not admin_user.username:
                admin_user.username = "admin"
        else:
            # Generate a username that is guaranteed unique.
            base_username = "admin"
            candidate = base_username
            counter = 1
            existing_usernames = {u.username.lower() for u in User.query.all()}
            while candidate.lower() in existing_usernames:
                candidate = f"{base_username}{counter}"
                counter += 1
            admin_user = User(
                username=candidate,
                email=expected_admin_email,
                password=generate_password_hash(expected_admin_password),
                is_admin=True,
                email_verified=True,
                suspended=False,
            )
            db.session.add(admin_user)

        db.session.commit()



@socketio.on('connect')
def on_connect():
    # Do not retain unauthenticated or suspended connections. Every existing
    # mutation event already authorizes its own resource access as well.
    if not current_user.is_authenticated or current_user.suspended:
        return False
    join_room(f'user:{current_user.id}')


@socketio.on('join_user')
def on_join_user(data):
    """Client data: {"user_id": 123}"""
    if not current_user.is_authenticated:
        return
    if not socket_event_allowed('join_user'):
        return socket_rate_limit_error()
    try:
        user_id = int((data or {}).get('user_id'))
    except (TypeError, ValueError):
        return
    if user_id == current_user.id:
        join_room(f"user:{current_user.id}")


@socketio.on('join_tournament')
def on_join_tournament(data):
    """Client data: {"tournament_id": 1}"""
    if not current_user.is_authenticated:
        return
    if not socket_event_allowed('join_tournament'):
        return socket_rate_limit_error()
    try:
        tournament_id = int((data or {}).get('tournament_id'))
    except (TypeError, ValueError):
        return
    tournament = db.session.get(Tournament, tournament_id)
    if tournament and can_access_tournament_chat(current_user.id, tournament_id):
        join_room(f"tournament:{tournament_id}")


@socketio.on('join_global_chat')
def on_join_global_chat(data):
    if current_user.is_authenticated:
        if not socket_event_allowed('join_global_chat'):
            return socket_rate_limit_error()
        join_room('global_chat')


def chat_client_id(data):
    value = (data or {}).get('client_message_id')
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9-]{36}', value):
        raise ValueError('Invalid message identifier.')
    return value


@socketio.on('send_global_chat_message')
def on_send_global_chat_message(data):
    data = data if isinstance(data, dict) else {}
    if not current_user.is_authenticated or current_user.suspended:
        return {'status':'error', 'message':'Log in to send messages.'}
    message = data.get('message', '')
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_CHAT_MESSAGE_LENGTH:
        return {'status':'error', 'message':'Enter a message of up to 1,000 characters.'}
    try:
        client_id = chat_client_id(data)
    except ValueError as error:
        return {'status':'error', 'message':str(error)}
    if client_id:
        existing = GlobalChatMessage.query.filter_by(client_message_id=client_id).first()
        if existing:
            return {'status':'success', 'id':existing.id} if existing.user_id == current_user.id else {'status':'error', 'message':'Invalid message identifier.'}
    if not socket_event_allowed('send_global_chat_message'):
        return socket_rate_limit_error()
    reply_id = data.get('reply_to_id')
    parent = db.session.get(GlobalChatMessage, reply_id) if isinstance(reply_id, int) and reply_id > 0 else None
    if reply_id is not None and (not parent or parent.deleted_at):
        return {'status':'error', 'message':'That message is unavailable.'}
    sender_id, username, created = current_user.id, current_user.username, datetime.utcnow()
    new = GlobalChatMessage(user_id=sender_id, message=message.strip(), reply_to_id=parent.id if parent else None, client_message_id=client_id, created_at=created)
    quoted = quoted_message(parent)
    db.session.add(new)
    try:
        db.session.flush(); message_id = new.id; db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = GlobalChatMessage.query.filter_by(client_message_id=client_id, user_id=sender_id).first() if client_id else None
        if not existing:
            raise
        return {'status':'success', 'id':existing.id}
    payload = {'id':message_id, 'user_id':sender_id, 'username':username, 'message':message.strip(), 'created_at':created.isoformat()+'Z', 'reply':quoted, 'client_message_id':client_id}
    socketio.emit('new_global_chat_message', payload, room='global_chat')
    socketio.emit('new_global_chat_message', payload, room=f'user:{sender_id}')
    return {'status':'success', 'id':message_id}


@socketio.on('join_direct_message')
def on_join_direct_message(data):
    if not current_user.is_authenticated or current_user.suspended:
        return
    if not socket_event_allowed('join_direct_message'):
        return socket_rate_limit_error()
    try:
        other_user_id = int((data or {}).get('user_id'))
    except (TypeError, ValueError):
        return
    recipient = db.session.get(User, other_user_id)
    if not can_direct_message(current_user, recipient):
        return emit('socket_error', {'message': 'This conversation is unavailable.'})
    join_room(direct_message_room_key(current_user.id, recipient.id))
    DirectMessage.query.filter_by(
        sender_id=recipient.id, recipient_id=current_user.id, read_at=None,
    ).update({'read_at': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()


@socketio.on('send_direct_message')
def on_send_direct_message(data):
    data = data if isinstance(data, dict) else {}
    if not current_user.is_authenticated or current_user.suspended:
        return {'status':'error', 'message':'Log in to send messages.'}
    try:
        recipient_id = int((data or {}).get('user_id'))
    except (TypeError, ValueError):
        return {'status':'error', 'message':'Choose a valid conversation.'}
    recipient = db.session.get(User, recipient_id, options=[joinedload(User.settings)])
    raw = data.get('message', '')
    message = raw.strip() if isinstance(raw, str) else ''
    if not message or len(message) > MAX_CHAT_MESSAGE_LENGTH:
        return {'status':'error', 'message':'Message must be 1,000 characters or fewer.'}
    if not can_direct_message(current_user, recipient):
        return {'status':'error', 'message':'This conversation is unavailable. Check blocking and direct-message settings.'}

    try:
        client_id = chat_client_id(data)
    except ValueError as error:
        return {'status':'error', 'message':str(error)}
    if client_id:
        existing = DirectMessage.query.filter_by(client_message_id=client_id).first()
        if existing:
            return {'status':'success', 'id':existing.id} if existing.sender_id == current_user.id and existing.recipient_id == recipient.id else {'status':'error', 'message':'Invalid message identifier.'}
    if not socket_event_allowed('send_direct_message'):
        return socket_rate_limit_error()
    reply_id = data.get('reply_to_id')
    parent = db.session.get(DirectMessage, reply_id) if isinstance(reply_id, int) and reply_id > 0 else None
    if reply_id is not None and (not parent or parent.deleted_at or {parent.sender_id, parent.recipient_id} != {current_user.id, recipient.id}):
        return {'status':'error', 'message':'Choose a message from this conversation to reply to.'}

    sender_id, sender_name = current_user.id, current_user.username
    recipient_id = recipient.id
    reply = quoted_message(parent)
    created_at = datetime.utcnow()
    stored_message = DirectMessage(sender_id=sender_id, recipient_id=recipient_id,
        message=message, client_message_id=client_id, reply_to_id=parent.id if parent else None, created_at=created_at)
    db.session.add(stored_message)
    try:
        db.session.flush()
        message_id = stored_message.id
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = DirectMessage.query.filter_by(client_message_id=client_id, sender_id=sender_id, recipient_id=recipient_id).first() if client_id else None
        if not existing:
            raise
        return {'status':'success', 'id':existing.id}
    payload = {
        'id': message_id, 'sender_id':sender_id, 'recipient_id':recipient_id,
        'username':sender_name, 'message':message, 'client_message_id':client_id, 'created_at':created_at.isoformat() + 'Z', 'reply':reply,
    }
    socketio.emit(
        'new_direct_message', payload,
        room=f'user:{recipient_id}',
    )
    socketio.emit('new_direct_message', payload, room=f'user:{sender_id}')
    socketio.start_background_task(chat_notification, recipient_id, sender_id, sender_name)
    return {'status': 'success', 'id': message_id}


def chat_notification(recipient_id, sender_id, sender_name):
    with app.app_context():
        try:
            create_and_emit_notification(recipient_id, f'{sender_name} sent you a message.', 'chat', f'/messages/{sender_id}')
            count = DirectMessage.query.filter_by(recipient_id=recipient_id, read_at=None).count()
            socketio.emit('unread_count', {'unread':count}, room=f'user:{recipient_id}')
        except Exception as error:
            db.session.rollback()
            app.logger.warning('Chat notification failed (%s); message saved.', type(error).__name__)


@app.route('/chat/send', methods=['POST'])
@login_required
def send_chat_http():
    data = request.get_json(silent=True) or {}
    result = on_send_direct_message(data) if data.get('user_id') else on_send_global_chat_message(data)
    return jsonify(result)


@app.route('/chat/message/<kind>/<int:message_id>/delete', methods=['POST'])
@login_required
def delete_chat_message(kind, message_id):
    model = {'direct':DirectMessage, 'global':GlobalChatMessage}.get(kind)
    if not model or current_user.suspended:
        abort(403)
    row = db.session.get(model, message_id)
    if not row:
        abort(404)
    owner_id = row.sender_id if kind == 'direct' else row.user_id
    if owner_id != current_user.id:
        abort(403)
    recipient_id = row.recipient_id if kind == 'direct' else None
    row.message = 'This message was deleted.'
    row.deleted_at = row.deleted_at or datetime.utcnow()
    db.session.commit()
    payload = {'id':message_id, 'kind':kind}
    if kind == 'direct':
        for uid in (owner_id, recipient_id):
            socketio.emit('chat_message_deleted', payload, room=f'user:{uid}')
    else:
        socketio.emit('chat_message_deleted', payload, room='global_chat')
    return jsonify({'status':'success'})


@socketio.on('chat_typing')
def chat_typing(data):
    if not current_user.is_authenticated or current_user.suspended or not isinstance(data, dict):
        return
    if not socket_event_allowed('chat_typing'):
        return
    partner_id = data.get('user_id')
    payload = {'user_id':current_user.id, 'username':current_user.username, 'typing':data.get('typing') is True}
    if partner_id:
        partner = db.session.get(User, partner_id)
        if can_direct_message(current_user, partner):
            socketio.emit('chat_typing', payload, room=f'user:{partner.id}')
    else:
        socketio.emit('chat_typing', payload, room='global_chat', skip_sid=request.sid)


@socketio.on('mark_notification_read')
def on_mark_notification_read(data):
    """Return the unread count or mark notifications as read for the authenticated user."""
    if not current_user.is_authenticated:
        return
    if not socket_event_allowed('mark_notification_read'):
        return socket_rate_limit_error()

    data = data or {}
    only_count = data.get('only_count', False)
    if isinstance(only_count, str):
        only_count = only_count.lower() in {'1', 'true', 'yes', 'y'}

    unread_count = mark_notifications_read_for_user(current_user.id, only_count=bool(only_count))

    socketio.emit(
        'unread_count',
        {'unread': unread_count},
        room=f'user:{int(current_user.id)}'
    )



@socketio.on('leave_tournament')
def on_leave_tournament(data):
    if not current_user.is_authenticated:
        return
    try:
        tournament_id = int((data or {}).get('tournament_id'))
    except (TypeError, ValueError):
        return
    leave_room(f"tournament:{tournament_id}")


@socketio.on('send_chat_message')
def on_send_chat_message(data):
    data = data or {}
    if not current_user.is_authenticated:
        return
    if not socket_event_allowed('send_chat_message'):
        return socket_rate_limit_error()
    try:
        tournament_id = int(data.get('tournament_id'))
    except (TypeError, ValueError):
        return
    message = (data.get('message') or '').strip()
    if not message or len(message) > MAX_CHAT_MESSAGE_LENGTH:
        return
    if not can_access_tournament_chat(current_user.id, tournament_id):
        return

    msg = TournamentChatMessage(
        tournament_id=tournament_id,
        user_id=current_user.id,
        message=message,
    )
    db.session.add(msg)
    db.session.commit()

    emit('new_chat_message', {
        'tournament_id': tournament_id,
        'user_id': current_user.id,
        'username': current_user.username,
        'message': message,
        'created_at': msg.created_at.isoformat() if msg.created_at else None,
    }, room=f"tournament:{tournament_id}")


@socketio.on('disconnect')
def on_disconnect():
    """Discard per-connection throttling state when the socket closes."""
    sid = getattr(request, 'sid', None)
    if sid:
        for key in [key for key in socket_event_windows if key[0] == sid]:
            socket_event_windows.pop(key, None)


if __name__ == '__main__':
    #setting host to 0.0.0.0 makes the app accessible from any IP address
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=port)
