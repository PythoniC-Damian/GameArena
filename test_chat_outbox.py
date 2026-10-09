"""Isolated burst delivery and idempotent recovery contracts."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from app import app, db, socketio, DirectMessage, PlayerConnection, socket_event_windows
from test_interface_contracts import player, client, token


def test_concurrent_http_messages_keep_distinct_identity(monkeypatch):
    monkeypatch.setattr(socketio, 'start_background_task', lambda *args, **kwargs: None)
    socket_event_windows.clear()
    with app.app_context():
        owner, other = player('outbox_owner'), player('outbox_other')
        db.session.add(PlayerConnection(low_id=min(owner.id,other.id),high_id=max(owner.id,other.id),requester_id=owner.id,status='accepted'));db.session.commit()
        owner_id, other_id = owner.id, other.id
    payloads = [{'user_id':other_id,'message':f'Burst {i}','client_message_id':str(uuid4())} for i in range(5)]
    def send(payload):
        viewer = app.test_client()
        with viewer.session_transaction() as session:
            session['_user_id']=str(owner_id); session['_fresh']=True
        csrf=token(viewer.get('/profile'))
        response=viewer.post('/chat/send',json=payload,headers={'Accept':'application/json','X-CSRFToken':csrf})
        assert response.status_code==200
        return response.json
    with ThreadPoolExecutor(max_workers=5) as executor:
        results=list(executor.map(send,payloads))
    assert all(result['status']=='success' for result in results)
    assert len({result['id'] for result in results})==5
    # A response lost for every message can be recovered without duplicates.
    with ThreadPoolExecutor(max_workers=5) as executor:
        recovered=list(executor.map(send,payloads))
    assert {result['id'] for result in results}=={result['id'] for result in recovered}
    with app.app_context(): assert DirectMessage.query.count()==5


def test_duplicate_ack_does_not_consume_burst_limit(monkeypatch):
    monkeypatch.setattr(socketio, 'start_background_task', lambda *args, **kwargs: None)
    socket_event_windows.clear()
    with app.app_context():
        owner, other=player('ack_owner'),player('ack_other');viewer=client(owner);other_id=other.id
        db.session.add(PlayerConnection(low_id=min(owner.id,other.id),high_id=max(owner.id,other.id),requester_id=owner.id,status='accepted'));db.session.commit()
    connection=socketio.test_client(app,flask_test_client=viewer)
    payload={'user_id':other_id,'message':'One message','client_message_id':str(uuid4())}
    sent=connection.emit('send_direct_message',payload,callback=True)
    assert sent['status']=='success'
    for _ in range(12): assert connection.emit('send_direct_message',payload,callback=True)==sent
    following=connection.emit('send_direct_message',{'user_id':other_id,'message':'Next message','client_message_id':str(uuid4())},callback=True)
    assert following['status']=='success'
    with app.app_context(): assert DirectMessage.query.count()==2
    connection.disconnect()
