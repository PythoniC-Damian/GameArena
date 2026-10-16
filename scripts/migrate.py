"""Explicit release migration command; importing the app never runs this."""
import os
import sys
import time
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from dotenv import load_dotenv
load_dotenv(root / '.env', override=False)


def upgrade_with_retry(config, attempts=3):
    """Alembic rolls back its transaction; retry only transient DDL lock failures."""
    from alembic import command
    from sqlalchemy.exc import OperationalError
    for attempt in range(attempts):
        try:
            command.upgrade(config, 'head')
            return
        except OperationalError as error:
            if getattr(error.orig, 'pgcode', None) not in {'40P01', '55P03'} or attempt + 1 == attempts:
                raise
            print('Migration encountered a transient database lock; retrying its rolled-back transaction.', flush=True)
            time.sleep(attempt + 1)


def main():
    url = os.environ.get('MIGRATION_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('A PostgreSQL database URL must be provided.')
    from db_migrate import migrate
    from alembic.config import Config
    # Keep the existing additive migrations and verify their recorded baseline.
    migrate(url=url)
    upgrade_with_retry(Config(str(root / 'alembic.ini')))


if __name__ == '__main__':
    main()
