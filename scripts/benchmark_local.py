"""Measure local backend response times using only an isolated PostgreSQL DB."""
import json
import os
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))


def main():
    url = os.environ.get('GAMEARENA_TEST_DATABASE_URL', '')
    parsed = urlparse(url)
    if parsed.hostname not in {'localhost', '127.0.0.1'} or not parsed.path.endswith(('_test', '_preview')):
        raise SystemExit('Use an explicit loopback isolated test/preview database.')
    os.environ.update(GAMEARENA_TESTING='1', DATABASE_URL=url)
    for key in ('PAYSTACK_SECRET_KEY', 'PAYSTACK_PUBLIC_KEY', 'RESEND_API_KEY', 'SMTP_SERVER',
                'SMTP_USERNAME', 'SMTP_PASSWORD', 'SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY',
                'VAPID_PUBLIC_KEY', 'VAPID_PRIVATE_KEY', 'VAPID_SUBJECT', 'ADMIN_EMAIL', 'ADMIN_PASSWORD'):
        os.environ[key] = ''
    from app import app
    client = app.test_client()
    result = {'scope':'local Flask responses only; excludes browser, network and production latency', 'routes':{}}
    for path in ['/', '/tournaments', '/api/v1/tournaments', '/health']:
        values = []
        client.get(path)
        for _ in range(20):
            started = time.perf_counter(); response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError(f'Benchmark route failed: {path} status={response.status_code}')
            values.append((time.perf_counter() - started) * 1000)
        result['routes'][path] = {'samples':20, 'p50_ms':round(statistics.median(values),2),
            'p95_ms':round(sorted(values)[18],2)}
    print(json.dumps(result, indent=2))
    destination = root/'docs/validation/stack-local-latency.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
