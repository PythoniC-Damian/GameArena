"""Notification grouping metadata."""
from alembic import op
revision='20261102_social_notifications'
down_revision='20261029_settings_security'
branch_labels=None
depends_on=None
def upgrade():
    op.execute('ALTER TABLE notification ADD COLUMN IF NOT EXISTS kind VARCHAR(20)')
    op.execute('ALTER TABLE notification ADD COLUMN IF NOT EXISTS sender_id INTEGER')
def downgrade():
    raise RuntimeError('Preserve notification records; use a forward migration.')
