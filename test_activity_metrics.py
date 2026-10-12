from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from app import app, db
from gamearena.activity import activity_report
from gamearena.models import UserActivityDay, DirectMessage, GlobalChatMessage, UserTournament
from test_interface_contracts import player, client, event


def test_distinct_activity_and_lagos_boundaries():
    with app.app_context():
        one, two, recipient, admin = [player(name) for name in ('active_one','active_two','recipient_only','activity_admin')]
        admin.is_admin = True
        now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        today = now.date()
        db.session.add_all([
            UserActivityDay(user_id=one.id, activity_date=today),
            UserActivityDay(user_id=admin.id, activity_date=today),
            DirectMessage(sender_id=one.id, recipient_id=recipient.id, message='Hi', created_at=datetime(2026,10,11,23,30)),
            GlobalChatMessage(user_id=one.id, message='Again', created_at=datetime(2026,10,12,1)),
            GlobalChatMessage(user_id=two.id, message='Earlier', created_at=datetime(2026,9,13,0)),
            GlobalChatMessage(user_id=recipient.id, message='Too old', created_at=datetime(2026,9,12,22,59)),
            GlobalChatMessage(user_id=recipient.id, message='Future', created_at=datetime(2026,10,12,23,1)),
        ])
        db.session.commit()
        report = activity_report(now)
        assert report['total']==3 and report['active_30']==2
        assert report['active_today']==1 and report['active_7']==1
        assert len(report['days'])==30 and report['days'][-1]['count']==1
        assert report['players'][0][1]=='active_one' and report['players'][0][3]==1


def test_visits_count_once_but_polling_and_admins_do_not():
    with app.app_context():
        owner, admin = player('visiting_player'), player('visiting_admin')
        admin.is_admin=True;db.session.commit()
        browser=client(owner)
        browser.get('/notifications/count')
        assert UserActivityDay.query.count()==0
        for _ in range(2):
            assert browser.get('/tournaments',headers={'Accept':'text/html'}).status_code==200
        assert UserActivityDay.query.count()==1
        assert client(admin).get('/admin/activity').status_code==200
        assert UserActivityDay.query.count()==1
        assert client(owner).get('/admin/activity').status_code==403
        assert app.test_client().get('/admin/activity').status_code==302


def test_report_includes_entries_and_has_safe_empty_state():
    with app.app_context():
        owner, admin = player('entry_player'), player('entry_admin')
        admin.is_admin=True
        tournament=event()
        db.session.add(UserTournament(user_id=owner.id,tournament_id=tournament.id,payment_status='pending',joined_at=datetime.utcnow()))
        db.session.commit()
        report=activity_report()
        assert report['active_30']==1
        page=client(admin).get('/admin/activity')
        assert page.status_code==200
        assert 'entry_player' in page.text and 'Earlier days include messages' in page.text
        assert '/players/' in page.text
        assert 'recipient_only' not in page.text


def test_new_activity_table_is_private_after_migration():
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with app.app_context(), db.engine.connect() as connection:
        transaction=connection.begin()
        try:
            revision=importlib.import_module('migrations.versions.20261012_user_activity')
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade();revision.upgrade()
            assert connection.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid='public.user_activity_day'::regclass")).scalar()
        finally:
            transaction.rollback()
