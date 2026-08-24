"""Apply safe schema changes required by the production application.

This script is intentionally separate from app.py so deployment can run schema
checks before starting Gunicorn. It never deletes or merges business records.
"""
import os
import sys

from sqlalchemy import create_engine, inspect, text


CONSTRAINT_NAME = 'unique_user_tournament_registration'


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


def migrate(url=None):
    url = url or database_url()
    engine = create_engine(url, future=True)
    dialect = engine.dialect.name
    if dialect not in {'postgresql', 'sqlite'}:
        raise RuntimeError(f'Unsupported database dialect: {dialect}')

    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table('user_tournament'):
            raise RuntimeError('user_tournament table is missing; initialize the application schema first.')

        id_definition = 'SERIAL PRIMARY KEY' if dialect == 'postgresql' else 'INTEGER PRIMARY KEY'
        connection.execute(text(
            'CREATE TABLE IF NOT EXISTS rate_limit_bucket ('
            f'id {id_definition}, '
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
            if dialect == 'postgresql':
                connection.execute(text(
                    f'ALTER TABLE user_tournament ADD CONSTRAINT {CONSTRAINT_NAME} '
                    'UNIQUE (user_id, tournament_id)'
                ))
            else:
                connection.execute(text(
                    f'CREATE UNIQUE INDEX IF NOT EXISTS {CONSTRAINT_NAME} '
                    'ON user_tournament (user_id, tournament_id)'
                ))

    print('Database schema check completed successfully.')


if __name__ == '__main__':
    try:
        migrate()
    except Exception as error:
        print(f'Database migration stopped: {error}', file=sys.stderr)
        raise SystemExit(1)
