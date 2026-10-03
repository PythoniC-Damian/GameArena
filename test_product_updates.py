"""Isolated contracts for themes, preview notifications, photos, chat and push."""
import io
from PIL import Image
from app import app, db, socketio, UserSettings, UserBlock, DirectMessage, GlobalChatMessage, Notification, PushSubscription
from test_interface_contracts import player, client, token


def test_preview_is_private_and_opening_does_not_mark_read():
    with app.app_context():
        owner, other = player('preview_owner'), player('preview_other')
        db.session.add_all([Notification(user_id=owner.id,message='My update'),Notification(user_id=other.id,message='Private other update')]); db.session.commit()
        viewer = client(owner)
        response = viewer.get('/notifications/preview')
        assert response.status_code == 200 and response.json['unread'] == 1
        assert len(response.json['notifications']) == 1
        assert 'Private other update' not in response.text
        assert Notification.query.filter_by(user_id=owner.id).first().read_at is None
        page = viewer.get('/profile')
        assert 'data-notification-menu' in page.text and 'View all notifications' in page.text
        assert viewer.post('/notifications/read-all',headers={'Accept':'application/json','X-CSRFToken':token(page)}).json == {'unread':0}
    assert app.test_client().get('/notifications/preview').status_code == 302


def test_theme_persists_and_invalid_values_are_rejected():
    with app.app_context():
        owner = player('theme_owner'); viewer = client(owner)
        csrf = token(viewer.get('/settings'))
        data = {'csrf_token':csrf,'username':owner.username,'theme':'light','allow_direct_messages':'on','profile_public':'on'}
        assert viewer.post('/settings',data=data).status_code == 302
        assert db.session.get(UserSettings,1).theme == 'light'
        assert '"light"' in viewer.get('/profile').text
        data['theme'] = 'invalid'; viewer.post('/settings',data=data)
        db.session.expire_all(); assert UserSettings.query.filter_by(user_id=owner.id).first().theme == 'light'


def test_photo_upload_validates_and_persists_without_trusting_filenames(tmp_path,monkeypatch):
    monkeypatch.setenv('AVATAR_UPLOAD_DIR',str(tmp_path)); monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY',raising=False)
    with app.app_context():
        owner = player('photo_owner'); viewer = client(owner); csrf = token(viewer.get('/profile'))
        image = io.BytesIO(); Image.new('RGB',(640,480),'green').save(image,'PNG'); image.seek(0)
        assert viewer.post('/profile/photo',data={'csrf_token':csrf,'avatar':(image,'../../photo.png')}).status_code == 302
        db.session.refresh(owner); assert owner.avatar_url.startswith('/media/avatars/')
        path = owner.avatar_url; image_response = viewer.get(path)
        assert image_response.status_code == 200 and 'immutable' in image_response.headers['Cache-Control']
        with Image.open(next(tmp_path.glob('*.webp'))) as saved: assert saved.size == (384,384)
        viewer.post('/profile/photo',data={'csrf_token':csrf,'avatar':(io.BytesIO(b'<svg>bad</svg>'),'bad.svg')})
        db.session.refresh(owner); assert owner.avatar_url == path
        assert viewer.post('/profile/photo',data={'avatar':(io.BytesIO(b'bad'),'bad.jpg')}).status_code == 400


def test_unblocking_restores_delivery_without_reloading_socket():
    with app.app_context():
        a,b = player('chat_first'),player('chat_second'); aid,bid = a.id,b.id; first,second = client(a),client(b)
    sender = socketio.test_client(app,flask_test_client=first); recipient = socketio.test_client(app,flask_test_client=second)
    assert sender.is_connected() and recipient.is_connected()
    csrf = token(second.get('/settings'))
    second.post(f'/users/{aid}/block',data={'csrf_token':csrf})
    result = sender.emit('send_direct_message',{'user_id':bid,'message':'Blocked'},callback=True)
    assert result['status'] == 'error'
    second.post(f'/users/{aid}/unblock',data={'csrf_token':csrf})
    recipient.get_received()
    result = sender.emit('send_direct_message',{'user_id':bid,'message':'Delivered without refresh'},callback=True)
    assert result['status'] == 'success'
    messages = [item for item in recipient.get_received() if item['name']=='new_direct_message']
    assert messages and messages[0]['args'][0]['message']=='Delivered without refresh'
    sender.disconnect(); recipient.disconnect()
    with app.app_context(): assert UserBlock.query.count()==0 and DirectMessage.query.count()==1


def test_replies_are_stored_and_reject_foreign_conversations():
    with app.app_context():
        a,b,c = player('reply_first'),player('reply_second'),player('reply_third'); aid,bid,cid = a.id,b.id,c.id
        original = DirectMessage(sender_id=bid,recipient_id=aid,message='Original message')
        foreign = DirectMessage(sender_id=cid,recipient_id=bid,message='Private foreign message')
        db.session.add_all([original,foreign]); db.session.commit(); original_id,foreign_id=original.id,foreign.id; viewer=client(a)
    sender = socketio.test_client(app,flask_test_client=viewer)
    invalid=sender.emit('send_direct_message',{'user_id':bid,'message':'Cannot quote','reply_to_id':foreign_id},callback=True)
    assert invalid['status']=='error'
    sent=sender.emit('send_direct_message',{'user_id':bid,'message':'Reply text','reply_to_id':original_id},callback=True)
    assert sent['status']=='success'
    history = viewer.get(f'/chat/history?partner={bid}').json
    assert history['messages'][-1]['reply']['message']=='Original message'
    assert 'Private foreign message' not in str(history)
    assert 'Original message' in viewer.get(f'/messages/{bid}').text
    sender.disconnect()


