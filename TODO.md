# GameArena Deployment To Do

## Step 1 — Deployment config fixes (Render + WebSockets)
- [x] 1. Update `Procfile` to use eventlet worker for Flask-SocketIO
- [x] 2. Add `eventlet` to `requirements.txt`
- [x] 3. Add `psycopg2-binary` to `requirements.txt` (Postgres)
- [x] 4. Create `render.yaml` Render Blueprint (web service + free Postgres)

## Step 2 — Git setup & push to GitHub
- [x] 5. Install GitHub CLI (`gh`) via winget
- [x] 6. Authenticate `gh`
- [x] 7. `git init` + add files + initial commit
- [x] 8. Create `GameArena` repo on GitHub via `gh repo create`
- [x] 9. Push to `main`

## Step 3 — Render deployment
- [ ] 10. Connect repo to Render (Blueprint) with env vars
