# Render timeout investigation and local server fix

The supplied October 5 logs show successful migration and worker startup, HTTP 200 health checks, two SIGTERM events, a late SSL monkey-patching warning, and slow requests. They do not include the failed health request or a crash traceback; the reason for the SIGTERM events is not established. Messages page took 4.410 seconds / 18 queries, dashboard about 2.3 seconds / 12 queries. SQL timing excludes connection acquisition, so total minus SQL time is not purely Python processing.

## Implemented

- `scripts/serve.py` patches gevent before importing Gunicorn/application dependencies, then registers psycogreen's psycopg2 wait callback. This lets database waits yield to other greenlets.
- requirements pins psycogreen 1.0.2. Existing psycopg2, SQLAlchemy, one WebSocket worker, worker timeout, and default NullPool remain.
- Procfile/Render Blueprint use the new launcher; migrations still run separately and `/health` still checks the database. No schema/financial changes.
- CI includes the Linux Gunicorn configuration check; a subprocess regression test exercises actual isolated PostgreSQL I/O and a Flask health request while another connection runs pg_sleep.

## Live application

No live settings changed or deployment performed. A saved Render dashboard start command does not automatically follow a repository Blueprint file. After the code and dependency are deployed, the web service must use:

```sh
python scripts/migrate.py && python scripts/serve.py --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --timeout 120 --bind 0.0.0.0:$PORT app:app
```

Requires authorized deployment/start-command update. Monitor startup, health, chat HTTP + WebSocket, authentication and payment initialization after release without submitting real payments. These fixes address confirmed code hazards, not a proven complete root cause for the observed outage. Database/network latency and repeated queries remain; no production load or Linux Gunicorn runtime test has been run locally on Windows.

Sources: https://www.gevent.org/api/gevent.monkey.html ; https://www.psycopg.org/docs/advanced.html ; https://github.com/psycopg/psycogreen ; https://render.com/docs/health-checks

## Validation completed

20 targeted tests passed (server concurrency, infrastructure, chat outbox), 17 existing deprecation/cache warnings. The first attempt could not connect to the stopped isolated test database; after restarting that local database the suite passed in 91.02 seconds. The cooperative subprocess health check passed during an unrelated pg_sleep, with no MonkeyPatchWarning. Python compilation, pip check and git diff --check passed. Gunicorn is Linux-only and its actual production process was not run locally; the new Linux CI startup check is authored but not executed here.
