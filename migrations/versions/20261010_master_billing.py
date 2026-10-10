"""Separate recurring membership ledger; no wallet changes."""
from alembic import op
import sqlalchemy as sa
revision='20261010_master_billing'
down_revision='20261010_master_membership'
branch_labels=None
depends_on=None

def upgrade():
    tables=sa.inspect(op.get_bind()).get_table_names()
    if 'master_subscription' not in tables:
        op.create_table('master_subscription',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('user_id',sa.Integer(),sa.ForeignKey('user.id'),nullable=False),sa.Column('plan_code',sa.String(80),nullable=False),sa.Column('billing_email',sa.String(150),nullable=False),sa.Column('subscription_code',sa.String(80),unique=True),sa.Column('customer_code',sa.String(80)),sa.Column('email_token',sa.String(150)),sa.Column('status',sa.String(30),nullable=False,server_default='pending'),sa.Column('next_payment_at',sa.DateTime()),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.now()))
        op.create_index('ix_master_subscription_user_id','master_subscription',['user_id'])
    if 'master_payment' not in tables:
        op.create_table('master_payment',sa.Column('reference',sa.String(100),primary_key=True),sa.Column('subscription_id',sa.Integer(),sa.ForeignKey('master_subscription.id'),nullable=False),sa.Column('status',sa.String(20),nullable=False,server_default='pending'),sa.Column('checkout_url',sa.String(500)),sa.Column('paid_at',sa.DateTime()),sa.Column('period_end',sa.DateTime()),sa.Column('created_at',sa.DateTime(),nullable=False,server_default=sa.func.now()))

def downgrade():
    raise RuntimeError('Preserve billing records; use a planned migration.')
