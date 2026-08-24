import os
import http.client
import json
import hmac
import hashlib
import secrets
import re
import urllib.parse
from flask import Flask, render_template, redirect, url_for, request, flash, abort, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO, join_room, leave_room, emit
from sqlalchemy.pool import NullPool

from wtforms import StringField, PasswordField, SubmitField, SelectField, IntegerField, validators
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote_plus, urlparse
import random
import smtplib
import ssl
try:
    import requests
    REQUESTS_AVAILABLE = True 
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Warning: requests module not available, payment features will not work")
from dotenv import load_dotenv

base_dir = os.path.abspath(os.path.dirname(__file__))

# Load environment variables from the project .env file first
load_dotenv(os.path.join(base_dir, '.env'), override=True)

app = Flask(__name__)

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

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.socket.io https://js.paystack.co",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://images.unsplash.com https://source.unsplash.com",
    "connect-src 'self' https://api.paystack.co https://accounts.google.com https://oauth2.googleapis.com wss:",
    "frame-src https://checkout.paystack.com",
    "font-src 'self' data:",
])
SENSITIVE_CACHE_PATHS = (
    '/dashboard',
    '/wallet',
    '/profile',
    '/notifications',
    '/admin',
    '/pay/',
    '/verify-payment',
    '/wallet/verify-deposit',
)
database_url = (os.environ.get('DATABASE_URL') or '').strip()
if is_production:
    if not database_url:
        raise RuntimeError('DATABASE_URL must be configured in production.')
    if not database_url.lower().startswith(('postgresql://', 'postgres://', 'postgresql+')):
        raise RuntimeError('DATABASE_URL must point to PostgreSQL in production.')
RATE_LIMITS = {
    'login_ip': (10, 15 * 60),
    'login_account': (5, 15 * 60),
    'register_ip': (8, 60 * 60),
    'password_reset_ip': (5, 60 * 60),
    'verification_ip': (10, 15 * 60),
    'verification_resend': (3, 15 * 60),
    'payment_user': (10, 10 * 60),
    'payment_verification': (20, 10 * 60),
}
RATE_LIMIT_CLEANUP_INTERVAL = 100
RATE_LIMIT_RETENTION_SECONDS = max(window for _, window in RATE_LIMITS.values()) + 60 * 60
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

    if current_user.is_authenticated and request.path.startswith(SENSITIVE_CACHE_PATHS):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# Socket.IO (WebSockets)
# Note: for production you may want a message queue (Redis) to support multi-worker.
socketio_cors_origins = [
    origin.strip()
    for origin in (os.environ.get('SOCKETIO_CORS_ALLOWED_ORIGINS') or '').split(',')
    if origin.strip()
]
socketio = SocketIO(app, cors_allowed_origins=socketio_cors_origins or None)

