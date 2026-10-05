web: python scripts/migrate.py && gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --timeout 120 --bind 0.0.0.0:$PORT app:app
