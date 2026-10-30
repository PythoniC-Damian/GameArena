"""Production entry point: patch I/O before Gunicorn or application imports.

Run with the same Gunicorn arguments as before. Migrations stay in a separate
process; the cooperative database adapter applies only to the web server.
"""
from gevent import monkey
monkey.patch_all()

from psycogreen.gevent import patch_psycopg
patch_psycopg()

import os
import sys
from pathlib import Path

# This entry point has already patched threading and database I/O. Activate
# bounded reuse even on existing services whose Blueprint env has not synced.
# An explicit DATABASE_POOL_MODE=null remains a supported rollback.
os.environ.setdefault('DATABASE_POOL_MODE', 'queue')
os.environ.setdefault('DATABASE_POOL_SIZE', '3')
os.environ.setdefault('DATABASE_MAX_OVERFLOW', '0')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == '__main__':
    from gunicorn.app.wsgiapp import run
    run()
