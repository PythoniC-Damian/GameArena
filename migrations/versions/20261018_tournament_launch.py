"""Reviewed event information and minimal signed-in tournament funnel."""
from alembic import op
from gamearena.database_security import secure_backend_tables

revision = '20261018_tournament_launch'
down_revision = '20261017_competition_flow'
branch_labels = None
depends_on = None


def upgrade():
    from gamearena.models import TournamentLaunchPlan, TournamentVisit
    for model in (TournamentLaunchPlan, TournamentVisit):
        model.__table__.create(op.get_bind(), checkfirst=True)
    secure_backend_tables(op.get_bind(), tables=('tournament_launch_plan', 'tournament_visit'))


def downgrade():
    raise RuntimeError('Retain launch acknowledgements and tournament records during rollback.')
