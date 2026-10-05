import html
import unittest
import re
import json
import app as app_module
import db_migrate
import tempfile
import os
from unittest.mock import MagicMock, patch
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
        self.app_context = app.app_context()
        self.app_context.push()
        self.client = app.test_client()

        self.user = User(username='tester', email='tester@example.com')
        self.user.set_password('secret123')
        db.session.add(self.user)
        db.session.commit()

    def csrf_token(self, path='/login'):
        response = self.client.get(path)
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)

    def tearDown(self):
        db.session.remove()
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

    def test_database_uri_is_postgresql_test_database(self):
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        self.assertTrue(uri.lower().startswith(('postgresql://', 'postgres://', 'postgresql+')))

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

    def test_resend_email_provider_request_and_success_logging(self):
        response = MagicMock(status=200)
        response.read.return_value = b'{"id":"email-test-id"}'
        response.getheader.return_value = 'req_test_123'
        with patch.dict(os.environ, {'RESEND_API_KEY': 'test-api-key', 'EMAIL_FROM': 'noreply@example.com'}, clear=True):
            with patch('app.http.client.HTTPSConnection') as https_connection:
                https_connection.return_value.getresponse.return_value = response
                with patch.object(app_module.app.logger, 'info') as info:
                    result = app_module.send_email(
                        'Verification email', 'user@example.com',
                        'Your verification code is 123456.',
                    )

        self.assertTrue(result)
        https_connection.assert_called_once_with(
            'api.resend.com', timeout=app_module.EMAIL_NETWORK_TIMEOUT_SECONDS,
        )
        request_args, request_kwargs = https_connection.return_value.request.call_args
        self.assertEqual(request_args[:2], ('POST', '/emails'))
        self.assertEqual(request_kwargs['headers']['Authorization'], 'Bearer test-api-key')
        payload = json.loads(request_kwargs['body'])
        self.assertEqual(payload['from'], 'noreply@example.com')
        self.assertEqual(payload['to'], 'user@example.com')
        self.assertEqual(payload['text'], 'Your verification code is 123456.')
        log_messages = ' '.join(call.args[0] % call.args[1:] if len(call.args) > 1 else str(call.args[0]) for call in info.call_args_list)
        self.assertIn('recipient_domain=example.com', log_messages)
        self.assertIn('req_test_123', log_messages)
        self.assertNotIn('123456', log_messages)
        self.assertNotIn('test-api-key', log_messages)

    def test_email_provider_rejection_and_timeout_fail_safely(self):
        secret = 'test-api-key-must-not-be-logged'
        response = MagicMock(status=401)
        response.read.return_value = b'{"message":"Unauthorized"}'
        response.getheader.return_value = 'req_rejected'
        with patch.dict(os.environ, {'RESEND_API_KEY': secret}, clear=True):
            with patch('app.http.client.HTTPSConnection') as https_connection:
                https_connection.return_value.getresponse.return_value = response
                with patch.object(app_module.app.logger, 'warning') as warning:
                    rejected = app_module.send_email(
                        'Verification email', 'user@example.com',
                        'Your verification code is 123456.',
                    )
            with patch('app.http.client.HTTPSConnection', side_effect=TimeoutError(secret)):
                with patch.object(app_module.app.logger, 'warning') as timeout_warning:
                    timed_out = app_module.send_email(
                        'Verification email', 'user@example.com',
                        'Your verification code is 123456.',
                    )

        self.assertFalse(rejected)
        self.assertFalse(timed_out)
        messages = ' '.join(
            str(call)
            for call in warning.call_args_list + timeout_warning.call_args_list
        )
        self.assertIn('invalid_api_key', messages)
        self.assertIn('timeout', messages)
        self.assertNotIn(secret, messages)
        self.assertNotIn('123456', messages)

    def test_resend_email_falls_back_to_smtp_after_resend_rejection(self):
        response = MagicMock(status=503)
        response.getheader.return_value = 'req_unavailable'
        with patch.dict(os.environ, {
            'RESEND_API_KEY': 'test-api-key',
            'SMTP_SERVER': 'smtp.test',
            'SMTP_PORT': '587',
            'SMTP_USERNAME': 'test-user',
            'SMTP_PASSWORD': 'test-password',
            'SMTP_USE_TLS': 'true',
        }, clear=True):
            with patch('app.http.client.HTTPSConnection') as https_connection:
                https_connection.return_value.getresponse.return_value = response
                with patch('app.smtplib.SMTP') as smtp:
                    smtp.return_value.__enter__.return_value.send_message.return_value = {}
                    result = app_module.send_email('Subject', 'user@example.com', 'Body')

        self.assertTrue(result)
        smtp.assert_called_once_with(
            'smtp.test', 587, timeout=app_module.EMAIL_NETWORK_TIMEOUT_SECONDS,
        )

    def test_verification_page_loads_and_email_url_verifies_user(self):
        page = self.client.get('/verify-email')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['X-Frame-Options'], 'DENY')

        token = self.csrf_token('/verify-email')
        with patch.object(app_module, 'send_email', return_value=True) as send_email:
            resend = self.client.post('/verify-email', data={
                'action': 'resend', 'email': self.user.email, 'csrf_token': token,
            })
        self.assertEqual(resend.status_code, 302)

        email_body = send_email.call_args.args[2]
        verification_code = self.user.verification_code
        verification_url = re.search(
            r'Open the verification page: (https?://\S+)', email_body,
        ).group(1)
        parsed_url = urlparse(verification_url)
        endpoint, _ = app.url_map.bind(parsed_url.netloc).match(parsed_url.path, method='GET')
        self.assertEqual(endpoint, 'verify_email')

        linked_page = self.client.get(parsed_url.path + '?' + parsed_url.query)
        self.assertEqual(linked_page.status_code, 200)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', linked_page.text).group(1)
        response = self.client.post('/verify-email', data={
            'email': self.user.email,
            'code': verification_code,
            'csrf_token': token,
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.query.get(self.user.id).email_verified)
        self.assertIsNone(User.query.get(self.user.id).verification_code)

        reused = self.client.post('/verify-email', data={
            'email': self.user.email,
            'code': verification_code,
            'csrf_token': token,
        })
        self.assertEqual(reused.status_code, 302)
        self.assertIsNone(User.query.get(self.user.id).verification_code)

    def test_invalid_and_expired_verification_codes_are_rejected(self):
        self.user.verification_code = '111111'
        self.user.verification_expires_at = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()
        token = self.csrf_token('/verify-email')
        invalid = self.client.post('/verify-email', data={
            'email': self.user.email, 'code': '999999', 'csrf_token': token,
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertIn('invalid or has expired', invalid.text)
        self.assertFalse(User.query.get(self.user.id).email_verified)

        self.user.verification_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        with patch.object(app_module, 'send_email') as send_email:
            expired = self.client.post('/verify-email', data={
                'email': self.user.email, 'code': '111111', 'csrf_token': token,
            })

        self.assertEqual(expired.status_code, 200)
        self.assertIn('invalid or has expired', expired.text)
        self.assertEqual(User.query.get(self.user.id).verification_code, '111111')
        self.assertFalse(User.query.get(self.user.id).email_verified)
        send_email.assert_not_called()

    def test_resend_replaces_previous_code_and_reports_delivery(self):
        self.user.verification_code = '111111'
        self.user.verification_expires_at = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()
        token = self.csrf_token('/verify-email')

        with patch.object(app_module, 'generate_code', return_value='222222'):
            with patch.object(app_module, 'send_email', return_value=True) as send_email:
                response = self.client.post('/verify-email', data={
                    'action': 'resend', 'email': self.user.email, 'csrf_token': token,
                })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.query.get(self.user.id).verification_code, '222222')
        self.assertNotEqual(User.query.get(self.user.id).verification_code, '111111')
        send_email.assert_called_once()

    def test_resend_provider_failure_is_not_reported_as_success(self):
        token = self.csrf_token('/verify-email')
        with patch.object(app_module, 'send_email', return_value=False):
            response = self.client.post('/verify-email', data={
                'action': 'resend', 'email': self.user.email, 'csrf_token': token,
            }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("couldn't send the verification email right now", html.unescape(response.text))
        self.assertNotIn('Verification code sent.', response.text)
        self.assertIsNotNone(User.query.get(self.user.id).verification_code)

    def test_verification_resend_still_requires_csrf(self):
        response = self.client.post('/verify-email', data={
            'action': 'resend', 'email': self.user.email,
        })

        self.assertEqual(response.status_code, 400)

    def test_registration_enters_verification_flow_only_with_truthful_mail_status(self):
        token = self.csrf_token('/register')
        with patch.object(app_module, 'send_email', return_value=False) as send_email:
            response = self.client.post('/register', data={
                'username': 'new_player',
                'email': 'new-player@example.com',
                'password': 'secret123',
                'confirm_password': 'secret123',
                'csrf_token': token,
            }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("couldn't send the verification email", html.unescape(response.text))
        new_user = User.query.filter_by(email='new-player@example.com').one()
        self.assertFalse(new_user.email_verified)
        self.assertIsNotNone(new_user.verification_code)
        send_email.assert_called_once()

    def test_password_reset_still_uses_shared_email_sender(self):
        token = self.csrf_token('/forgot-password')
        with patch.object(app_module, 'send_email', return_value=True) as send_email:
            response = self.client.post('/forgot-password', data={
                'email': self.user.email, 'csrf_token': token,
            }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('will be sent if email delivery is available', response.text)
        self.assertIsNotNone(User.query.get(self.user.id).reset_code)
        send_email.assert_called_once()

    def test_rate_limit_cleanup_removes_only_expired_buckets(self):
        old_bucket = RateLimitBucket(bucket_key='old', window_started=datetime.utcnow() - timedelta(hours=3), count=1)
        recent_bucket = RateLimitBucket(bucket_key='recent', window_started=datetime.utcnow(), count=1)
        db.session.add_all([old_bucket, recent_bucket])
        db.session.commit()

        with patch.object(app_module, 'RATE_LIMIT_RETENTION_SECONDS', 60 * 60):
            app_module.cleanup_rate_limit_buckets()

        self.assertIsNone(RateLimitBucket.query.filter_by(bucket_key='old').first())
        self.assertIsNotNone(RateLimitBucket.query.filter_by(bucket_key='recent').first())

    def test_sqlite_schema_migration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database_file = os.path.join(directory, 'migration.db')
            engine = create_engine(f'sqlite:///{database_file}')
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE user_tournament (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, tournament_id INTEGER NOT NULL)'))

            with self.assertRaises(RuntimeError):
                db_migrate.migrate(f'sqlite:///{database_file}')

    def test_sqlite_duplicate_registration_migration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database_file = os.path.join(directory, 'duplicates.db')
            engine = create_engine(f'sqlite:///{database_file}')
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE user_tournament (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, tournament_id INTEGER NOT NULL)'))
                connection.execute(text('INSERT INTO user_tournament (user_id, tournament_id) VALUES (1, 1), (1, 1)'))

            with self.assertRaises(RuntimeError):
                db_migrate.migrate(f'sqlite:///{database_file}')

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
            token = self.csrf_token('/verify-email')
            with patch.object(app_module, 'send_email', return_value=True) as send_email:
                first = self.client.post('/verify-email', data={
                    'action': 'resend', 'email': self.user.email, 'csrf_token': token,
                })
                with patch.object(app_module.time, 'sleep', side_effect=AssertionError('rate limiting must not sleep')):
                    response = self.client.post('/verify-email', data={
                        'action': 'resend', 'email': self.user.email, 'csrf_token': token,
                    })

        self.assertEqual(first.status_code, 302)
        self.assertEqual(response.status_code, 429)
        self.assertGreaterEqual(int(response.headers['Retry-After']), 1)
        self.assertIn('Please wait before requesting another verification code.', response.text)
        send_email.assert_called_once()

    def test_verification_resend_is_limited_by_ip_across_addresses(self):
        with patch.dict(app_module.RATE_LIMITS, {'verification_resend': (1, 60)}, clear=False):
            token = self.csrf_token('/verify-email')
            self.client.post('/verify-email', data={
                'action': 'resend', 'email': 'first@example.com', 'csrf_token': token,
            })
            response = self.client.post('/verify-email', data={
                'action': 'resend', 'email': 'second@example.com', 'csrf_token': token,
            })

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
                mock_post.return_value.status_code = 200
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
            mock_post.return_value.status_code = 200
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
