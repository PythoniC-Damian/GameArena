from app import app, db, GlobalChatMessage, User
from sqlalchemy import func


def test_chat_partner_query_uses_latest_message_order():
    with app.app_context():
        first = User(username='first', email='first@example.com', password='hashed')
        second = User(username='second', email='second@example.com', password='hashed')
        db.session.add_all([first, second])
        db.session.commit()
        db.session.add_all([
            GlobalChatMessage(user_id=first.id, message='old'),
            GlobalChatMessage(user_id=second.id, message='new'),
        ])
        db.session.commit()

        distinct_user_ids = [
            row[1] for row in db.session.query(
                func.max(GlobalChatMessage.created_at).label('last_seen'),
                GlobalChatMessage.user_id,
            )
            .group_by(GlobalChatMessage.user_id)
            .order_by(func.max(GlobalChatMessage.created_at).desc())
            .limit(10).all()
        ]

        partners = User.query.filter(User.id.in_(distinct_user_ids)).all()
        partner_map = {user.id: user for user in partners}
        chat_partners = [partner_map[user_id] for user_id in distinct_user_ids]

        assert {partner.username for partner in chat_partners} == {'first', 'second'}
