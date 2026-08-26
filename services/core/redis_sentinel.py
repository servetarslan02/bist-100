"""ALPHA BIST — Redis Sentinel Client (High Availability)

Redis Sentinel desteği: master otomatik failover.
Tek node varsa normal client gibi çalışır (backward compatible).
Sentinel varsa master-slave otomatik geçiş.

Kullanım:
    from services.core.redis_sentinel import get_ha_redis

    r = await get_ha_redis()
    await r.set("key", "value")
"""

import os
import asyncio
import structlog

try:
    import redis.asyncio as aioredis
    from redis.sentinel import Sentinel
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

logger = structlog.get_logger()


# =====================================================
# Config
# =====================================================

def _get_sentinel_hosts() -> list[tuple[str, int]]:
    """Sentinel adreslerini ortam değişkeninden oku."""
    raw = os.environ.get("REDIS_SENTINEL_HOSTS", "")
    if not raw:
        return []
    hosts = []
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            host, port = entry.rsplit(":", 1)
            hosts.append((host.strip(), int(port)))
        elif entry:
            hosts.append((entry, 26379))
    return hosts


def _get_sentinel_master() -> str:
    """Sentinel master adı."""
    return os.environ.get("REDIS_SENTINEL_MASTER", "alpha-master")


def _get_redis_password() -> str:
    return os.environ.get("REDIS_PASSWORD", "")


# =====================================================
# HA Redis Client
# =====================================================

_ha_redis = None
_ha_loop = None


async def get_ha_redis():
    """High-Availability Redis client döndür.

    Öncelik:
    1. Sentinel varsa → Sentinel üzerinden master'a bağlan
    2. Yoksa → normal Redis URL ile bağlan (backward compatible)
    """
    global _ha_redis, _ha_loop

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _ha_redis is not None and _ha_loop is current_loop:
        return _ha_redis

    sentinel_hosts = _get_sentinel_hosts()
    password = _get_redis_password()

    if sentinel_hosts and HAS_REDIS:
        # Sentinel modu
        try:
            master_name = _get_sentinel_master()
            sentinel = Sentinel(
                sentinel_hosts,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
            )
            master = sentinel.master_for(
                master_name,
                socket_timeout=1,
                socket_connect_timeout=1,
                password=password,
                decode_responses=True,
            )
            # Bağlantıyı test et
            await master.ping()
            _ha_redis = master
            _ha_loop = current_loop
            logger.info("Redis Sentinel connected",
                       master=master_name, sentinels=len(sentinel_hosts))
            return _ha_redis
        except Exception as e:
            logger.warning("Redis Sentinel failed, falling back to direct",
                         error=str(e))

    # Direct mod (backward compatible)
    try:
        from .config import settings
        _ha_redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
        _ha_loop = current_loop
        logger.info("Redis direct connection", host=settings.redis_host)
        return _ha_redis
    except Exception as e:
        logger.error("Redis connection failed", error=str(e))
        raise


async def close_ha_redis():
    """HA Redis bağlantısını kapat."""
    global _ha_redis, _ha_loop
    if _ha_redis:
        try:
            await _ha_redis.close()
        except Exception:
            logger.warning("Caught Exception in close_ha_redis", exc_info=True)
        _ha_redis = None
        _ha_loop = None
        logger.info("HA Redis closed")
