"""Legacy queue launcher. GameArena currently uses its shared synchronous mail service.

There is no configured Celery app or durable broker in this project. This helper
does not import/start the web app or imply messages have been queued.
"""
if __name__ == '__main__':
    print('No background queue is configured. See app.send_email for current delivery.')
