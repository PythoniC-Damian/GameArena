"""Private/group notification switches are checked at enqueue and delivery."""
def chat_alert_allowed(preferences,target_url):
    if not preferences:return True
    if not preferences.chat_notifications:return False
    name='group_chat_notifications' if (target_url or '').startswith(('/chat','/tournament/','/match/')) else 'private_chat_notifications'
    return bool(getattr(preferences,name,True))
