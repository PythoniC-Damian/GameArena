"""Distinguish owner-approved pay-once passes from recurring memberships."""
from alembic import op
import sqlalchemy as sa
revision = '20261012_master_one_time'
down_revision = '20261010_master_billing'
branch_labels = None
depends_on = None

def upgrade():
    if 'billing_mode' not in {column['name'] for column in sa.inspect(op.get_bind()).get_columns('master_subscription')}:
        op.add_column('master_subscription', sa.Column('billing_mode', sa.String(20), nullable=False, server_default='recurring'))

def downgrade():
    raise RuntimeError('Preserve payment-mode records; use a planned migration.')
