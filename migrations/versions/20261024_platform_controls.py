"""Admin catalogue settings, support threads and explicit event terms."""
from alembic import op
revision = '20261024_platform_controls'
down_revision = '20261021_shop_collections'
branch_labels = None
depends_on = None


def upgrade():
    for column, definition in [('rules','TEXT'),('eligibility','VARCHAR(1000)'),('event_format',"VARCHAR(40) NOT NULL DEFAULT 'custom'"),('payout_method',"VARCHAR(30) NOT NULL DEFAULT 'unconfirmed'")]:
        op.execute(f'ALTER TABLE tournament ADD COLUMN IF NOT EXISTS {column} {definition}')
    op.execute('ALTER TABLE tournament_artwork ALTER COLUMN draft_id DROP NOT NULL')
    op.execute('''CREATE TABLE IF NOT EXISTS platform_setting (
        key VARCHAR(80) PRIMARY KEY, value JSON NOT NULL, updated_by INTEGER REFERENCES "user"(id), updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    op.execute('''CREATE TABLE IF NOT EXISTS support_reply (
        id SERIAL PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES user_report(id), author_id INTEGER NOT NULL REFERENCES "user"(id),
        message VARCHAR(2000) NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_support_reply_report_id ON support_reply(report_id)')
    op.execute("INSERT INTO platform_setting (key,value) VALUES ('shop_catalog','{}') ON CONFLICT (key) DO NOTHING")
    # Only unused, expired open events. Preserve every event with an entry, payment,
    # drawn match or funded organiser record; those schedules are accepted history.
    op.execute('''UPDATE tournament t SET match_time=NULL
        WHERE t.status='open' AND t.match_time < CURRENT_TIMESTAMP
        AND NOT EXISTS (SELECT 1 FROM user_tournament u WHERE u.tournament_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM tournament_match m WHERE m.tournament_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM organizer_finance f WHERE f.tournament_id=t.id)''')
    op.execute('''UPDATE tournament_competition c SET game_rules=replace(replace(c.game_rules,
        'Start: Tuesday 20 October 2026 at 18:00 WAT (17:00 UTC).',
        'Start time: To be decided; follow the schedule on the event page.'),
        'Player one hosts the private room', 'The assigned host creates the private room')
        FROM tournament t WHERE t.id=c.tournament_id AND t.id=6 AND lower(t.game) LIKE '%efootball%'
        AND t.status='open' AND t.match_time IS NULL
        AND NOT EXISTS (SELECT 1 FROM user_tournament u WHERE u.tournament_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM tournament_match m WHERE m.tournament_id=t.id)''')
    op.execute('''UPDATE tournament t SET rules=c.game_rules,event_format='single_elimination_1v1',payout_method='organizer_bank'
        FROM tournament_competition c WHERE t.id=c.tournament_id AND t.id=6 AND lower(t.game) LIKE '%efootball%'
        AND c.game_rules LIKE '%paid directly by the organiser%'
        AND NOT EXISTS (SELECT 1 FROM user_tournament u WHERE u.tournament_id=t.id)
        AND NOT EXISTS (SELECT 1 FROM tournament_match m WHERE m.tournament_id=t.id)''')
    op.execute("UPDATE tournament t SET payout_method='gp_wallet',rules=COALESCE(t.rules,t.description) WHERE EXISTS (SELECT 1 FROM organizer_finance f WHERE f.tournament_id=t.id)")
    from gamearena.database_security import secure_backend_tables
    secure_backend_tables(op.get_bind(), tables=['platform_setting','support_reply'])


def downgrade():
    raise RuntimeError('Preserve catalogue settings, support history and accepted event terms.')
