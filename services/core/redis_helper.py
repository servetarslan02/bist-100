import os
import tempfile
from typing import Any

import orjson
import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.redis_helper")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator

_redis_client = None
_redis_available = None
_CACHE_FILE = os.path.join(tempfile.gettempdir(), "alpha_bist_cache.json")


def _load_cache():
    if os.path.exists(_CACHE_FILE):
        try:
            with open(_CACHE_FILE) as f:
                return orjson.loads(f.read())
        except Exception:
            logger.warning("Caught Exception in _load_cache", exc_info=True)
    return {}


def _save_cache(data):
    try:
        with open(_CACHE_FILE, "w") as f:
            f.write(orjson.dumps(data).decode())
    except Exception:
        logger.warning("Caught Exception in _save_cache", exc_info=True)


def get_client():
    global _redis_client, _redis_available
    if _redis_available is False:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib

        host = os.environ.get("REDIS_HOST", "redis")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        db = int(os.environ.get("REDIS_DB", "0"))
        password = os.environ.get("REDIS_PASSWORD", "") or None
        _redis_client = redis_lib.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            socket_timeout=1,
            socket_connect_timeout=1,
            decode_responses=False,
        )
        _redis_client.ping()
        _redis_available = True
        return _redis_client
    except Exception:
        _redis_available = False
        return None


@otel_trace("redis_helper.get_cached")
def get_cached(key: str) -> Any | None:
    r = get_client()
    if r is None:
        cache = _load_cache()
        if key in cache:
            return orjson.loads(cache[key])
        return None
    try:
        data = r.get(key)
        if data:
            return orjson.loads(data)
    except Exception:
        logger.warning("Caught Exception in get_cached", exc_info=True)
    return None


@otel_trace("redis_helper.set_cached")
def set_cached(key: str, data: Any, ttl: int = 300) -> bool:
    r = get_client()
    if r is None:
        cache = _load_cache()
        cache[key] = orjson.dumps(data, default=str).decode()
        _save_cache(cache)
        return True
    try:
        r.setex(key, ttl, orjson.dumps(data, default=str).decode())
        return True
    except Exception:
        return False


@otel_trace("redis_helper.delete_cached")
def delete_cached(key: str) -> bool:
    r = get_client()
    if r is None:
        cache = _load_cache()
        if key in cache:
            del cache[key]
            _save_cache(cache)
        return True
    try:
        r.delete(key)
        return True
    except Exception:
        return False


def is_available() -> bool:
    return True
