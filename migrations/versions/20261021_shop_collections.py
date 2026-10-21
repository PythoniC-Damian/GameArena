"""Add independent equipped card and nameplate slots; retain existing ownership."""
from alembic import op
revision = '20261021_shop_collections'
down_revision = '20261019_account_security'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS cosmetic_card VARCHAR(40)')
    op.execute('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS cosmetic_nameplate VARCHAR(40)')


def downgrade():
    raise RuntimeError('Keep purchased cosmetic slots and ownership during rollback.')
