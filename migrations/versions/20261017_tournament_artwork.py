"""Durable, server-authorized tournament carousel artwork."""
from alembic import op
from gamearena.database_security import secure_backend_tables
revision = '20261017_tournament_artwork'
down_revision = '20261016_organizer_finance'
branch_labels = None
depends_on = None


def upgrade():
    from gamearena.models import TournamentArtwork
    TournamentArtwork.__table__.create(op.get_bind(), checkfirst=True)
    secure_backend_tables(op.get_bind(), tables=('tournament_artwork',))


def downgrade():
    raise RuntimeError('Preserve published tournament artwork during rollback.')
