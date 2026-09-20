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
    engine = create_engine(url, future=True)
    dialect = engine.dialect.name
    if dialect != 'postgresql':
        raise RuntimeError(f'Unsupported database dialect: {dialect}')

    with engine.begin() as connection:
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

        # Keep this list near the migration declarations so a future migration
        # cannot silently be added without an implementation branch above.
        unknown = {migration[0] for migration in MIGRATIONS} - {
            '20260920_baseline_schema',
            '20260919_rate_limit_and_registration_constraint',
            '20260919_query_performance_indexes',
            '20260920_wallet_withdrawal_transfer_state',
        }
        if unknown:
            raise RuntimeError(f'Migration declarations without implementation: {sorted(unknown)}')

    print('Database schema check completed successfully.')


if __name__ == '__main__':
    try:
        migrate()
    except Exception as error:
        print(f'Database migration stopped: {error}', file=sys.stderr)
        raise SystemExit(1)
