import structlog

logger = structlog.get_logger(__name__)
from typing import Any

from main import run_backtest


def run() -> Any:
    """Otomatik eklendi."""
    start = "2015-01-01"
    end = "2025-01-01"

    logger.info(f"Running baseline backtest from {start} to {end}...")
    run_backtest(start_date=start, end_date=end, force_retrain=False)


if __name__ == "__main__":
    run()
