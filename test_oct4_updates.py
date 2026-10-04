import io
import uuid
from PIL import Image
import app as application
from app import app, db, socketio, DirectMessage, GlobalChatMessage, ProfilePhoto, UserSettings, UserBlock
from test_interface_contracts import player, client, token


def test_http_and_socket_share_message_identity_and_deletion(monkeypatch):
    monkeypatch.setattr(socketio,'start_background_task',lambda *args,**kwargs:None)
    with app.app_context():
        a,b=player('delivery_a'),player('delivery_b'); aid,bid=a.id,b.id; first,second=client(a),client(b)
    sender=socketio.test_client(app,flask_test_client=first); receiver=socketio.test_client(app,flask_test_client=second)
    csrf=token(first.get('/profile')); key=str(uuid.uuid4()); payload={'user_id':bid,'message':'Exactly once','client_message_id':key}
    sent=sender.emit('send_direct_message',payload,callback=True); assert sent['status']=='success'
    received=[x for x in receiver.get_received() if x['name']=='new_direct_message']; assert received[0]['args'][0]['client_message_id']==key
    repeated=first.post('/chat/send',json=payload,headers={'X-CSRFToken':csrf,'Accept':'application/json'}).json
    assert repeated['id']==sent['id']
    with app.app_context(): assert DirectMessage.query.count()==1
    assert second.post(f"/chat/message/direct/{sent['id']}/delete",headers={'X-CSRFToken':token(second.get('/profile')),'Accept':'application/json'}).status_code==403
    reply=receiver.emit('send_direct_message',{'user_id':aid,'message':'Quoted','reply_to_id':sent['id']},callback=True); assert reply['status']=='success'
    assert first.post(f"/chat/message/direct/{sent['id']}/delete",headers={'X-CSRFToken':csrf,'Accept':'application/json'}).json['status']=='success'
    history=second.get(f'/chat/history?partner={aid}').json
    assert 'Exactly once' not in str(history) and history['messages'][1]['reply']['message']=='This message was deleted.'
    assert sent['id'] in history['deleted_ids']
    assert first.post('/chat/send',json=payload).status_code==400
    sender.disconnect(); receiver.disconnect()


def test_typing_is_scoped_and_respects_blocks():
    with app.app_context():
        a,b,c=player('typing_a'),player('typing_b'),player('typing_c');aid,bid=a.id,b.id; first,second,third=client(a),client(b),client(c)
    connections=[socketio.test_client(app,flask_test_client=x) for x in (first,second,third)]
    connections[0].emit('chat_typing',{'user_id':bid,'typing':True})
    assert [x for x in connections[1].get_received() if x['name']=='chat_typing']
    assert not [x for x in connections[2].get_received() if x['name']=='chat_typing']
    with app.app_context():db.session.add(UserBlock(blocker_id=bid,blocked_id=aid));db.session.commit()
    connections[0].emit('chat_typing',{'user_id':bid,'typing':True})
    assert not [x for x in connections[1].get_received() if x['name']=='chat_typing']
    for connection in connections:connection.disconnect()


def test_production_photo_without_bucket_persists_in_database(monkeypatch):
    monkeypatch.setenv('RENDER','1');monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY','');monkeypatch.delenv('AVATAR_UPLOAD_DIR',raising=False)
    with app.app_context():
        owner=player('persistent_photo'); viewer=client(owner);csrf=token(viewer.get('/profile'))
        image=io.BytesIO();Image.new('RGB',(500,400),'blue').save(image,'PNG');image.seek(0)
        assert viewer.post('/profile/photo',data={'csrf_token':csrf,'avatar':(image,'photo.png')}).status_code==302
        db.session.refresh(owner); assert owner.avatar_url.startswith('/media/profile/')
        result=app.test_client().get(owner.avatar_url); assert result.status_code==200 and result.mimetype=='image/webp'
        with Image.open(io.BytesIO(result.data)) as saved:assert saved.size==(384,384)
        assert ProfilePhoto.query.count()==1


def test_bank_session_failure_is_json_and_api_missing_route_is_json():
    response=app.test_client().get('/wallet/banks',headers={'Accept':'application/json'})
    assert response.status_code==401 and response.is_json
    missing=app.test_client().get('/wallet/banks/not-a-route',headers={'Accept':'application/json'})
    assert missing.status_code==404 and missing.is_json


def test_global_http_and_reply_controls(monkeypatch):
    with app.app_context():
        viewer=client(player('global_sender'));csrf=token(viewer.get('/profile'));payload={'message':'Community message','client_message_id':str(uuid.uuid4())}
        sent=viewer.post('/chat/send',json=payload,headers={'X-CSRFToken':csrf}).json
        assert sent['status']=='success'
        assert viewer.post('/chat/send',json=payload,headers={'X-CSRFToken':csrf}).json['id']==sent['id']
        assert GlobalChatMessage.query.count()==1
        page=viewer.get('/chat').text
        assert 'ga-chat-reply-button' not in page and 'messageActions' in page and 'chatTyping' in page
        assert viewer.post(f"/chat/message/global/{sent['id']}/delete",headers={'X-CSRFToken':csrf}).json['status']=='success'
        assert 'Community message' not in viewer.get('/chat').text
