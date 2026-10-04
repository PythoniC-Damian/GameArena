import re
from datetime import datetime, timedelta

from app import (
    Achievement,
    DirectMessage,
    GlobalChatMessage,
    Notification,
    Tournament,
    TournamentMatch,
    TournamentStat,
    User,
    UserAchievement,
    UserBlock,
    UserReport,
    UserSettings,
    UserTournament,
    WalletTransaction,
    PAYSTACK_CURRENCY,
    apply_wallet_deposit,
    app,
    complete_withdrawal,
    award_achievements_for_user,
    create_tournament_matches,
    db,
    advance_tournament_bracket,
    can_direct_message,
    socketio,
)


def make_user(username, *, is_admin=False):
    user = User(
        username=username,
        email=f'{username}@example.test',
        password='hashed-password',
        email_verified=True,
        is_admin=is_admin,
    )
    db.session.add(user)
    db.session.commit()
    return user


def client_for(user):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    return client


def csrf_for(client, path):
    response = client.get(path)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text)
    assert token
    return token.group(1)


def test_settings_persist_account_preferences_and_game_ids():
    with app.app_context():
        player = make_user('settings_player')
        client = client_for(player)
        token = csrf_for(client, '/settings')
        response = client.post('/settings', data={
            'csrf_token': token,
            'username': 'settings_player_updated',
            'bio': 'Ready to compete',
            'preferred_games': ['PUBG', 'eFootball'],
            'game_ids': 'PUBG: player-42',
            'tournament_notifications': 'on',
            'allow_direct_messages': 'on',
            'profile_public': 'on',
            'larger_text': 'on',
        })

        preferences = UserSettings.query.filter_by(user_id=player.id).one()
        refreshed = db.session.get(User, player.id)
        assert response.status_code == 302
        assert refreshed.username == 'settings_player_updated'
        assert refreshed.bio == 'Ready to compete'
        assert preferences.preferred_games == ['PUBG', 'eFootball']
        assert preferences.game_ids == {'PUBG': 'player-42'}
        assert preferences.larger_text is True


def test_search_respects_private_profiles_and_finds_tournaments_and_games():
    with app.app_context():
        public_player = make_user('search_public_player')
        private_player = make_user('search_private_player')
        db.session.add(UserSettings(user_id=private_player.id, profile_public=False))
        tournament = Tournament(
            name='Search Cup', game='SearchGame', entry_fee=0,
            prize=1000, status='open',
        )
        db.session.add(tournament)
        db.session.commit()

        response = app.test_client().get('/search?q=search')
        private_profile = app.test_client().get(f'/players/{private_player.id}')
        assert response.status_code == 200
        assert public_player.username in response.text
        assert private_player.username not in response.text
        assert 'Search Cup' in response.text
        assert 'SearchGame' in response.text
        assert private_profile.status_code == 404


def test_achievement_award_is_server_calculated_and_idempotent():
    with app.app_context():
        player = make_user('achievement_player')
        tournament = Tournament(name='First Cup', game='PUBG')
        db.session.add(tournament)
        db.session.commit()
        db.session.add(UserTournament(
            user_id=player.id, tournament_id=tournament.id,
            payment_status='paid',
        ))
        definition = Achievement(
            key='test_first_tournament', name='First Tournament',
            description='Joined your first tournament.', icon='flag',
            category='milestone', rule_type='tournaments', threshold=1,
        )
        db.session.add(definition)
        db.session.commit()

        award_achievements_for_user(player.id)
        award_achievements_for_user(player.id)

        records = UserAchievement.query.filter_by(
            user_id=player.id, achievement_id=definition.id,
        ).all()
        unlock_notifications = Notification.query.filter_by(
            user_id=player.id, category='achievement',
        ).all()
        assert len(records) == 1
        assert records[0].unlocked_at is not None
        assert records[0].progress == 1
        assert len(unlock_notifications) == 1


