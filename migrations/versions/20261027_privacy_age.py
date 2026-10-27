"""Record adult declarations without storing dates of birth."""
from alembic import op
revision='20261027_privacy_age'
down_revision='20261027_waiting_list'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS adult_confirmed_at TIMESTAMP')
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS adult_policy_version VARCHAR(20)')

def downgrade():
    raise RuntimeError('Preserve adult eligibility declaration records.')
