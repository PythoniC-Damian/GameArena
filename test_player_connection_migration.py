import os
from alembic import command
from alembic.config import Config
from app import app, db, DirectMessage, PlayerConnection, User
from sqlalchemy import text
from test_interface_contracts import player


def test_rollout_preserves_history_and_grandfathers_only_existing_accounts(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['GAMEARENA_TEST_DATABASE_URL'])
    monkeypatch.delenv('MIGRATION_DATABASE_URL',raising=False)
    with app.app_context():
        first,second=player('legacy_first'),player('legacy_second')
        db.session.add_all([DirectMessage(sender_id=second.id,recipient_id=first.id,message='Original introduction'),
                            DirectMessage(sender_id=first.id,recipient_id=second.id,message='Old reply')]);db.session.commit()
        config=Config('alembic.ini')
        command.stamp(config,'20261006_supabase_auth')
        command.upgrade(config,'20261009_player_connections')
        db.session.expire_all()
        connection=PlayerConnection.query.one()
        assert connection.requester_id==second.id and connection.status=='pending' and connection.intro_used
        assert DirectMessage.query.count()==2
        # Recreate the exact pre-rollout schema, rather than a create_all schema.
        db.session.execute(text('ALTER TABLE "user" DROP COLUMN requires_player_consent'));db.session.commit()
        command.upgrade(config,'head')
        db.session.expire_all()
        assert not first.requires_player_consent and not second.requires_player_consent
        assert PlayerConnection.query.one().status=='accepted'
        newcomer=player('after_rollout')
        assert newcomer.requires_player_consent
        # Old application versions that omit the field also get the safe default.
        db.session.execute(text("INSERT INTO \"user\" (username,email,password) VALUES ('raw_new','raw@preview.invalid','hash')"));db.session.commit()
        assert User.query.filter_by(username='raw_new').one().requires_player_consent
        command.upgrade(config,'head')
        db.session.expire_all()
        assert PlayerConnection.query.one().status=='accepted'
        assert newcomer.requires_player_consent
