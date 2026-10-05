"""Apply safe schema changes required by the production application.

This script is intentionally separate from app.py so deployment can run schema
checks before starting Gunicorn. It never deletes or merges business records.
"""
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

load_dotenv()


CONSTRAINT_NAME = 'unique_user_tournament_registration'
MIGRATIONS = (
    ('20260920_baseline_schema',),
    ('20260919_rate_limit_and_registration_constraint',),
    ('20260919_query_performance_indexes',),
    ('20260920_wallet_withdrawal_transfer_state',),
    ('20261001_product_features',),
    ('20261003_chat_replies_and_web_push',),
    ('20261004_chat_delivery_and_profile_photos',),
)

# These are deliberately additive. PostgreSQL's IF NOT EXISTS keeps deployment
# idempotent and avoids touching or rewriting business records.
PERFORMANCE_INDEXES = (
    'CREATE INDEX IF NOT EXISTS ix_tournament_status_match_time ON tournament (status, match_time)',
    'CREATE INDEX IF NOT EXISTS ix_tournament_stat_tournament_rank ON tournament_stat (tournament_id, rank)',
    'CREATE INDEX IF NOT EXISTS ix_tournament_stat_user_id ON tournament_stat (user_id)',
    'CREATE INDEX IF NOT EXISTS ix_user_tournament_user_joined_at ON user_tournament (user_id, joined_at)',
    'CREATE INDEX IF NOT EXISTS ix_user_tournament_tournament_payment_status ON user_tournament (tournament_id, payment_status)',
    'CREATE INDEX IF NOT EXISTS ix_wallet_transaction_user_created_at ON wallet_transaction (user_id, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_wallet_transaction_user_status ON wallet_transaction (user_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_notification_user_read_created_at ON notification (user_id, read_at, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_tournament_chat_message_tournament_created_at ON tournament_chat_message (tournament_id, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_global_chat_message_created_at ON global_chat_message (created_at)',
    'CREATE INDEX IF NOT EXISTS ix_global_chat_message_user_created_at ON global_chat_message (user_id, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_tournament_match_tournament_status ON tournament_match (tournament_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_tournament_match_player_one_status ON tournament_match (player_one_user_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_tournament_match_player_two_status ON tournament_match (player_two_user_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_match_chat_message_match_created_at ON tournament_match_chat_message (match_id, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_match_dispute_match_status ON tournament_match_dispute (match_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_wallet_transaction_withdrawal_state ON wallet_transaction (type, status, created_at)',
)


def bootstrap_baseline_schema(connection):
    """Create the ORM baseline only for a completely empty PostgreSQL schema.

    This reuses the application's existing SQLAlchemy model metadata rather
    than maintaining a second, potentially divergent handwritten schema.
    ``GAMEARENA_SCHEMA_BOOTSTRAP`` is intentionally consumed only here; the
    Gunicorn import path never sets it.
    """
    if inspect(connection).has_table('user'):
        return
    os.environ['GAMEARENA_SCHEMA_BOOTSTRAP'] = '1'
    try:
        from app import app as flask_app, db
        with flask_app.app_context():
            db.create_all()
    finally:
        os.environ.pop('GAMEARENA_SCHEMA_BOOTSTRAP', None)


