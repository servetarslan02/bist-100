"""
ALPHA BIST — Data Refresh Worker

Piyasa verilerini güncelleyen worker.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class DataRefreshWorker:
    """Piyasa verisi yenileme worker'ı."""

    def __init__(self):
        self._last_refresh: str | None = None
        self._refresh_count: int = 0

    def refresh_market_data(self) -> dict[str, Any]:
        """BIST-100 piyasa verilerini yenile."""
        result = {"timestamp": datetime.now(_TZ_ISTANBUL).isoformat()}

        try:
            from services.ingestion.bist_universe import bist_universe
            tickers = bist_universe.BIST_100_TICKERS
            result["bist100_count"] = len(tickers) if tickers else 0

            # BIST-50 cache yenile
            from services.core.short_selling import short_selling_monitor
            short_selling_monitor.auto_refresh_if_needed()
            result["bist50_cache"] = "ok"

            self._last_refresh = result["timestamp"]
            self._refresh_count += 1
            result["status"] = "completed"

        except Exception as e:
            logger.error("Data refresh failed", error=str(e))
            result["status"] = "failed"

        return result

    def get_status(self) -> dict[str, Any]:
        return {"last_refresh": self._last_refresh, "refresh_count": self._refresh_count}


data_refresh_worker = DataRefreshWorker()
