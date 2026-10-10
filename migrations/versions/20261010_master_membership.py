"""Master entitlement, cosmetics and saved tournament reminders."""
from alembic import op
import sqlalchemy as sa
revision = '20261010_master_membership'
down_revision = '20261009_legacy_messaging'
branch_labels = None
depends_on = None

def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('user')}
    for column in [sa.Column('master_expires_at', sa.DateTime()), sa.Column('master_frame', sa.String(20), nullable=False, server_default='blue'), sa.Column('master_profile_theme', sa.String(20), nullable=False, server_default='arena')]:
        if column.name not in columns: op.add_column('user', column)
    if 'saved_tournament' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table('saved_tournament', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False), sa.Column('tournament_id', sa.Integer(), sa.ForeignKey('tournament.id'), nullable=False), sa.Column('reminder_enabled', sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column('reminded_for', sa.DateTime()), sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint('user_id', 'tournament_id', name='unique_saved_tournament'))

def downgrade():
    raise RuntimeError('Preserve membership and saved-event data; restore through a planned migration.')
