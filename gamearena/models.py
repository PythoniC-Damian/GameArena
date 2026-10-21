"""Existing models, extracted unchanged; table names and accounting are preserved."""
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from gamearena.extensions import db
from gamearena.constants import MAX_CHAT_MESSAGE_LENGTH

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    supabase_auth_id = db.Column(db.String(36), unique=True, nullable=True)
    auth_session_version = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    requires_player_consent = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
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

    master_expires_at = db.Column(db.DateTime, nullable=True)
    master_frame = db.Column(db.String(20), nullable=False, default="blue", server_default="blue")
    master_profile_theme = db.Column(db.String(20), nullable=False, default="arena", server_default="arena")

    @property
    def master_active(self):
        return bool(not self.suspended and (self.is_admin or (
            self.master_expires_at and self.master_expires_at > datetime.utcnow())))

    # Profile (Phase 1)
    avatar_url = db.Column(db.String(500), nullable=True)
    bio = db.Column(db.Text, nullable=True)

    # Wallet balance for deposits/withdrawals
    wallet_balance = db.Column(db.Integer, default=0)
    wallet_winnings_balance = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    wallet_bonus_balance = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    cosmetic_frame = db.Column(db.String(40), nullable=True)
    cosmetic_card = db.Column(db.String(40), nullable=True)
    cosmetic_nameplate = db.Column(db.String(40), nullable=True)

    @property
    def purchased_balance(self):
        return (self.wallet_balance or 0) - (self.wallet_winnings_balance or 0)

    @property
    def profile_frame(self):
        return self.cosmetic_frame or (self.master_frame if self.master_active else '')

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


class AccountSecurity(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    totp_secret = db.Column(db.Text)
    pending_secret = db.Column(db.Text)
    pending_at = db.Column(db.DateTime)
    enabled_at = db.Column(db.DateTime)
    recovery_hashes = db.Column(db.JSON, nullable=False, default=list)
    last_counter = db.Column(db.BigInteger, nullable=False, default=-1)
    version = db.Column(db.Integer, nullable=False, default=0)


class SecurityAuditEvent(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Retain audit identity after account deletion, without cross-transaction FK locks.
    actor_id = db.Column(db.Integer, nullable=True)
    event = db.Column(db.String(64), nullable=False)
    endpoint = db.Column(db.String(120), nullable=False)
    method = db.Column(db.String(8), nullable=False)
    status = db.Column(db.Integer, nullable=False)
    request_id = db.Column(db.String(64), nullable=False)
    __table_args__ = (db.Index('ix_security_audit_occurred', 'occurred_at', 'id'),)


class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    tournament_notifications = db.Column(db.Boolean, nullable=False, default=True)
    match_notifications = db.Column(db.Boolean, nullable=False, default=True)
    wallet_notifications = db.Column(db.Boolean, nullable=False, default=True)
    chat_notifications = db.Column(db.Boolean, nullable=False, default=True)
    marketing_notifications = db.Column(db.Boolean, nullable=False, default=False)
    profile_public = db.Column(db.Boolean, nullable=False, default=True)
    allow_direct_messages = db.Column(db.Boolean, nullable=False, default=True)
    theme = db.Column(db.String(20), nullable=False, default='dark')
    display_currency = db.Column(db.String(3), nullable=False, default='GP', server_default='GP')
    language = db.Column(db.String(8), nullable=False, default='en', server_default='en')
    reduce_motion = db.Column(db.Boolean, nullable=False, default=False)
    larger_text = db.Column(db.Boolean, nullable=False, default=False)
    preferred_games = db.Column(db.JSON, nullable=False, default=list)
    game_ids = db.Column(db.JSON, nullable=False, default=dict)
    match_preferences = db.Column(db.JSON, nullable=False, default=dict)
    user = db.relationship('User', backref=db.backref('settings', uselist=False))


class Achievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    icon = db.Column(db.String(40), nullable=False, default='trophy')
    category = db.Column(db.String(40), nullable=False, default='milestone')
    rule_type = db.Column(db.String(40), nullable=False)
    threshold = db.Column(db.Integer, nullable=False, default=1)
    hidden = db.Column(db.Boolean, nullable=False, default=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class UserAchievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey('achievement.id'), nullable=False)
    progress = db.Column(db.Integer, nullable=False, default=0)
    unlocked_at = db.Column(db.DateTime, nullable=True)
    achievement = db.relationship('Achievement')
    user = db.relationship('User', backref=db.backref('achievement_records', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'achievement_id', name='unique_user_achievement'),
        db.Index('ix_user_achievement_user_unlocked', 'user_id', 'unlocked_at'),
    )


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
    competition = db.relationship('TournamentCompetition', uselist=False, lazy='selectin')
    launch_plan = db.relationship('TournamentLaunchPlan', uselist=False, lazy='selectin')
    artwork = db.relationship('TournamentArtwork', foreign_keys='TournamentArtwork.tournament_id', lazy='selectin', order_by='TournamentArtwork.position')
    participants = db.relationship('UserTournament', back_populates='tournament')
    leaderboard = db.relationship('TournamentStat', back_populates='tournament', cascade='all, delete-orphan', order_by='TournamentStat.rank')

    __table_args__ = (
        db.Index('ix_tournament_status_match_time', 'status', 'match_time'),
    )

    @property
    def prize_pool(self):
        return self.prize


class TournamentLaunchPlan(db.Model):
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), primary_key=True)
    registration_closes_at = db.Column(db.DateTime, nullable=False)
    eligibility = db.Column(db.String(1000), nullable=False)
    rules = db.Column(db.Text, nullable=False)
    cancellation_policy = db.Column(db.String(2000), nullable=False)
    funding_note = db.Column(db.String(1000), nullable=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    snapshot = db.Column(db.String(64), nullable=False)


class TournamentVisit(db.Model):
    """First signed-in view and join intent; no guest/device tracking."""
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    viewed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    join_requested = db.Column(db.Boolean, nullable=False, default=False)


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
        db.Index('ix_tournament_stat_tournament_rank', 'tournament_id', 'rank'),
        db.Index('ix_tournament_stat_user_id', 'user_id'),
    )


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
        db.Index('ix_user_tournament_user_joined_at', 'user_id', 'joined_at'),
        db.Index('ix_user_tournament_tournament_payment_status', 'tournament_id', 'payment_status'),
    )


class WalletTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'deposit' or 'withdrawal'
    amount = db.Column(db.Integer, nullable=False, default=0)
    winnings_spent = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    wallet_source = db.Column(db.String(12), nullable=False, default='combined', server_default='combined')
    bonus_spent = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # Deposits retain their existing pending/completed/failed lifecycle.
    # Withdrawals use pending -> processing -> completed, with failed for a
    # definitive provider failure after the reserved funds have been released.
    status = db.Column(db.String(20), default='completed')
    withdrawal_fee_kobo = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    @property
    def incoming(self):
        return self.type in {'deposit', 'prize_credit', 'entry_refund', 'organizer_income', 'reserve_refund'}

    @property
    def category_label(self):
        return {'deposit':'Wallet deposit', 'withdrawal':'Bank withdrawal', 'tournament_entry':'Tournament entry',
            'cosmetic_purchase':'Cosmetic purchase', 'prize_reserve':'Prize funding', 'prize_credit':'Tournament prize',
            'entry_refund':'Entry refund', 'organizer_income':'Organiser earnings', 'reserve_refund':'Prize funding returned'}.get(self.type, self.type.replace('_',' ').capitalize())

    @property
    def payout_kobo(self):
        return self.amount * 100 - (self.withdrawal_fee_kobo or 0)

    transaction_ref = db.Column(db.String(100), unique=True, nullable=True)
    bank_name = db.Column(db.String(120), nullable=True)
    bank_code = db.Column(db.String(20), nullable=True)
    account_number = db.Column(db.String(40), nullable=True)
    account_name = db.Column(db.String(200), nullable=True)
    idempotency_key = db.Column(db.String(100), unique=True, nullable=True)
    provider_recipient_code = db.Column(db.String(100), nullable=True)
    provider_transfer_code = db.Column(db.String(100), unique=True, nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)
    processing_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    failed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    @property
    def public_transaction_id(self):
        """Stable receipt identifier derived from the immutable database identity.

        UUID5 keeps historical receipts stable without replacing payment-provider
        references or changing the primary key used by accounting and webhooks.
        """
        import uuid
        if self.id is None:
            return None
        return 'GA-' + uuid.uuid5(uuid.NAMESPACE_URL, f'https://gamearena01.com/wallet/transactions/{self.id}').hex.upper()

    user = db.relationship('User', backref=db.backref('wallet_transactions', lazy=True))

    __table_args__ = (
        db.Index('ix_wallet_transaction_user_created_at', 'user_id', 'created_at'),
        db.Index('ix_wallet_transaction_user_status', 'user_id', 'status'),
        db.Index('ix_wallet_transaction_withdrawal_state', 'type', 'status', 'created_at'),
    )


