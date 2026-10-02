"""Start a local UI fixture with an explicitly isolated PostgreSQL database.

Set GAMEARENA_PREVIEW_DATABASE_URL to a loopback PostgreSQL database whose
name ends in _preview. This script cannot connect to a remote production DB.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
database = os.environ.get('GAMEARENA_PREVIEW_DATABASE_URL', '')
parsed = urlparse(database)
if parsed.scheme not in {'postgresql', 'postgres'} or parsed.hostname not in {'localhost', '127.0.0.1'} or not parsed.path.endswith('_preview'):
    raise SystemExit('Use an explicit loopback PostgreSQL database ending in _preview.')
os.environ.update(GAMEARENA_TESTING='1', DATABASE_URL=database, GAMEARENA_SCHEMA_BOOTSTRAP='1', SECRET_KEY='isolated-ui-preview-only')
for key in ('ADMIN_EMAIL', 'ADMIN_PASSWORD', 'PAYSTACK_SECRET_KEY', 'PAYSTACK_PUBLIC_KEY', 'RESEND_API_KEY', 'SMTP_SERVER', 'SMTP_USERNAME', 'SMTP_PASSWORD'):
    os.environ.pop(key, None)
from app import app, db, socketio, User, Tournament, TournamentStat, UserTournament, TournamentMatch, Notification, GlobalChatMessage, UserSettings
from werkzeug.security import generate_password_hash

with app.app_context():
    if not User.query.filter_by(username='arena_preview').first():
        viewer = User(username='arena_preview', email='preview@example.com', password=generate_password_hash('Preview-Only-42!'), email_verified=True, wallet_balance=4200, bio='Mobile esports player. Ready for the next match.')
        rival = User(username='rival_preview', email='rival@example.com', password=generate_password_hash('Preview-Only-42!'), email_verified=True)
        admin = User(username='admin_preview', email='admin@example.com', password=generate_password_hash('Preview-Only-42!'), email_verified=True, is_admin=True)
        db.session.add_all([viewer, rival, admin]); db.session.flush()
        db.session.add(UserSettings(user_id=viewer.id, preferred_games=['PUBG Mobile']))
        games = ['Free Fire', 'PUBG Mobile', 'eFootball', 'Call of Duty Mobile']
        events = []
        for index, game in enumerate(games):
            event = Tournament(name=f'{game} Preview Cup', game=game, entry_fee=1000 if index else 0, prize=10000, max_participants=16, status='open', match_time=datetime.utcnow()+timedelta(days=index+1), description='Isolated preview fixture for layout and interaction checks.')
            db.session.add(event); events.append(event)
        db.session.flush()
        event = events[0]
        db.session.add(UserTournament(user_id=viewer.id, tournament_id=event.id, payment_status='free', amount_paid=0))
        db.session.add(TournamentStat(user_id=viewer.id, tournament_id=event.id, rank=1, wins=3, points=90))
        db.session.add(TournamentStat(user_id=rival.id, tournament_id=event.id, rank=2, wins=2, points=65))
        db.session.add(TournamentMatch(tournament_id=event.id, player_one_user_id=viewer.id, player_two_user_id=rival.id, status='scheduled'))
        db.session.add(Notification(user_id=viewer.id, message='Your next tournament is ready. Check your match schedule.', category='match', target_url=f'/tournament/{event.id}'))
        db.session.add(GlobalChatMessage(user_id=rival.id, message='Good luck in the arena. Who is playing today?'))
        db.session.commit()
app.config['TESTING'] = False
app.jinja_env.auto_reload = True
socketio.run(app, host='127.0.0.1', port=5057, debug=False, use_reloader=False)
