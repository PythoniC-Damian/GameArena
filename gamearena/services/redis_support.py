"""Short-lived shared public-data caching and atomic Socket.IO limits."""
import hashlib
import json
import secrets
from functools import lru_cache, wraps
from flask import current_app, request, make_response


@lru_cache(maxsize=8)
def redis_connection(url):
    from redis import Redis
    return Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1,
                          retry_on_timeout=False, health_check_interval=30)


def public_json_cache(ttl=20):
    """Cache only successful, explicit public JSON; never HTML or mutations."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            url = current_app.config.get('CACHE_REDIS_URL')
            if not url or request.method != 'GET':
                return function(*args, **kwargs)
            parameters = sorted(request.args.items(multi=True))
            digest = hashlib.sha256(json.dumps([request.path, parameters]).encode()).hexdigest()
            key = f"{current_app.config['CACHE_NAMESPACE']}:public:v1:{digest}"
            connection = redis_connection(url)
            try:
                value = connection.get(key)
                if value:
                    response = current_app.response_class(value, mimetype='application/json')
                    response.headers['Cache-Control'] = 'public, max-age=30, s-maxage=60, stale-while-revalidate=60'
                    response.headers['Vary'] = 'Accept'
                    response.headers['X-GameArena-Cache'] = 'hit'
                    return response
            except Exception:
                current_app.logger.warning('Public cache unavailable; querying database.')
                return function(*args, **kwargs)
            response = make_response(function(*args, **kwargs))
            if response.status_code == 200 and response.is_json:
                try:
                    # Bound one cached payload; TTL bounds its lifetime.
                    if len(response.get_data()) <= 256_000:
                        connection.setex(key, ttl, response.get_data())
                except Exception:
                    current_app.logger.warning('Public cache write unavailable.')
            return response
        return wrapped
    return decorate


SLIDING_WINDOW = """
local stamp = redis.call('TIME')
local now = tonumber(stamp[1])*1000 + math.floor(tonumber(stamp[2])/1000)
local window = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now-window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 1
"""


def shared_socket_allowed(user_id, event, limit, window):
    url = current_app.config.get('SOCKET_RATE_LIMIT_REDIS_URL')
    if not url:
        return None
    digest = hashlib.sha256(f'{user_id}:{event}'.encode()).hexdigest()
    key = f"{current_app.config['CACHE_NAMESPACE']}:socket:{digest}"
    try:
        return bool(redis_connection(url).eval(SLIDING_WINDOW, 1, key,
                    window * 1000, limit, secrets.token_hex(12)))
    except Exception:
        # Do not silently lose the cross-instance abuse guard on an outage.
        current_app.logger.warning('Shared socket limiter unavailable; event refused.')
        return False
