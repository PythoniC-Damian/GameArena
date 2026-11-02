from datetime import datetime
import app as application
from app import app,db
from gamearena.models import UserSettings,PlayerConnection,Notification,DirectMessage,UserBlock
from gamearena.push_summary import payload_for
from test_interface_contracts import player,client,token

def connect(a,b):
    db.session.add(PlayerConnection(low_id=min(a.id,b.id),high_id=max(a.id,b.id),requester_id=a.id,status='accepted'))

def test_friend_list_is_paginated_and_respects_profile_and_block_privacy():
    with app.app_context():
        owner,viewer=player('list_owner'),player('list_viewer')
        friends=[player(f'friend_{i:02}') for i in range(23)]
        for other in friends:connect(owner,other)
        db.session.add(UserSettings(user_id=friends[0].id,profile_public=False))
        db.session.add(UserBlock(blocker_id=viewer.id,blocked_id=friends[1].id));db.session.commit()
        browser=client(viewer);first=browser.get(f'/players/{owner.id}/friends').json
        assert first['count']==23 and first['next_offset']==20
        assert 'friend_00' not in first['html'] and 'friend_01' not in first['html']
        assert first['html'].count('class="ga-friend-row"')==20 and 'Add friend' in first['html']
        last=browser.get(f'/players/{owner.id}/friends?offset=20').json
        assert last['next_offset'] is None and last['html'].count('class="ga-friend-row"')==1
        assert '/players/' in last['html']
        db.session.add(UserSettings(user_id=owner.id,profile_public=False));db.session.commit()
        assert browser.get(f'/players/{owner.id}/friends').status_code==404
        assert client(owner).get(f'/players/{owner.id}/friends').status_code==200

def test_profile_uses_equipped_cover_and_chat_controls_are_streamlined():
    with app.app_context():
        owner,other=player('cover_owner'),player('chat_partner');connect(owner,other)
        owner.cosmetic_card='frost-card';db.session.commit();browser=client(other)
        page=browser.get(f'/players/{owner.id}').text
        assert 'ga-profile-cover' in page and 'data-arena-card="frost-card"' in page
        assert 'data-open-friends' in page and 'Unfriend' in page
        chat=browser.get(f'/messages/{owner.id}').text
        assert 'Private chat' in chat and 'data-chat-expand' in chat
        assert '>Unfriend<' not in chat and 'dmUnreadCount' not in chat
        global_chat=browser.get('/chat').text
        assert '>Community<' not in global_chat and 'data-chat-expand' in global_chat

def test_live_message_ack_is_authenticated_scoped_and_does_not_mark_friend_requests():
    with app.app_context():
        owner,other=player('live_owner'),player('live_other')
        application.create_and_emit_notification(owner.id,'A message','chat',f'/messages/{other.id}',kind='messages',sender_id=other.id)
        application.create_and_emit_notification(owner.id,'A request','chat',f'/messages/{other.id}',kind='requests',sender_id=other.id)
        message=Notification.query.filter_by(kind='messages').one();request=Notification.query.filter_by(kind='requests').one()
        browser=client(owner);csrf=token(browser.get('/settings'))
        assert browser.post(f'/notifications/{message.id}/seen-live').status_code==400
        stranger=client(other)
        assert stranger.post(f'/notifications/{message.id}/seen-live',data={'csrf_token':token(stranger.get('/settings'))}).status_code==404
        assert browser.post(f'/notifications/{request.id}/seen-live',data={'csrf_token':csrf}).status_code==404
        result=browser.post(f'/notifications/{message.id}/seen-live',data={'csrf_token':csrf})
        assert result.status_code==200 and result.json['unread']==1
        db.session.refresh(message);assert message.read_at
        assert db.session.get(Notification,request.id).read_at is None

def test_push_summary_keeps_seven_latest_senders_and_separate_request_group():
    with app.app_context():
        owner=player('push_owner');others=[player('sender_'+str(i)) for i in range(9)]
        for other in others:
            db.session.add(Notification(user_id=owner.id,category='chat',kind='messages',sender_id=other.id,message='sent a message',target_url=f'/messages/{other.id}'))
            db.session.add(DirectMessage(sender_id=other.id,recipient_id=owner.id,message='latest '+other.username))
        db.session.commit()
        latest=others[0]
        record=Notification(user_id=owner.id,category='chat',kind='messages',sender_id=latest.id,message='new update',target_url=f'/messages/{latest.id}')
        db.session.add(record);db.session.add(DirectMessage(sender_id=latest.id,recipient_id=owner.id,message='newest preview'));db.session.commit()
        payload=payload_for(record)
        assert payload['group']=='messages' and len(payload['entries'])==7
        assert payload['entries'][0]['sender_id']==latest.id and payload['entries'][0]['text']=='newest preview'
        assert len({e['sender_id'] for e in payload['entries']})==7
        request=Notification(user_id=owner.id,category='chat',kind='requests',sender_id=others[1].id,message='friend request')
        db.session.add(request);db.session.commit()
        summary=payload_for(request);assert summary['group']=='requests' and len(summary['entries'])==1
        assert summary['url']=='/chat?inbox=requests'


def test_social_metadata_migration_is_additive_and_idempotent():
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with app.app_context():
        user=player('migration_owner')
        db.session.add(Notification(user_id=user.id,message='Existing unread alert'));db.session.commit()
        with db.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration=importlib.import_module('migrations.versions.20261102_social_notifications')
                migration.upgrade();migration.upgrade()
        assert Notification.query.one().message=='Existing unread alert'
