"""Bound database round trips without caching player data or weakening guards."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import Mock

import app as application
from sqlalchemy import event as sql_event
from app import app, db, Achievement, UserAchievement, Notification, UserSettings
from test_interface_contracts import player, client, event


@contextmanager
def statements():
    queries = []
    engine = db.engine
    def collect(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    sql_event.listen(engine, 'before_cursor_execute', collect)
    try:
        yield queries
    finally:
        sql_event.remove(engine, 'before_cursor_execute', collect)


def definitions(start, stop):
    db.session.add_all([Achievement(key=f'performance_{index}', name=f'Badge {index}',
        description='Join tournaments', rule_type='tournaments', threshold=1)
        for index in range(start, stop)])
    db.session.commit()


def test_profile_calculates_progress_once_and_badges_do_not_add_queries(monkeypatch):
    with app.app_context():
        owner = player('performance_profile')
        db.session.add(UserSettings(user_id=owner.id)); db.session.commit()
        browser = client(owner)
        definitions(0, 4)
        browser.get('/profile')  # First visit creates missing badge records.
        with statements() as small:
            assert browser.get('/profile').status_code == 200
        definitions(4, 32)
        browser.get('/profile')
        progress = Mock(wraps=application.achievement_progress_for_user)
        monkeypatch.setattr(application, 'achievement_progress_for_user', progress)
        with statements() as large:
            assert browser.get('/profile').status_code == 200
        assert progress.call_count == 1
        assert len(large) <= len(small) + 2, (len(small), len(large))
        assert not any(query.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for query in large)
        assert UserAchievement.query.filter_by(user_id=owner.id).count() == 32


def test_common_pages_keep_queries_bounded_with_more_tournaments():
    with app.app_context():
        owner = player('performance_routes')
        db.session.add(UserSettings(user_id=owner.id)); db.session.commit()
        browser = client(owner)
        routes = ('/', '/tournaments', '/leaderboard', '/dashboard', '/wallet',
                  '/settings', '/notifications', '/chat', '/search?q=PUBG')
        event('First Cup')
        small = {}
        for path in routes:
            with statements() as queries:
                response = browser.get(path)
                assert response.status_code == 200, (path, response.status_code)
            small[path] = len(queries)
        for index in range(11):
            tournament = event(f'Cup {index}')
            tournament.match_time = datetime.utcnow() + timedelta(days=1)
        db.session.commit()
        for path in routes:
            with statements() as queries:
                response = browser.get(path)
                assert response.status_code == 200, (path, response.status_code)
            assert len(queries) <= small[path] + 5, (path, small[path], len(queries))


def test_achievement_bulk_awards_still_notify_once():
    with app.app_context():
        owner = player('performance_awards')
        definitions(0, 32)
        # Zero thresholds unlock immediately, exercising batched notifications.
        Achievement.query.update({'threshold': 0}); db.session.commit()
        application.award_achievements_for_user(owner.id)
        application.award_achievements_for_user(owner.id)
        assert UserAchievement.query.filter_by(user_id=owner.id).count() == 32
        assert Notification.query.filter_by(user_id=owner.id, category='achievement').count() == 32
