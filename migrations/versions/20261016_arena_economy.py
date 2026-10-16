"""Separate credits, cosmetic ownership, organizer drafts and saved language."""
from alembic import op
from sqlalchemy import text
from gamearena.database_security import secure_backend_tables
revision = '20261016_arena_economy'
down_revision = '20261012_user_activity'
branch_labels = None
depends_on = None

def upgrade():
    connection = op.get_bind()
    for statement in (
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS wallet_winnings_balance INTEGER NOT NULL DEFAULT 0',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS wallet_bonus_balance INTEGER NOT NULL DEFAULT 0',
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS cosmetic_frame VARCHAR(40)',
        "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language VARCHAR(8) NOT NULL DEFAULT 'en'",
        'ALTER TABLE wallet_transaction ADD COLUMN IF NOT EXISTS winnings_spent INTEGER NOT NULL DEFAULT 0',
        'ALTER TABLE wallet_transaction ADD COLUMN IF NOT EXISTS bonus_spent INTEGER NOT NULL DEFAULT 0',
    ):
        connection.execute(text(statement))
    from gamearena.models import CosmeticOwnership, OrganizerDraft
    for model in (CosmeticOwnership, OrganizerDraft):
        model.__table__.create(connection, checkfirst=True)
    secure_backend_tables(connection)

def downgrade():
    raise RuntimeError('Financial balances and owned items require an explicit recovery plan.')
