import unittest
import re
import app as app_module
import db_migrate
import tempfile
import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine, inspect, text
from datetime import datetime, timedelta

from app import (
    app,
    db,
    Notification,
    Tournament,
    User,
    UserTournament,
    RateLimitBucket,
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

    def csrf_token(self, path='/login'):
        response = self.client.get(path)
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)

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

    def test_health_endpoint_returns_minimal_database_ready_response(self):
        response = self.client.get('/health')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'status': 'ok'})
        self.assertNotIn('SECRET_KEY', response.text)
        self.assertNotIn('DATABASE_URL', response.text)

    def test_health_endpoint_returns_safe_error_when_database_is_unavailable(self):
        with patch.object(app_module.db.session, 'execute', side_effect=RuntimeError('database details')):
            response = self.client.get('/health')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {'status': 'unavailable'})
        self.assertNotIn('database details', response.text)

    def test_email_logging_never_includes_message_body_or_code(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app_module.app.logger, 'info') as info, patch.object(app_module.app.logger, 'warning') as warning:
            result = app_module.send_email('Verification email', 'user@example.com', 'Your verification code is 123456.')

        messages = [str(call) for call in info.call_args_list + warning.call_args_list]
        self.assertFalse(result)
        self.assertNotIn('123456', ' '.join(messages))
        self.assertNotIn('Verification code is', ' '.join(messages))

    def test_rate_limit_cleanup_removes_only_expired_buckets(self):
        old_bucket = RateLimitBucket(bucket_key='old', window_started=datetime.utcnow() - timedelta(hours=3), count=1)
        recent_bucket = RateLimitBucket(bucket_key='recent', window_started=datetime.utcnow(), count=1)
        db.session.add_all([old_bucket, recent_bucket])
        db.session.commit()

        with patch.object(app_module, 'RATE_LIMIT_RETENTION_SECONDS', 60 * 60):
            app_module.cleanup_rate_limit_buckets()

        self.assertIsNone(RateLimitBucket.query.filter_by(bucket_key='old').first())
        self.assertIsNotNone(RateLimitBucket.query.filter_by(bucket_key='recent').first())

    def test_local_schema_migration_is_idempotent_and_adds_required_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            database_file = os.path.join(directory, 'migration.db')
            engine = create_engine(f'sqlite:///{database_file}')
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE user_tournament (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, tournament_id INTEGER NOT NULL)'))

            db_migrate.migrate(f'sqlite:///{database_file}')
            db_migrate.migrate(f'sqlite:///{database_file}')

            with engine.connect() as connection:
                inspector = inspect(connection)
                self.assertTrue(inspector.has_table('rate_limit_bucket'))
                indexes = inspector.get_indexes('user_tournament')
                self.assertTrue(any(index['name'] == db_migrate.CONSTRAINT_NAME and index['unique'] for index in indexes))

    def test_local_schema_migration_stops_on_duplicate_registrations(self):
        with tempfile.TemporaryDirectory() as directory:
            database_file = os.path.join(directory, 'duplicates.db')
            engine = create_engine(f'sqlite:///{database_file}')
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE user_tournament (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, tournament_id INTEGER NOT NULL)'))
                connection.execute(text('INSERT INTO user_tournament (user_id, tournament_id) VALUES (1, 1), (1, 1)'))

            with self.assertRaises(RuntimeError):
                db_migrate.migrate(f'sqlite:///{database_file}')

            with engine.connect() as connection:
                indexes = inspect(connection).get_indexes('user_tournament')
                self.assertFalse(any(index['name'] == db_migrate.CONSTRAINT_NAME for index in indexes))

    def test_security_headers_on_normal_response(self):
        response = self.client.get('/')

        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['Referrer-Policy'], 'strict-origin-when-cross-origin')
        self.assertIn("default-src 'self'", response.headers['Content-Security-Policy'])
        self.assertNotIn("'unsafe-eval'", response.headers['Content-Security-Policy'])
        self.assertEqual(
            response.headers['Permissions-Policy'],
            'camera=(), microphone=(), geolocation=(), payment=(self "https://checkout.paystack.com")',
        )
        self.assertNotIn('Strict-Transport-Security', response.headers)

    def test_authenticated_sensitive_response_is_not_cached(self):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.user.id)
            session['_fresh'] = True

        response = self.client.get('/wallet')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response.headers['Pragma'], 'no-cache')
        self.assertEqual(response.headers['Expires'], '0')

    def test_security_headers_are_added_to_error_responses(self):
        response = self.client.get('/route-that-does-not-exist')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    def test_hsts_is_only_added_for_production_https_requests(self):
        with patch.object(app_module, 'is_production', False):
            development_response = self.client.get('/', headers={'X-Forwarded-Proto': 'https'})
        self.assertNotIn('Strict-Transport-Security', development_response.headers)

        with patch.object(app_module, 'is_production', True):
            production_response = self.client.get('/', headers={'X-Forwarded-Proto': 'https'})
        self.assertEqual(
            production_response.headers['Strict-Transport-Security'],
            'max-age=31536000',
        )

    def test_login_rate_limit_returns_429_with_retry_after(self):
        token = self.csrf_token()
        with patch.dict(app_module.RATE_LIMITS, {'login_ip': (1, 60), 'login_account': (1, 60)}, clear=False):
            self.client.post('/login', data={'email': 'unknown@example.com', 'password': 'wrong', 'csrf_token': token})
            response = self.client.post('/login', data={'email': 'unknown@example.com', 'password': 'wrong', 'csrf_token': token})

        self.assertEqual(response.status_code, 429)
        self.assertGreaterEqual(int(response.headers['Retry-After']), 1)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_registration_and_password_reset_rate_limits(self):
        with patch.dict(app_module.RATE_LIMITS, {'register_ip': (1, 60), 'password_reset_ip': (1, 60)}, clear=False):
            register_token = self.csrf_token('/register')
            self.client.post('/register', data={'username': 'new-user', 'email': 'new@example.com', 'password': 'secret123', 'confirm_password': 'secret123', 'csrf_token': register_token})
            register_response = self.client.post('/register', data={'username': 'new-user-2', 'email': 'new2@example.com', 'password': 'secret123', 'confirm_password': 'secret123', 'csrf_token': register_token})
            reset_token = self.csrf_token('/forgot-password')
            self.client.post('/forgot-password', data={'email': 'unknown@example.com', 'csrf_token': reset_token})
            reset_response = self.client.post('/forgot-password', data={'email': 'unknown2@example.com', 'csrf_token': reset_token})

        self.assertEqual(register_response.status_code, 429)
        self.assertEqual(reset_response.status_code, 429)

    def test_verification_resend_rate_limit_returns_429(self):
        with patch.dict(app_module.RATE_LIMITS, {'verification_resend': (1, 60)}, clear=False):
            self.client.get('/verify-email?email=unknown@example.com&resend=1')
            response = self.client.get('/verify-email?email=unknown@example.com&resend=1')

        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response.headers)

    def test_verification_resend_is_limited_by_ip_across_addresses(self):
        with patch.dict(app_module.RATE_LIMITS, {'verification_resend': (1, 60)}, clear=False):
            self.client.get('/verify-email?email=first@example.com&resend=1')
            response = self.client.get('/verify-email?email=second@example.com&resend=1')

        self.assertEqual(response.status_code, 429)

    def test_payment_rate_limits_apply_to_initialization_and_verification(self):
        tournament = Tournament(name='Rate Cup', game='PUBG', entry_fee=1000, max_participants=10)
        db.session.add(tournament)
        db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.user.id)
            session['_fresh'] = True

        with patch.dict(app_module.RATE_LIMITS, {'payment_user': (1, 60), 'payment_verification': (1, 60)}, clear=False):
            token = self.csrf_token('/wallet')
            with patch('app.requests.post') as mock_post:
                mock_post.return_value.json.return_value = {'status': True, 'data': {'authorization_url': 'https://paystack.test/pay'}}
                first = self.client.post(f'/initialize-payment/{tournament.id}', data={'csrf_token': token})
                second = self.client.post(f'/initialize-payment/{tournament.id}', data={'csrf_token': token})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 429)

            join = UserTournament.query.filter_by(user_id=self.user.id, tournament_id=tournament.id).first()
            with patch('app.verify_paystack_reference', return_value=None):
                self.client.get(f'/verify-payment?reference={join.transaction_ref}')
                verification_response = self.client.get(f'/verify-payment?reference={join.transaction_ref}')

        self.assertEqual(verification_response.status_code, 429)
        self.assertEqual(verification_response.headers['X-Frame-Options'], 'DENY')

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
                login_response = self.client.get('/login/google', follow_redirects=False)
                state = parse_qs(urlparse(login_response.headers['Location']).query)['state'][0]
                mock_post.return_value.json.return_value = {'access_token': 'google-token'}
                mock_get.return_value.json.return_value = {
                    'email': 'googleuser@example.com',
                    'name': 'Google User',
                    'picture': 'https://example.com/avatar.png'
                }

                response = self.client.get(f'/auth/google/callback?code=test-code&state={state}', follow_redirects=False)

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

        wallet_page = self.client.get('/wallet')
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', wallet_page.text).group(1)

        with patch('app.requests.post') as mock_post:
            mock_post.return_value.json.return_value = {
                'status': True,
                'data': {'authorization_url': 'https://paystack.test/pay'},
            }
            response = self.client.post(f'/initialize-payment/{tournament.id}', data={'csrf_token': csrf_token})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('authorization_url', data)

        updated_join = UserTournament.query.get(pending_join.id)
        self.assertEqual(updated_join.payment_status, 'pending')
        self.assertNotEqual(updated_join.transaction_ref, 'old-ref')

    def test_google_callback_requires_oauth_state(self):
        with patch.dict('os.environ', {'GOOGLE_CLIENT_ID': 'test-client-id'}, clear=False):
            response = self.client.get('/auth/google/callback?code=test-code', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_user_tournament_registration_is_unique(self):
        tournament = Tournament(name='Unique Cup', game='PUBG', entry_fee=1000)
        db.session.add(tournament)
        db.session.commit()
        db.session.add(UserTournament(user_id=self.user.id, tournament_id=tournament.id, payment_status='pending'))
        db.session.commit()

        db.session.add(UserTournament(user_id=self.user.id, tournament_id=tournament.id, payment_status='pending'))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_wallet_transaction_reference_is_unique(self):
        from app import WalletTransaction

        first = WalletTransaction(user_id=self.user.id, type='deposit', amount=100, transaction_ref='same-ref')
        db.session.add(first)
        db.session.commit()
        db.session.add(WalletTransaction(user_id=self.user.id, type='deposit', amount=100, transaction_ref='same-ref'))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_wallet_payment_processing_is_idempotent(self):
        from app import WalletTransaction, apply_wallet_deposit

        wallet_transaction = WalletTransaction(
            user_id=self.user.id,
            type='deposit',
            amount=500,
            status='pending',
            transaction_ref='wallet-test-ref',
        )
        db.session.add(wallet_transaction)
        db.session.commit()
        transaction = {
            'reference': 'wallet-test-ref',
            'amount': 50000,
            'currency': 'NGN',
            'metadata': {'user_id': self.user.id, 'type': 'wallet_deposit'},
        }

        self.assertEqual(apply_wallet_deposit(wallet_transaction, transaction)[1], 'processed')
        self.assertEqual(apply_wallet_deposit(wallet_transaction, transaction)[1], 'already_processed')
        self.assertEqual(User.query.get(self.user.id).wallet_balance, 500)


if __name__ == '__main__':
    unittest.main()
