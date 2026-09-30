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
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)
for email_setting in (
    'RESEND_API_KEY', 'SMTP_SERVER', 'SMTP_PORT', 'SMTP_USERNAME',
    'SMTP_PASSWORD', 'EMAIL_FROM',
):
    os.environ[email_setting] = ''


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
