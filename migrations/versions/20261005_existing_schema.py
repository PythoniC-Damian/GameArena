"""Verified baseline of the existing additive migration history."""
from alembic import op
from sqlalchemy import inspect, text
revision = '20261005_existing_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    from db_migrate import MIGRATIONS
    connection = op.get_bind()
    if not inspect(connection).has_table('schema_migration'):
        raise RuntimeError('Run db_migrate.py before baselining the existing schema.')
    applied = {row[0] for row in connection.execute(text('SELECT migration_id FROM schema_migration'))}
    if {item[0] for item in MIGRATIONS} - applied:
        raise RuntimeError('Existing schema migrations are incomplete; refusing to baseline.')
    # This baseline records provenance only. It changes no business tables.


def downgrade():
    raise RuntimeError('Baseline downgrade is disabled; existing business tables must be preserved.')
