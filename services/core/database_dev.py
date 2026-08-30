from typing import Any

"""ALPHA BIST — Database Dev Compatibility Shim

DEPRECATED: This module exists only for backward compatibility with tests.
All production code should use services.core.database directly.

This shim re-exports the production database functions so that existing
test imports don't break.
"""

import functools
import warnings

from opentelemetry import trace

tracer = trace.get_tracer("alpha-bist.database_dev")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return await func(self, *args, **kwargs)

        return wrapper

    return decorator


from .database import (
    init_databases,
    pg_execute,
    pg_fetch,
    pg_fetchrow,
    pg_fetchval,
)

warnings.warn(
    "services.core.database_dev is DEPRECATED. Use services.core.database instead.",
    DeprecationWarning,
    stacklevel=2,
)


class _DevDBCompat:
    """Compatibility wrapper that mimics the old dev_db interface."""

    @otel_trace("database_dev.pg_fetch")
    async def pg_fetch(self, query, *args) -> Any:
        """Otomatik eklendi."""
        return await pg_fetch(query, *args)

    @otel_trace("database_dev.pg_fetchrow")
    async def pg_fetchrow(self, query, *args) -> Any:
        """Otomatik eklendi."""
        return await pg_fetchrow(query, *args)

    @otel_trace("database_dev.pg_fetchval")
    async def pg_fetchval(self, query, *args) -> Any:
        """Otomatik eklendi."""
        return await pg_fetchval(query, *args)

    @otel_trace("database_dev.pg_execute")
    async def pg_execute(self, query, *args) -> Any:
        """Otomatik eklendi."""
        return await pg_execute(query, *args)

    @otel_trace("database_dev.init")
    async def init(self) -> Any:
        """Otomatik eklendi."""
        await init_databases()


dev_db = _DevDBCompat()
