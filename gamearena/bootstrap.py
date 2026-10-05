"""Create the configured Flask shell without importing routes or models."""
import os
from urllib.parse import urlparse
from flask import Flask
from gamearena.database import engine_options


def create_base_app(root, testing=False):
    app = Flask('app', template_folder=os.path.join(root, 'templates'),
                static_folder=os.path.join(root, 'static'),
                instance_path=os.path.join(root, 'instance'))
    app.config.update(TESTING=testing,
        SQLALCHEMY_ENGINE_OPTIONS=engine_options(os.environ),
        BACKGROUND_JOBS_ENABLED=not testing and os.environ.get('BACKGROUND_JOBS_ENABLED', '').lower() == 'true',
        JOB_REDIS_URL='' if testing else os.environ.get('JOB_REDIS_URL', ''),
        CACHE_REDIS_URL='' if testing else os.environ.get('CACHE_REDIS_URL', ''),
        SOCKET_RATE_LIMIT_REDIS_URL='' if testing else os.environ.get('SOCKET_RATE_LIMIT_REDIS_URL', ''),
        CACHE_NAMESPACE=os.environ.get('CACHE_NAMESPACE', 'gamearena'),
        PUBLIC_BASE_URL=os.environ.get('PUBLIC_BASE_URL', 'https://gamearena01.com').rstrip('/'))
    if app.config['BACKGROUND_JOBS_ENABLED'] and not app.config['JOB_REDIS_URL']:
        raise RuntimeError('JOB_REDIS_URL is required when background jobs are enabled.')
    for name in ['JOB_REDIS_URL', 'CACHE_REDIS_URL', 'SOCKET_RATE_LIMIT_REDIS_URL']:
        value = app.config[name]
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {'redis', 'rediss'} or not parsed.hostname:
                raise ValueError(f'{name} must be a Redis connection URL.')
    return app
