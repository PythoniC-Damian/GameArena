web: python scripts/migrate.py && python scripts/serve.py --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --timeout 120 --bind 0.0.0.0:$PORT app:app