def test_unblock_does_not_override_other_players_privacy():
    with app.app_context():
        a,b = player('block_first'),player('block_second'); viewer=client(a)
        db.session.add_all([UserBlock(blocker_id=a.id,blocked_id=b.id),UserBlock(blocker_id=b.id,blocked_id=a.id)]);db.session.commit()
        viewer.post(f'/users/{b.id}/unblock',data={'csrf_token':token(viewer.get('/settings'))})
        assert UserBlock.query.count()==1
        assert viewer.get(f'/messages/{b.id}').status_code==302


def test_push_is_not_enabled_without_configuration_and_rejects_private_endpoints(monkeypatch):
    monkeypatch.delenv('VAPID_PRIVATE_KEY',raising=False)
    with app.app_context():
        owner=player('push_owner');viewer=client(owner);csrf=token(viewer.get('/settings'))
        assert viewer.get('/notifications/push').json['configured'] is False
        assert viewer.post('/notifications/push',json={'subscription':{'endpoint':'https://127.0.0.1/private','keys':{'p256dh':'A'*87,'auth':'A'*22}}},headers={'X-CSRFToken':csrf}).status_code==400
        assert PushSubscription.query.count()==0


def test_hero_uses_all_local_images_and_has_no_cube():
    import app as application
    with app.test_request_context('/'):
        images=application.utility_processor()['carousel_images']
        assert len(images)==len(application.hero_image_catalog())
        assert all('optimized/' in image for image in images)
    page=app.test_client().get('/').text
    assert 'featuredCube' not in page and 'data-pause' in page


def test_configured_push_is_owner_scoped_csrf_protected_and_removed_on_logout(monkeypatch):
    for key in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'):monkeypatch.setenv(key,'test-only')
    value={'endpoint':'https://fcm.googleapis.com/fcm/send/isolated-test','keys':{'p256dh':'A'*87,'auth':'A'*22}}
    with app.app_context():
        owner,other=player('device_owner'),player('device_other');viewer,outsider=client(owner),client(other)
        csrf=token(viewer.get('/settings'))
        assert viewer.post('/notifications/push',json={'subscription':value}).status_code==400
        assert viewer.post('/notifications/push',json={'subscription':value},headers={'X-CSRFToken':csrf}).json['status']=='saved'
        assert PushSubscription.query.count()==1
        foreign_csrf=token(outsider.get('/settings'))
        assert outsider.post('/notifications/push',json={'subscription':value},headers={'X-CSRFToken':foreign_csrf}).status_code==409
        outsider.delete('/notifications/push',json={'subscription':value},headers={'X-CSRFToken':foreign_csrf})
        assert PushSubscription.query.count()==1
        viewer.post('/logout',data={'csrf_token':csrf})
        assert PushSubscription.query.count()==0


def test_push_respects_existing_chat_preferences_and_uses_background_delivery(monkeypatch):
    import app as application
    for key in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'):monkeypatch.setenv(key,'test-only')
    calls=[];monkeypatch.setattr(socketio,'start_background_task',lambda *args: calls.append(args))
    with app.app_context():
        owner=player('push_preference_owner')
        preferences=UserSettings(user_id=owner.id,chat_notifications=False)
        db.session.add_all([preferences,PushSubscription(user_id=owner.id,endpoint_hash='a'*64,subscription={'endpoint':'https://fcm.googleapis.com/isolated'})]);db.session.commit()
        application.create_and_emit_notification(owner.id,'Suppressed chat','chat')
        assert not calls and Notification.query.count()==0
        preferences.chat_notifications=True;db.session.commit()
        application.create_and_emit_notification(owner.id,'New message','chat','/messages/2')
        assert len(calls)==1 and calls[0][2]['url']=='/messages/2'


def test_reply_push_migration_is_additive_and_repeatable():
    from db_migrate import ensure_chat_replies_and_push
    class Recorder:
        def __init__(self):self.statements=[]
        def execute(self,statement):self.statements.append(str(statement))
    connection=Recorder();ensure_chat_replies_and_push(connection)
    assert len(connection.statements)==9
    assert all('IF NOT EXISTS' in statement for statement in connection.statements[:6])
    assert 'ENABLE ROW LEVEL SECURITY' in connection.statements[6]
    assert 'REVOKE ALL' in connection.statements[7]
    assert not any(statement.lstrip().startswith(('DROP ', 'DELETE ')) for statement in connection.statements)


def test_server_timing_reports_app_and_database_without_query_text():
    with app.app_context():
        owner=player('timing_owner');response=client(owner).get('/profile')
        header=response.headers.get('Server-Timing','')
        assert 'app;dur=' in header and 'db;dur=' in header
        assert 'SELECT' not in header and owner.email not in header
