"""Keep messaging open between accounts present at rollout."""
from alembic import op
import sqlalchemy as sa

revision = '20261009_legacy_messaging'
down_revision = '20261009_player_connections'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'requires_player_consent' not in {c['name'] for c in sa.inspect(bind).get_columns('user')}:
        # Existing rows receive false; subsequent inserts receive true. PostgreSQL
        # runs this migration transactionally, so registration cannot slip between.
        op.add_column('user', sa.Column('requires_player_consent', sa.Boolean(), nullable=False, server_default=sa.false()))
        op.alter_column('user', 'requires_player_consent', server_default=sa.true())
    op.execute(sa.text('''UPDATE player_connection AS connection SET status = 'accepted'
        FROM "user" AS low_user, "user" AS high_user
        WHERE low_user.id = connection.low_id AND high_user.id = connection.high_id
          AND NOT low_user.requires_player_consent AND NOT high_user.requires_player_consent'''))


def downgrade():
    raise RuntimeError('The messaging rollout boundary must be preserved.')
