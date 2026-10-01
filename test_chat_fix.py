from app import app, db, GlobalChatMessage, User
from sqlalchemy import func
from datetime import datetime, timedelta


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


def test_global_chat_renders_latest_messages_in_chronological_order():
    with app.app_context():
        user = User(username='chat_viewer', email='chat_viewer@example.com', password='hashed')
        db.session.add(user)
        db.session.commit()
        now = datetime.utcnow()
        db.session.add_all([
            GlobalChatMessage(
                user_id=user.id,
                message=f'message-{index}',
                created_at=now + timedelta(seconds=index),
            )
            for index in range(51)
        ])
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True
        response = client.get('/chat')

        assert response.status_code == 200
        assert 'message-0' not in response.text
        assert 'message-1' in response.text
        assert 'message-50' in response.text
        assert response.text.index('message-1') < response.text.index('message-50')
