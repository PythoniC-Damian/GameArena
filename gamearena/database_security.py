"""Server-owned GameArena tables must not be accessible through client API roles."""
from sqlalchemy import text

BACKEND_TABLES = (
    'achievement', 'alembic_version', 'direct_message', 'global_chat_message',
    'master_payment', 'master_subscription', 'notification', 'player_connection',
    'profile_photo', 'push_subscription', 'rate_limit_bucket', 'saved_tournament',
    'schema_migration', 'tournament', 'tournament_chat_message', 'tournament_match',
    'tournament_match_chat_message', 'tournament_match_dispute', 'tournament_stat',
    'user', 'user_achievement', 'user_block', 'user_report', 'user_settings',
    'user_tournament', 'wallet_transaction',
)


def secure_backend_tables(connection):
    """Idempotent permission-only changes; retain owner/server and service access.

    No browser policies are appropriate: Flask authorizes all application queries.
    Auth and Storage schemas are intentionally outside this migration's scope.
    """
    quote = connection.dialect.identifier_preparer.quote_identifier
    roles = connection.execute(text(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')"
    )).scalars().all()
    grantees = ', '.join(['PUBLIC'] + [quote(role) for role in roles])
    existing = set(connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )).scalars())
    secured = []
    for table in BACKEND_TABLES:
        if table not in existing:
            continue
        relation = 'public.' + quote(table)
        connection.execute(text(f'ALTER TABLE {relation} ENABLE ROW LEVEL SECURITY'))
        connection.execute(text(f'REVOKE ALL PRIVILEGES ON TABLE {relation} FROM {grantees}'))
        # Explicit column grants are separate from table grants in PostgreSQL.
        columns = connection.execute(text(
            "SELECT a.attname FROM pg_attribute a "
            "WHERE a.attrelid = to_regclass(:relation) AND a.attnum > 0 "
            "AND NOT a.attisdropped AND a.attacl IS NOT NULL"
        ), {'relation': relation}).scalars().all()
        if columns:
            column_list = ', '.join(quote(column) for column in columns)
            connection.execute(text(
                f'REVOKE ALL PRIVILEGES ({column_list}) ON TABLE {relation} FROM {grantees}'
            ))
        sequences = connection.execute(text(
            "SELECT DISTINCT n.nspname, s.relname FROM pg_class s "
            "JOIN pg_namespace n ON n.oid = s.relnamespace "
            "JOIN pg_depend d ON d.objid = s.oid "
            "WHERE s.relkind = 'S' AND d.refobjid = to_regclass(:relation) "
            "AND d.deptype IN ('a', 'i')"
        ), {'relation': relation}).all()
        for schema, sequence in sequences:
            name = quote(schema) + '.' + quote(sequence)
            connection.execute(text(f'REVOKE ALL PRIVILEGES ON SEQUENCE {name} FROM {grantees}'))
        secured.append(table)
    # Migrations create tables as the connected owner. Supabase's existing
    # per-schema defaults must not silently expose newly created application data.
    for kind in ('TABLES', 'SEQUENCES'):
        connection.execute(text(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
            f'REVOKE ALL PRIVILEGES ON {kind} FROM {grantees}'
        ))
    return secured