instance_dir = os.path.join(base_dir, 'instance')
os.makedirs(instance_dir, exist_ok=True)
database_path = os.path.join(instance_dir, 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or f'sqlite:///{database_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Use NullPool so SQLAlchemy does not rely on a queue-based connection pool.
# The gunicorn/eventlet worker monkey-patches Python's threading, which breaks
# QueuePool's condition lock at runtime ("cannot wait on un-acquired lock"),
# causing a 500 on every DB query. NullPool opens a fresh connection per check
# out and avoids the threading lock entirely.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}

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


MAX_CHAT_MESSAGE_LENGTH = 1000
MAX_MATCH_PROOF_LENGTH = 2000


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
    return sum(
        1 for membership in tournament.participants
        if membership.payment_status in {'paid', 'free'}
    )

db = SQLAlchemy(app)
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


def create_and_emit_notification(user_id: int, message: str):
    """Create a Notification row and emit it to the user's Socket.IO room."""
    if not user_id or not message:
        return
    notif = Notification(user_id=int(user_id), message=message)
    db.session.add(notif)
    db.session.commit()

    # Emit to the specific user room.
    # Dashboard client listens for event name: 'notification'
    socketio.emit(
        'notification',
        {'message': message, 'created_at': notif.created_at.isoformat() if notif.created_at else None},
        room=f'user:{int(user_id)}'
    )


def generate_code(length=8):
    return ''.join(random.choice('0123456789') for _ in range(length))



login_manager.login_view = "login"
csrf = CSRFProtect(app)

# Tournament images keyed by normalized game name
GAME_IMAGE_MAP = {
    'call of duty mobile': 'images/call_of_duty.jpg',
    'call of duty': 'images/call_of_duty.jpg',
    'free fire': 'images/free fire.jpg',
    'pubg mobile': 'images/PUBG.jpg',
    'pubg': 'images/PUBG.jpg',
    'efootball': 'images/efootball_3.jpg',
    'fifa': 'images/efootball_3.jpg',
}

GAME_IMAGE_CAROUSEL_MAP = {
    'call of duty mobile': ['images/call_of_duty.jpg', 'images/call of duty 2.webp', 'images/call of duty 3.jpg'],
    'call of duty': ['images/call_of_duty.jpg', 'images/call of duty 2.webp', 'images/call of duty 3.jpg'],
    'free fire': ['images/free fire.jpg', 'images/free fire 2.webp', 'images/free fire 3.jpg'],
    'pubg mobile': ['images/PUBG.jpg', 'images/PUBG 2.jpg'],
    'pubg': ['images/PUBG.jpg', 'images/PUBG 2.jpg'],
    'efootball': ['images/efootball-messi.jpg', 'images/efootball_2.jpg', 'images/efootball_3.jpg'],
    'fifa': ['images/efootball-messi.jpg', 'images/efootball_2.jpg', 'images/efootball_3.jpg'],
}

@app.context_processor
def utility_processor():
    def tournament_image(game_name):
        if not game_name:
            return 'https://source.unsplash.com/1200x800/?gaming'
        key = game_name.strip().lower()
        if key in GAME_IMAGE_MAP:
            value = GAME_IMAGE_MAP[key]
            return value if value.startswith('http') else url_for('static', filename=value)
        return f'https://source.unsplash.com/1200x800/?{quote_plus(game_name)}'

    def game_image_carousel(game_name):
        if not game_name:
            return []
        key = game_name.strip().lower()
        if key in GAME_IMAGE_CAROUSEL_MAP:
            return [url_for('static', filename=image) for image in GAME_IMAGE_CAROUSEL_MAP[key]]
        fallback = tournament_image(game_name)
        return [fallback]

    def carousel_images():
        image_dir = os.path.join(app.root_path, 'static', 'images')
        allowed_ext = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
        images = []
        if os.path.isdir(image_dir):
            for filename in sorted(os.listdir(image_dir)):
                if os.path.splitext(filename)[1].lower() in allowed_ext:
                    images.append(url_for('static', filename=f'images/{filename}'))
        return images

    return dict(tournament_image=tournament_image, game_image_carousel=game_image_carousel, carousel_images=carousel_images())


def generate_code(length=6):
    return ''.join(random.choice('0123456789') for _ in range(length))


def send_email(subject, recipient, body):
    """Send email synchronously."""
    email_from = os.environ.get('EMAIL_FROM') or os.environ.get('SMTP_USERNAME') or 'noreply@gamearena.com'

    # --- Resend (preferred) ---
    resend_api_key = os.environ.get('RESEND_API_KEY')
    if resend_api_key:
        try:
            payload = {
                "from": email_from,
                "to": recipient,
                "subject": subject,
                "text": body,
            }
            # Use the standard library http.client instead of requests/urllib3.
            # On Render the app runs under a gunicorn "gevent" worker, which
            # monkey-patches Python's ssl/socket layer. urllib3's HTTPS handling
            # recurses infinitely under that patch ("maximum recursion depth
            # exceeded"). http.client talks to the TLS socket directly and is
# not affected by the recursion, so verification emails actually get
            # sent through Resend here.
            body_bytes = json.dumps(payload).encode('utf-8')
            conn = http.client.HTTPSConnection('api.resend.com', timeout=15)
            resp = None
            resp_body = b''
            try:
                conn.request(
                    'POST',
                    '/emails',
                    body=body_bytes,
                    headers={
                        'Authorization': f'Bearer {resend_api_key}',
                        'Content-Type': 'application/json',
                        'Content-Length': str(len(body_bytes)),
                    },
                )
                resp = conn.getresponse()
                resp_body = resp.read()
            except Exception as inner_e:
                # Even if reading the response raises (e.g. under the gevent
                # worker), capture whatever status/body we already have AND the
                # underlying error, so the actual reason is never hidden. The
                # API key is never written to the log.
                status = getattr(resp, 'status', None) or 'N/A'
                reason = getattr(resp, 'reason', None) or 'N/A'
                detail = resp_body.decode('utf-8', 'replace').strip() if resp_body else ''
                app.logger.warning(
                    f"Resend email failed for {recipient}: {status} {reason} (error: {type(inner_e).__name__})"
                )
            finally:
                conn.close()

            if resp is not None and resp.status < 300:
                app.logger.info(f"Resend email sent to {recipient}")
                return True
            if resp is not None:
                app.logger.warning(f"Resend email failed for {recipient}: {resp.status} {resp.reason}")
        except Exception as e:
            app.logger.warning(f"Resend email failed for {recipient}: {type(e).__name__}")

    smtp_server = os.environ.get('SMTP_SERVER')
    smtp_port = os.environ.get('SMTP_PORT')
    smtp_username = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    smtp_use_tls = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')


    if smtp_server and smtp_port and smtp_username and smtp_password:
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = email_from
        msg['To'] = recipient
        msg.set_content(body)

        try:
            if smtp_use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(smtp_server, int(smtp_port), timeout=15) as server:
                    server.starttls(context=context)
                    server.login(smtp_username, smtp_password)
                    server.send_message(msg)
            else:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(smtp_server, int(smtp_port), context=context, timeout=15) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(msg)
            app.logger.info(f"Email sent to {recipient}")
            return True
        except Exception as e:
            app.logger.warning(f"SMTP email failed for {recipient}: {type(e).__name__}")

    app.logger.warning(f"Email delivery unavailable for {recipient}")
    return False


def send_verification_code(user):
    """Generate verification code and send email"""
    # Create an in-app notification for the user
    # (the dashboard socket will display it)
    create_and_emit_notification(user.id, 'Email verification code generated.')
    user.verification_code = generate_code(6)
    user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
    db.session.commit()
    
    subject = 'Verify your GameArena email'
    body = (
        f'Hi {user.username},\n\n'
        f'Use the code below to verify your email address on GameArena:\n\n'
        f'{user.verification_code}\n\n'
        'This code expires in 15 minutes.\n\n'
        'If you did not request this, please ignore this message.\n\n'
        'Thanks,\nGameArena Team'
    )
    send_email(subject, user.email, body)


def send_password_reset_code(user):
    """Generate reset code and send email"""
    create_and_emit_notification(user.id, 'Password reset code generated.')
    user.reset_code = generate_code(6)
    user.reset_expires_at = datetime.utcnow() + timedelta(minutes=15)
    db.session.commit()
    
    subject = 'Reset your GameArena password'
    body = (
        f'Hi {user.username},\n\n'
        f'Use the code below to reset your GameArena password:\n\n'
        f'{user.reset_code}\n\n'
        'This code expires in 15 minutes.\n\n'
        'If you did not request this, please ignore this message.\n\n'
        'Thanks,\nGameArena Team'
    )
    send_email(subject, user.email, body)


# Form Classes
class RegistrationForm(FlaskForm):
    username = StringField('Username', [
        validators.DataRequired(),
        validators.Length(min=3, max=150),
        validators.Regexp(r'^[a-zA-Z0-9_]+$', message="Username can only contain letters, numbers, and underscores")
    ])
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email(),
        validators.Length(max=150)
    ])
    password = PasswordField('Password', [
        validators.DataRequired(),
        validators.Length(min=6, message="Password must be at least 6 characters long")
    ])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    password = PasswordField('Password', [validators.DataRequired()])
    submit = SubmitField('Login')

