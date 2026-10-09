from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from app import app, db, socketio, UserSettings, DirectMessage, PlayerConnection, UserBlock
from test_interface_contracts import player, client, token


def post(viewer, url, data=None, payload=None):
    csrf = token(viewer.get('/profile'))
    return viewer.post(url, data=data, json=payload, headers={'X-CSRFToken':csrf})


def test_one_introduction_then_acceptance_and_request_filter(monkeypatch):
    monkeypatch.setattr(socketio, 'start_background_task', lambda *a, **kw: None)
    with app.app_context():
        one,two,third = player('request_one'),player('request_two'),player('request_third')
        a,b,c = client(one),client(two),client(third)
        payload={'user_id':two.id,'message':'Hello','client_message_id':str(uuid4())}
        first=post(a,'/chat/send',payload=payload).json
        assert first['status']=='success'
        assert post(a,'/chat/send',payload=payload).json['id']==first['id']
        assert post(a,'/chat/send',payload={'user_id':two.id,'message':'Second'}).json['status']=='error'
        assert post(b,'/chat/send',payload={'user_id':one.id,'message':'Reply before acceptance'}).json['status']=='error'
        inbox=b.get('/chat/conversations').json['conversations']
        assert inbox[0]['id']==one.id and inbox[0]['request']
        assert 'Accept player' in b.get(f'/messages/{one.id}').text
        assert post(a,f'/players/{two.id}/connection',data={'action':'accept'}).status_code==403
        assert post(c,f'/players/{two.id}/connection',data={'action':'accept'}).status_code==403
        assert post(b,f'/players/{one.id}/connection',data={'action':'accept'}).status_code==302
        assert not b.get('/chat/conversations').json['conversations'][0]['request']
        for sender,target in ((a,two),(b,one)):
            assert post(sender,'/chat/send',payload={'user_id':target.id,'message':'Now friends'}).json['status']=='success'
        db.session.add(UserBlock(blocker_id=two.id,blocked_id=one.id));db.session.commit()
        assert post(a,'/chat/send',payload={'user_id':two.id,'message':'Blocked'}).json['status']=='error'
        assert post(a,f'/players/{two.id}/connection',data={'action':'request'}).status_code==403


def test_cancel_resend_delete_and_decline_do_not_reset_introduction(monkeypatch):
    monkeypatch.setattr(socketio, 'start_background_task', lambda *a, **kw: None)
    with app.app_context():
        one,two=player('cancel_one'),player('cancel_two');a,b=client(one),client(two)
        url=f'/players/{two.id}/connection'
        assert post(a,url,data={'action':'request'}).status_code==302
        assert b.get('/chat/conversations').json['conversations'][0]['preview']=='Player request'
        assert 'Cancel request' in a.get(f'/players/{two.id}').text
        sent=post(a,'/chat/send',payload={'user_id':two.id,'message':'One intro'}).json
        assert post(a,f"/chat/message/direct/{sent['id']}/delete").status_code==200
        assert post(a,url,data={'action':'cancel'}).status_code==302
        assert b.get('/chat/conversations').json['conversations'][0]['request']
        assert post(a,url,data={'action':'request'}).status_code==302
        assert post(a,'/chat/send',payload={'user_id':two.id,'message':'Cannot repeat'}).json['status']=='error'
        assert post(b,f'/players/{one.id}/connection',data={'action':'decline'}).status_code==302
        assert b.get('/chat/conversations').json['conversations'][0]['request']
        post(a,url,data={'action':'request'})
        db.session.expire_all()
        assert PlayerConnection.query.one().status=='declined'
        assert a.post(url,data={'action':'request'}).status_code==400


def test_parallel_introductions_save_only_one(monkeypatch):
    monkeypatch.setattr(socketio, 'start_background_task', lambda *a, **kw: None)
    with app.app_context():
        one,two=player('parallel_one'),player('parallel_two');owner,target=one.id,two.id
    def send(i):
        viewer=app.test_client()
        with viewer.session_transaction() as session: session['_user_id']=str(owner);session['_fresh']=True
        return post(viewer,'/chat/send',payload={'user_id':target,'message':f'Introduction {i}','client_message_id':str(uuid4())}).json
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(send,range(4)))
    assert sum(r['status']=='success' for r in results)==1
    with app.app_context(): assert DirectMessage.query.count()==1


