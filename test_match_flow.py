import importlib
import re
from datetime import datetime, timedelta

app_module = importlib.import_module('app')


def create_pending_match():
    tournament = app_module.Tournament(
        name='Result Review Tournament', game='eFootball', status='live',
    )
    submitter = app_module.User(
        username='result_submitter', email='result_submitter@example.com',
        password='hashed', email_verified=True,
    )
    opponent = app_module.User(
        username='result_opponent', email='result_opponent@example.com',
        password='hashed', email_verified=True,
    )
    app_module.db.session.add_all([tournament, submitter, opponent])
    app_module.db.session.commit()
    match = app_module.TournamentMatch(
        tournament_id=tournament.id,
        player_one_user_id=submitter.id,
        player_two_user_id=opponent.id,
        submitted_by_user_id=submitter.id,
        winner_user_id=submitter.id,
        status='pending_confirmation',
        proof_note='Test evidence',
    )
    app_module.db.session.add(match)
    app_module.db.session.commit()
    return tournament, submitter, opponent, match


def authenticated_client(user_id):
    client = app_module.app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


def csrf_token(client, path):
    response = client.get(path)
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)


def test_create_tournament_matches_pairs_participants():
    with app_module.app.app_context():
        app_module.TournamentMatch.query.delete()
        app_module.TournamentMatchChatMessage.query.delete()
        app_module.GlobalChatMessage.query.delete()
        app_module.UserTournament.query.delete()
        app_module.Tournament.query.delete()
        app_module.User.query.delete()
        app_module.db.session.commit()

        tournament = app_module.Tournament(
            name='Test Match Tournament',
            game='eFootball',
            entry_fee=1000,
            prize=5000,
            max_participants=4,
            status='open'
        )
        app_module.db.session.add(tournament)
        app_module.db.session.commit()

        for index in range(4):
            user = app_module.User(
                username=f'player{index}',
                email=f'player{index}@test.com',
                password='hashed',
                email_verified=True,
            )
            app_module.db.session.add(user)
        app_module.db.session.commit()

        users = app_module.User.query.order_by(app_module.User.id).all()
        for user in users:
            app_module.db.session.add(app_module.UserTournament(user_id=user.id, tournament_id=tournament.id, payment_status='paid'))
        app_module.db.session.commit()

        matches = app_module.create_tournament_matches(tournament)

        assert len(matches) == 2
        assert tournament.status == 'live'
        assert all(match.tournament_id == tournament.id for match in matches)


def test_submit_match_result_marks_pending_confirmation():
    with app_module.app.app_context():
        app_module.TournamentMatch.query.delete()
        app_module.TournamentMatchChatMessage.query.delete()
        app_module.GlobalChatMessage.query.delete()
        app_module.UserTournament.query.delete()
        app_module.Tournament.query.delete()
        app_module.User.query.delete()
        app_module.db.session.commit()

        tournament = app_module.Tournament(
            name='Result Tournament',
            game='PUBG',
            entry_fee=1000,
            prize=5000,
            max_participants=2,
            status='live'
        )
        app_module.db.session.add(tournament)
        app_module.db.session.commit()

        player_one = app_module.User(username='p1', email='p1@test.com', password='hashed', email_verified=True)
        player_two = app_module.User(username='p2', email='p2@test.com', password='hashed', email_verified=True)
        app_module.db.session.add_all([player_one, player_two])
        app_module.db.session.commit()

        app_module.db.session.add_all([
            app_module.UserTournament(user_id=player_one.id, tournament_id=tournament.id, payment_status='paid'),
            app_module.UserTournament(user_id=player_two.id, tournament_id=tournament.id, payment_status='paid')
        ])
        app_module.db.session.commit()

        match = app_module.TournamentMatch(
            tournament_id=tournament.id,
            player_one_user_id=player_one.id,
            player_two_user_id=player_two.id,
            status='scheduled'
        )
        app_module.db.session.add(match)
        app_module.db.session.commit()

        result = app_module.submit_match_result(
            match=match,
            user=player_one,
            room_code='ABC123',
            room_password='secret',
            player_profile_id='p1-id',
            opponent_profile_id='p2-id',
            winner_user_id=player_one.id,
            proof_note='Clip uploaded',
        )

        assert result.status == 'pending_confirmation'
        assert result.room_code == 'ABC123'
        assert result.winner_user_id == player_one.id


