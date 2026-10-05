"""Isolated infrastructure contracts; no live provider or Redis calls."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
import json
import pytest
import fakeredis
from app import app, db, User, Tournament, socketio
from gamearena.database import engine_options
from gamearena.services import jobs, redis_support
from gamearena.workers import deliver_account_email
from test_interface_contracts import player, client, event


@pytest.fixture
def shared(monkeypatch):
    connection = fakeredis.FakeRedis()
    monkeypatch.setattr(redis_support, 'redis_connection', lambda url: connection)
    monkeypatch.setattr(jobs, 'redis_connection', lambda url: connection)
    for key in ['CACHE_REDIS_URL', 'JOB_REDIS_URL', 'SOCKET_RATE_LIMIT_REDIS_URL']:
        monkeypatch.setitem(app.config, key, 'redis://isolated-fake/15')
    monkeypatch.setitem(app.config, 'CACHE_NAMESPACE', 'isolated-test')
    return connection


def test_public_cache_shared_between_clients_and_never_contains_account_data(shared):
    with app.app_context():
        owner = player('cache_owner'); tournament = event()
        guest = app.test_client(); signed_in = client(owner)
        first = guest.get('/api/v1/tournaments')
        assert first.status_code == 200 and first.json['data'][0]['id'] == tournament.id
        cached = signed_in.get('/api/v1/tournaments')
        assert cached.headers['X-GameArena-Cache'] == 'hit'
        assert 'no-store' in cached.headers['Cache-Control']
        assert cached.json == first.json
        assert owner.email.encode() not in cached.data
        assert signed_in.get('/profile').headers.get('X-GameArena-Cache') is None


def test_cache_outage_falls_back_without_hiding_real_tournament_data(shared, monkeypatch):
    shared.get = Mock(side_effect=ConnectionError())
    shared.setex = Mock(side_effect=ConnectionError())
    with app.app_context():
        tournament = event()
        result = app.test_client().get('/api/v1/tournaments')
        assert result.status_code == 200 and result.json['data'][0]['id'] == tournament.id


def test_invalid_public_requests_are_not_cached(shared):
    result = app.test_client().get('/api/v1/tournaments?status=invalid')
    assert result.status_code == 400
    assert list(shared.scan_iter('isolated-test:public:*')) == []


def test_atomic_limiter_shares_budget_across_clients_and_fails_closed(shared):
    with app.app_context():
        assert redis_support.shared_socket_allowed(1, 'send', 2, 10)
        assert redis_support.shared_socket_allowed(1, 'send', 2, 10)
        assert not redis_support.shared_socket_allowed(1, 'send', 2, 10)
        assert redis_support.shared_socket_allowed(2, 'send', 2, 10)
        shared.eval = Mock(side_effect=ConnectionError())
        assert not redis_support.shared_socket_allowed(3, 'send', 2, 10)


def test_queue_stores_only_id_purpose_and_version_and_deduplicates(shared, monkeypatch):
    from rq import Queue
    from rq.serializers import JSONSerializer
    monkeypatch.setitem(app.config, 'BACKGROUND_JOBS_ENABLED', True)
    with app.app_context():
        user = player('queued_mail'); user.verification_code = '123456'
        user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()
        assert jobs.queue_account_email(user, 'verification')
        assert jobs.queue_account_email(user, 'verification')
        queue = Queue('gamearena-delivery', connection=shared, serializer=JSONSerializer)
        assert queue.count == 1
        job = queue.jobs[0]
        assert list(job.args[:2]) == [user.id, 'verification']
        assert '123456' not in str(job.args) and user.email not in str(job.args)
        assert job.retries_left == 3
        assert job.failure_ttl == 3600


@pytest.mark.parametrize('state', ['superseded', 'expired', 'verified', 'deleted'])
def test_worker_skips_invalid_account_code(state, monkeypatch):
    delivery = Mock(return_value=True)
    monkeypatch.setattr('gamearena.services.email.send_email', delivery)
    with app.app_context():
        user = player('stale_mail'); user.email_verified = False
        user.verification_code = '123456'; user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
        version = jobs.token_version(user.verification_code); user_id = user.id
        if state == 'superseded': user.verification_code = '654321'
        if state == 'expired': user.verification_expires_at = datetime.utcnow() - timedelta(seconds=1)
        if state == 'verified': user.email_verified = True
        if state == 'deleted': db.session.delete(user)
        db.session.commit()
        deliver_account_email(user_id, 'verification', version)
        assert not delivery.called


def test_worker_provider_failure_is_retryable_and_uses_stable_idempotency(monkeypatch):
    delivery = Mock(return_value=False)
    monkeypatch.setattr('gamearena.services.email.send_email', delivery)
    with app.app_context():
        user = player('retry_mail'); user.email_verified = False
        user.verification_code = '123456'; user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit(); version = jobs.token_version(user.verification_code)
        with pytest.raises(RuntimeError, match='did not accept'):
            deliver_account_email(user.id, 'verification', version)
        key = delivery.call_args.kwargs['idempotency_key']
        delivery.return_value = True
        deliver_account_email(user.id, 'verification', version)
        assert key == delivery.call_args.kwargs['idempotency_key']


def test_queue_outage_uses_existing_synchronous_email(shared, monkeypatch):
    from app import send_verification_code
    monkeypatch.setitem(app.config, 'BACKGROUND_JOBS_ENABLED', True)
    shared.pipeline = Mock(side_effect=ConnectionError())
    delivery = Mock(return_value=True); monkeypatch.setattr('app.send_email', delivery)
    with app.test_request_context('/'):
        user = player('fallback_mail')
        assert send_verification_code(user)
        assert delivery.called


def test_queued_email_executes_in_worker(shared, monkeypatch):
    from rq import Queue, SimpleWorker
    from rq.serializers import JSONSerializer
    from rq.timeouts import TimerDeathPenalty
    class LocalWorker(SimpleWorker):
        death_penalty_class = TimerDeathPenalty
    delivery = Mock(return_value=True)
    monkeypatch.setattr('gamearena.services.email.send_email', delivery)
    monkeypatch.setitem(app.config, 'BACKGROUND_JOBS_ENABLED', True)
    with app.app_context():
        user = player('executed_mail'); user.email_verified = False
        user.verification_code = '123456'
        user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()
        assert jobs.queue_account_email(user, 'verification')
        queue = Queue('gamearena-delivery', connection=shared, serializer=JSONSerializer)
        job = queue.jobs[0]
        LocalWorker([queue], connection=shared, serializer=JSONSerializer).work(burst=True)
        assert job.get_status(refresh=True) == 'finished'
        assert delivery.call_count == 1


def test_push_worker_respects_changed_preferences_and_retries_transient_failure(monkeypatch):
    from app import Notification, UserSettings
    from gamearena.workers import deliver_notification_push
    delivery = Mock(return_value={'retry':True})
    monkeypatch.setattr('web_push.deliver_push', delivery)
    with app.app_context():
        owner = player('push_worker')
        preferences = UserSettings(user_id=owner.id, chat_notifications=False)
        record = Notification(user_id=owner.id, category='chat', message='Test message')
        db.session.add_all([preferences, record]); db.session.commit()
        deliver_notification_push(record.id)
        assert not delivery.called
        preferences.chat_notifications = True; db.session.commit()
        with pytest.raises(RuntimeError, match='temporarily unavailable'):
            deliver_notification_push(record.id)


def test_pool_configuration_preserves_default_and_bounds_opt_in_pool():
    from sqlalchemy.pool import NullPool, QueuePool
    assert engine_options({})['poolclass'] is NullPool
    options = engine_options({'DATABASE_POOL_MODE':'queue'})
    assert options['poolclass'] is QueuePool and options['max_overflow'] == 0
    with pytest.raises(ValueError): engine_options({'DATABASE_POOL_MODE':'queue','DATABASE_POOL_SIZE':'100'})
    with pytest.raises(ValueError): engine_options({'DATABASE_POOL_MODE':'unknown'})


def test_legacy_api_url_names_and_request_id_are_preserved():
    from flask import url_for
    with app.test_request_context('/'):
        assert url_for('api_tournaments') == '/api/v1/tournaments'
    result = app.test_client().get('/api/v1/tournaments', headers={'X-Request-ID':'unsafe id with spaces'})
    assert ' ' not in result.headers['X-Request-ID']
    assert 'db;dur=' in result.headers['Server-Timing']


def test_asset_manifest_and_no_build_fallback(tmp_path, monkeypatch):
    from gamearena.assets import frontend_assets
    monkeypatch.setattr(app, 'static_folder', str(tmp_path))
    with app.test_request_context('/'):
        assert frontend_assets() is None
        (tmp_path/'build/.vite').mkdir(parents=True)
        (tmp_path/'build/assets').mkdir()
        (tmp_path/'build/assets/hero.js').write_text('')
        (tmp_path/'build/.vite/manifest.json').write_text(json.dumps({'frontend/carousels.ts':{'file':'assets/hero.js'}}))
        assert frontend_assets()['script'] == '/static/build/assets/hero.js'
        (tmp_path/'build/.vite/manifest.json').write_text('[]')
        assert frontend_assets() is None


def test_queue_pool_reuses_a_local_database_connection():
    import os
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ['GAMEARENA_TEST_DATABASE_URL'],
        **engine_options({'DATABASE_POOL_MODE':'queue', 'DATABASE_POOL_SIZE':'1'}))
    try:
        with engine.connect() as connection:
            first = connection.execute(text('SELECT pg_backend_pid()')).scalar()
        with engine.connect() as connection:
            second = connection.execute(text('SELECT pg_backend_pid()')).scalar()
        assert first == second
    finally:
        engine.dispose()
