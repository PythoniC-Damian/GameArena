# GameArena

GameArena is a Flask-based gaming tournament platform I'm currently building.

The idea is to give gamers a place to join and compete in tournaments for games such as eFootball, COD, Free Fire, PUBG, Blood Strike, and others.

# Current Features

 User registration and login
 Gaming tournaments
 Tournament registration
 Entry fees and prize pools
 User profiles
 Wallet system
 Real-time chat and notifications
 Payment integration
 Tournament participant tracking

# Tech Stack

 Python
 Flask
 Flask-SQLAlchemy
 Flask-SocketIO
 HTML
 CSS
 JavaScript
 Tailwind CSS
 PostgreSQL / SQLite
 Gunicorn

# Running Locally

Create and activate a virtual environment, install the required packages, and run:

```powershell
$env:FLASK_DEBUG = "true"
python app.py
```

The app should then be available locally through the address shown in the terminal.

# Production

The application is set up to run with Gunicorn and Flask-SocketIO.

The current `Procfile` uses:

```text
web: gunicorn app:app --worker-class gevent -w 1 --timeout 120 --bind 0.0.0.0:$PORT
```

The Gevent worker is used for the real-time features such as chat and notifications.

# Deployment

The project includes a `render.yaml` file for deployment on Render.

For deployment, the required environment variables include:

 `SECRET_KEY`
 `PAYSTACK_SECRET_KEY`
 `PAYSTACK_PUBLIC_KEY`
 `RESEND_API_KEY`
 `GOOGLE_CLIENT_ID`
 `GOOGLE_CLIENT_SECRET`
 `GOOGLE_REDIRECT_URI`
 `DATABASE_URL`

Sensitive keys and `.env` files should not be committed to the repository.

## Project Status

GameArena is still under development. I'm continuing to work on the tournament system, payments, real-time features, user experience, and deployment.

## Git

To push the project to GitHub:

```powershell
git add .
git commit -m "Update GameArena"
git push
```
