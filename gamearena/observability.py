"""Request and database timing without logging bodies, tokens or query strings."""
import os
import re
import secrets
import time
from flask import current_app, g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine


def begin_request_timing():
    g.request_started_at = time.perf_counter()
    g.db_time_ms = 0
    g.db_queries = 0
    candidate = request.headers.get('X-Request-ID', '')
    g.request_id = candidate if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', candidate) else secrets.token_hex(8)


def log_completed_request(response):
    started = getattr(g, 'request_started_at', None)
    if started is not None:
        elapsed = (time.perf_counter() - started) * 1000
        database = getattr(g, 'db_time_ms', 0)
        response.headers['Server-Timing'] = f'app;dur={elapsed:.1f}, db;dur={database:.1f}'
        if not request.path.startswith('/static/'):
            logger = current_app.logger.warning if elapsed >= current_app.config.get('SLOW_REQUEST_MS', 1000) else current_app.logger.info
            logger('request_completed request_id=%s method=%s path=%s status=%s duration_ms=%.2f db_ms=%.2f db_queries=%s',
                   g.request_id, request.method, request.path, response.status_code,
                   elapsed, database, getattr(g, 'db_queries', 0))
    response.headers.setdefault('X-Request-ID', getattr(g, 'request_id', secrets.token_hex(8)))
    return response


def start_query_timing(connection, cursor, statement, parameters, context, executemany):
    if has_request_context():
        context.gamearena_query_start = time.perf_counter()
        g.db_queries = getattr(g, 'db_queries', 0) + 1


def finish_query_timing(connection, cursor, statement, parameters, context, executemany):
    started = getattr(context, 'gamearena_query_start', None)
    if started is not None and has_request_context():
        g.db_time_ms = getattr(g, 'db_time_ms', 0) + (time.perf_counter() - started) * 1000


def init_observability(app):
    app.config['SLOW_REQUEST_MS'] = max(100, int(os.environ.get('SLOW_REQUEST_MS', '1000')))
    app.before_request(begin_request_timing)
    app.after_request(log_completed_request)
    for name, function in [('before_cursor_execute', start_query_timing), ('after_cursor_execute', finish_query_timing)]:
        if not event.contains(Engine, name, function):
            event.listen(Engine, name, function)
