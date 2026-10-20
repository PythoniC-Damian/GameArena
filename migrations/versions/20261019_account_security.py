"""Encrypted authenticator factors and redacted security audit events."""
from alembic import op
from gamearena.database_security import secure_backend_tables
revision = '20261019_account_security'
down_revision = '20261018_tournament_launch'
branch_labels = None
depends_on = None


def upgrade():
    from gamearena.models import AccountSecurity, SecurityAuditEvent
    for model in (AccountSecurity, SecurityAuditEvent):
        model.__table__.create(op.get_bind(), checkfirst=True)
    secure_backend_tables(op.get_bind(), tables=('account_security','security_audit_event'))


def downgrade():
    raise RuntimeError('Preserve MFA and audit records during rollback.')
