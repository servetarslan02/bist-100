"""ALPHA BIST — Database Dev Compatibility Shim

DEPRECATED: This module exists only for backward compatibility with tests.
All production code should use services.core.database directly.

This shim re-exports the production database functions so that existing
test imports don't break.
"""

import warnings
from .database import (
    get_pg_pool,
    get_pg_connection,
    get_pg_transaction,
    pg_execute,
    pg_fetch,
    pg_fetchrow,
    pg_fetchval,
    get_ch_client,
    ch_execute,
    ch_insert,
    ch_query_df,
    get_redis,
    redis_get,
    redis_set,
    redis_delete,
    redis_hgetall,
    redis_hset,
    redis_publish,
    check_db_health,
    init_databases,
    close_databases,
)

warnings.warn(
    "services.core.database_dev is DEPRECATED. Use services.core.database instead.",
    DeprecationWarning,
    stacklevel=2,
)


class _DevDBCompat:
    """Compatibility wrapper that mimics the old dev_db interface."""

    async def pg_fetch(self, query, *args):
        return await pg_fetch(query, *args)

    async def pg_fetchrow(self, query, *args):
        return await pg_fetchrow(query, *args)

    async def pg_fetchval(self, query, *args):
        return await pg_fetchval(query, *args)

    async def pg_execute(self, query, *args):
        return await pg_execute(query, *args)

    async def init(self):
        await init_databases()


dev_db = _DevDBCompat()
