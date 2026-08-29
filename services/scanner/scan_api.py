"""
ALPHA BIST — Scan Metrics API v1.0

Tarama istatistiklerini API'den erişilebilir yapar.
Dashboard ve monitoring için endpoint'ler.

Endpoint'ler:
- GET /api/scan/status — tarama durumu
- GET /api/scan/results — son tarama sonuçları
- GET /api/scan/history/{ticker} — hisse tarama geçmişi
- GET /api/scan/performance — performans istatistikleri
- GET /api/scan/alerts — son alert'ler
- GET /api/scan/tiers — tier bazlı özet
- POST /api/scan/trigger — manuel tarama tetikle
"""

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class ScanAPI:
    """Scan metrics API endpoint'leri.

    FastAPI/Flask router'ı olarak kullanılabilir
    veya doğrudan fonksiyon çağrısı ile.
    """

    def __init__(self):
        """Otomatik eklendi."""
        # Singleton referansları
        from .alpha_engine import alpha_engine
        from .custom_filters import custom_filter_engine
        from .deduplicator import scan_deduplicator
        from .performance_tracker import performance_tracker
        from .scan_alerts import scan_alert_manager
        from .scan_persistence import scan_persistence
        from .scan_scheduler import scan_scheduler
        from .tiered_scanner import tiered_scanner

        self._engine = alpha_engine
        self._scanner = tiered_scanner
        self._dedup = scan_deduplicator
        self._scheduler = scan_scheduler
        self._persistence = scan_persistence
        self._perf_tracker = performance_tracker
        self._alert_manager = scan_alert_manager
        self._filter_engine = custom_filter_engine

    def get_status(self) -> dict[str, Any]:
        """Tarama durumu.

        Returns:
            Sistem durumu
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "scheduler": self._scheduler.get_stats(),
            "deduplicator": self._dedup.get_stats(),
            "scanner": self._scanner.get_tier_summary(),
            "last_scan": self._engine.get_last_summary(),
            "market_open": self._scheduler.is_market_open(),
        }

    def get_results(self, limit: int = 50) -> dict[str, Any]:
        """Son tarama sonuçları.

        Args:
            limit: Maksimum sonuç

        Returns:
            Son tarama sonuçları
        """
        last_results = self._engine.get_last_results()

        # Limit
        limited = last_results[:limit] if last_results else []

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_results": len(last_results) if last_results else 0,
            "results": [
                {
                    "ticker": r.ticker if hasattr(r, "ticker") else r.get("ticker", ""),
                    "score": r.opportunity_score if hasattr(r, "opportunity_score") else r.get("score", 0),
                    "signal": r.signal_type if hasattr(r, "signal_type") else r.get("signal", ""),
                    "direction": r.signal_direction if hasattr(r, "signal_direction") else r.get("direction", ""),
                    "confidence": r.signal_confidence if hasattr(r, "signal_confidence") else r.get("confidence", 0),
                    "price": r.price if hasattr(r, "price") else r.get("price", 0),
                    "tier": r.current_tier if hasattr(r, "current_tier") else r.get("tier", 0),
                }
                for r in limited
            ],
        }

    def get_ticker_history(self, ticker: str, days: int = 30) -> dict[str, Any]:
        """Hisse tarama geçmişi.

        Args:
            ticker: Hisse kodu
            days: Son kaç gün

        Returns:
            Tarama geçmişi
        """
        history = self._persistence.get_scan_history(ticker, days=days)
        dedup_info = self._dedup.get_last_scan_info(ticker)

        return {
            "ticker": ticker,
            "days": days,
            "total_records": len(history),
            "dedup_info": dedup_info,
            "history": history[:50],  # Son 50 kayıt
        }

    def get_performance(self) -> dict[str, Any]:
        """Performans istatistikleri.

        Returns:
            Performans istatistikleri
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "tracker": self._perf_tracker.get_summary(),
            "persistence": self._persistence.get_scan_stats(),
            "signal_accuracy": self._perf_tracker.get_signal_accuracy(),
            "top_filters": self._perf_tracker.get_top_performing_filters(),
            "regime_performance": self._perf_tracker.get_regime_performance(),
        }

    def get_alerts(self, limit: int = 50) -> dict[str, Any]:
        """Son alert'ler.

        Args:
            limit: Maksimum alert

        Returns:
            Alert'ler
        """
        alerts = self._alert_manager.get_alerts(limit=limit)

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": self._alert_manager.get_alert_summary(),
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "type": a.alert_type.value,
                    "severity": a.severity.value,
                    "ticker": a.ticker,
                    "title": a.title,
                    "message": a.message,
                    "score": a.score,
                    "signal": a.signal,
                    "timestamp": a.timestamp,
                    "acknowledged": a.acknowledged,
                }
                for a in alerts
            ],
        }

    def get_tiers(self) -> dict[str, Any]:
        """Tier bazlı özet.

        Returns:
            Tier istatistikleri
        """
        summary = self._scanner.get_tier_summary()
        top_opportunities = self._scanner.get_top_opportunities(n=20)

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": summary,
            "top_opportunities": top_opportunities,
        }

    def get_filters(self) -> dict[str, Any]:
        """Filtre bilgileri.

        Returns:
            Filtre listesi ve istatistikleri
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "filters": self._filter_engine.get_filters(),
        }

    def get_dedup_stats(self) -> dict[str, Any]:
        """Deduplication istatistikleri.

        Returns:
            Deduplication istatistikleri
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "stats": self._dedup.get_stats(),
            "tracked": self._dedup.get_all_tracked(),
        }

    def get_scheduler_stats(self) -> dict[str, Any]:
        """Scheduler istatistikleri.

        Returns:
            Scheduler istatistikleri
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "stats": self._scheduler.get_stats(),
            "interval_history": self._scheduler.get_interval_history(limit=20),
        }

    def get_full_dashboard(self) -> dict[str, Any]:
        """Tam dashboard verisi.

        Returns:
            Tüm istatistikler
        """
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "status": self.get_status(),
            "results": self.get_results(limit=20),
            "tiers": self.get_tiers(),
            "performance": self.get_performance(),
            "alerts": self.get_alerts(limit=10),
            "filters": self.get_filters(),
            "dedup": self.get_dedup_stats(),
            "scheduler": self.get_scheduler_stats(),
        }


# Singleton
scan_api = ScanAPI()
