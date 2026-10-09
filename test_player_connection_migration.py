import os
from alembic import command
from alembic.config import Config
from app import app, db, DirectMessage, PlayerConnection
from test_interface_contracts import player


def test_existing_conversations_preserve_history_and_require_consent(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['GAMEARENA_TEST_DATABASE_URL'])
    monkeypatch.delenv('MIGRATION_DATABASE_URL',raising=False)
    with app.app_context():
        first,second=player('legacy_first'),player('legacy_second')
        db.session.add_all([DirectMessage(sender_id=second.id,recipient_id=first.id,message='Original introduction'),
                            DirectMessage(sender_id=first.id,recipient_id=second.id,message='Old reply')]);db.session.commit()
        config=Config('alembic.ini')
        command.stamp(config,'20261006_supabase_auth')
        command.upgrade(config,'head')
        db.session.expire_all()
        connection=PlayerConnection.query.one()
        assert connection.requester_id==second.id and connection.status=='pending' and connection.intro_used
        assert DirectMessage.query.count()==2
        connection.status='accepted';db.session.commit()
        command.upgrade(config,'head')
        db.session.expire_all()
        assert PlayerConnection.query.one().status=='accepted'
