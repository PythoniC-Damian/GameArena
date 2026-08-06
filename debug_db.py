import sys
import os
sys.path.insert(0, os.getcwd())

from app import app, db, Tournament

with app.app_context():
    try:
        tournaments = Tournament.query.all()
        print(f'Found {len(tournaments)} tournaments')
        for t in tournaments:
            print(f'  {t.name} - {t.game} - Prize: {t.prize}')
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()