from app import app, db, DirectMessage, GlobalChatMessage, socketio
from test_interface_contracts import player, client, token


def test_inbox_lists_private_partners_with_photos_and_latest_message():
    with app.app_context():
        owner = player('inbox_owner')
        peers = [player(f'inbox_peer_{i}') for i in range(9)]
        peers[0].avatar_url = '/media/avatar/photo'
        for peer in peers:
            db.session.add(DirectMessage(sender_id=owner.id, recipient_id=peer.id, message=f'Hello {peer.username}'))
        stranger = player('public_chat_only')
        db.session.add(GlobalChatMessage(user_id=stranger.id, message='Public message'))
        db.session.add(DirectMessage(sender_id=peers[0].id, recipient_id=owner.id, message='Latest reply'))
        db.session.commit()
        viewer = client(owner)
        page = viewer.get(f'/messages/{peers[0].id}')
        assert page.status_code == 200
        assert '/media/avatar/photo' in page.text
        assert f'/players/{peers[0].id}' in page.text
        for peer in peers: assert peer.username in page.text
        assert stranger.username not in page.text
        items = viewer.get('/chat/conversations').json['conversations']
        assert len(items) == 9
        assert items[0]['id'] == peers[0].id
        assert items[0]['preview'] == 'Latest reply' and items[0]['unread'] == 1
        assert items[0]['avatar_url'] == '/media/avatar/photo'
        assert len(viewer.get('/chat').text) > 0
        assert len(viewer.get('/chat/conversations').json['conversations']) == 9


def test_only_recipient_can_mark_specifically_viewed_messages_and_notify_sender():
    with app.app_context():
        sender, recipient, outsider = player('seen_sender'), player('seen_recipient'), player('seen_outsider')
        first = DirectMessage(sender_id=sender.id, recipient_id=recipient.id, message='Visible')
        second = DirectMessage(sender_id=sender.id, recipient_id=recipient.id, message='Offscreen')
        unrelated = DirectMessage(sender_id=sender.id, recipient_id=outsider.id, message='Private elsewhere')
        db.session.add_all([first, second, unrelated]); db.session.commit()
        receiving = client(recipient)
        sending = client(sender)
        socket = socketio.test_client(app, flask_test_client=sending)
        socket.emit('join_user', {'user_id':sender.id})
        socket.get_received()
        page = receiving.get(f'/messages/{sender.id}')
        db.session.expire_all()
        assert db.session.get(DirectMessage, first.id).read_at is None
        csrf = token(page)
        response = receiving.post(f'/messages/{sender.id}/read', json={'ids':[first.id, unrelated.id]}, headers={'X-CSRFToken':csrf})
        assert response.status_code == 200 and response.json['read_ids'] == [first.id]
        db.session.expire_all()
        assert db.session.get(DirectMessage, first.id).read_at is not None
        assert db.session.get(DirectMessage, second.id).read_at is None
        assert db.session.get(DirectMessage, unrelated.id).read_at is None
        receipts = [item for item in socket.get_received() if item['name'] == 'direct_messages_read']
        assert receipts[0]['args'][0]['ids'] == [first.id]
        # Polling recovers read updates even when there are no new messages.
        history = sending.get(f'/chat/history?partner={recipient.id}&after={unrelated.id}').json
        assert history['messages'] == [] and history['read_ids'] == [first.id]
        own_page = sending.get(f'/messages/{recipient.id}')
        assert '✓✓ Seen' in own_page.text and '✓ Sent' in own_page.text
        assert receiving.post(f'/messages/{sender.id}/read', json={}, headers={'X-CSRFToken':csrf}).status_code == 400
        assert receiving.post(f'/messages/{sender.id}/read', json=[first.id], headers={'X-CSRFToken':csrf}).status_code == 400
        assert receiving.post(f'/messages/{sender.id}/read', json={'ids':[second.id]}).status_code == 400
        socket.disconnect()