def test_direct_messages_are_persisted_and_blocked_conversations_are_rejected(monkeypatch):
    tasks = []
    start_background_task = socketio.start_background_task
    def capture_task(*args, **kwargs):
        task = start_background_task(*args, **kwargs)
        tasks.append(task)
        return task
    monkeypatch.setattr(socketio, 'start_background_task', capture_task)
    with app.app_context():
        sender = make_user('dm_sender')
        recipient = make_user('dm_recipient')
        web_client = client_for(sender)
        socket_client = socketio.test_client(app, flask_test_client=web_client)
        socket_client.emit('join_direct_message', {'user_id': recipient.id})
        socket_client.emit('send_direct_message', {
            'user_id': recipient.id, 'message': 'Hello privately',
        })

        stored = DirectMessage.query.filter_by(
            sender_id=sender.id, recipient_id=recipient.id,
        ).one()
        assert stored.message == 'Hello privately'
        # Delivery is acknowledged before background notification processing.
        assert len(tasks) == 1
        tasks[0].join()
        assert Notification.query.filter_by(
            user_id=recipient.id, category='chat',
        ).count() == 1

        db.session.add(UserBlock(blocker_id=recipient.id, blocked_id=sender.id))
        db.session.commit()
        socket_client.emit('send_direct_message', {
            'user_id': recipient.id, 'message': 'This must be blocked',
        })
        assert DirectMessage.query.filter_by(
            sender_id=sender.id, recipient_id=recipient.id,
        ).count() == 1
        assert can_direct_message(sender, recipient) is False
        socket_client.disconnect()


def test_player_and_chat_reports_are_visible_to_admin_review():
    with app.app_context():
        reporter = make_user('safety_reporter')
        target = make_user('safety_target')
        message = GlobalChatMessage(user_id=target.id, message='Reported content')
        db.session.add(message)
        db.session.commit()
        reporter_client = client_for(reporter)
        token = csrf_for(reporter_client, '/profile')
        blocked = reporter_client.post(
            f'/users/{target.id}/block',
            data={'csrf_token': token},
            headers={'Referer': f'/players/{target.id}'},
        )
        reported = reporter_client.post(
            f'/chat/messages/{message.id}/report',
            data={'csrf_token': token, 'reason': 'Inappropriate chat'},
        )
        assert blocked.status_code == 302
        assert reported.status_code == 302
        assert UserBlock.query.filter_by(blocker_id=reporter.id, blocked_id=target.id).count() == 1
        report = UserReport.query.filter_by(content_type='global_chat', content_id=message.id).one()
        assert report.reporter_id == reporter.id
        assert report.reason == 'Inappropriate chat'

        admin = make_user('safety_admin', is_admin=True)
        admin_client = client_for(admin)
        queue = admin_client.get('/admin/reports')
        token = csrf_for(admin_client, '/admin/reports')
        resolved = admin_client.post(
            f'/admin/reports/{report.id}/review',
            data={'csrf_token': token, 'action': 'resolve'},
        )
        assert queue.status_code == 200
        assert 'Inappropriate chat' in queue.text
        assert resolved.status_code == 302
        assert db.session.get(UserReport, report.id).status == 'resolved'


def test_notification_read_is_scoped_to_owner_and_keeps_safe_target():
    with app.app_context():
        owner = make_user('notification_owner')
        other = make_user('notification_other')
        owned_notification = Notification(
            user_id=owner.id, message='Match needs review',
            category='match', target_url='/tournaments',
        )
        private_notification = Notification(
            user_id=other.id, message='Private notification',
            category='system',
        )
        db.session.add_all([owned_notification, private_notification])
        db.session.commit()
        client = client_for(owner)
        token = csrf_for(client, '/notifications')

        response = client.post(
            f'/notifications/{owned_notification.id}/read',
            data={'csrf_token': token, 'next': '/tournaments'},
        )
        forbidden = client.post(
            f'/notifications/{private_notification.id}/read',
            data={'csrf_token': token},
        )
        assert response.status_code == 302
        assert response.headers['Location'].endswith('/tournaments')
        assert db.session.get(Notification, owned_notification.id).read_at is not None
        assert forbidden.status_code == 404
        assert db.session.get(Notification, private_notification.id).read_at is None


