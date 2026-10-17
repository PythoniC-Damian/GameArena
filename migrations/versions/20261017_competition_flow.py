"""Checked-in brackets, private match preparation and player evidence."""
from alembic import op
from gamearena.database_security import secure_backend_tables
revision='20261017_competition_flow'
down_revision='20261017_tournament_artwork'
branch_labels=None
depends_on=None


def upgrade():
    from gamearena.models import TournamentCompetition, TournamentCheckIn, MatchLobby, MatchEvidence
    for model in (TournamentCompetition,TournamentCheckIn,MatchLobby,MatchEvidence):
        model.__table__.create(op.get_bind(),checkfirst=True)
    op.execute('ALTER TABLE match_evidence DROP CONSTRAINT IF EXISTS uq_match_evidence_player')
    secure_backend_tables(op.get_bind(),tables=('tournament_competition','tournament_check_in','match_lobby','match_evidence'))


def downgrade():
    raise RuntimeError('Retain match evidence and competition records during rollback.')
