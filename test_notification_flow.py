import unittest
from unittest.mock import patch

from app import (
    app,
    db,
    Notification,
    Tournament,
    User,
    UserTournament,
    get_unread_notification_count,
    mark_notifications_read_for_user,
)


class NotificationFlowTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.app_context = app.app_context()
        self.app_context.push()
        self.client = app.test_client()
        db.drop_all()
        db.create_all()

        self.user = User(username='tester', email='tester@example.com')
        self.user.set_password('secret123')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_only_count_does_not_mark_notifications_as_read(self):
        notification = Notification(user_id=self.user.id, message='Welcome')
        db.session.add(notification)
        db.session.commit()

        count = mark_notifications_read_for_user(self.user.id, only_count=True)

        self.assertEqual(count, 1)
        self.assertEqual(get_unread_notification_count(self.user.id), 1)
        self.assertIsNone(Notification.query.get(notification.id).read_at)

    def test_marking_read_updates_unread_count(self):
        notification = Notification(user_id=self.user.id, message='Welcome')
        db.session.add(notification)
        db.session.commit()

        count = mark_notifications_read_for_user(self.user.id, only_count=False)

        self.assertEqual(count, 0)
        self.assertEqual(get_unread_notification_count(self.user.id), 0)
        self.assertIsNotNone(Notification.query.get(notification.id).read_at)

    def test_database_uri_is_project_local(self):
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        self.assertTrue('instance' in uri or 'memory' in uri or uri.endswith('.db'))

    def test_google_login_redirects_to_google_authorization(self):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.user.id)
            session['_fresh'] = True

        with patch.dict('os.environ', {'GOOGLE_CLIENT_ID': 'test-client-id'}, clear=False):
            response = self.client.get('/login/google', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('accounts.google.com/o/oauth2/v2/auth', response.headers['Location'])
        self.assertIn('client_id=test-client-id', response.headers['Location'])

    def test_google_callback_creates_or_logs_in_user(self):
        with patch.dict('os.environ', {'GOOGLE_CLIENT_ID': 'test-client-id', 'GOOGLE_CLIENT_SECRET': 'test-secret'}, clear=False):
            with patch('app.requests.post') as mock_post, patch('app.requests.get') as mock_get:
                mock_post.return_value.json.return_value = {'access_token': 'google-token'}
                mock_get.return_value.json.return_value = {
                    'email': 'googleuser@example.com',
                    'name': 'Google User',
                    'picture': 'https://example.com/avatar.png'
                }

                response = self.client.get('/auth/google/callback?code=test-code', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.headers['Location'])

        user = User.query.filter_by(email='googleuser@example.com').first()
        self.assertIsNotNone(user)
        self.assertTrue(user.email_verified)

    def test_initialize_payment_reuses_pending_join_record(self):
        tournament = Tournament(
            name='Free Fire Cup',
            game='Free Fire',
            entry_fee=2000,
            prize=10000,
            max_participants=10,
        )
        db.session.add(tournament)
        db.session.commit()

        pending_join = UserTournament(
            user_id=self.user.id,
            tournament_id=tournament.id,
            payment_status='pending',
            transaction_ref='old-ref',
            amount_paid=tournament.entry_fee,
        )
        db.session.add(pending_join)
        db.session.commit()

        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.user.id)
            session['_fresh'] = True

        with patch('app.requests.post') as mock_post:
            mock_post.return_value.json.return_value = {
                'status': True,
                'data': {'authorization_url': 'https://paystack.test/pay'},
            }
            response = self.client.post(f'/initialize-payment/{tournament.id}')

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('authorization_url', data)

        updated_join = UserTournament.query.get(pending_join.id)
        self.assertEqual(updated_join.payment_status, 'pending')
        self.assertNotEqual(updated_join.transaction_ref, 'old-ref')


if __name__ == '__main__':
    unittest.main()
