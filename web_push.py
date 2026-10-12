"""Optional standards-based Web Push; never expose VAPID private keys to clients."""
import json
import os
from urllib.parse import urlparse


def push_configured():
    return all(os.environ.get(name) for name in ('VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT'))


def public_key_configuration(value=None):
    """Validate only the PUBLIC setting; diagnostics never include key material."""
    import base64
    import re
    value = os.environ.get('VAPID_PUBLIC_KEY', '') if value is None else value
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    value = re.sub(r'\s+', '', value)
    status = {'valid': False, 'characters': len(value), 'decoded_bytes': None}
    if not value:
        status['error'] = 'The server public notification key is missing.'
        return '', status
    if not re.fullmatch(r'[A-Za-z0-9_+/=-]+', value):
        status['error'] = 'The server public notification key contains invalid characters.'
        return '', status
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, base64.binascii.Error):
        status['error'] = 'The server public notification key is not valid Base64.'
        return '', status
    status['decoded_bytes'] = len(raw)
    if len(raw) != 65 or raw[0] != 4:
        status['error'] = f'The server public notification key decodes to {len(raw)} bytes; a 65-byte uncompressed P-256 public key is required.'
        return '', status
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        status['error'] = 'The server public notification key is not a valid P-256 curve point.'
        return '', status
    status['valid'] = True
    return base64.urlsafe_b64encode(raw).decode().rstrip('='), status


def valid_subscription(value):
    if not isinstance(value, dict):
        return False
    endpoint = value.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2000:
        return False
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or ''
    except ValueError:
        return False
    trusted = host in {'fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com'} or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
    try:
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    keys = value.get('keys', {})
    import re
    return bool(parsed.scheme == 'https' and trusted and not parsed.username and not parsed.password and
        isinstance(keys, dict) and all(isinstance(keys.get(key), str) and re.fullmatch(r'[A-Za-z0-9_-]{16,160}=?=?',keys[key]) for key in ('p256dh','auth')))


def deliver_push(subscriptions, payload, logger):
    if not push_configured():
        return
    from pywebpush import webpush, WebPushException
    retry = False
    expired = []
    for subscription in subscriptions:
        try:
            webpush(subscription_info=subscription, data=json.dumps(payload),
                vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],
                vapid_claims={'sub':os.environ['VAPID_SUBJECT']}, timeout=10, ttl=3600)
        except WebPushException as error:
            # Provider endpoints and encryption credentials are deliberately not logged.
            status = getattr(error.response, 'status_code', None)
            logger.warning('Push delivery failed (status=%s).', status)
            if status in (404, 410):
                import hashlib
                expired.append(hashlib.sha256(subscription['endpoint'].encode()).hexdigest())
            retry = retry or status is None or status == 429 or status >= 500
        except Exception as error:
            logger.warning('Push delivery failed (%s).', type(error).__name__)
            retry = True
    return {'retry': retry, 'expired': expired}