def test_only_opponent_can_confirm_a_submitted_result():
    with app_module.app.app_context():
        tournament, submitter, opponent, match = create_pending_match()
        submitter_client = authenticated_client(submitter.id)
        submitter_token = csrf_token(
            submitter_client, f'/tournament/{tournament.id}',
        )
        submitter_response = submitter_client.post(
            f'/match/{match.id}/confirm-result',
            data={'csrf_token': submitter_token},
        )

        assert submitter_response.status_code == 302
        assert app_module.db.session.get(app_module.TournamentMatch, match.id).status == 'pending_confirmation'

        opponent_client = authenticated_client(opponent.id)
        opponent_token = csrf_token(
            opponent_client, f'/tournament/{tournament.id}',
        )
        opponent_response = opponent_client.post(
            f'/match/{match.id}/confirm-result',
            data={'csrf_token': opponent_token},
        )

        assert opponent_response.status_code == 302
        assert app_module.db.session.get(app_module.TournamentMatch, match.id).status == 'confirmed'


def test_dispute_freezes_result_until_admin_reopens_match():
    with app_module.app.app_context():
        tournament, submitter, opponent, match = create_pending_match()
        opponent_client = authenticated_client(opponent.id)
        opponent_token = csrf_token(
            opponent_client, f'/tournament/{tournament.id}',
        )
        dispute_response = opponent_client.post(
            f'/match/{match.id}/dispute',
            data={'csrf_token': opponent_token, 'reason': 'The reported winner is incorrect.'},
        )

        assert dispute_response.status_code == 302
        assert app_module.db.session.get(app_module.TournamentMatch, match.id).status == 'disputed'

        admin = app_module.User(
            username='review_admin', email='review_admin@example.com',
            password='hashed', email_verified=True, is_admin=True,
        )
        app_module.db.session.add(admin)
        app_module.db.session.commit()
        admin_client = authenticated_client(admin.id)
        admin_token = csrf_token(admin_client, f'/tournament/{tournament.id}')
        review_response = admin_client.post(
            f'/admin/matches/{match.id}/review-dispute',
            data={'csrf_token': admin_token, 'decision': 'reopen'},
        )

        refreshed_match = app_module.db.session.get(app_module.TournamentMatch, match.id)
        dispute = app_module.TournamentMatchDispute.query.filter_by(match_id=match.id).one()
        assert review_response.status_code == 302
        assert refreshed_match.status == 'ongoing'
        assert refreshed_match.winner_user_id is None
        assert refreshed_match.submitted_by_user_id is None
        assert dispute.status == 'resolved'


def test_free_tournament_member_is_shown_as_registered():
    with app_module.app.app_context():
        tournament = app_module.Tournament(
            name='Free Entry Tournament', game='PUBG', status='open',
            match_time=datetime.utcnow() + timedelta(hours=1),
        )
        user = app_module.User(
            username='free_member', email='free_member@example.com',
            password='hashed', email_verified=True,
        )
        app_module.db.session.add_all([tournament, user])
        app_module.db.session.commit()
        app_module.db.session.add(app_module.UserTournament(
            user_id=user.id, tournament_id=tournament.id, payment_status='free',
        ))
        app_module.db.session.commit()

        client = authenticated_client(user.id)
        response = client.get(f'/tournament/{tournament.id}')

        assert response.status_code == 200
        assert "You're in this tournament" in response.text
        assert 'Join Tournament' not in response.text


