"""Exercise real PostgreSQL grants, RLS and migration defaults in isolated tests."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app import app, db
from gamearena.database_security import BACKEND_TABLES, secure_backend_tables


def test_backend_security_denies_clients_preserves_owner_and_defaults():
    with app.app_context(), db.engine.connect() as connection:
        transaction = connection.begin()
        try:
            for role in ('anon', 'authenticated'):
                if not connection.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'), {'role': role}).scalar():
                    connection.execute(text(f'CREATE ROLE {role} NOLOGIN'))
            connection.execute(text('GRANT USAGE ON SCHEMA public TO anon, authenticated'))
            connection.execute(text('GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, PUBLIC'))
            connection.execute(text('GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, PUBLIC'))
            connection.execute(text('GRANT SELECT (username) ON public."user" TO anon'))
            connection.execute(text('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated'))
            connection.execute(text('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated'))
            secured = secure_backend_tables(connection)
            assert 'user' in secured and 'wallet_transaction' in secured
            assert secure_backend_tables(connection) == secured
            for table in secured:
                assert connection.execute(text('SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(:name)'), {'name': 'public.' + '"' + table + '"'}).scalar()
                for role in ('anon', 'authenticated'):
                    assert not connection.execute(text("SELECT has_table_privilege(:role,:name,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"), {'role': role, 'name': 'public.' + '"' + table + '"'}).scalar()
            for role in ('anon', 'authenticated'):
                connection.execute(text(f'SET LOCAL ROLE {role}'))
                for sql in (
                    'SELECT username FROM public."user" LIMIT 0',
                    'INSERT INTO public."user" (id) VALUES (-2147483647)',
                    'UPDATE public."user" SET username=username WHERE false',
                    'DELETE FROM public."user" WHERE false',
                    "SELECT nextval('public.user_id_seq')",
                ):
                    with connection.begin_nested() as savepoint:
                        with pytest.raises(DBAPIError) as failure:
                            connection.execute(text(sql))
                        assert failure.value.orig.pgcode == '42501'
                        savepoint.rollback()
                connection.execute(text('RESET ROLE'))
            # Owner can still run queries and reversible writes after RLS.
            connection.execute(text('SELECT id FROM public."user" LIMIT 0'))
            connection.execute(text('UPDATE public."user" SET username=username WHERE false'))
            connection.execute(text('CREATE TABLE public.security_default_probe (id SERIAL PRIMARY KEY)'))
            for role in ('anon', 'authenticated'):
                assert not connection.execute(text("SELECT has_table_privilege(:role, 'public.security_default_probe', 'SELECT,INSERT,UPDATE,DELETE')"), {'role': role}).scalar()
                assert not connection.execute(text("SELECT has_sequence_privilege(:role, 'public.security_default_probe_id_seq', 'USAGE,SELECT,UPDATE')"), {'role': role}).scalar()
        finally:
            transaction.rollback()
