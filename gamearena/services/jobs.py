"""Optional RQ delivery; jobs carry IDs and token versions, not email codes."""
import hashlib
import hmac
from flask import current_app
from gamearena.services.redis_support import redis_connection


def token_version(code):
    return hmac.new(current_app.secret_key.encode(), (code or '').encode(), hashlib.sha256).hexdigest()


def enqueue_delivery(function, args, job_id, ttl):
    if not current_app.config.get('BACKGROUND_JOBS_ENABLED'):
        return False
    try:
        from rq import Queue, Retry
        from rq.serializers import JSONSerializer
        queue = Queue('gamearena-delivery', connection=redis_connection(current_app.config['JOB_REDIS_URL']), serializer=JSONSerializer)
        queue.enqueue(function, args=args, job_id=job_id, unique=True,
            description='GameArena delivery', job_timeout=60,
            ttl=ttl, result_ttl=60, failure_ttl=3600,
            retry=Retry(max=3, interval=[10, 30, 60]))
        return True
    except ImportError:
        current_app.logger.warning('Delivery queue dependencies unavailable; using existing delivery path.')
        return False
    except Exception as error:
        from rq.exceptions import DuplicateJobError
        if isinstance(error, DuplicateJobError):
            return True
        current_app.logger.warning('Delivery queue unavailable; using existing delivery path (%s).', type(error).__name__)
        return False


def queue_account_email(user, purpose):
    code = user.verification_code if purpose == 'verification' else user.reset_code
    version = token_version(code)
    return enqueue_delivery('gamearena.workers.deliver_account_email',
        (user.id, purpose, version), f'account-{purpose}-{user.id}-{version}', 600)


def queue_push(notification_id):
    return enqueue_delivery('gamearena.workers.deliver_notification_push',
        (notification_id,), f'push-{notification_id}', 300)
