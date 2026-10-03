"""Optional standards-based Web Push; never expose VAPID private keys to clients."""
import json
import os
from urllib.parse import urlparse


def push_configured():
    return all(os.environ.get(name) for name in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'))


def valid_subscription(value):
    if not isinstance(value, dict):
        return False
    endpoint = value.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2000:
        return False
    parsed = urlparse(endpoint)
    host = parsed.hostname or ''
    trusted = host in {'fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'} or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
    keys = value.get('keys', {})
    import re
    return bool(parsed.scheme == 'https' and trusted and not parsed.username and not parsed.password and
        isinstance(keys, dict) and all(isinstance(keys.get(key), str) and re.fullmatch(r'[A-Za-z0-9_-]{16,160}=?=?',keys[key]) for key in ('p256dh','auth')))


def deliver_push(subscriptions, payload, logger):
    if not push_configured():
        return
    from pywebpush import webpush, WebPushException
    for subscription in subscriptions:
        try:
            webpush(subscription_info=subscription, data=json.dumps(payload),
                vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],
                vapid_claims={'sub':os.environ['VAPID_SUBJECT']}, timeout=10, ttl=300)
        except WebPushException as error:
            # Provider endpoints and encryption credentials are deliberately not logged.
            logger.warning('Push delivery failed (status=%s).', getattr(error.response,'status_code',None))
