"""Saved wallet display denomination."""
from alembic import op
revision='20261016_wallet_currency'
down_revision='20261016_arena_economy'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS display_currency VARCHAR(3) NOT NULL DEFAULT 'GP'")

def downgrade():
    raise RuntimeError('Preserve saved currency preferences during rollback.')