class RateLimitBucket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bucket_key = db.Column(db.String(255), unique=True, nullable=False)
    window_started = db.Column(db.DateTime, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(30), nullable=False, default='system')
    target_url = db.Column(db.String(500), nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User', backref=db.backref('notifications', lazy=True))

    __table_args__ = (
        db.Index('ix_notification_user_read_created_at', 'user_id', 'read_at', 'created_at'),
    )


class TournamentChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    tournament = db.relationship('Tournament', backref=db.backref('chat_messages', lazy=True))

    __table_args__ = (
        db.Index('ix_tournament_chat_message_tournament_created_at', 'tournament_id', 'created_at'),
    )


class GlobalChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    client_message_id = db.Column(db.String(36), nullable=True, unique=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('global_chat_message.id', ondelete='SET NULL'), nullable=True)
    reply_to = db.relationship('GlobalChatMessage', remote_side=[id], lazy='joined', join_depth=1)

    __table_args__ = (
        db.Index('ix_global_chat_message_created_at', 'created_at'),
        db.Index('ix_global_chat_message_user_created_at', 'user_id', 'created_at'),
    )


class DirectMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(MAX_CHAT_MESSAGE_LENGTH), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])
    client_message_id = db.Column(db.String(36), nullable=True, unique=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('direct_message.id', ondelete='SET NULL'), nullable=True)
    reply_to = db.relationship('DirectMessage', remote_side=[id], lazy='joined', join_depth=1)

    __table_args__ = (
        db.Index('ix_direct_message_pair_created', 'sender_id', 'recipient_id', 'created_at'),
        db.Index('ix_direct_message_recipient_read', 'recipient_id', 'read_at'),
    )


class PlayerConnection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    low_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    high_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    intro_used = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.now())
    __table_args__ = (
        db.UniqueConstraint('low_id', 'high_id', name='uq_player_connection_pair'),
        db.CheckConstraint('low_id < high_id', name='ck_player_connection_order'),
        db.CheckConstraint('requester_id IN (low_id, high_id)', name='ck_player_connection_requester'),
        db.CheckConstraint("status IN ('pending','accepted','cancelled','declined')", name='ck_player_connection_status'),
    )


class ProfilePhoto(db.Model):
    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    image = db.Column(db.LargeBinary, nullable=False)


class PushSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    endpoint_hash = db.Column(db.String(64), nullable=False, unique=True)
    subscription = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)


class UserBlock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    blocker = db.relationship('User', foreign_keys=[blocker_id])
    blocked = db.relationship('User', foreign_keys=[blocked_id])

    __table_args__ = (
        db.UniqueConstraint('blocker_id', 'blocked_id', name='unique_user_block'),
        db.CheckConstraint('blocker_id <> blocked_id', name='check_user_block_not_self'),
        db.Index('ix_user_block_blocked_id', 'blocked_id'),
    )


class UserReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    content_type = db.Column(db.String(30), nullable=False, default='player')
    content_id = db.Column(db.Integer, nullable=True)
    reason = db.Column(db.String(2000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reporter = db.relationship('User', foreign_keys=[reporter_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    __table_args__ = (
        db.Index('ix_user_report_status_created', 'status', 'created_at'),
        db.Index('ix_user_report_target_user', 'target_user_id', 'created_at'),
    )


class TournamentMatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    player_one_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    player_two_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(30), default='scheduled')
    round_number = db.Column(db.Integer, nullable=True)
    match_order = db.Column(db.Integer, nullable=True)
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

    __table_args__ = (
        db.Index('ix_tournament_match_tournament_status', 'tournament_id', 'status'),
        db.Index('ix_tournament_match_player_one_status', 'player_one_user_id', 'status'),
        db.Index('ix_tournament_match_player_two_status', 'player_two_user_id', 'status'),
        db.UniqueConstraint('tournament_id', 'round_number', 'match_order', name='unique_tournament_bracket_match'),
    )


class TournamentMatchChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('tournament_match.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    match = db.relationship('TournamentMatch', backref=db.backref('chat_messages', lazy=True))

    __table_args__ = (
        db.Index('ix_match_chat_message_match_created_at', 'match_id', 'created_at'),
    )


class TournamentMatchDispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('tournament_match.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User')
    match = db.relationship('TournamentMatch', backref=db.backref('disputes', lazy=True))

    __table_args__ = (
        db.Index('ix_match_dispute_match_status', 'match_id', 'status'),
    )



class SavedTournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    reminder_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    reminded_for = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User')
    tournament = db.relationship('Tournament')
    __table_args__ = (db.UniqueConstraint('user_id', 'tournament_id', name='unique_saved_tournament'),)


class MasterSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    plan_code = db.Column(db.String(80), nullable=False)
    billing_mode = db.Column(db.String(20), nullable=False, default='recurring', server_default='recurring')
    billing_email = db.Column(db.String(150), nullable=False)
    subscription_code = db.Column(db.String(80), unique=True, nullable=True)
    customer_code = db.Column(db.String(80), nullable=True)
    email_token = db.Column(db.String(150), nullable=True)
    status = db.Column(db.String(30), nullable=False, default='pending')
    next_payment_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User')


class MasterPayment(db.Model):
    reference = db.Column(db.String(100), primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('master_subscription.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    checkout_url = db.Column(db.String(500), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    period_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    subscription = db.relationship('MasterSubscription')


class UserActivityDay(db.Model):
    """One signed-in player visit per Lagos calendar day; no URL or device data."""
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True)
    activity_date = db.Column(db.Date, primary_key=True)
    __table_args__ = (db.Index('ix_user_activity_day_date', 'activity_date', 'user_id'),)


class CosmeticOwnership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_key = db.Column(db.String(40), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('wallet_transaction.id'), nullable=True)
    acquired_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'item_key', name='unique_owned_cosmetic'),)


class OrganizerDraft(db.Model):
    __table_args__ = (db.Index('ix_organizer_draft_owner_status', 'owner_id', 'status'),)
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    game = db.Column(db.String(100), nullable=False)
    rules = db.Column(db.Text, nullable=False)
    entry_fee = db.Column(db.Integer, nullable=False, default=0)
    prize_pool = db.Column(db.Integer, nullable=False, default=0)
    capacity = db.Column(db.Integer, nullable=False, default=16)
    starts_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='draft')
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=True, unique=True)
    review_note = db.Column(db.String(500), nullable=True)
    agreement_version = db.Column(db.String(40))
    accepted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    tournament = db.relationship('Tournament')
    artwork = db.relationship('TournamentArtwork', foreign_keys='TournamentArtwork.draft_id', lazy='selectin', order_by='TournamentArtwork.position', cascade='all, delete-orphan')
    owner = db.relationship('User')


class OrganizerProfile(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    contact = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    review_note = db.Column(db.String(500))
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.DateTime)
    user = db.relationship('User', foreign_keys=[user_id])


class OrganizerFinance(db.Model):
    """One funded event; locked with its tournament before any settlement."""
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prize_reserved = db.Column(db.Integer, nullable=False)
    reserve_winnings = db.Column(db.Integer, nullable=False, default=0)
    fee_bps = db.Column(db.Integer, nullable=False, default=500)
    agreement_version = db.Column(db.String(40), nullable=False)
    accepted_at = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String(20), nullable=False, default='funded')
    entry_revenue = db.Column(db.Integer, nullable=False, default=0)
    platform_fee = db.Column(db.Integer, nullable=False, default=0)
    settled_at = db.Column(db.DateTime)
    settled_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    settlement_note = db.Column(db.String(500))


class TournamentArtwork(db.Model):
    """Validated, bounded WebP images; binary data loads only on media requests."""
    id = db.Column(db.String(32), primary_key=True)
    draft_id = db.Column(db.Integer, db.ForeignKey('organizer_draft.id'), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=True, index=True)
    position = db.Column(db.Integer, nullable=False)
    image = db.deferred(db.Column(db.LargeBinary, nullable=False))
    __table_args__ = (
        db.UniqueConstraint('draft_id', 'position', name='uq_tournament_artwork_draft_position'),
        db.UniqueConstraint('tournament_id', 'position', name='uq_tournament_artwork_event_position'),
        db.CheckConstraint('position BETWEEN 1 AND 3', name='ck_tournament_artwork_position'),
    )


class TournamentCompetition(db.Model):
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), primary_key=True)
    phase = db.Column(db.String(20), nullable=False, default='registration')
    game_rules = db.Column(db.Text, nullable=False)
    no_show_policy = db.Column(db.String(1000), nullable=False)
    checkin_closes_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    __table_args__ = (db.CheckConstraint("phase IN ('registration','check_in','live','finished')", name='ck_competition_phase'),)


class TournamentCheckIn(db.Model):
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    game_id = db.Column(db.String(150), nullable=False)
    normalized_game_id = db.Column(db.String(150), nullable=False)
    checked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    rules_version = db.Column(db.String(30), nullable=False, default='1v1-v1')
    __table_args__ = (db.UniqueConstraint('tournament_id','normalized_game_id',name='uq_checkin_game_account'),)
    user = db.relationship('User')


class MatchLobby(db.Model):
    match_id = db.Column(db.Integer, db.ForeignKey('tournament_match.id'), primary_key=True)
    published_at = db.Column(db.DateTime)
    player_one_ready_at = db.Column(db.DateTime)
    player_two_ready_at = db.Column(db.DateTime)
    player_one_score = db.Column(db.Integer)
    player_two_score = db.Column(db.Integer)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(db.DateTime)
    review_note = db.Column(db.String(1000))


class MatchEvidence(db.Model):
    id = db.Column(db.String(32), primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('tournament_match.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image = db.deferred(db.Column(db.LargeBinary, nullable=False))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User')
