"""Community mention resolution and reversible player connections."""
from uuid import uuid4
from app import app, db, socketio, socket_event_windows
from gamearena.models import UserBlock, GlobalChatMessage, PlayerConnection, DirectMessage, Notification
from gamearena.chat_mentions import resolve_mentions, mention_text
from test_interface_contracts import player, client, token


def send(viewer, text, key=None):
    csrf=token(viewer.get('/chat'))
    return viewer.post('/chat/send',json={'message':text,'client_message_id':key or str(uuid4())},headers={'X-CSRFToken':csrf,'Accept':'application/json'})


def connect(viewer,other,action):
    return viewer.post(f'/players/{other.id}/connection',data={'action':action,'csrf_token':token(viewer.get('/profile'))},headers={'Accept':'application/json'})


def test_mentions_suggest_prefixes_and_exclude_blocked_or_suspended_players():
    with app.app_context():
        owner=player('mention_owner');bat=player('Batman');bat2=player('Batgirl');bee=player('Bee');blocked=player('Batblocked');suspended=player('Batsuspended');suspended.suspended=True
        db.session.add(UserBlock(blocker_id=blocked.id,blocked_id=owner.id));db.session.commit();viewer=client(owner)
        assert {r['username'] for r in viewer.get('/chat/mentions?q=B').json['users']}=={'Batman','Batgirl','Bee'}
        assert {r['username'] for r in viewer.get('/chat/mentions?q=bat').json['users']}=={'Batman','Batgirl'}
        assert viewer.get('/chat/mentions?q=%25').json['users']==[]
        assert app.test_client().get('/chat/mentions?q=B').status_code==302
        data=viewer.get('/chat/mentions?q=Bat').json
        assert all(set(row)=={'id','username'} for row in data['users'])


def test_mentions_persist_render_safely_and_notify_once_across_retries():
    socket_event_windows.clear()
    with app.app_context():
        owner=player('mention_author');bat=player('Batman');viewer=client(owner)
        text='🎮 <script>alert(1)</script> @Batman and @Batman!';key=str(uuid4())
        result=send(viewer,text,key);assert result.status_code==200 and result.json['status']=='success',result.text
        assert len(result.json['mentions'])==2
        row=GlobalChatMessage.query.one();assert len(row.mentions)==2
        assert Notification.query.filter_by(user_id=bat.id).count()==1
        assert send(viewer,text,key).json['id']==row.id
        assert Notification.query.filter_by(user_id=bat.id).count()==1
        page=viewer.get('/chat');assert 'class="ga-chat-mention"' in page.text and '&lt;script&gt;' in page.text
        assert f'href="/players/{bat.id}"' in page.text
        history=viewer.get('/chat/history?after=0').json['messages'];assert history[0]['mentions']==row.mentions
        assert '<script>' not in str(mention_text(text,row.mentions))
        response=viewer.post(f'/chat/message/global/{row.id}/delete',data={'csrf_token':token(page)})
        assert response.status_code==200;db.session.refresh(row);assert row.mentions==[]
        assert viewer.get('/chat/history?after=0').json['messages'][0]['mentions']==[]


def test_five_mentions_allowed_six_and_group_mentions_rejected_on_http_and_socket():
    socket_event_windows.clear()
    with app.app_context():
        owner=player('mention_limit');bat=player('Batman');viewer=client(owner)
        assert send(viewer,' '.join(['@Batman']*5)).json['status']=='success'
        assert send(viewer,' '.join(['@Batman']*6)).json['status']=='error'
        for group in ('@all','@everyone','@here'):
            assert send(viewer,group).json['status']=='error'
        assert GlobalChatMessage.query.count()==1
        live=socketio.test_client(app,flask_test_client=viewer)
        result=live.emit('send_global_chat_message',{'message':' '.join(['@Batman']*6)},callback=True)
        assert result['status']=='error';live.disconnect()
        assert resolve_mentions('Email hi@example.com; @Unknown',owner.id)==[]


def test_unfriend_works_for_either_player_and_requires_new_acceptance(monkeypatch):
    monkeypatch.setattr(socketio,'start_background_task',lambda *a,**kw:None)
    with app.app_context():
        owner=player('friend_owner');other=player('friend_other');outsider=player('friend_outsider')
        # Legacy accounts may chat freely until they explicitly establish/remove a friendship.
        owner.requires_player_consent=other.requires_player_consent=False
        db.session.add(PlayerConnection(low_id=min(owner.id,other.id),high_id=max(owner.id,other.id),requester_id=owner.id,status='accepted'))
        db.session.add(DirectMessage(sender_id=owner.id,recipient_id=other.id,message='Keep history'))
        db.session.commit();viewer=client(other);author=client(owner)
        page=viewer.get(f'/players/{owner.id}');assert 'Unfriend' in page.text
        assert viewer.post(f'/players/{owner.id}/connection',data={'action':'unfriend'}).status_code==400
        assert connect(client(outsider),owner,'unfriend').status_code==409
        result=connect(viewer,owner,'unfriend');assert result.status_code==200 and result.json['connection']['state']=='cancelled'
        assert DirectMessage.query.count()==1
        csrf=token(author.get('/profile'))
        denied=author.post('/chat/send',json={'message':'Cannot bypass unfriend','user_id':other.id},headers={'X-CSRFToken':csrf,'Accept':'application/json'})
        assert denied.json['status']=='error'
        assert connect(author,other,'request').json['connection']['state']=='outgoing'
        assert connect(viewer,owner,'accept').json['connection']['state']=='accepted'
        assert connect(author,other,'unfriend').json['connection']['state']=='cancelled'
        assert DirectMessage.query.count()==1


def test_unfriend_is_available_even_when_the_other_player_disables_messages():
    from gamearena.models import UserSettings
    with app.app_context():
        owner=player('remove_private_friend');other=player('private_friend')
        db.session.add(PlayerConnection(low_id=min(owner.id,other.id),high_id=max(owner.id,other.id),requester_id=owner.id,status='accepted'));db.session.commit()
        preferences=UserSettings(user_id=other.id,allow_direct_messages=False);db.session.add(preferences);db.session.commit()
        result=connect(client(owner),other,'unfriend')
        assert result.status_code==200 and result.json['connection']['state']=='cancelled'