def test_leaderboard_game_filter_keeps_own_placement_visible():
    with app.app_context():
        player = make_user('ranking_player')
        pubg = Tournament(name='PUBG Ranking Cup', game='PUBG')
        efootball = Tournament(name='Football Ranking Cup', game='eFootball')
        db.session.add_all([pubg, efootball])
        db.session.commit()
        db.session.add_all([
            TournamentStat(user_id=player.id, tournament_id=pubg.id, rank=438, wins=3, points=20),
            TournamentStat(user_id=player.id, tournament_id=efootball.id, rank=4, wins=8, points=90),
        ])
        db.session.commit()
        client = client_for(player)

        response = client.get('/leaderboard?game=PUBG')
        assert response.status_code == 200
        assert 'PUBG Ranking Cup' in response.text
        assert 'Football Ranking Cup' not in response.text
        assert '#438' in response.text


def test_bracket_advances_only_after_complete_confirmed_round_and_is_idempotent():
    with app.app_context():
        tournament = Tournament(
            name='Bracket Cup', game='PUBG', status='ongoing',
            first_place='5000', max_participants=4,
        )
        players = [make_user(f'bracket_player_{index}') for index in range(4)]
        db.session.add(tournament)
        db.session.commit()
        now = datetime.utcnow()
        db.session.add_all([
            UserTournament(
                user_id=player.id, tournament_id=tournament.id,
                payment_status='free', joined_at=now + timedelta(seconds=index),
            )
            for index, player in enumerate(players)
        ])
        db.session.commit()

        first_round = create_tournament_matches(tournament)
        assert len(first_round) == 2
        assert all(match.round_number == 1 for match in first_round)
        first_round[0].winner_user_id = first_round[0].player_one_user_id
        first_round[0].status = 'confirmed'
        db.session.commit()
        assert advance_tournament_bracket(first_round[0]) is False

        first_round[1].winner_user_id = first_round[1].player_one_user_id
        first_round[1].status = 'confirmed'
        db.session.commit()
        assert advance_tournament_bracket(first_round[0]) is True
        final_match = TournamentMatch.query.filter_by(
            tournament_id=tournament.id, round_number=2,
        ).one()
        assert advance_tournament_bracket(first_round[0]) is False

        final_match.winner_user_id = final_match.player_two_user_id
        final_match.status = 'confirmed'
        db.session.commit()
        assert advance_tournament_bracket(final_match) is True
        assert advance_tournament_bracket(final_match) is False
        db.session.refresh(tournament)
        assert tournament.status == 'finished'
        assert tournament.first_place == '5000'
        assert TournamentMatch.query.filter_by(
            tournament_id=tournament.id, round_number=2,
        ).count() == 1
        assert Notification.query.filter_by(
            user_id=final_match.winner_user_id, category='tournament',
        ).count() >= 1


def test_settings_and_report_pages_require_login_and_admin():
    anonymous = app.test_client()
    assert anonymous.get('/settings').status_code == 302
    assert anonymous.get('/support').status_code == 302
    with app.app_context():
        regular_user = make_user('report_access_player')
        regular_client = client_for(regular_user)
        assert regular_client.get('/admin/reports').status_code == 403
        admin = make_user('report_access_admin', is_admin=True)
        assert client_for(admin).get('/admin/reports').status_code == 200


def test_support_request_is_stored_as_existing_report_type():
    with app.app_context():
        player = make_user('support_player')
        client = client_for(player)
        token = csrf_for(client, '/support')
        response = client.post('/support', data={
            'csrf_token': token, 'reason': 'Please help with tournament access.',
        })

        support_report = UserReport.query.filter_by(
            reporter_id=player.id, content_type='support',
        ).one()
        assert response.status_code == 302
        assert support_report.status == 'pending'
        assert support_report.reason == 'Please help with tournament access.'


