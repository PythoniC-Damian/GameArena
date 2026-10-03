"""PostgreSQL-only pytest setup for GameArena."""
import os

import pytest
from dotenv import dotenv_values
from sqlalchemy import text


TEST_DATABASE_URL = (os.environ.get('GAMEARENA_TEST_DATABASE_URL') or '').strip()
NORMAL_DATABASE_URL = (dotenv_values('.env').get('DATABASE_URL') or '').strip()

if not TEST_DATABASE_URL:
    raise pytest.UsageError(
        'GAMEARENA_TEST_DATABASE_URL must name an isolated PostgreSQL test database.'
    )
if not TEST_DATABASE_URL.lower().startswith(('postgresql://', 'postgres://', 'postgresql+')):
    raise pytest.UsageError('GAMEARENA_TEST_DATABASE_URL must point to PostgreSQL.')
if NORMAL_DATABASE_URL and TEST_DATABASE_URL == NORMAL_DATABASE_URL:
    raise pytest.UsageError(
        'GAMEARENA_TEST_DATABASE_URL must not be the DATABASE_URL configured in .env.'
    )

os.environ['GAMEARENA_TESTING'] = '1'
os.environ['DATABASE_URL'] = TEST_DATABASE_URL
os.environ['GAMEARENA_SCHEMA_BOOTSTRAP'] = '1'
for private_setting in ('ADMIN_EMAIL','ADMIN_PASSWORD','PAYSTACK_SECRET_KEY','PAYSTACK_PUBLIC_KEY','SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT','GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET'):
    os.environ[private_setting] = ''
for email_setting in (
    'RESEND_API_KEY', 'SMTP_SERVER', 'SMTP_PORT', 'SMTP_USERNAME',
    'SMTP_PASSWORD', 'EMAIL_FROM',
):
    os.environ[email_setting] = ''


# Several legacy tests intentionally keep an outer application context while
# switching test clients. Flask-Login caches its user on that context's g.
# Reset that cache per test request so permissions are tested for the actual
# session instead of the preceding client's cached user.
from app import app as test_app
from flask import g


@test_app.before_request
def fresh_test_session_user():
    g.pop('_login_user', None)
    g.pop('csrf_token', None)


@pytest.fixture(autouse=True)
def clean_test_database():
    """Keep each test independent without touching the normal database."""
    from app import app, db

    with app.app_context():
        table_names = ', '.join(
            f'"{table.name}"' for table in db.metadata.sorted_tables
        )
        db.session.execute(text(f'TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE'))
        db.session.commit()
    yield
    with app.app_context():
        db.session.rollback()
