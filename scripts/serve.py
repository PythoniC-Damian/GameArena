"""Production entry point: patch I/O before Gunicorn or application imports.

Run with the same Gunicorn arguments as before. Migrations stay in a separate
process; the cooperative database adapter applies only to the web server.
"""
from gevent import monkey
monkey.patch_all()

from psycogreen.gevent import patch_psycopg
patch_psycopg()

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == '__main__':
    from gunicorn.app.wsgiapp import run
    run()
