"""Exercise cooperative database I/O in a separate, early-patched process."""
import os
from pathlib import Path
import subprocess
import sys


def test_slow_database_query_does_not_block_health_check():
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
print('cooperative health check passed')
'''
    result = subprocess.run([sys.executable, '-c', probe], cwd=Path(__file__).parent,
        env=os.environ.copy(), capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'MonkeyPatchWarning' not in result.stderr
    assert 'cooperative health check passed' in result.stdout
