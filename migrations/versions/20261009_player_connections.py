"""Add explicit player consent and preserve existing message history."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_player_connections'
down_revision = '20261006_supabase_auth'
branch_labels = None
depends_on = None


def upgrade():
    from gamearena.models import PlayerConnection
    PlayerConnection.__table__.create(op.get_bind(), checkfirst=True)
    # Old conversations retain their messages, but require explicit acceptance.
    op.execute(sa.text('''
        INSERT INTO player_connection (low_id, high_id, requester_id, status, intro_used, created_at)
        SELECT DISTINCT ON (LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id))
            LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id), sender_id,
            'pending', TRUE, created_at
        FROM direct_message WHERE sender_id <> recipient_id
        ORDER BY LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id), id
        ON CONFLICT (low_id, high_id) DO NOTHING
    '''))


def downgrade():
    raise RuntimeError('Player consent records must be preserved.')
