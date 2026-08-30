from typing import Any

"""ALPHA BIST - Structured Logging"""

import logging
import sys

import structlog


def setup_logging(log_level: str = "WARNING") -> Any:
    """Configure structured logging for ALPHA BIST."""

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Suppress noisy libraries — SSD write reduction
    for noisy in ["httpx", "httpcore", "urllib3", "asyncio", "aiohttp",
                  "websockets", "grpc", "opentelemetry", "uvicorn.access",
                  "uvicorn.error", "fastapi", "starlette", "clickhouse_connect",
                  "redis", "celery", "kombu", "billiard", "watchfiles"]:
        logging.getLogger(noisy).setLevel(logging.ERROR)


# Setup on import
setup_logging()

# Export logger
logger = structlog.get_logger(__name__)