def ensure_wallet_withdrawal_columns(connection):
    columns = {column['name'] for column in inspect(connection).get_columns('wallet_transaction')}
    additions = {
        'bank_code': 'VARCHAR(20)',
        'idempotency_key': 'VARCHAR(100)',
        'provider_recipient_code': 'VARCHAR(100)',
        'provider_transfer_code': 'VARCHAR(100)',
        'failure_reason': 'VARCHAR(500)',
        'processing_at': 'TIMESTAMP',
        'completed_at': 'TIMESTAMP',
        'failed_at': 'TIMESTAMP',
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(text(f'ALTER TABLE wallet_transaction ADD COLUMN {name} {definition}'))
    connection.execute(text(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_transaction_idempotency_key '
        'ON wallet_transaction (idempotency_key) WHERE idempotency_key IS NOT NULL'
    ))


def ensure_product_features(connection):
    statements = (
        "CREATE TABLE IF NOT EXISTS user_settings ("
        "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES \"user\" (id), "
        "tournament_notifications BOOLEAN NOT NULL DEFAULT TRUE, "
        "match_notifications BOOLEAN NOT NULL DEFAULT TRUE, "
        "wallet_notifications BOOLEAN NOT NULL DEFAULT TRUE, "
        "chat_notifications BOOLEAN NOT NULL DEFAULT TRUE, "
        "marketing_notifications BOOLEAN NOT NULL DEFAULT FALSE, "
        "profile_public BOOLEAN NOT NULL DEFAULT TRUE, "
        "allow_direct_messages BOOLEAN NOT NULL DEFAULT TRUE, "
        "theme VARCHAR(20) NOT NULL DEFAULT 'dark', "
        "reduce_motion BOOLEAN NOT NULL DEFAULT FALSE, "
        "larger_text BOOLEAN NOT NULL DEFAULT FALSE, "
        "preferred_games JSON NOT NULL DEFAULT '[]', "
        "game_ids JSON NOT NULL DEFAULT '{}', "
        "match_preferences JSON NOT NULL DEFAULT '{}')",
        "CREATE TABLE IF NOT EXISTS achievement ("
        "id SERIAL PRIMARY KEY, key VARCHAR(80) NOT NULL UNIQUE, "
        "name VARCHAR(120) NOT NULL, description VARCHAR(300) NOT NULL, "
        "icon VARCHAR(40) NOT NULL DEFAULT 'trophy', category VARCHAR(40) NOT NULL DEFAULT 'milestone', "
        "rule_type VARCHAR(40) NOT NULL, threshold INTEGER NOT NULL DEFAULT 1, "
        "hidden BOOLEAN NOT NULL DEFAULT FALSE, enabled BOOLEAN NOT NULL DEFAULT TRUE)",
        "CREATE TABLE IF NOT EXISTS user_achievement ("
        "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES \"user\" (id), "
        "achievement_id INTEGER NOT NULL REFERENCES achievement (id), progress INTEGER NOT NULL DEFAULT 0, "
        "unlocked_at TIMESTAMP NULL, CONSTRAINT unique_user_achievement UNIQUE (user_id, achievement_id))",
        "CREATE INDEX IF NOT EXISTS ix_user_achievement_user_unlocked ON user_achievement (user_id, unlocked_at)",
        "CREATE TABLE IF NOT EXISTS direct_message ("
        "id SERIAL PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES \"user\" (id), "
        "recipient_id INTEGER NOT NULL REFERENCES \"user\" (id), message VARCHAR(1000) NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, read_at TIMESTAMP NULL)",
        "CREATE INDEX IF NOT EXISTS ix_direct_message_pair_created ON direct_message (sender_id, recipient_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_direct_message_recipient_read ON direct_message (recipient_id, read_at)",
        "CREATE TABLE IF NOT EXISTS user_block ("
        "id SERIAL PRIMARY KEY, blocker_id INTEGER NOT NULL REFERENCES \"user\" (id), "
        "blocked_id INTEGER NOT NULL REFERENCES \"user\" (id), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "CONSTRAINT unique_user_block UNIQUE (blocker_id, blocked_id), "
        "CONSTRAINT check_user_block_not_self CHECK (blocker_id <> blocked_id))",
        "CREATE INDEX IF NOT EXISTS ix_user_block_blocked_id ON user_block (blocked_id)",
        "CREATE TABLE IF NOT EXISTS user_report ("
        "id SERIAL PRIMARY KEY, reporter_id INTEGER NOT NULL REFERENCES \"user\" (id), "
        "target_user_id INTEGER NULL REFERENCES \"user\" (id), content_type VARCHAR(30) NOT NULL DEFAULT 'player', "
        "content_id INTEGER NULL, reason VARCHAR(2000) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending', "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, reviewed_at TIMESTAMP NULL, "
        "reviewed_by_id INTEGER NULL REFERENCES \"user\" (id))",
        "CREATE INDEX IF NOT EXISTS ix_user_report_status_created ON user_report (status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_user_report_target_user ON user_report (target_user_id, created_at)",
        "ALTER TABLE notification ADD COLUMN IF NOT EXISTS category VARCHAR(30) NOT NULL DEFAULT 'system'",
        "ALTER TABLE notification ADD COLUMN IF NOT EXISTS target_url VARCHAR(500) NULL",
        "ALTER TABLE tournament_match ADD COLUMN IF NOT EXISTS round_number INTEGER NULL",
        "ALTER TABLE tournament_match ADD COLUMN IF NOT EXISTS match_order INTEGER NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tournament_bracket_match_slot "
        "ON tournament_match (tournament_id, round_number, match_order) "
        "WHERE round_number IS NOT NULL AND match_order IS NOT NULL",
    )
    for statement in statements:
        connection.execute(text(statement))

    definitions = (
        ('first_tournament', 'First Tournament', 'Joined your first tournament.', 'flag', 'tournaments', 1),
        ('first_win', 'First Win', 'Won your first confirmed match.', 'trophy', 'wins', 1),
        ('five_wins', 'Five Wins', 'Won five confirmed matches.', 'medal', 'wins', 5),
        ('ten_wins', 'Ten Wins', 'Won ten confirmed matches.', 'crown', 'wins', 10),
        ('win_streak_5', 'On a Roll', 'Won five confirmed matches in a row.', 'flame', 'win_streak', 5),
        ('ten_tournaments', 'Tournament Regular', 'Joined ten tournaments.', 'users', 'tournaments', 10),
        ('top_100', 'Top 100', 'Placed in the top 100 of a tournament.', 'chart', 'top_rank', 100),
        ('top_10', 'Top 10', 'Placed in the top 10 of a tournament.', 'star', 'top_rank', 10),
        ('first_champion', 'Champion', 'Finished first in a tournament leaderboard.', 'crown', 'champions', 1),
    )
    for key, name, description, icon, rule_type, threshold in definitions:
        connection.execute(text(
            "INSERT INTO achievement (key, name, description, icon, category, rule_type, threshold, hidden, enabled) "
            "VALUES (:key, :name, :description, :icon, 'milestone', :rule_type, :threshold, FALSE, TRUE) "
            "ON CONFLICT (key) DO NOTHING"
        ), {
            'key': key, 'name': name, 'description': description, 'icon': icon,
            'rule_type': rule_type, 'threshold': threshold,
        })
    connection.execute(text(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_wallet_transaction_provider_transfer_code '
        'ON wallet_transaction (provider_transfer_code) WHERE provider_transfer_code IS NOT NULL'
    ))


def database_url():
    value = (os.environ.get('DATABASE_URL') or '').strip()
    if not value:
        raise RuntimeError('DATABASE_URL is required.')
    return value


def duplicate_registrations(connection):
    return connection.execute(text(
        'SELECT user_id, tournament_id, COUNT(*) AS duplicate_count '
        'FROM user_tournament GROUP BY user_id, tournament_id '
        'HAVING COUNT(*) > 1'
    )).fetchall()


def has_registration_constraint(connection):
    inspector = inspect(connection)
    for constraint in inspector.get_unique_constraints('user_tournament'):
        if constraint.get('name') == CONSTRAINT_NAME:
            return True
    for index in inspector.get_indexes('user_tournament'):
        if index.get('name') == CONSTRAINT_NAME and index.get('unique'):
            return True
    return False


def ensure_chat_replies_and_push(connection):
    for table in ('global_chat_message', 'direct_message'):
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS reply_to_id INTEGER REFERENCES {table}(id) ON DELETE SET NULL'))
        connection.execute(text(f'CREATE INDEX IF NOT EXISTS ix_{table}_reply_to ON {table}(reply_to_id)'))
    connection.execute(text('CREATE TABLE IF NOT EXISTS push_subscription ('
        'id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES "user"(id), '
        'endpoint_hash VARCHAR(64) NOT NULL UNIQUE, subscription JSON NOT NULL, '
        'created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'))
    connection.execute(text('CREATE INDEX IF NOT EXISTS ix_push_subscription_user_id ON push_subscription(user_id)'))
    # Supabase exposes public-schema tables through its API. These credentials
    # are server-only; no browser role should be able to read subscriptions.
    connection.execute(text('ALTER TABLE push_subscription ENABLE ROW LEVEL SECURITY'))
    connection.execute(text('REVOKE ALL ON push_subscription FROM PUBLIC'))
    connection.execute(text("DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN REVOKE ALL ON push_subscription FROM anon; END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN REVOKE ALL ON push_subscription FROM authenticated; END IF; "
        "END $$"))


def ensure_chat_delivery_and_photos(connection):
    for table in ('direct_message', 'global_chat_message'):
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS client_message_id VARCHAR(36)'))
        connection.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP'))
        connection.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_client_message_id ON {table}(client_message_id)'))
    connection.execute(text('CREATE TABLE IF NOT EXISTS profile_photo (id VARCHAR(32) PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES "user"(id), image BYTEA NOT NULL)'))
    connection.execute(text('ALTER TABLE profile_photo ENABLE ROW LEVEL SECURITY'))
    connection.execute(text('REVOKE ALL ON profile_photo FROM PUBLIC'))
    connection.execute(text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON profile_photo FROM anon; END IF; IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON profile_photo FROM authenticated; END IF; END $$"))


def ensure_migration_table(connection):
    connection.execute(text(
        'CREATE TABLE IF NOT EXISTS schema_migration ('
        'migration_id VARCHAR(150) PRIMARY KEY, '
        'applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)'
    ))


def applied_migrations(connection):
    return {
        row[0] for row in connection.execute(
            text('SELECT migration_id FROM schema_migration')
        ).fetchall()
    }


def mark_migration_applied(connection, migration_id):
    connection.execute(
        text('INSERT INTO schema_migration (migration_id) VALUES (:migration_id)'),
        {'migration_id': migration_id},
    )


def migrate(url=None):
    url = url or database_url()
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(url, future=True)
    dialect = engine.dialect.name
    if dialect != 'postgresql':
        raise RuntimeError(f'Unsupported database dialect: {dialect}')

    try:
        with engine.begin() as connection:
            connection.execute(text('SELECT pg_advisory_xact_lock(718425109)'))
            inspector = inspect(connection)
            if not inspector.has_table('user_tournament'):
                bootstrap_baseline_schema(connection)

            ensure_migration_table(connection)
            completed = applied_migrations(connection)

            if '20260920_baseline_schema' not in completed:
                mark_migration_applied(connection, '20260920_baseline_schema')

            if '20260919_rate_limit_and_registration_constraint' not in completed:
                connection.execute(text(
                    'CREATE TABLE IF NOT EXISTS rate_limit_bucket ('
                    'id SERIAL PRIMARY KEY, '
                    'bucket_key VARCHAR(255) NOT NULL UNIQUE, '
                    'window_started TIMESTAMP NOT NULL, '
                    'count INTEGER NOT NULL DEFAULT 0)'
                ))

                duplicates = duplicate_registrations(connection)
                if duplicates:
                    print('ERROR: duplicate user/tournament registrations found; no constraint was added.', file=sys.stderr)
                    for user_id, tournament_id, count in duplicates:
                        print(f'  user_id={user_id}, tournament_id={tournament_id}, count={count}', file=sys.stderr)
                    raise RuntimeError('Resolve duplicate registrations explicitly before migration.')

                if not has_registration_constraint(connection):
                    connection.execute(text(
                        f'ALTER TABLE user_tournament ADD CONSTRAINT {CONSTRAINT_NAME} '
                        'UNIQUE (user_id, tournament_id)'
                    ))
                mark_migration_applied(connection, '20260919_rate_limit_and_registration_constraint')

            if '20260919_query_performance_indexes' not in completed:
                for statement in PERFORMANCE_INDEXES:
                    connection.execute(text(statement))
                mark_migration_applied(connection, '20260919_query_performance_indexes')

            if '20260920_wallet_withdrawal_transfer_state' not in completed:
                ensure_wallet_withdrawal_columns(connection)
                mark_migration_applied(connection, '20260920_wallet_withdrawal_transfer_state')

            if '20261001_product_features' not in completed:
                ensure_product_features(connection)
                mark_migration_applied(connection, '20261001_product_features')
            if '20261003_chat_replies_and_web_push' not in completed:
                ensure_chat_replies_and_push(connection)
                mark_migration_applied(connection, '20261003_chat_replies_and_web_push')

            if '20261004_chat_delivery_and_profile_photos' not in completed:
                ensure_chat_delivery_and_photos(connection)
                mark_migration_applied(connection, '20261004_chat_delivery_and_profile_photos')

            # Keep this list near the migration declarations so a future migration
            # cannot silently be added without an implementation branch above.
            unknown = {migration[0] for migration in MIGRATIONS} - {
                '20260920_baseline_schema',
                '20260919_rate_limit_and_registration_constraint',
                '20260919_query_performance_indexes',
                '20260920_wallet_withdrawal_transfer_state',
                '20261001_product_features',
                '20261003_chat_replies_and_web_push',
                '20261004_chat_delivery_and_profile_photos',
            }
            if unknown:
                raise RuntimeError(f'Migration declarations without implementation: {sorted(unknown)}')

    finally:
        engine.dispose()

    print('Database schema check completed successfully.')


if __name__ == '__main__':
    try:
        migrate()
    except Exception as error:
        print(f'Database migration stopped: {error}', file=sys.stderr)
        raise SystemExit(1)
