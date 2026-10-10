"""Schedule every minute: python scripts/master_reminders.py. No emails or payments."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import app, socketio, get_unread_notification_count
from gamearena.pro import deliver_due_reminders
from gamearena.services.jobs import queue_push
from web_push import push_configured, deliver_push
from gamearena.models import PushSubscription
with app.app_context():
    notifications = deliver_due_reminders()
    for notification in notifications:
        socketio.emit('notification', {'id':notification.id,'message':notification.message,'category':notification.category,'target_url':notification.target_url}, room=f'user:{notification.user_id}')
        socketio.emit('notification_unread_count', {'unread':get_unread_notification_count(notification.user_id)}, room=f'user:{notification.user_id}')
        if push_configured() and not queue_push(notification.id):
            subscriptions = [row.subscription for row in PushSubscription.query.filter_by(user_id=notification.user_id).all()]
            deliver_push(subscriptions, {'title':'GameArena','body':notification.message,'url':notification.target_url}, app.logger)
    print(f'Created {len(notifications)} tournament reminders.')
