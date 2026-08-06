# GameArena Deployment To Do

## Step 1 — Deployment config fixes (Render + WebSockets)
- [x] 1. Update `Procfile` + `render.yaml` to run via `python app.py` (socketio.run) — avoids gunicorn eventlet worker "class uri invalid" error
- [x] 2. Add `eventlet` to `requirements.txt`
- [x] 3. Add `psycopg2-binary` to `requirements.txt` (Postgres)
- [x] 4. Create `render.yaml` Render Blueprint (web service + free Postgres)
- [x] 4b. Fix `gunicorn==23.2.1` → `23.0.0` (23.2.1 never existed)
- [x] 4c. Pin `requests==2.32.3` (modern, Python 3.12-compatible)
- [x] 4d. Remove `resend==0.3.0` (hard-pinned broken `requests==2.23.0`); replaced SDK with direct Resend REST API call via `requests`
- [x] 4e. Pin Python 3.12 via `runtime.txt` (`python-3.12.0`) + `PYTHON_VERSION` in `render.yaml` (fixes eventlet 0.36.0 crash on Python 3.14)

## Step 2 — Git setup & push to GitHub
- [x] 5. Install GitHub CLI (`gh`) via winget
- [x] 6. Authenticate `gh`
- [x] 7. `git init` + add files + initial commit
- [x] 8. Create `GameArena` repo on GitHub via `gh repo create`
- [x] 9. Push to `main`

## Step 3 — Render deployment
- [ ] 10. Connect repo to Render (Blueprint) with env vars
