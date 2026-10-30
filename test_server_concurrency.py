"""Exercise cooperative database I/O in a separate, early-patched process."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.parametrize('pool_mode', ['null', 'queue'])
def test_slow_database_query_does_not_block_health_check(pool_mode):
    # Do not patch pytest's already-imported network/thread modules. The child
    # starts in the same order as production, against the isolated test DB only.
    probe = r'''
import runpy
runpy.run_path('scripts/serve.py', run_name='server_probe')
import os
from gevent import monkey, spawn, sleep
import psycopg2
from psycopg2.extensions import get_wait_callback
from app import app
from sqlalchemy import create_engine, text
from gamearena.database import engine_options
assert monkey.is_module_patched('ssl')
assert get_wait_callback() is not None

connection = psycopg2.connect(os.environ['GAMEARENA_TEST_DATABASE_URL'])
query_started = []
def slow_query():
    with connection.cursor() as cursor:
        query_started.append(True)
        cursor.execute('SELECT pg_sleep(1.5)')
    connection.rollback()

task = spawn(slow_query)
sleep(0.05)
assert query_started and not task.ready(), 'DB wait blocked the event loop'
try:
    with app.test_client() as client:
        response = client.get('/health')
    assert response.status_code == 200
    assert not task.ready(), 'Health check waited for unrelated DB query'
    task.get(timeout=5)
finally:
    connection.close()
# Exercise a saturated cooperative pool too: waiting for a returned connection
# must yield safely instead of triggering the old condition-lock error.
engine = create_engine(os.environ['GAMEARENA_TEST_DATABASE_URL'], **engine_options({
    'DATABASE_POOL_MODE':'queue', 'DATABASE_POOL_SIZE':'2', 'DATABASE_POOL_TIMEOUT':'2'}))
def pooled_query():
    with engine.connect() as connection:
        connection.execute(text('SELECT pg_sleep(0.1)'))
try:
    tasks = [spawn(pooled_query) for _ in range(4)]
    for task in tasks: task.get(timeout=5)
finally:
    engine.dispose()
print('cooperative health check passed')
'''
    result = subprocess.run([sys.executable, '-c', probe], cwd=Path(__file__).parent,
        env=dict(os.environ, DATABASE_POOL_MODE=pool_mode, DATABASE_POOL_SIZE='3'),
        # Windows antivirus/cold imports can exceed 35 seconds before the
        # probe starts. The assertions above still enforce cooperative I/O.
        capture_output=True, text=True, timeout=90 if os.name == 'nt' else 35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'MonkeyPatchWarning' not in result.stderr
    assert 'cooperative health check passed' in result.stdout