def test_wallet_deposit_and_withdrawal_emit_once_after_final_state():
    with app.app_context():
        player = make_user('wallet_notice_player')
        deposit = WalletTransaction(
            user_id=player.id, type='deposit', amount=500,
            status='pending', transaction_ref='wallet-deposit-test-1',
        )
        withdrawal = WalletTransaction(
            user_id=player.id, type='withdrawal', amount=200,
            status='processing', transaction_ref='wallet-withdraw-test-1',
        )
        db.session.add_all([deposit, withdrawal])
        db.session.commit()
        transaction = {
            'reference': deposit.transaction_ref,
            'amount': 50000,
            'currency': PAYSTACK_CURRENCY,
            'metadata': {'user_id': player.id, 'type': 'wallet_deposit'},
        }

        assert apply_wallet_deposit(deposit, transaction) == (True, 'processed')
        assert apply_wallet_deposit(deposit, transaction) == (True, 'already_processed')
        complete_withdrawal(withdrawal.id)
        complete_withdrawal(withdrawal.id)

        wallet_alerts = Notification.query.filter_by(
            user_id=player.id, category='wallet',
        ).all()
        assert len(wallet_alerts) == 2
        assert all(alert.target_url == '/wallet' for alert in wallet_alerts)


def test_bracket_creation_refuses_odd_fields_without_dropping_players():
    with app.app_context():
        tournament = Tournament(name='Odd Field Cup', game='PUBG', status='ongoing')
        players = [make_user(f'odd_field_player_{index}') for index in range(3)]
        db.session.add(tournament)
        db.session.commit()
        db.session.add_all([
            UserTournament(
                user_id=player.id, tournament_id=tournament.id,
                payment_status='paid',
            )
            for player in players
        ])
        db.session.commit()

        assert create_tournament_matches(tournament) == []
        assert TournamentMatch.query.filter_by(tournament_id=tournament.id).count() == 0
        assert tournament.status == 'ongoing'


def test_product_migration_uses_only_additive_idempotent_statements():
    from db_migrate import MIGRATIONS, ensure_product_features

    class RecordingConnection:
        def __init__(self):
            self.statements = []

        def execute(self, statement, params=None):
            self.statements.append(str(statement).upper())

    connection = RecordingConnection()
    ensure_product_features(connection)
    statements = '\n'.join(connection.statements)

    assert ('20261001_product_features',) in MIGRATIONS
    assert 'CREATE TABLE IF NOT EXISTS USER_SETTINGS' in statements
    assert 'CREATE TABLE IF NOT EXISTS ACHIEVEMENT' in statements
    assert 'CREATE TABLE IF NOT EXISTS DIRECT_MESSAGE' in statements
    assert 'CREATE TABLE IF NOT EXISTS USER_BLOCK' in statements
    assert 'CREATE TABLE IF NOT EXISTS USER_REPORT' in statements
    assert 'ALTER TABLE NOTIFICATION ADD COLUMN IF NOT EXISTS CATEGORY' in statements
    assert 'ALTER TABLE TOURNAMENT_MATCH ADD COLUMN IF NOT EXISTS ROUND_NUMBER' in statements
    assert 'DROP TABLE' not in statements
    assert 'TRUNCATE' not in statements
    assert 'DELETE FROM' not in statements


def test_error_pages_are_safe_and_api_errors_remain_json():
    client = app.test_client()
    page_error = client.get('/does-not-exist')
    api_error = client.get('/api/v1/does-not-exist')

    assert page_error.status_code == 404
    assert 'Page not found' in page_error.text
    assert 'Traceback' not in page_error.text
    assert api_error.status_code == 404
    assert api_error.get_json()['error']['status'] == 404
