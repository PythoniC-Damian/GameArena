"""Enable Master only for the named demo player in a loopback preview database."""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import dotenv_values
root = Path(__file__).resolve().parent.parent
url = dotenv_values(root / '.env').get('DATABASE_URL', '')
parsed = urlparse(url)
if parsed.hostname not in {'localhost', '127.0.0.1'} or not parsed.path.endswith('_preview'):
    raise SystemExit('Master demo setup is restricted to a loopback *_preview database.')
from app import app, db, User, Tournament
if app.config['SESSION_COOKIE_SECURE']: raise SystemExit('Preview is unavailable in production.')
with app.app_context():
    user = User.query.filter_by(email='preview@example.com', username='PreviewPlayer').first()
    if not user: raise SystemExit('Create the isolated PreviewPlayer demo account first.')
    user.master_expires_at = datetime.utcnow()+timedelta(days=30)
    user.master_frame = 'green'
    if not Tournament.query.filter_by(name='Master Preview Cup').first():
        db.session.add(Tournament(name='Master Preview Cup',game='Free Fire',entry_fee=0,prize=0,max_participants=16,status='open',match_time=datetime.utcnow()+timedelta(days=1),description='Local demonstration tournament. No real money or live entry.'))
    db.session.commit()
    print('Master enabled for PreviewPlayer on the isolated local preview database.')
