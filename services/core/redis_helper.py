import functools
import os
import time
from typing import Any

import orjson
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.redis_helper")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


_redis_client = None
_redis_available = None
_mem_cache: dict[str, tuple[float, str]] = {}  # key -> (expiry_ts, json_str)


def _load_cache() -> dict[str, str]:
    """Saf in-memory önbellek okuma (Sıfır Disk I/O)."""
    global _mem_cache
    now = time.time()
    valid_cache = {}
    for k, (exp, val) in list(_mem_cache.items()):
        if exp > now:
            valid_cache[k] = val
        else:
            _mem_cache.pop(k, None)
    return valid_cache


def _save_cache(data: dict[str, str], ttl: int = 300) -> None:
    """Saf in-memory önbellek yazma (Sıfır Disk I/O)."""
    global _mem_cache
    now = time.time()
    for k, v in data.items():
        _mem_cache[k] = (now + ttl, str(v))



def get_client() -> Any:
    """Otomatik eklendi."""
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
    """Otomatik eklendi."""
    r = get_client()
    if r is None:
        now = time.time()
        if key in _mem_cache:
            exp, val = _mem_cache[key]
            if exp > now:
                return orjson.loads(val)
            _mem_cache.pop(key, None)
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
    """Otomatik eklendi."""
    r = get_client()
    if r is None:
        val_str = orjson.dumps(data, default=str).decode()
        _mem_cache[key] = (time.time() + ttl, val_str)
        return True
    try:
        r.setex(key, ttl, orjson.dumps(data, default=str).decode())
        return True
    except Exception:
        return False


@otel_trace("redis_helper.delete_cached")
def delete_cached(key: str) -> bool:
    """Otomatik eklendi."""
    r = get_client()
    if r is None:
        _mem_cache.pop(key, None)
        return True
    try:
        r.delete(key)
        return True
    except Exception:
        return False


@otel_trace("redis_helper.mget_cached")
def mget_cached(keys: list[str]) -> dict[str, Any]:
    """Çoklu anahtarı pipeline ile tek seferde çeker (Roundtrip tasarrufu)."""
    if not keys:
        return {}
    r = get_client()
    if r is None:
        now = time.time()
        res = {}
        for k in keys:
            if k in _mem_cache:
                exp, val = _mem_cache[k]
                if exp > now:
                    try:
                        res[k] = orjson.loads(val)
                    except Exception as json_err:
                        logger.debug("mget_mem_json_parse_failed", key=k, error=str(json_err))
                else:
                    _mem_cache.pop(k, None)
        return res
    try:
        pipe = r.pipeline(transaction=False)
        for k in keys:
            pipe.get(k)
        results = pipe.execute()
        res = {}
        for k, v in zip(keys, results, strict=False):
            if v is not None:
                try:
                    res[k] = orjson.loads(v)
                except Exception as json_err:
                    logger.debug("mget_redis_json_parse_failed", key=k, error=str(json_err))
        return res
    except Exception as e:
        logger.warning("mget_cached_failed", error=str(e))
        return {}


@otel_trace("redis_helper.mset_cached")
def mset_cached(mapping: dict[str, Any], ttl: int = 300) -> bool:
    """Çoklu anahtarı pipeline ile tek seferde yazar."""
    if not mapping:
        return True
    r = get_client()
    if r is None:
        now = time.time()
        for k, v in mapping.items():
            payload = orjson.dumps(v, default=str).decode()
            _mem_cache[k] = (now + ttl, payload)
        return True
    try:
        pipe = r.pipeline(transaction=False)
        for k, v in mapping.items():
            payload = orjson.dumps(v, default=str).decode()
            pipe.setex(k, ttl, payload)
        pipe.execute()
        return True
    except Exception as e:
        logger.warning("mset_cached_failed", error=str(e))
        return False


def is_available() -> bool:
    """Otomatik eklendi."""
    return get_client() is not None

