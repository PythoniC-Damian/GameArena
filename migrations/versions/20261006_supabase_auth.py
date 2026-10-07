"""Preserve business user IDs while linking managed identities."""
from alembic import op
import sqlalchemy as sa

revision = '20261006_supabase_auth'
down_revision = '20261005_existing_schema'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('user')}
    if 'supabase_auth_id' not in columns:
        op.add_column('user', sa.Column('supabase_auth_id', sa.String(36), nullable=True))
        op.create_unique_constraint('uq_user_supabase_auth_id', 'user', ['supabase_auth_id'])
    if 'auth_session_version' not in columns:
        op.add_column('user', sa.Column('auth_session_version', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    raise RuntimeError('Auth identity removal requires an explicit account rollback plan.')
