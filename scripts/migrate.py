"""Explicit release migration command; importing the app never runs this."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from dotenv import load_dotenv
load_dotenv(root / '.env', override=False)


def main():
    url = os.environ.get('MIGRATION_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('A PostgreSQL database URL must be provided.')
    from db_migrate import migrate
    from alembic.config import Config
    from alembic import command
    # Keep the existing additive migrations and verify their recorded baseline.
    migrate(url=url)
    command.upgrade(Config(str(root / 'alembic.ini')), 'head')


if __name__ == '__main__':
    main()
