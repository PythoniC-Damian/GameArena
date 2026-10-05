"""Run on a separate trusted worker, with the same environment as the web app."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)


def main():
    url = os.environ.get('JOB_REDIS_URL')
    if not url:
        raise SystemExit('JOB_REDIS_URL must be configured for the delivery worker.')
    from redis import Redis
    from rq import Queue, Worker, SpawnWorker
    from rq.serializers import JSONSerializer
    connection = Redis.from_url(url, socket_connect_timeout=5, socket_timeout=30)
    # Windows cannot fork; production Linux uses the standard isolated worker.
    worker_type = SpawnWorker if os.name == 'nt' else Worker
    worker_type([Queue('gamearena-delivery', connection=connection, serializer=JSONSerializer)], connection=connection, serializer=JSONSerializer).work(with_scheduler=True)


if __name__ == '__main__':
    main()
