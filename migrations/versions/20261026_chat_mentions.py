"""Persist only validated individual community-chat mention spans."""
from alembic import op
revision = '20261026_chat_mentions'
down_revision = '20261024_platform_controls'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE global_chat_message ADD COLUMN IF NOT EXISTS mentions JSON NOT NULL DEFAULT '[]'")


def downgrade():
    raise RuntimeError('Keep validated mention metadata with chat history.')
