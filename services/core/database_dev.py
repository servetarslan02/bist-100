"""ALPHA BIST — Database Dev Compatibility Shim

DEPRECATED: This module exists only for backward compatibility with tests.
All production code should use services.core.database directly.

This shim re-exports the production database functions so that existing
test imports don't break.
"""

import warnings
from .database import (
    pg_execute,
    pg_fetch,
    pg_fetchrow,
    pg_fetchval,
    init_databases,
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
