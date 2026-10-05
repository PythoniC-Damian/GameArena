"""Version migrations on the existing PostgreSQL database; never SQLite."""
import os
from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

load_dotenv(override=False)
url = os.environ.get('MIGRATION_DATABASE_URL') or os.environ.get('DATABASE_URL', '')
if not url.lower().startswith(('postgresql://', 'postgres://', 'postgresql+')):
    raise RuntimeError('A PostgreSQL migration URL is required.')
if url.startswith('postgres://'):
    url = url.replace('postgres://', 'postgresql://', 1)
if context.is_offline_mode():
    raise RuntimeError('Baseline verification requires an online database connection.')
engine = create_engine(url, future=True, poolclass=NullPool,
                       connect_args={'connect_timeout': 10})
try:
    with engine.begin() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            connection.execute(text('SELECT pg_advisory_xact_lock(718425109)'))
            context.run_migrations()
finally:
    engine.dispose()