def test_dashboard_shows_scheduled_match_and_confirmed_stats():
    with app_module.app.app_context():
        tournament = app_module.Tournament(
            name='Dashboard Tournament', game='eFootball', status='live',
            match_time=datetime.utcnow() + timedelta(hours=2),
        )
        player = app_module.User(
            username='dashboard_player', email='dashboard_player@example.com',
            password='hashed', email_verified=True,
        )
        opponent = app_module.User(
            username='dashboard_opponent', email='dashboard_opponent@example.com',
            password='hashed', email_verified=True,
        )
        app_module.db.session.add_all([tournament, player, opponent])
        app_module.db.session.commit()
        app_module.db.session.add_all([
            app_module.TournamentMatch(
                tournament_id=tournament.id,
                player_one_user_id=player.id,
                player_two_user_id=opponent.id,
                status='scheduled',
            ),
            app_module.TournamentMatch(
                tournament_id=tournament.id,
                player_one_user_id=player.id,
                player_two_user_id=opponent.id,
                submitted_by_user_id=opponent.id,
                winner_user_id=player.id,
                status='confirmed',
            ),
        ])
        app_module.db.session.commit()

        response = authenticated_client(player.id).get('/dashboard')

        assert response.status_code == 200
        assert 'Matches played' in response.text
        assert 'Wins / losses' in response.text
        assert 'Win rate' in response.text
        assert 'dashboard_opponent' in response.text
        assert 'Dashboard Tournament' in response.text


def test_admin_can_login_without_email_verification():
    with app_module.app.test_client() as client:
        with app_module.app.app_context():
            app_module.TournamentMatch.query.delete()
            app_module.TournamentMatchChatMessage.query.delete()
            app_module.GlobalChatMessage.query.delete()
            app_module.UserTournament.query.delete()
            app_module.Tournament.query.delete()
            app_module.User.query.delete()
            app_module.db.session.commit()

            admin_user = app_module.User(
                username='admin_test',
                email='admin_test@example.com',
                password=app_module.generate_password_hash('secure123'),
                is_admin=True,
                email_verified=False,
            )
            app_module.db.session.add(admin_user)
            app_module.db.session.commit()

        login_page = client.get('/login')
        csrf_token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', login_page.text).group(1)
        response = client.post('/login', data={
            'email': 'admin_test@example.com',
            'password': 'secure123',
            'csrf_token': csrf_token,
        }, follow_redirects=False)

        assert response.status_code == 302
        assert '/dashboard' in response.headers['Location']


def test_match_chat_message_is_stored():
    with app_module.app.app_context():
        app_module.TournamentMatch.query.delete()
        app_module.TournamentMatchChatMessage.query.delete()
        app_module.GlobalChatMessage.query.delete()
        app_module.UserTournament.query.delete()
        app_module.Tournament.query.delete()
        app_module.User.query.delete()
        app_module.db.session.commit()

        player_one = app_module.User(username='chat1', email='chat1@test.com', password='hashed', email_verified=True)
        player_two = app_module.User(username='chat2', email='chat2@test.com', password='hashed', email_verified=True)
        app_module.db.session.add_all([player_one, player_two])
        app_module.db.session.commit()

        tournament = app_module.Tournament(name='Chat Tournament', game='Free Fire', entry_fee=1000, prize=5000, max_participants=2)
        app_module.db.session.add(tournament)
        app_module.db.session.commit()

        match = app_module.TournamentMatch(
            tournament_id=tournament.id,
            player_one_user_id=player_one.id,
            player_two_user_id=player_two.id,
            status='scheduled',
        )
        app_module.db.session.add(match)
        app_module.db.session.commit()

        message = app_module.TournamentMatchChatMessage(match_id=match.id, user_id=player_one.id, message='hello there')
        app_module.db.session.add(message)
        app_module.db.session.commit()

        stored = app_module.TournamentMatchChatMessage.query.filter_by(match_id=match.id).all()
        assert len(stored) == 1
        assert stored[0].message == 'hello there'
