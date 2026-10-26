"""Declined requests can be retried after a bounded cooldown."""
from alembic import op
revision = '20261026_friend_retry'
down_revision = '20261026_chat_mentions'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE player_connection ADD COLUMN IF NOT EXISTS request_retry_at TIMESTAMP')
    # Historical declines have no reliable decline timestamp. Start their one-time
    # cooldown at migration time instead of leaving them permanently unavailable.
    op.execute("UPDATE player_connection SET request_retry_at=(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')+INTERVAL '24 hours' WHERE status='declined' AND request_retry_at IS NULL")


def downgrade():
    raise RuntimeError('Preserve request cooldowns and player consent history.')
