"""Protect server-owned application data from direct Supabase client access."""
from alembic import op
from gamearena.database_security import secure_backend_tables

revision = '20261012_backend_rls'
down_revision = '20261012_master_one_time'
branch_labels = None
depends_on = None


def upgrade():
    secure_backend_tables(op.get_bind())


def downgrade():
    raise RuntimeError('Do not reopen application data; plan explicit API permissions instead.')
