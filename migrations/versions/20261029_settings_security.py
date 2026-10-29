"""Optional email second step and separate private/group notification choices."""
from alembic import op
revision='20261029_settings_security'
down_revision='20261027_privacy_age'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('ALTER TABLE account_security ADD COLUMN IF NOT EXISTS email_enabled_at TIMESTAMP')
    op.execute('ALTER TABLE account_security ADD COLUMN IF NOT EXISTS email_version INTEGER NOT NULL DEFAULT 0')
    op.execute('ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS private_chat_notifications BOOLEAN NOT NULL DEFAULT TRUE')
    op.execute('ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS group_chat_notifications BOOLEAN NOT NULL DEFAULT TRUE')
    op.execute('''CREATE TABLE IF NOT EXISTS email_login_challenge (
        id VARCHAR(48) PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        purpose VARCHAR(12) NOT NULL,code_hash VARCHAR(64) NOT NULL,issued_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
        expires_at TIMESTAMP NOT NULL,used_at TIMESTAMP,attempts INTEGER NOT NULL DEFAULT 0,
        factor_version INTEGER NOT NULL,auth_version INTEGER NOT NULL)''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_email_login_challenge_user_id ON email_login_challenge(user_id)')
    from gamearena.database_security import secure_backend_tables
    secure_backend_tables(op.get_bind(),tables=['email_login_challenge'])

def downgrade():
    raise RuntimeError('Preserve security and notification choices.')
