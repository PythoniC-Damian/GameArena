# TODO — Fix Production Login + Migrate Data to Render Postgres

## PWA Installability (Completed)
- [x] Added `static/manifest.json` (PWA manifest)
- [x] Added `static/sw.js` (service worker for offline + installability)
- [x] Added `static/icons/` (192px, 512px, maskable, apple-touch icons)
- [x] Added `templates/_pwa_meta.html` and `templates/_pwa_register.html` includes
- [x] Added `templates/_pwa_install_button.html` (Install App button)
- [x] Injected PWA meta + SW registration + install button into all templates
- [x] Committed and pushed to main (triggers Render deploy)

## Goal
Get the admin AND all existing users able to log in on the live Render site
(https://gamearena-p8en.onrender.com) by migrating local SQLite data to Render's
Postgres DB and providing the admin env vars to Render.

## Steps
- [x] 1. Edit `render.yaml` to add `ADMIN_EMAIL` and `ADMIN_PASSWORD` env vars
- [x] 2. Create `migrate_to_postgres.py` migration script (reads local SQLite, inserts into Postgres)
- [x] 3. Fix `app.py` admin bootstrap to avoid UNIQUE username crash on Postgres
- [x] 4. Commit and push changes to GitHub (origin/main) - triggers Render auto-deploy
- [x] 5. Admin login works on production (admin env vars set)
- [x] 6. Migration to Postgres completed successfully (all data copied)
- [x] 7. Done: Admin login works on production
- [x] 8. Add Admin Panel link to dashboard navigation (visible to admins)

## Notes
- Migration script must NOT store or log the database URL.
- `.env` and `*.db` are already gitignored — secrets stay local.

