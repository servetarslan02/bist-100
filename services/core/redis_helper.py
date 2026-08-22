"""
ALPHA BIST — Redis Helper v1.0

Shared Redis connection pool + utility functions.
Tüm API endpoint'leri bu modülü kullanır — her istekte yeni bağlantı açmaz.

Kullanım:
    from services.core.redis_helper import redis_helper
    r = redis_helper.get_client()
    cached = r.get("key")
"""

import json
import os
from typing import Optional, Any
import structlog

logger = structlog.get_logger()

# Lazy-loaded Redis client (connection pool)
_redis_client = None
_redis_available: Optional[bool] = None


def get_client():
    """Redis client'ı getir (connection pool'lu)."""
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

        _redis_client = redis_lib.Redis(
            host=host,
            port=port,
            db=db,
            socket_timeout=1,
            socket_connect_timeout=1,
            retry_on_timeout=False,
            decode_responses=False,
        )
        # Test connection
        _redis_client.ping()
        _redis_available = True
        logger.info("Redis connection pool initialized", host=host, port=port)
        return _redis_client
    except Exception as e:
        _redis_available = False
        logger.warning("Redis not available, caching disabled", error=str(e))
        return None


def get_cached(key: str) -> Optional[Any]:
    """Cache'den JSON veri getir."""
    r = get_client()
    if r is None:
        return None
    try:
        data = r.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.debug("redis_get_cached_failed", key=key, error=str(e))
    return None


def set_cached(key: str, data: Any, ttl: int = 300) -> bool:
    """Cache'e JSON veri yaz."""
    r = get_client()
    if r is None:
        return False
    try:
        r.setex(key, ttl, json.dumps(data, default=str))
        return True
    except Exception as e:
        logger.debug("redis_set_cached_failed", key=key, error=str(e))
        return False


def get_cached_raw(key: str) -> Optional[bytes]:
    """Cache'den ham veri getir."""
    r = get_client()
    if r is None:
        return None
    try:
        return r.get(key)
    except Exception as e:
        logger.debug("redis_get_cached_raw_failed", key=key, error=str(e))
        return None


def set_cached_raw(key: str, data: str, ttl: int = 300) -> bool:
    """Cache'e ham string yaz."""
    r = get_client()
    if r is None:
        return False
    try:
        r.setex(key, ttl, data)
        return True
    except Exception as e:
        logger.debug("redis_set_cached_raw_failed", key=key, error=str(e))
        return False


def delete_cached(key: str) -> bool:
    """Cache'den sil."""
    r = get_client()
    if r is None:
        return False
    try:
        r.delete(key)
        return True
    except Exception as e:
        logger.debug("redis_delete_cached_failed", key=key, error=str(e))
        return False


def is_available() -> bool:
    """Redis erişilebilir mi?"""
    global _redis_available
    if _redis_available is None:
        get_client()
    return _redis_available is True