def test_theme_saves_only_appearance_and_logout_requires_confirmation():
    with app.app_context():
        user=player('theme_player');viewer=client(user)
        assert post(viewer,'/settings/theme',payload={'theme':'light'}).json=={'theme':'light'}
        assert UserSettings.query.filter_by(user_id=user.id).one().theme=='light'
        assert user.username=='theme_player'
        assert 'const savedTheme = "light"' in viewer.get('/settings').text
        assert post(viewer,'/settings/theme',payload={'theme':'other'}).status_code==400
        assert viewer.post('/settings/theme',json={'theme':'dark'}).status_code==400
        assert viewer.get('/logout').status_code==200
        with viewer.session_transaction() as session: assert session.get('_user_id')==str(user.id)
        assert post(viewer,'/logout').status_code==200
        with viewer.session_transaction() as session: assert session.get('_user_id')==str(user.id)
        assert post(viewer,'/logout',data={'confirmed':'1'}).status_code==302
        with viewer.session_transaction() as session: assert not session.get('_user_id')


def test_existing_players_chat_without_requests_but_newcomers_need_consent(monkeypatch):
    monkeypatch.setattr(socketio, 'start_background_task', lambda *a, **kw: None)
    with app.app_context():
        one,two,new=player('old_one'),player('old_two'),player('new_player')
        one.requires_player_consent=two.requires_player_consent=False;db.session.commit()
        a,b,c=client(one),client(two),client(new)
        page=a.get(f'/players/{two.id}').text
        assert '>Add player<' not in page and '>Block<' not in page and '>Report<' not in page
        for sender,target in ((a,two),(b,one),(a,two)):
            result=post(sender,'/chat/send',payload={'user_id':target.id,'message':'Open conversation'}).json
            assert result['status']=='success' and not result.get('awaiting_acceptance')
        assert not b.get('/chat/conversations').json['conversations'][0]['request']
        assert 'Players added' not in a.get(f'/messages/{two.id}').text
        assert '>Add player<' in a.get(f'/players/{new.id}').text
        assert post(a,'/chat/send',payload={'user_id':new.id,'message':'Introduction'}).json['status']=='success'
        assert post(a,'/chat/send',payload={'user_id':new.id,'message':'Second'}).json['status']=='error'
        assert post(c,'/chat/send',payload={'user_id':two.id,'message':'Introduction'}).json['status']=='success'
        assert post(c,'/chat/send',payload={'user_id':two.id,'message':'Second'}).json['status']=='error'
        db.session.add(UserBlock(blocker_id=two.id,blocked_id=one.id));db.session.commit()
        assert post(a,'/chat/send',payload={'user_id':two.id,'message':'Still blocked'}).json['status']=='error'


def test_connection_json_actions_and_notification_text(monkeypatch):
    from app import Notification
    monkeypatch.setattr(socketio,'start_background_task',lambda *a,**kw:None)
    with app.app_context():
        one,two=player('ajax_one'),player('ajax_two');a,b=client(one),client(two)
        def action(viewer,target,value):
            csrf=token(viewer.get('/profile'))
            response=viewer.post(f'/players/{target.id}/connection',data={'action':value,'csrf_token':csrf},headers={'Accept':'application/json'})
            assert response.status_code==200 and response.is_json
            return response.json
        state=action(a,two,'request')
        assert state['connection']['state']=='outgoing' and 'Cancel request' in state['controls_html']
        assert Notification.query.filter_by(user_id=two.id).one().message=='ajax_one sent you a player request.'
        assert action(a,two,'cancel')['connection']['state']=='cancelled'
        action(a,two,'request')
        # The requester receives both the transient notification and state event.
        sender_socket=socketio.test_client(app,flask_test_client=a)
        sender_socket.emit('join_user',{'user_id':one.id});sender_socket.get_received()
        state=action(b,one,'accept')
        assert state['connection']['can_send'] and state['connection']['state']=='accepted'
        assert 'Players added' not in state['controls_html']
        assert Notification.query.filter_by(user_id=one.id).one().message=='ajax_two added you.'
        events=sender_socket.get_received()
        assert any(event['name']=='notification' and event['args'][0]['message']=='ajax_two added you.' for event in events)
        assert any(event['name']=='player_connection_changed' and event['args'][0]['partner_id']==two.id for event in events)
        sender_socket.disconnect()
        assert a.get(f'/players/{two.id}/connection').json['connection']['state']=='accepted'
        with a.session_transaction() as session:
            assert not session.get('_flashes')
