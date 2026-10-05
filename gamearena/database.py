"""Explicit database pooling options; retain the proven default."""
from sqlalchemy.pool import NullPool, QueuePool


def engine_options(environ):
    mode = environ.get('DATABASE_POOL_MODE', 'null').strip().lower()
    if mode not in {'null', 'queue'}:
        raise ValueError('DATABASE_POOL_MODE must be null or queue.')
    options = {'connect_args': {'connect_timeout': 10}}
    if mode == 'null':
        options['poolclass'] = NullPool
    else:
        def number(name, default, minimum, maximum):
            value = int(environ.get(name, default))
            if not minimum <= value <= maximum:
                raise ValueError(f'{name} is outside its supported range.')
            return value
        options.update(poolclass=QueuePool, pool_pre_ping=True,
            pool_size=number('DATABASE_POOL_SIZE', 5, 1, 20),
            max_overflow=number('DATABASE_MAX_OVERFLOW', 0, 0, 20),
            pool_timeout=number('DATABASE_POOL_TIMEOUT', 10, 1, 60),
            pool_recycle=number('DATABASE_POOL_RECYCLE', 300, 30, 3600))
    return options
