"""Private daily player activity for the administrator's 30-day metrics."""
from alembic import op
import sqlalchemy as sa
from gamearena.database_security import secure_backend_tables
revision = '20261012_user_activity'
down_revision = '20261012_backend_rls'
branch_labels = None
depends_on = None


def upgrade():
    if 'user_activity_day' not in sa.inspect(op.get_bind()).get_table_names(schema='public'):
        op.create_table('user_activity_day',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('activity_date', sa.Date(), primary_key=True))
        op.create_index('ix_user_activity_day_date', 'user_activity_day', ['activity_date', 'user_id'])
    secure_backend_tables(op.get_bind())


def downgrade():
    raise RuntimeError('Preserve historical activity; plan any retention changes explicitly.')
