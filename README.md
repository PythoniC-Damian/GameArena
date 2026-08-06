# GameArena Flask App

This is the GameArena Flask application.

## Deployment Setup

The app is ready for deployment with a production web server.

### Required files
- `requirements.txt`
- `Procfile`
- `app.py`
- `.gitignore`

### `Procfile`

```text
web: gunicorn app:app --worker-class eventlet -w 1 --timeout 120 --bind 0.0.0.0:$PORT
```

> The `eventlet` worker class is **required** for Flask-SocketIO (real-time chat & notifications) to work in production. Do not use the default `gunicorn` worker.

### Local development

Run locally with:

```powershell
$env:FLASK_DEBUG = "true"
python app.py
```

Or use `gunicorn`:

```powershell
gunicorn app:app --worker-class eventlet -w 1 --timeout 120 --bind 0.0.0.0:5000
```

### Render deployment (recommended)

The repo includes a `render.yaml` **Blueprint** that provisions the web service + a free Postgres database automatically.

**Option A — Blueprint (recommended):**
1. Push this repo to GitHub.
2. In the Render dashboard, click **New → Blueprint**.
3. Select the `GameArena` repo. Render reads `render.yaml` and creates the web service + free Postgres.
4. Set the secret env vars (marked `sync: false` in `render.yaml`):
   - `SECRET_KEY`
   - `PAYSTACK_SECRET_KEY`
   - `PAYSTACK_PUBLIC_KEY`
   - `RESEND_API_KEY`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI` (set to `https://<your-app>.onrender.com/auth/google/callback`)
5. `DATABASE_URL` is auto-wired from the provisioned Postgres DB.
6. Deploy and open the public URL.

**Option B — Manual:**
1. Push this repo to GitHub.
2. In Render, create a **New Web Service** and connect the repo.
3. Add a **PostgreSQL** database from the Render dashboard and copy its Internal Database URL.
4. Set the same env vars above, including `DATABASE_URL`.
5. Deploy.

### Git setup

If you have git installed locally, run:

```powershell
git init
git add .
git commit -m "Initial GameArena app"
git remote add origin https://github.com/<yourname>/<repo>.git
git branch -M main
git push -u origin main
```

## Notes

- The app currently uses `gunicorn` for production.
- The Flask `app.run()` block uses `FLASK_DEBUG` and `PORT`.
- Keep `.env` local and do not commit it.
