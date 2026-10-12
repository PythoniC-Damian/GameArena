import hashlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from flask import g
from app import app, db, socketio, Notification, PushSubscription, UserSettings
from gamearena.models import UserActivityDay
from gamearena.activity import notify_activity_changed
from test_interface_contracts import player, client, token


def test_activity_updates_reach_only_admins_after_committed_visit():
    with app.app_context():
        admin, visitor = player('live_admin'), player('live_visitor')
        admin.is_admin=True;db.session.commit()
        g.pop('_login_user',None)
        admin_socket=socketio.test_client(app,flask_test_client=client(admin))
        g.pop('_login_user',None)
        visitor_socket=socketio.test_client(app,flask_test_client=client(visitor))
        admin_socket.get_received();visitor_socket.get_received()
        response=client(visitor).get('/tournaments',headers={'Accept':'text/html'})
        assert response.status_code==200 and UserActivityDay.query.count()==1
        assert any(event['name']=='activity_updated' for event in admin_socket.get_received())
        assert not any(event['name']=='activity_updated' for event in visitor_socket.get_received())
        page=client(admin).get('/admin/activity/live')
        assert page.status_code==200 and 'Live' not in page.json.get('error','')
        assert 'live_visitor' in page.json['html'] and 'no-store' in page.headers['Cache-Control']
        assert client(visitor).get('/admin/activity/live').status_code==403
        admin_socket.disconnect();visitor_socket.disconnect()


def test_live_search_has_avatars_and_obeys_profile_privacy():
    with app.app_context():
        public, private, suspended = [player(name) for name in ('KingPublic','KingPrivate','KingSuspended')]
        public.avatar_url='/static/icons/icon-192.png'
        suspended.suspended=True
        db.session.add(UserSettings(user_id=private.id,profile_public=False));db.session.commit()
        result=app.test_client().get('/search?q=ki&live=1')
        assert result.status_code==200
        html=result.json['html']
        assert 'KingPublic' in html and '<img' in html
        assert 'KingPrivate' not in html and 'KingSuspended' not in html
        assert public.email not in html and 'no-store' in result.headers['Cache-Control']
        assert '<img' in app.test_client().get('/search?q=ki').text


def fake_push_environment(monkeypatch):
    for name in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'):
        monkeypatch.setenv(name,'mock-test-value')


def test_expired_push_endpoints_are_cleaned_without_leaking_them(monkeypatch):
    from web_push import deliver_push
    fake_push_environment(monkeypatch)
    class ProviderError(Exception):
        response=SimpleNamespace(status_code=410)
    send=Mock(side_effect=ProviderError())
    monkeypatch.setitem(sys.modules,'pywebpush',SimpleNamespace(webpush=send,WebPushException=ProviderError))
    subscription={'endpoint':'https://fcm.googleapis.com/fake-test-only','keys':{'auth':'fake','p256dh':'fake'}}
    logger=Mock()
    outcome=deliver_push([subscription],{'body':'Test'},logger)
    assert outcome['retry'] is False
    assert outcome['expired']==[hashlib.sha256(subscription['endpoint'].encode()).hexdigest()]
    assert subscription['endpoint'] not in str(logger.mock_calls)


def test_worker_rechecks_preferences_and_removes_expired_subscription(monkeypatch):
    from gamearena.workers import deliver_notification_push
    import web_push
    fake_push_environment(monkeypatch)
    with app.app_context():
        owner=player('push_owner')
        endpoint='https://fcm.googleapis.com/fake-only'
        digest=hashlib.sha256(endpoint.encode()).hexdigest()
        record=Notification(user_id=owner.id,message='New message',category='chat')
        db.session.add_all([record,PushSubscription(user_id=owner.id,endpoint_hash=digest,subscription={'endpoint':endpoint})]);db.session.commit()
        send=Mock(return_value={'retry':False,'expired':[digest]});monkeypatch.setattr(web_push,'deliver_push',send)
        db.session.add(UserSettings(user_id=owner.id,chat_notifications=False));db.session.commit()
        deliver_notification_push(record.id);send.assert_not_called()
        owner.settings.chat_notifications=True;db.session.commit()
        deliver_notification_push(record.id);send.assert_called_once()
        assert PushSubscription.query.count()==0


def test_push_test_endpoint_requires_config_subscription_and_csrf(monkeypatch):
    import app as application
    with app.app_context():
        owner=player('push_test_owner');browser=client(owner)
        csrf=token(browser.get('/settings'))
        headers={'X-CSRFToken':csrf}
        assert browser.post('/notifications/push/test',headers=headers).status_code==503
        fake_push_environment(monkeypatch)
        assert browser.post('/notifications/push/test',headers=headers).status_code==400
        db.session.add(PushSubscription(user_id=owner.id,endpoint_hash='mock-endpoint-hash',subscription={}));db.session.commit()
        deliver=Mock();monkeypatch.setattr(application,'create_and_emit_notification',deliver)
        assert browser.post('/notifications/push/test').status_code==400
        # Test rate limit is already used twice by the checks above; third call is allowed.
        assert browser.post('/notifications/push/test',headers=headers).status_code==202
        deliver.assert_called_once()
        assert browser.post('/notifications/push/test',headers=headers).status_code==429
