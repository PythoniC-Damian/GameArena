"""Security and functional contracts for the coordinated GameArena interface."""
import re
from datetime import datetime, timedelta
import app as application
from app import app, db, User, UserSettings, UserTournament, Tournament, TournamentMatch, Notification, GlobalChatMessage, socketio


def test_dashboard_keeps_active_rounds_and_older_pending_results_visible():
    with app.app_context():
        owner, opponent = player('dashboard_owner'), player('dashboard_opponent')
        active = event('Active second round', status='live')
        pending = event('Older result awaiting review', status='live')
        completed = event('Completed results', status='live')
        past = datetime.utcnow() - timedelta(days=2)
        active.match_time = past
        db.session.add(TournamentMatch(tournament_id=active.id, player_one_user_id=owner.id,
            player_two_user_id=opponent.id, status='scheduled', round_number=2, match_order=1))
        db.session.add(TournamentMatch(tournament_id=pending.id, player_one_user_id=owner.id,
            player_two_user_id=opponent.id, status='pending_confirmation', updated_at=past))
        for order in range(6):
            db.session.add(TournamentMatch(tournament_id=completed.id, player_one_user_id=owner.id,
                player_two_user_id=opponent.id, status='confirmed', round_number=1,
                match_order=order, winner_user_id=owner.id))
        db.session.commit()
        page = client(owner).get('/dashboard')
        assert page.status_code == 200
        assert 'Active second round' in page.text and 'Round 2' in page.text
        assert 'Older result awaiting review' in page.text
        assert 'No match results awaiting your review.' not in page.text


def player(name):
    user = User(username=name, email=f'{name}@example.test', password='hash', email_verified=True)
    db.session.add(user); db.session.commit()
    return user


def client(user):
    result = app.test_client()
    with result.session_transaction() as session:
        session['_user_id'] = str(user.id); session['_fresh'] = True
    return result


def token(response):
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def event(name='Test Arena', fee=0, status='open', capacity=4):
    result = Tournament(name=name, game='PUBG Mobile', entry_fee=fee, prize=10000, max_participants=capacity, status=status)
    db.session.add(result); db.session.commit()
    return result


def test_guest_header_is_consistent_and_private_controls_are_absent():
    with app.app_context():
        tournament = event()
        for path in ('/', '/tournaments', '/leaderboard', '/search?q=PUBG', f'/tournament/{tournament.id}', '/register', '/login'):
            response = app.test_client().get(path)
            assert response.status_code == 200
            assert response.text.count('class="ga-header"') == 1
            assert 'class="ga-notifications' not in response.text
            assert 'cdn.tailwindcss.com' not in response.text
            assert 'socket.io.min.js' not in response.text
            mobile_menu = re.search(r'<nav class="ga-menu".*?</nav>', response.text, re.S).group(0)
            assert 'href="/tournaments"' not in mobile_menu and 'href="/leaderboard"' not in mobile_menu


def test_notifications_read_unread_are_owner_scoped_and_do_not_auto_read():
    with app.app_context():
        owner, other = player('owner'), player('other')
        own = Notification(user_id=owner.id, message='Own update', category='tournament')
        foreign = Notification(user_id=other.id, message='Private update', category='wallet')
        db.session.add_all([own, foreign]); db.session.commit()
        viewer = client(owner)
        page = viewer.get('/notifications'); csrf = token(page)
        assert viewer.get('/notifications/count').json == {'unread': 1}
        assert 'Private update' not in page.text
        assert viewer.post(f'/notifications/{foreign.id}/read', data={'csrf_token':csrf}).status_code == 404
        assert viewer.post('/notifications/read-all', data={}).status_code == 400
        assert viewer.post('/notifications/read-all', data={'csrf_token':csrf}).status_code == 302
        assert viewer.get('/notifications/count').json == {'unread': 0}
        db.session.refresh(foreign); assert foreign.read_at is None
        assert viewer.post(f'/notifications/{own.id}/unread', data={'csrf_token':csrf}).status_code == 302
        assert viewer.get('/notifications/count').json == {'unread': 1}


def test_free_join_requires_post_and_rechecks_capacity():
    with app.app_context():
        first, second = player('first'), player('second')
        tournament = event(capacity=1)
        a, b = client(first), client(second)
        confirm = a.get(f'/join-tournament/{tournament.id}')
        assert confirm.status_code == 200
        assert UserTournament.query.count() == 0
        csrf = token(confirm)
        assert a.post(f'/join-tournament/{tournament.id}', data={}).status_code == 400
        assert a.post(f'/join-tournament/{tournament.id}', data={'csrf_token':csrf}).status_code == 302
        csrf_b = token(b.get('/profile'))
        assert b.post(f'/join-tournament/{tournament.id}', data={'csrf_token':csrf_b}).status_code == 302
        assert UserTournament.query.count() == 1


