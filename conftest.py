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
for setting in ('SECURITY_ENFORCE_ADMIN_MFA','SECURITY_REQUIRE_STEP_UP','ORIGIN_PROTECTION_ENABLED'):
    os.environ[setting] = 'false'
for setting in ('ORIGIN_SHARED_SECRET','SECURITY_ENCRYPTION_KEY'):
    os.environ[setting] = ''
os.environ['SECURITY_ALERT_EMAIL'] = ''
os.environ['WITHDRAWALS_ENABLED'] = 'true'
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


# Permission/MFA guards must see this request's client, even in legacy tests
# that retain an outer application context while switching browser sessions.
_request_hooks = test_app.before_request_funcs[None]
_request_hooks.insert(0, _request_hooks.pop())


@pytest.fixture(autouse=True)
def clean_test_database(monkeypatch):
    """Keep each test independent without touching the normal database."""
    from app import app, db, socketio

    # Legacy fixtures predate the adult declaration; dedicated privacy tests enable the gate.
    monkeypatch.setitem(test_app.config, 'ADULT_ACCESS_REQUIRED', False)
    tasks = []
    start_background_task = socketio.start_background_task
    def track_task(*args, **kwargs):
        task = start_background_task(*args, **kwargs)
        tasks.append(task)
        return task
    monkeypatch.setattr(socketio, 'start_background_task', track_task)
    with app.app_context():
        table_names = ', '.join(
            f'"{table.name}"' for table in db.metadata.sorted_tables
        )
        db.session.execute(text(f'TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE'))
        db.session.commit()
    yield
    # Complete asynchronous notifications before the next test truncates tables.
    for task in tasks:
        if task is not None: task.join()
    with app.app_context():
        db.session.rollback()
