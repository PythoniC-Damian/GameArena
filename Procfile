web: python db_migrate.py && gunicorn --worker-class gevent -w 1 --timeout 120 --bind 0.0.0.0:$PORT app:app
