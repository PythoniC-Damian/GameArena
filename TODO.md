# TODO — Fix Production Login + Migrate Data to Render Postgres

## Goal
Get the admin AND all existing users able to log in on the live Render site
(https://gamearena-p8en.onrender.com) by migrating local SQLite data to Render's
Postgres DB and providing the admin env vars to Render.

## Steps
- [x] 1. Edit `render.yaml` to add `ADMIN_EMAIL` and `ADMIN_PASSWORD` env vars
- [x] 2. Create `migrate_to_postgres.py` migration script (reads local SQLite, inserts into Postgres)
- [x] 3. Fix `app.py` admin bootstrap to avoid UNIQUE username crash on Postgres
- [ ] 4. User runs the migration locally with their private Postgres URL
- [ ] 5. User sets `ADMIN_EMAIL` and `ADMIN_PASSWORD` in Render dashboard
- [ ] 6. Redeploy on Render + push render.yaml/app.py changes
- [ ] 7. Verify login for admin and existing users on the live site

## Notes
- Migration script must NOT store or log the database URL.
- `.env` and `*.db` are already gitignored — secrets stay local.