class EmailVerificationForm(FlaskForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    code = StringField('Verification Code', [
        validators.DataRequired(),
        validators.Length(min=4, max=10)
    ])
    submit = SubmitField('Verify Email')

class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    submit = SubmitField('Send Reset Code')

class ResetPasswordForm(FlaskForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    code = StringField('Reset Code', [
        validators.DataRequired(),
        validators.Length(min=4, max=10)
    ])
    new_password = PasswordField('New Password', [
        validators.DataRequired(),
        validators.Length(min=6, message="Password must be at least 6 characters long")
    ])
    submit = SubmitField('Reset Password')

class TournamentForm(FlaskForm):
    game = StringField('Game Name', [
        validators.DataRequired(),
        validators.Length(min=3, max=100)
    ])
    entry_fee = StringField('Entry Fee (₦)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Entry fee must be a number")
    ])
    prize_pool = StringField('Prize Pool (₦)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Prize pool must be a number")
    ])
    match_time = StringField('Match Time (YYYY-MM-DD HH:MM)', [
        validators.Optional(),
        validators.Length(max=50)
    ])
    max_participants = StringField('Max Participants', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Max participants must be a number")
    ])
    submit = SubmitField('Create Tournament')


class TournamentSetupForm(FlaskForm):
    entry_fee = StringField('Entry Fee (₦)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Entry fee must be a number")
    ])
    prize_pool = StringField('Prize Pool (₦)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Prize pool must be a number")
    ])
    max_participants = StringField('Max Participants', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Max participants must be a number")
    ])
    room_id = StringField('Room ID', [
        validators.Optional(),
        validators.Length(max=50)
    ])
    room_password = StringField('Room Password', [
        validators.Optional(),
        validators.Length(max=100)
    ])
    match_time = StringField('Match Time (YYYY-MM-DD HH:MM)', [
        validators.Optional(),
        validators.Length(max=50)
    ])
    status = SelectField('Status', choices=[
        ('open', 'Open'),
        ('ongoing', 'Ongoing'),
        ('finished', 'Finished'),
        ('cancelled', 'Cancelled')
    ], default='open')
    first_place = StringField('1st Place', [
        validators.Optional(),
        validators.Length(max=150)
    ])
    second_place = StringField('2nd Place', [
        validators.Optional(),
        validators.Length(max=150)
    ])
    third_place = StringField('3rd Place', [
        validators.Optional(),
        validators.Length(max=150)
    ])
    submit = SubmitField('Save Tournament Setup')


class LeaderboardEntryForm(FlaskForm):
    user_id = SelectField('Player', coerce=int, validators=[validators.DataRequired()])
    wins = IntegerField('Wins', [validators.DataRequired(), validators.NumberRange(min=0)])
    kills = IntegerField('Kills', [validators.DataRequired(), validators.NumberRange(min=0)])
    points = IntegerField('Points', [validators.DataRequired(), validators.NumberRange(min=0)])
    rank = IntegerField('Rank', [validators.DataRequired(), validators.NumberRange(min=1)])
    submit = SubmitField('Save Entry')


# -------------------------
# USER MODEL
# -------------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # Admin flag
    suspended = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(10))
    verification_expires_at = db.Column(db.DateTime)
    reset_code = db.Column(db.String(10))
    reset_expires_at = db.Column(db.DateTime)

    # Profile (Phase 1)
    avatar_url = db.Column(db.String(500), nullable=True)
    bio = db.Column(db.Text, nullable=True)

    # Wallet balance for deposits/withdrawals
    wallet_balance = db.Column(db.Integer, default=0)

    # Payout / prize receiving details (needed for Paystack transfers)
    payout_bank = db.Column(db.String(120), nullable=True)
    payout_account_number = db.Column(db.String(40), nullable=True)
    payout_account_name = db.Column(db.String(200), nullable=True)

    tournaments_joined = db.relationship('UserTournament', back_populates='user')
    tournament_stats = db.relationship('TournamentStat', back_populates='user', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)



