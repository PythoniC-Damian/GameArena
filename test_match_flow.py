import importlib
import re

app_module = importlib.import_module('app')


def test_create_tournament_matches_pairs_participants():
    with app_module.app.app_context():
        app_module.TournamentMatch.query.delete()
        app_module.TournamentMatchChatMessage.query.delete()
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


def test_admin_can_login_without_email_verification():
    with app_module.app.test_client() as client:
        with app_module.app.app_context():
            app_module.TournamentMatch.query.delete()
            app_module.TournamentMatchChatMessage.query.delete()
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
