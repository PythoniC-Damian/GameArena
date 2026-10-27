"""Keep free waiting-list records separate from tournament entries and money."""
from alembic import op
revision='20261027_waiting_list'
down_revision='20261026_friend_retry'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE IF NOT EXISTS tournament_interest (
        id SERIAL PRIMARY KEY, tournament_id INTEGER NOT NULL REFERENCES tournament(id),
        user_id INTEGER NOT NULL REFERENCES "user"(id), created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
        CONSTRAINT uq_tournament_interest_player UNIQUE(tournament_id,user_id))''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_tournament_interest_tournament_id ON tournament_interest(tournament_id)')
    from gamearena.database_security import secure_backend_tables
    secure_backend_tables(op.get_bind(),tables=['tournament_interest'])


def downgrade():
    raise RuntimeError('Preserve waiting-list signups.')