# -------------------------
# TOURNAMENT MODEL
# -------------------------
class Tournament(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    game = db.Column(db.String(100), nullable=False)
    entry_fee = db.Column(db.Integer, default=100)
    prize = db.Column(db.Integer, default=5000)
    max_participants = db.Column(db.Integer, default=50)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=db.func.now())
    status = db.Column(db.String(20), default='open')
    room_id = db.Column(db.String(50))
    room_password = db.Column(db.String(100))
    match_time = db.Column(db.DateTime)
    first_place = db.Column(db.String(150))
    second_place = db.Column(db.String(150))
    third_place = db.Column(db.String(150))
    participants = db.relationship('UserTournament', back_populates='tournament')
    leaderboard = db.relationship('TournamentStat', back_populates='tournament', cascade='all, delete-orphan', order_by='TournamentStat.rank')

    @property
    def prize_pool(self):
        return self.prize


# -------------------------
# LEADERBOARD MODEL
# -------------------------
class TournamentStat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    wins = db.Column(db.Integer, default=0)
    kills = db.Column(db.Integer, default=0)
    points = db.Column(db.Integer, default=0)
    rank = db.Column(db.Integer, default=0)

    # Prize distribution tracking
    prize_code = db.Column(db.String(20), nullable=True)
    prize_code_sent_at = db.Column(db.DateTime, nullable=True)
    prize_status = db.Column(db.String(20), default='not_started')  # not_started, pending, paid, failed
    paystack_transfer_ref = db.Column(db.String(100), nullable=True)
    prize_paid_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', back_populates='tournament_stats')
    tournament = db.relationship('Tournament', back_populates='leaderboard')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'tournament_id', name='unique_user_tournament_stat'),
    )





# -------------------------
# USER-TOURNAMENT MODEL
# -------------------------
class UserTournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=db.func.now())
    payment_status = db.Column(db.String(20), default='pending')  # pending, paid, failed, refunded
    transaction_ref = db.Column(db.String(100), unique=True)
    amount_paid = db.Column(db.Integer, default=0)

    user = db.relationship('User', back_populates='tournaments_joined')
    tournament = db.relationship('Tournament', back_populates='participants')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'tournament_id', name='unique_user_tournament_registration'),
    )


# -------------------------
# WALLET TRANSACTIONS MODEL
# -------------------------
class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'deposit' or 'withdrawal'
    amount = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), default='completed')  # completed, pending, failed
    transaction_ref = db.Column(db.String(100), unique=True, nullable=True)
    bank_name = db.Column(db.String(120), nullable=True)
    account_number = db.Column(db.String(40), nullable=True)
    account_name = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User', backref=db.backref('wallet_transactions', lazy=True))


class RateLimitBucket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bucket_key = db.Column(db.String(255), unique=True, nullable=False)
    window_started = db.Column(db.DateTime, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)


def client_rate_limit_key():
    return request.remote_addr or 'unknown-client'


def rate_limit_response(retry_after):
    response = jsonify({'status': 'error', 'message': 'Too many requests. Please try again later.'})
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
    elif path == '/verify-email':
        if request.method == 'GET' and request.args.get('resend') == '1':
            email = (request.args.get('email') or '').strip().lower()
            checks = [
                ('verification_resend_ip:' + client_key, 'verification_resend'),
                ('verification_resend_email:' + (email or 'unknown'), 'verification_resend'),
            ]
        elif request.method == 'POST':
            checks = [('verification_ip:' + client_key, 'verification_ip')]
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
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User', backref=db.backref('notifications', lazy=True))


# -------------------------
# TOURNAMENT CHAT (Phase 1)
# -------------------------
class TournamentChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    tournament = db.relationship('Tournament', backref=db.backref('chat_messages', lazy=True))


class GlobalChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')


class TournamentMatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    player_one_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    player_two_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(30), default='scheduled')
    room_code = db.Column(db.String(100), nullable=True)
    room_password = db.Column(db.String(100), nullable=True)
    player_one_profile_id = db.Column(db.String(150), nullable=True)
    player_two_profile_id = db.Column(db.String(150), nullable=True)
    winner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    proof_note = db.Column(db.Text, nullable=True)
    submitted_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    tournament = db.relationship('Tournament', backref=db.backref('matches', lazy=True))
    player_one = db.relationship('User', foreign_keys=[player_one_user_id])
    player_two = db.relationship('User', foreign_keys=[player_two_user_id])
    winner = db.relationship('User', foreign_keys=[winner_user_id])
    submitted_by = db.relationship('User', foreign_keys=[submitted_by_user_id])


class TournamentMatchChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('tournament_match.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    match = db.relationship('TournamentMatch', backref=db.backref('chat_messages', lazy=True))


class TournamentMatchDispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('tournament_match.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    match = db.relationship('TournamentMatch', backref=db.backref('disputes', lazy=True))


def create_tournament_matches(tournament):
    if not tournament:
        return []

    existing_matches = TournamentMatch.query.filter_by(tournament_id=tournament.id).all()
    if existing_matches:
        return existing_matches

    participants = [entry.user_id for entry in tournament.participants if entry.payment_status == 'paid']
    if len(participants) < 2:
        return []

    random.shuffle(participants)
    matches = []
    for index in range(0, len(participants), 2):
        pair = participants[index:index + 2]
        if len(pair) < 2:
            break
        match = TournamentMatch(
            tournament_id=tournament.id,
            player_one_user_id=pair[0],
            player_two_user_id=pair[1],
            status='scheduled'
        )
        db.session.add(match)
        matches.append(match)

    tournament.status = 'live'
    db.session.commit()
    return matches


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
        return User.query.get(int(user_id))
    except Exception as exc:
        app.logger.warning(f"Unable to load user {user_id}: {exc}")
        return None


# -------------------------
# HOME
# -------------------------
@app.route("/")
def home():
    tournaments = Tournament.query.all()
    return render_template("index.html", tournaments=tournaments)


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
# PUBLIC LEADERBOARD
# -------------------------
@app.route("/leaderboard")
def leaderboard():
    tournaments = Tournament.query.order_by(Tournament.match_time.desc()).all()
    return render_template("leaderboard.html", tournaments=tournaments)


# -------------------------
# TOURNAMENTS PAGE (dedicated listing)
# -------------------------
@app.route("/tournaments")
def tournaments_page():
    tournaments = Tournament.query.all()
    return render_template("tournaments.html", tournaments=tournaments)


# -------------------------
# WALLET PAGE
# -------------------------
@app.route("/wallet")
@login_required
def wallet():
    all_joins = UserTournament.query.filter_by(user_id=current_user.id).order_by(UserTournament.joined_at.desc()).all()
    total_spent = sum((ut.amount_paid or 0) for ut in all_joins if ut.payment_status == 'paid')
    pending_transactions = [ut for ut in all_joins if ut.payment_status == 'pending']
    wallet_transactions = WalletTransaction.query.filter_by(user_id=current_user.id).order_by(WalletTransaction.created_at.desc()).all()
    wallet_balance = current_user.wallet_balance or 0
    return render_template("wallet.html", transactions=all_joins, total_spent=total_spent, pending_transactions=pending_transactions, wallet_transactions=wallet_transactions, wallet_balance=wallet_balance, paystack_public_key=PAYSTACK_PUBLIC_KEY)


@app.route('/chat')
@login_required
def chat():
    all_messages = GlobalChatMessage.query.order_by(GlobalChatMessage.created_at.asc()).limit(50).all()

    # Defensively drop any messages whose user relationship is missing (orphaned
    # rows, e.g. a chat message referencing a user that no longer exists). This
    # prevents an AttributeError -> HTTP 500 when rendering the template.
    messages = [m for m in all_messages if m.user is not None]

    # Most recent 10 distinct chatting users.
    # NOTE: SQLite allows SELECT DISTINCT x ORDER BY y, but Postgres does NOT
    # (ORDER BY column must appear in the DISTINCT select list). Use a subquery
    # that works on both engines: get the max created_at per user, order by it,
# then fetch the most recent 10 user ids and load those users.
    from sqlalchemy import func
    # Select user_id first, then the aggregated last_seen (row[0] = user_id).
    distinct_user_ids = [
        row[0] for row in db.session.query(
            GlobalChatMessage.user_id,
            func.max(GlobalChatMessage.created_at).label('last_seen'),
        )
        .group_by(GlobalChatMessage.user_id)
        .order_by(func.max(GlobalChatMessage.created_at).desc())
        .limit(10).all()
    ]
    # Preserve order of most-recent first
    chat_partners = []
    if distinct_user_ids:
        partners = User.query.filter(User.id.in_(distinct_user_ids)).all()
        partner_map = {u.id: u for u in partners}
        chat_partners = [partner_map[uid] for uid in distinct_user_ids if uid in partner_map]

    return render_template('chat.html', messages=messages, chat_partners=chat_partners)


# -------------------------
# PROFILE PAGE
# -------------------------
@app.route("/profile")
@login_required
def profile():
    joined_count = UserTournament.query.filter_by(user_id=current_user.id).count()
    stats = sorted(
        current_user.tournament_stats,
        key=lambda stat: (stat.rank or 999, -(stat.points or 0))
    )
    return render_template("profile.html", joined_count=joined_count, stats=stats)


# -------------------------
# NEW: TOURNAMENT DETAILS PAGE 🔥
# -------------------------
@app.route("/tournament/<int:tournament_id>")
def tournament_details(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    joined_paid = False
    can_view_match_rooms = is_admin_user()

    if current_user.is_authenticated:
        join = UserTournament.query.filter_by(
            user_id=current_user.id,
            tournament_id=tournament_id
        ).first()
        if join and join.payment_status == 'paid':
            joined_paid = True
            can_view_match_rooms = True

    matches = []
    if tournament.id:
        matches = TournamentMatch.query.filter_by(tournament_id=tournament.id).order_by(TournamentMatch.created_at.asc()).all()

    return render_template(
        "tournament_details.html",
        tournament=tournament,
        joined_paid=joined_paid,
        matches=matches,
        can_view_match_rooms=can_view_match_rooms,
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
            send_verification_code(new_user)
            flash("Account created successfully! Check your email for the verification code.", "success")
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
                send_verification_code(user)
                flash("Email not verified. A new code was sent to your inbox.", "error")
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
    if request.method == 'POST':
        email = form.email.data.lower().strip()

    if request.method == 'GET' and request.args.get('resend') == '1' and email:
        user = User.query.filter_by(email=email.lower().strip()).first()
        if user:
            send_verification_code(user)
            flash('Verification code resent. Check your email.', 'success')
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

        if not user.verification_code or user.verification_code != form.code.data:
            flash('Invalid verification code.', 'error')
            return render_template('verify_email.html', form=form)

        if not user.verification_expires_at or user.verification_expires_at < datetime.utcnow():
            flash('Verification code has expired. A new code was sent.', 'error')
            send_verification_code(user)
            return redirect(url_for('verify_email', email=user.email))

        user.email_verified = True
        user.verification_code = None
        user.verification_expires_at = None
        db.session.commit()

        flash('Email verified successfully! You can now log in.', 'success')
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
        flash('If that email exists, a reset code has been sent.', 'success')
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
    all_joins = UserTournament.query.filter_by(user_id=current_user.id).order_by(UserTournament.joined_at.desc()).all()

    # Deduplicate: show only one entry per tournament (latest join)
    seen_tournaments = set()
    joined_tournaments = []
    for ut in all_joins:
        if ut.tournament_id not in seen_tournaments:
            joined_tournaments.append(ut)
            seen_tournaments.add(ut.tournament_id)

    upcoming_matches = [
        ut for ut in joined_tournaments
        if ut.tournament.match_time and ut.tournament.match_time >= datetime.utcnow()
    ]

    tournament_stats = sorted(
        current_user.tournament_stats,
        key=lambda stat: (stat.rank or 999, -(stat.points or 0))
    )

    recent_notifications = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )

    total_paid = sum((ut.amount_paid or 0) for ut in joined_tournaments if ut.payment_status == 'paid')

    return render_template(
        "dashboard.html",
        joined_tournaments=joined_tournaments,
        upcoming_matches=upcoming_matches,
        tournament_stats=tournament_stats,
        recent_notifications=recent_notifications,
        total_paid=total_paid,
    )


@app.route("/notifications")
@login_required
def notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    unread_count = sum(1 for notification in notifications if notification.read_at is None)
    return render_template("notifications.html", notifications=notifications, unread_count=unread_count)


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
@app.route("/join-tournament/<int:tournament_id>")
@login_required
def join_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)

    existing_join = UserTournament.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()

    if existing_join:
        flash(f"You've already joined {tournament.game}!", "warning")
        return redirect(url_for("dashboard"))

    if active_participant_count(tournament) >= tournament.max_participants:
        flash(f"{tournament.game} is FULL!", "error")
        return redirect(url_for("home"))

    # If tournament has entry fee, redirect to payment
    if tournament.entry_fee > 0:
        return redirect(url_for('pay_for_tournament', tournament_id=tournament_id))

    # Free tournament - join directly
    join = UserTournament(
        user_id=current_user.id,
        tournament_id=tournament_id,
        payment_status='free',
        amount_paid=0
    )
    db.session.add(join)
    db.session.commit()

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
        flash('Not enough paid participants to create matches yet.', 'error')
    else:
        flash(f'{len(matches)} matches created for this tournament.', 'success')
    return redirect(url_for('tournament_details', tournament_id=tournament_id))


def _get_paid_participants_not_in_assigned_match(tournament_id: int, exclude_user_id: int | None = None):
    """Return paid user_ids in this tournament that are not already assigned to an active match.

    Active match statuses:
    - scheduled
    - ongoing
    - pending_confirmation
    - confirmed
    """
    active_statuses = {'scheduled', 'ongoing', 'pending_confirmation', 'confirmed'}

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

    # Only paid participants can request matchmaking
    join = UserTournament.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id,
    ).first()

    if not join or join.payment_status != 'paid':
        flash('Only paid participants can matchmake.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament_id))

    #This here is to prevent making multiple assignments for the same user
    active_statuses = {'scheduled', 'ongoing', 'pending_confirmation', 'confirmed'}
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
        flash('Only the assigned players or an admin can submit match results.', 'error')
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
    flash('Match result submitted and waiting for confirmation.', 'success')
    return redirect(url_for('tournament_details', tournament_id=tournament.id))



@app.route('/match/<int:match_id>/confirm-result', methods=['POST'])
@login_required
def confirm_match_result(match_id):
    match = TournamentMatch.query.get_or_404(match_id)
    tournament = match.tournament

    if not can_access_match(current_user.id, match):
        flash('Only the assigned players or an admin can confirm match results.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    if is_admin_user() or current_user.id in {match.player_one_user_id, match.player_two_user_id}:
        match.status = 'confirmed'
        db.session.commit()
        flash('Match result confirmed.', 'success')
    else:
        flash('You are not part of this match.', 'error')
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
        flash('Only the assigned players or an admin can dispute a match result.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))

    reason = request.form.get('reason', '').strip()
    if len(reason) > MAX_MATCH_PROOF_LENGTH:
        flash('Dispute reason is too long.', 'error')
        return redirect(url_for('tournament_details', tournament_id=tournament.id))
    if reason:
        dispute = TournamentMatchDispute(match_id=match.id, user_id=current_user.id, reason=reason)
        db.session.add(dispute)
        db.session.commit()
        flash('Dispute submitted for review.', 'success')
    else:
        flash('Please describe the issue before submitting a dispute.', 'error')
    return redirect(url_for('tournament_details', tournament_id=tournament.id))


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
    tournament = user_tournament.tournament
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
    return True, 'processed'


@app.route("/pay/<int:tournament_id>")
@login_required
def pay_for_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)

    # Check if already joined
    existing_join = UserTournament.query.filter_by(
        user_id=current_user.id,
        tournament_id=tournament_id
    ).first()

    if existing_join:
        flash("You've already joined this tournament!", "warning")
        return redirect(url_for("dashboard"))

    if active_participant_count(tournament) >= tournament.max_participants:
        flash("Tournament is full!", "error")
        return redirect(url_for("home"))

    return render_template("payment.html", tournament=tournament, paystack_public_key=PAYSTACK_PUBLIC_KEY)


@app.route("/initialize-payment/<int:tournament_id>", methods=['POST'])
@login_required
def initialize_payment(tournament_id):
    if not REQUESTS_AVAILABLE:
        return jsonify({'status': 'error', 'message': 'Payment system not available'})
        
    try:
        tournament = Tournament.query.get_or_404(tournament_id)
        
        # This line is to:
        # Check if the user already has a registration for this tournament.
        # Allow a retry if the prior join is still pending payment so the user can
        # continue the payment flow without getting stuck.
        existing_join = UserTournament.query.filter_by(
            user_id=current_user.id,
            tournament_id=tournament_id
        ).first()

        if existing_join and existing_join.payment_status == 'paid':
            return jsonify({'status': 'error', 'message': 'Already joined this tournament'})

        if existing_join and existing_join.payment_status == 'pending':
            # Reuse the pending registration and create a fresh Paystack reference.
            import uuid
            transaction_ref = str(uuid.uuid4())
            existing_join.transaction_ref = transaction_ref
            existing_join.amount_paid = tournament.entry_fee
            db.session.commit()

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

            response = requests.post(f'{PAYSTACK_BASE_URL}/transaction/initialize', json=data, headers=headers)
            response_data = response.json()

            if response_data['status']:
                return jsonify({
                    'status': 'success',
                    'authorization_url': response_data['data']['authorization_url'],
                    'reference': transaction_ref
                })
            return jsonify({'status': 'error', 'message': 'Payment initialization failed'})

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

        response = requests.post(f'{PAYSTACK_BASE_URL}/transaction/initialize', json=data, headers=headers)
        response_data = response.json()

        if response_data['status']:
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
                'authorization_url': response_data['data']['authorization_url'],
                'reference': transaction_ref
            })
        else:
            return jsonify({'status': 'error', 'message': 'Payment initialization failed'})

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
        if event.get('event') != 'charge.success' or not is_valid_paystack_reference(reference):
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
        response = requests.post(f'{PAYSTACK_BASE_URL}/transaction/initialize', json=payload, headers=headers)
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

    flash(f'₦{wt.amount:,} deposited successfully!', 'success')
    return redirect(url_for('wallet'))


@app.route("/wallet/withdraw", methods=['POST'])
@login_required
def wallet_withdraw():
    req_data = request.get_json(silent=True)
    if not req_data:
        return jsonify({'status': 'error', 'message': 'Invalid request data'})

    amount = str(req_data.get('amount', '')).strip()
    bank_name = str(req_data.get('bank_name', '')).strip()
    account_number = str(req_data.get('account_number', '')).strip()
    account_name = str(req_data.get('account_name', '')).strip()

    if not amount or not amount.isdigit() or int(amount) <= 0:
        return jsonify({'status': 'error', 'message': 'Please enter a valid withdrawal amount.'})

    if not bank_name or not account_number or not account_name:
        return jsonify({'status': 'error', 'message': 'Please fill in all bank details.'})

    amount = int(amount)
    balance = current_user.wallet_balance or 0

    if amount > balance:
        return jsonify({'status': 'error', 'message': f'Insufficient balance. You have ₦{balance:,} in your wallet.'})

    import uuid
    transaction_ref = str(uuid.uuid4())

    #Remember Jegede This code is to Deduct from wallet and create withdrawal record
    current_user.wallet_balance = balance - amount

    wt = WalletTransaction(
        user_id=current_user.id,
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

    return jsonify({'status': 'success', 'message': f'₦{amount:,} withdrawn successfully to {account_name} ({bank_name} - {account_number}).'})

# LOGOUT
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


# CREATE TEST DATA & ADMIN USER
with app.app_context():
    db.create_all()

    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
        try:
            def ensure_column(table, column, definition):
                result = db.session.execute(f"PRAGMA table_info({table})").mappings().fetchall()
                existing = [row['name'] for row in result]
                if column not in existing:
                    db.session.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

            ensure_column('user', 'suspended', "BOOLEAN DEFAULT 0")
            ensure_column('user', 'email_verified', "BOOLEAN DEFAULT 0")
            ensure_column('user', 'verification_code', 'TEXT')
            ensure_column('user', 'verification_expires_at', 'TEXT')
            ensure_column('user', 'reset_code', 'TEXT')
            ensure_column('user', 'reset_expires_at', 'TEXT')
            # NOTE: existing SQLite schema may not include these columns.
            # I only add columns if they do not exist (see PRAGMA check below).
            def ensure_column_if_missing(table, column, definition):
                try:
                    existing_cols = db.session.execute(f"PRAGMA table_info({table})").mappings().fetchall()
                    if any(r['name'] == column for r in existing_cols):
                        return
                    db.session.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                except Exception as e:
                    app.logger.warning(f"ensure_column_if_missing failed for {table}.{column}: {e}")

            ensure_column_if_missing('user', 'avatar_url', "TEXT")
            ensure_column_if_missing('user', 'bio', "TEXT")

            # Wallet balance
            ensure_column_if_missing('user', 'wallet_balance', "INTEGER DEFAULT 0")

            # Payout fields (needed for prize payouts)
            ensure_column_if_missing('user', 'payout_bank', "TEXT")
            ensure_column_if_missing('user', 'payout_account_number', "TEXT")
            ensure_column_if_missing('user', 'payout_account_name', "TEXT")

            # Prize tracking fields for existing SQLite.
            ensure_column_if_missing('tournament_stat', 'prize_code', "TEXT")
            ensure_column_if_missing('tournament_stat', 'prize_code_sent_at', "TEXT")
            ensure_column_if_missing('tournament_stat', 'prize_status', "TEXT DEFAULT 'not_started'")
            ensure_column_if_missing('tournament_stat', 'paystack_transfer_ref', "TEXT")
            ensure_column_if_missing('tournament_stat', 'prize_paid_at', "TEXT")

            ensure_column_if_missing('tournament_match', 'room_code', "TEXT")
            ensure_column_if_missing('tournament_match', 'room_password', "TEXT")
            ensure_column_if_missing('tournament_match', 'player_one_profile_id', "TEXT")
            ensure_column_if_missing('tournament_match', 'player_two_profile_id', "TEXT")
            ensure_column_if_missing('tournament_match', 'winner_user_id', "INTEGER")
            ensure_column_if_missing('tournament_match', 'proof_note', "TEXT")
            ensure_column_if_missing('tournament_match', 'submitted_by_user_id', "INTEGER")
            ensure_column_if_missing('tournament_match', 'updated_at', "TEXT")

            # Re-check/commit schema before any ORM queries.
            db.session.commit()


            # Ensure new tables/columns exist for Phase 1 features


            # If DB was created with an older schema, ALTER TABLE is needed.
            ensure_column('notification', 'user_id', "INTEGER")
            ensure_column('notification', 'message', "TEXT")
            ensure_column('notification', 'read_at', "TEXT")
            ensure_column('notification', 'created_at', "TEXT")

            ensure_column('tournament', 'status', "TEXT DEFAULT 'open'")

            ensure_column('tournament', 'room_id', 'TEXT')
            ensure_column('tournament', 'room_password', 'TEXT')
            ensure_column('tournament', 'match_time', 'TEXT')
            ensure_column('tournament', 'first_place', 'TEXT')
            ensure_column('tournament', 'second_place', 'TEXT')
            ensure_column('tournament', 'third_place', 'TEXT')
            db.session.commit()
        except Exception as e:
            app.logger.warning(f"Database schema upgrade warning: {e}")

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

    # Free Fire tournament card title (fixes “Chat Tournament” showing)
    # The homepage uses tournament.name for the card title.
    ff_name = "Free Fire Championship"
    ff_game_match = "free fire"

    ff_tournament = Tournament.query.filter(db.func.lower(Tournament.game) == ff_game_match).first()
    if ff_tournament:
        ff_tournament.name = ff_name
        if not ff_tournament.description:
            ff_tournament.description = "Join the ultimate Free Fire tournament! Compete with the best players and win amazing prizes."
        db.session.commit()


    # Create sample tournaments
    # Only insert if a tournament with the same game does not exist.
    sample_tournaments = [
            Tournament(
                name="Free Fire Championship 2024",
                game="Free Fire",
                entry_fee=3000,
                prize=50000,
                max_participants=50,
                description="Join the ultimate Free Fire tournament! Compete with the best players and win amazing prizes. Squad matches with intense gameplay and strategic battles await!"
            ),
            Tournament(
                name="PUBG Mobile Masters League",
                game="PUBG Mobile",
                entry_fee=2000,
                
                prize=10000,
                max_participants=100,
                description="The biggest PUBG Mobile tournament of the year! Classic mode battles with top-tier competition. Show your survival skills and claim victory!"
            ),
            Tournament(
                name="eFootball Legends Cup",
                game="eFootball",
                entry_fee=2500,
                prize=20000,
                max_participants=60,
                description="Compete in the eFootball Legends Cup! Showcase your skills, tactics, and teamwork to win big prizes."
            ),
            Tournament(
                name="Call of Duty: Mobile Warfare Cup",
                game="Call of Duty Mobile",
                entry_fee=1500,
                prize=7500,
                max_participants=75,
                description="Dominate the battlefield in Call of Duty Mobile! Fast-paced action, tactical gameplay, and massive rewards for the champions!"
            )
        ]


    # Insert missing tournaments if their game doesn't exist yet.
    existing_games = {t.game for t in Tournament.query.all()}
    for tournament in sample_tournaments:
        if tournament.game not in existing_games:
            db.session.add(tournament)
    db.session.commit()


@socketio.on('connect')
def on_connect():
    # Socket.IO client connected
    pass


@socketio.on('join_user')
def on_join_user(data):
    """Client data: {"user_id": 123}"""
    if not current_user.is_authenticated:
        return
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
        join_room('global_chat')


@socketio.on('send_global_chat_message')
def on_send_global_chat_message(data):
    message = ((data or {}).get('message') or '').strip()
    if not message or not current_user.is_authenticated:
        return
    if len(message) > MAX_CHAT_MESSAGE_LENGTH:
        return

    new_message = GlobalChatMessage(user_id=current_user.id, message=message)
    db.session.add(new_message)
    db.session.commit()

    emit('new_global_chat_message', {
        'user_id': current_user.id,
        'username': current_user.username,
        'message': message,
        'created_at': new_message.created_at.isoformat() if new_message.created_at else None,
    }, room='global_chat')


@socketio.on('mark_notification_read')
def on_mark_notification_read(data):
    """Return the unread count or mark notifications as read for the authenticated user."""
    if not current_user.is_authenticated:
        return

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


if __name__ == '__main__':
    #setting host to 0.0.0.0 makes the app accessible from any IP address
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=port)
