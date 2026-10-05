"""RQ worker entry points. Load current records and recheck their permissions."""
import hmac
from datetime import datetime, timezone
from urllib.parse import quote
from gamearena.services.jobs import token_version


def deliver_account_email(user_id, purpose, version):
    from app import app, db, User
    from gamearena.services.email import send_email, account_email_content
    if purpose not in {'verification', 'reset'}:
        raise ValueError('Unsupported account email purpose.')
    with app.app_context():
        user = db.session.get(User, user_id)
        if not user:
            return
        code = user.verification_code if purpose == 'verification' else user.reset_code
        expiry = user.verification_expires_at if purpose == 'verification' else user.reset_expires_at
        if not code or not expiry or expiry <= datetime.now(timezone.utc).replace(tzinfo=None) or not hmac.compare_digest(token_version(code), version):
            return  # Expired, verified or superseded by a resend.
        if purpose == 'verification' and user.email_verified:
            return
        link = app.config['PUBLIC_BASE_URL'] + '/verify-email?email=' + quote(user.email)
        subject, body = account_email_content(user, purpose, link)
        if not send_email(subject, user.email, body, idempotency_key=f'gamearena-account/{user_id}/{purpose}/{version}'):
            raise RuntimeError('Account email provider did not accept delivery.')


def deliver_notification_push(notification_id):
    from app import app, db, Notification, PushSubscription, UserSettings
    from web_push import deliver_push
    with app.app_context():
        record = db.session.get(Notification, notification_id)
        if not record:
            return
        preferences = db.session.query(UserSettings).filter_by(user_id=record.user_id).first()
        names = {'chat':'chat_notifications', 'match':'match_notifications',
                 'wallet':'wallet_notifications', 'tournament':'tournament_notifications',
                 'marketing':'marketing_notifications'}
        if preferences and record.category in names and not getattr(preferences, names[record.category]):
            return
        subscriptions = [item.subscription for item in PushSubscription.query.filter_by(user_id=record.user_id).all()]
        outcome = deliver_push(subscriptions, {'title':'GameArena', 'body':record.message,
            'url':record.target_url or '/notifications', 'id':record.id}, app.logger)
        if outcome and outcome.get('retry'):
            raise RuntimeError('Push provider temporarily unavailable.')
