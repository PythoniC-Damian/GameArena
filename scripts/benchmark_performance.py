"""Compare local fixture routes with the checked-in baseline, never production.

GAMEARENA_BENCHMARK_DATABASE_URL must use loopback and a database ending in
_preview, _perf or _test. Fixtures are added only; no live credentials are read.
"""
import ast
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from urllib.parse import urlparse

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
database = os.environ.get('GAMEARENA_BENCHMARK_DATABASE_URL', '')
parsed = urlparse(database)
if (parsed.scheme not in {'postgresql', 'postgres'} or parsed.hostname not in {'localhost', '127.0.0.1'}
        or not parsed.path.endswith(('_preview', '_perf', '_test'))):
    raise SystemExit('Use an isolated loopback database ending in _preview, _perf or _test.')
os.environ.update(GAMEARENA_TESTING='1', DATABASE_URL=database, GAMEARENA_SCHEMA_BOOTSTRAP='1',
                  SECRET_KEY='isolated-performance-fixture', AUTH_PROVIDER='local')
for name in ('ADMIN_EMAIL','ADMIN_PASSWORD','PAYSTACK_SECRET_KEY','PAYSTACK_PUBLIC_KEY','SUPABASE_URL',
             'SUPABASE_SERVICE_ROLE_KEY','VAPID_PUBLIC_KEY','VAPID_PRIVATE_KEY','VAPID_SUBJECT',
             'GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','RESEND_API_KEY','SMTP_SERVER','SMTP_USERNAME','SMTP_PASSWORD'):
    os.environ[name] = ''

import app as application
from flask import g
from flask_login import login_required
from sqlalchemy import event
from app import app, db, User, UserSettings, Achievement, Tournament, UserTournament


def fresh_request_user():
    # The benchmark retains an outer app context for instrumentation. Production
    # requests each get a fresh g, so do not reuse Flask-Login's cached identity.
    g.pop('_login_user', None)
    g.pop('csrf_token', None)


app.before_request_funcs[None].insert(0, fresh_request_user)


def measure(browser, path, samples=3):
    counts, timings = [], []
    engine = db.engine
    for _ in range(samples):
        queries = []
        def collect(connection, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        event.listen(engine, 'before_cursor_execute', collect)
        try:
            start = time.perf_counter()
            response = browser.get(path)
            assert response.status_code == 200, (path, response.status_code)
            timings.append(round((time.perf_counter() - start) * 1000, 1))
            counts.append(len(queries))
        finally:
            event.remove(engine, 'before_cursor_execute', collect)
    return dict(queries=counts, local_median_ms=statistics.median(timings), local_samples_ms=timings)


with app.app_context():
    app.config.update(ADULT_ACCESS_REQUIRED=False, SECURITY_REQUIRE_STEP_UP=False)
    owner = User.query.filter_by(username='performance_probe').first()
    if not owner:
        owner = User(username='performance_probe', email='performance-probe@example.test', password='fixture-only', email_verified=True)
        db.session.add(owner); db.session.flush()
        db.session.add(UserSettings(user_id=owner.id))
        tournament = Tournament(name='Performance fixture', game='PUBG Mobile', status='open')
        db.session.add(tournament); db.session.flush()
        db.session.add(UserTournament(user_id=owner.id, tournament_id=tournament.id, payment_status='free'))
        for index in range(32):
            db.session.add(Achievement(key=f'probe_badge_{index}', name=f'Probe badge {index}',
                description='Fixture badge', rule_type='tournaments', threshold=1))
        db.session.commit()
    browser = app.test_client()
    with browser.session_transaction() as session:
        session['_user_id'] = str(owner.id); session['_fresh'] = True
    browser.get('/profile')  # Compare steady state; award notifications only once.
    routes = ('/', '/tournaments', '/leaderboard', '/dashboard', '/profile', '/wallet',
              '/settings', '/notifications', '/chat', '/search?q=PUBG')
    result = {'scope': 'Isolated local PostgreSQL fixtures; these are not production latency promises.',
              'fixture_badges': 32, 'pool_mode': os.environ.get('DATABASE_POOL_MODE', 'null'),
              'current': {path: measure(browser, path) for path in routes}}
    baseline = os.environ.get('GAMEARENA_BASELINE_REF', '54f02a810fa44fa51d1eeabe73444712b5f3b345')
    git = os.environ.get('GAMEARENA_GIT', 'git')
    source = subprocess.check_output([git, 'show', f'{baseline}:app.py'], cwd=root, text=True, encoding='utf-8')
    functions = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                 and node.name in {'achievement_progress_for_user', 'award_achievements_for_user', 'profile'}]
    for node in functions:
        node.decorator_list = []
    namespace = vars(application).copy()
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), '<baseline functions>', 'exec'), namespace)
    current_profile = app.view_functions['profile']
    try:
        app.view_functions['profile'] = login_required(namespace['profile'])
        result['baseline_profile'] = measure(browser, '/profile')
        result['baseline_ref'] = baseline
    finally:
        app.view_functions['profile'] = current_profile
    print(json.dumps(result, indent=2))
