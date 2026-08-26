"""
ALPHA BIST — Data Refresh Worker

Piyasa verilerini güncelleyen worker.
BIST-30/50/100 için veri yenileme.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class DataRefreshWorker:
    """Piyasa verisi yenileme worker'ı."""

    def __init__(self):
        self._last_refresh: Optional[str] = None
        self._refresh_count: int = 0

    def refresh_market_data(self, universes: Optional[List[str]] = None) -> Dict[str, Any]:
        """Piyasa verilerini yenile.

        Args:
            universes: Yenilenecek endeksler. None ise tümü.
        """
        if universes is None:
            universes = ["bist30", "bist50", "bist100"]

        result = {"timestamp": datetime.now(_TZ_ISTANBUL).isoformat(), "universes": universes, "refreshed": {}}

        try:
            from services.ingestion.bist_universe import bist_universe

            for universe in universes:
                try:
                    if universe == "bist30":
                        tickers = bist_universe.BIST_30_TICKERS
                    elif universe == "bist50":
                        tickers = bist_universe.BIST_50_TICKERS
                    elif universe == "bist100":
                        tickers = bist_universe.BIST_100_TICKERS
                    else:
                        tickers = []

                    result["refreshed"][universe] = len(tickers) if tickers else 0
                except Exception as e:
                    result["refreshed"][universe] = f"error: {e}"

            # BIST-50 cache yenile
            try:
                from services.core.short_selling import short_selling_monitor
                short_selling_monitor.auto_refresh_if_needed()
                result["bist50_cache"] = "ok"
            except Exception as e:
                result["bist50_cache"] = f"error: {e}"

            self._last_refresh = result["timestamp"]
            self._refresh_count += 1
            result["status"] = "completed"

            logger.info("Data refresh completed", refreshed=result["refreshed"])

        except Exception as e:
            logger.error("Data refresh failed", error=str(e))
            result["status"] = "failed"

        return result

    def get_status(self) -> Dict[str, Any]:
        return {"last_refresh": self._last_refresh, "refresh_count": self._refresh_count}


data_refresh_worker = DataRefreshWorker()
