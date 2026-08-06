import sys
import os
sys.path.append(os.path.dirname(__file__))

from app import app, db, Tournament

with app.app_context():
    try:
        tournaments = Tournament.query.all()
        print(f'Found {len(tournaments)} tournaments:')
        for t in tournaments:
            print(f'  - {t.name} ({t.game}) - Fee: ${t.entry_fee}')
    except Exception as e:
        print(f'Error: {e}')