def test_pending_entries_can_resume_and_closed_entries_cannot_join():
    with app.app_context():
        user = player('entrant'); tournament = event(fee=1000)
        db.session.add(UserTournament(user_id=user.id, tournament_id=tournament.id, payment_status='pending', amount_paid=1000)); db.session.commit()
        viewer = client(user)
        assert viewer.get(f'/join-tournament/{tournament.id}').location.endswith(f'/pay/{tournament.id}')
        page = viewer.get(f'/pay/{tournament.id}'); assert page.status_code == 200
        tournament.status = 'finished'; db.session.commit()
        guest_details = app.test_client().get(f'/tournament/{tournament.id}').text
        assert 'Registration closed' in guest_details and 'Login to Join' not in guest_details
        assert viewer.get(f'/pay/{tournament.id}').status_code == 302
        assert viewer.post(f'/initialize-payment/{tournament.id}', headers={'X-CSRFToken':token(page)}).status_code == 409


def test_search_game_filter_and_public_profile_privacy():
    with app.app_context():
        public, private = player('visible_player'), player('hidden_player')
        db.session.add(UserSettings(user_id=private.id, profile_public=False)); tournament = event()
        other = Tournament(name='Other game', game='Free Fire', entry_fee=0, prize=10, max_participants=4)
        db.session.add(other); db.session.commit()
        guest = app.test_client()
        search = guest.get('/search?q=player').text
        assert 'visible_player' in search and 'hidden_player' not in search
        assert public.email not in search and private.email not in search
        public_page = guest.get(f'/players/{public.id}')
        assert public_page.status_code == 200 and public.email not in public_page.text
        results = guest.get('/tournaments?game=PUBG+Mobile').text
        assert tournament.name in results and 'Other game' not in results
        assert '/tournaments?game=PUBG' in guest.get('/search?q=PUBG').text


def test_rankings_and_payouts_do_not_invent_data():
    with app.app_context():
        tournament = event()
        viewer = app.test_client()
        ranking = viewer.get('/leaderboard').text
        assert 'View all tournaments' not in ranking and 'No player rankings' in ranking
        details = viewer.get(f'/tournament/{tournament.id}').text
        assert '₦10,000' in details and '₦5,000' not in details and '₦2,500' not in details


def test_cache_is_versioned_and_private_pages_are_not_cacheable():
    with app.app_context():
        page = app.test_client().get('/')
        asset = re.search(r'href="([^"]*css/app.css\?v=[^"]+)"', page.text).group(1)
        assert 'immutable' in app.test_client().get(asset).headers['Cache-Control']
        assert 'immutable' not in app.test_client().get('/static/css/app.css?v=wrong').headers['Cache-Control']
        assert 'no-store' in client(player('cache_owner')).get('/profile').headers['Cache-Control']
        worker = app.test_client().get('/sw.js')
        assert worker.status_code == 200 and worker.headers['Service-Worker-Allowed'] == '/'


def test_chat_acknowledgement_and_reconnect_history_are_authenticated():
    with app.app_context():
        user = player('chat_owner'); viewer = client(user)
        private = player('private_chat')
        db.session.add(UserSettings(user_id=private.id, allow_direct_messages=False))
        db.session.add(GlobalChatMessage(user_id=private.id, message='A public message with private DMs.'))
        db.session.commit()
        connection = socketio.test_client(app, flask_test_client=viewer)
        connection.emit('join_global_chat', {})
        result = connection.emit('send_global_chat_message', {'message':'Reconnect test'}, callback=True)
        assert result['status'] == 'success'
        history = viewer.get('/chat/history?after=0').json
        assert history['messages'][-1]['id'] == result['id']
        assert history['messages'][-1]['message'] == 'Reconnect test'
        assert viewer.get(f'/chat/history?after={result["id"]}').json['messages'] == []
        assert app.test_client().get('/chat/history').status_code == 302
        page = viewer.get('/chat').text
        assert f'href="/messages/{user.id}"' not in page
        assert f'href="/messages/{private.id}"' not in page
        connection.disconnect()


def test_bank_selector_uses_supported_provider_data_and_caches_it(monkeypatch):
    calls = []
    def provider(*args, **kwargs):
        calls.append(args)
        return [{'name':'Example Bank', 'code':'058', 'active':True}, {'name':'Inactive Bank', 'code':'099', 'active':False}]
    monkeypatch.setattr(application, 'PAYSTACK_SECRET_KEY', 'isolated-test-key')
    monkeypatch.setattr(application, 'paystack_transfer_request', provider)
    monkeypatch.setattr(application, '_supported_banks_cache', {'expires':0,'banks':[]})
    with app.app_context():
        viewer = client(player('bank_selector'))
        expected = {'banks':[{'name':'Example Bank','code':'058'}]}
        assert viewer.get('/wallet/banks').json == expected
        assert viewer.get('/wallet/banks').json == expected and len(calls) == 1
        assert app.test_client().get('/wallet/banks').status_code == 302
        page = viewer.get('/wallet').text
        assert 'Paystack bank code' not in page and 'id="withdrawBank"' in page


def test_unconfigured_bank_selector_does_not_call_a_provider(monkeypatch):
    monkeypatch.setattr(application, 'PAYSTACK_SECRET_KEY', '')
    monkeypatch.setattr(application, 'paystack_transfer_request', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('External provider called')))
    with app.app_context():
        assert client(player('bank_unavailable')).get('/wallet/banks').status_code == 503
