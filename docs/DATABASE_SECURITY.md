# Database access

GameArena authorizes application requests in Flask on Render and connects directly
as its trusted PostgreSQL backend role. The browser does not query public tables
through Supabase REST. Supabase Auth and Storage keep their separate permissions.

Migration `20261012_backend_rls` enables RLS on the explicitly listed application
and migration tables (26 at the initial live fix, plus daily activity after its migration), without browser policies. It revokes PUBLIC, anon and
authenticated table, explicit column and owned sequence privileges. Existing
backend-owner and service_role access is preserved. It does not force RLS on the
owner or change, delete or merge business records.

The connected migration owner's public-schema default table and sequence grants
are also restricted so future tables are not exposed automatically. Other object
creators still need their own explicit secure migrations. New tables must enable
RLS and define their intended grants before deployment; no permissive catch-all
policies should be added merely to silence Advisor warnings.

Apply through `python scripts/migrate.py`. The current live database can receive
this permission-only change independently of an application deployment. Test
client denial and backend access before committing the database transaction.
Security changes deliberately have no automatic downgrade that re-exposes data.
