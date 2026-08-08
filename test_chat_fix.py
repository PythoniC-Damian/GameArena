import sys, os
sys.path.insert(0, os.getcwd())
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(os.getcwd(), 'instance', 'database.db')

from app import app, db, GlobalChatMessage, User
from sqlalchemy import func

with app.app_context():
    messages = GlobalChatMessage.query.order_by(GlobalChatMessage.created_at.asc()).limit(50).all()

    distinct_user_ids = [
        row[0] for row in db.session.query(
            func.max(GlobalChatMessage.created_at).label('last_seen'),
            GlobalChatMessage.user_id,
        )
        .group_by(GlobalChatMessage.user_id)
        .order_by(func.max(GlobalChatMessage.created_at).desc())
        .limit(10).all()
    ]
    chat_partners = []
    if distinct_user_ids:
        partners = User.query.filter(User.id.in_(distinct_user_ids)).all()
        partner_map = {u.id: u for u in partners}
        chat_partners = [partner_map[uid] for uid in distinct_user_ids if uid in partner_map]

    print('messages:', len(messages))
    print('distinct ids:', distinct_user_ids)
    print('chat_partners:', [p.username for p in chat_partners])
    print('OK: chat query works')
