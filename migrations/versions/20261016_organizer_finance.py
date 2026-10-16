"""Funded organiser events and explicit wallet withdrawal sources."""
from alembic import op
from gamearena.database_security import secure_backend_tables
revision='20261016_organizer_finance'
down_revision='20261016_wallet_currency'
branch_labels=None
depends_on=None

def upgrade():
    op.execute("ALTER TABLE organizer_draft ADD COLUMN IF NOT EXISTS agreement_version VARCHAR(40)")
    op.execute("ALTER TABLE organizer_draft ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMP")
    op.execute("ALTER TABLE wallet_transaction ADD COLUMN IF NOT EXISTS wallet_source VARCHAR(12) NOT NULL DEFAULT 'combined'")
    from gamearena.models import OrganizerProfile, OrganizerFinance
    for model in (OrganizerProfile, OrganizerFinance):
        model.__table__.create(op.get_bind(), checkfirst=True)
    op.execute('CREATE INDEX IF NOT EXISTS ix_organizer_draft_owner_status ON organizer_draft (owner_id, status)')
    # Existing backend tables were secured by earlier revisions. Re-locking all
    # live tables here can deadlock with requests waiting on the wallet ALTER.
    secure_backend_tables(op.get_bind(), tables=('organizer_profile', 'organizer_finance'))

def downgrade():
    raise RuntimeError('Preserve financial records and signed agreements during rollback.')
