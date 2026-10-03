"""Add/remove six visibly named demo bots only in a loopback *_preview database."""
import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
parser=argparse.ArgumentParser(); parser.add_argument('--remove',action='store_true'); args=parser.parse_args()
database=os.environ.get('GAMEARENA_PREVIEW_DATABASE_URL',''); parsed=urlparse(database)
if parsed.scheme not in {'postgresql','postgres'} or parsed.hostname not in {'127.0.0.1','localhost'} or not parsed.path.endswith('_preview'):
    raise SystemExit('Demo bots require an explicit loopback PostgreSQL *_preview database.')
os.environ.update(GAMEARENA_TESTING='1',DATABASE_URL=database,GAMEARENA_SCHEMA_BOOTSTRAP='1')
for key in ('ADMIN_EMAIL','ADMIN_PASSWORD','PAYSTACK_SECRET_KEY','PAYSTACK_PUBLIC_KEY','VAPID_PRIVATE_KEY','SUPABASE_SERVICE_ROLE_KEY'):
    os.environ[key]=''
from app import app,db,User,UserSettings,Tournament,TournamentStat
names=['demo_bot_Viper','demo_bot_Nova','demo_bot_Blaze','demo_bot_Echo','demo_bot_Ace','demo_bot_Luna']
with app.app_context():
    if args.remove:
        bots=User.query.filter(User.username.in_(names),User.email.like('%@example.invalid')).all()
        ids=[bot.id for bot in bots]
        if ids:
            TournamentStat.query.filter(TournamentStat.user_id.in_(ids)).delete(synchronize_session=False)
            UserSettings.query.filter(UserSettings.user_id.in_(ids)).delete(synchronize_session=False)
            for bot in bots:db.session.delete(bot)
        db.session.commit();print(f'Removed {len(bots)} isolated demo bots and their sample rankings.')
    else:
        tournament=Tournament.query.filter(Tournament.name.like('%Preview Cup')).order_by(Tournament.id).first()
        if not tournament:raise SystemExit('Start scripts/preview_interface.py first to create preview tournaments.')
        for index,name in enumerate(names):
            bot=User.query.filter_by(username=name,email=f'{name}@example.invalid').first()
            if not bot:
                bot=User(username=name,email=f'{name}@example.invalid',password=generate_password_hash(secrets.token_urlsafe(32)),email_verified=True,bio='Demo bot — removable preview data. Not a real competitor.')
                db.session.add(bot);db.session.flush();db.session.add(UserSettings(user_id=bot.id,allow_direct_messages=False))
            if not TournamentStat.query.filter_by(user_id=bot.id,tournament_id=tournament.id).first():
                db.session.add(TournamentStat(user_id=bot.id,tournament_id=tournament.id,rank=index+3,points=60-index*7,wins=max(0,3-index//2),kills=18-index*2))
        db.session.commit();print('Six isolated demo bots and sample rankings are ready; no real users, matches or funds changed.')
