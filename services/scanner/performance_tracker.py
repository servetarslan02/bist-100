"""
ALPHA BIST — Scan Performance Tracker v1.0

Tarama performansını takip eder:
- Hangi tarama stratejisi daha iyi?
- Hangi rejimde daha başarılı?
- Sinyal doğruluğu nasıl?
- En iyi filtreler hangileri?

Kaynaklar: Endüstri standardı, awesome-quant
"""

import time
import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class ScanMetric:
    """Tek tarama metriği."""
    scan_type: str
    timestamp: float
    tickers_scanned: int
    opportunities_found: int
    signals_generated: int
    duration_ms: float
    regime: str


@dataclass
class SignalOutcome:
    """Sinyal sonucu (performans takibi için)."""
    ticker: str
    signal_type: str
    direction: str
    score: float
    confidence: float
    entry_price: float
    entry_time: str
    exit_price: float = 0.0
    exit_time: str = ""
    return_pct: float = 0.0
    correct: bool = False


class ScanPerformanceTracker:
    """Tarama performans takip sistemi.

    Metrikler:
    - Scan duration (ms)
    - Hit rate (opportunities / scanned)
    - Signal accuracy (correct / total signals)
    - Regime-based performance
    - Top performing filters
    """

    def __init__(self, max_history: int = 10000):
        self._max_history = max_history
        self._scan_metrics: List[ScanMetric] = []
        self._signal_outcomes: List[SignalOutcome] = []

    def record_scan(
        self,
        scan_type: str,
        tickers_scanned: int,
        opportunities_found: int,
        signals_generated: int,
        duration_ms: float,
        regime: str = "RANGE",
    ):
        """Tarama kaydet.

        Args:
            scan_type: Tarama türü (batch, live, event)
            tickers_scanned: Taranan hisse sayısı
            opportunities_found: Bulunan fırsat sayısı
            signals_generated: Üretilen sinyal sayısı
            duration_ms: Süre (milisaniye)
            regime: Piyasa rejimi
        """
        metric = ScanMetric(
            scan_type=scan_type,
            timestamp=time.time(),
            tickers_scanned=tickers_scanned,
            opportunities_found=opportunities_found,
            signals_generated=signals_generated,
            duration_ms=duration_ms,
            regime=regime,
        )

        self._scan_metrics.append(metric)

        # Limit kontrolü
        if len(self._scan_metrics) > self._max_history:
            self._scan_metrics = self._scan_metrics[-self._max_history:]

    def record_signal_outcome(self, outcome: SignalOutcome):
        """Sinyal sonucu kaydet (geriye dönük doğrulama).

        Args:
            outcome: Sinyal sonucu
        """
        self._signal_outcomes.append(outcome)

        if len(self._signal_outcomes) > self._max_history:
            self._signal_outcomes = self._signal_outcomes[-self._max_history:]

    def get_stats(self, scan_type: str = None) -> Dict[str, Any]:
        """Tarama istatistikleri.

        Args:
            scan_type: Tarama türü filtresi

        Returns:
            İstatistikler
        """
        if scan_type:
            metrics = [m for m in self._scan_metrics if m.scan_type == scan_type]
        else:
            metrics = self._scan_metrics

        if not metrics:
            return {
                "total_scans": 0,
                "scan_type": scan_type or "all",
            }

        recent = metrics[-100:]  # Son 100 tarama

        durations = [m.duration_ms for m in recent]
        hit_rates = [
            m.opportunities_found / max(m.tickers_scanned, 1)
            for m in recent
        ]
        opportunities = [m.opportunities_found for m in recent]
        signals = [m.signals_generated for m in recent]

        return {
            "total_scans": len(metrics),
            "scan_type": scan_type or "all",
            "avg_duration_ms": round(np.mean(durations), 2),
            "p95_duration_ms": round(np.percentile(durations, 95), 2),
            "avg_hit_rate": round(np.mean(hit_rates), 4),
            "avg_opportunities": round(np.mean(opportunities), 1),
            "avg_signals": round(np.mean(signals), 1),
            "total_opportunities": sum(opportunities),
            "total_signals": sum(signals),
        }

    def get_regime_performance(self) -> Dict[str, Dict[str, Any]]:
        """Rejim bazlı performans.

        Returns:
            Rejim → performans istatistikleri
        """
        regime_stats = {}

        for metric in self._scan_metrics:
            regime = metric.regime
            if regime not in regime_stats:
                regime_stats[regime] = {
                    "scan_count": 0,
                    "total_opportunities": 0,
                    "total_signals": 0,
                    "durations": [],
                    "hit_rates": [],
                }

            stats = regime_stats[regime]
            stats["scan_count"] += 1
            stats["total_opportunities"] += metric.opportunities_found
            stats["total_signals"] += metric.signals_generated
            stats["durations"].append(metric.duration_ms)
            stats["hit_rates"].append(
                metric.opportunities_found / max(metric.tickers_scanned, 1)
            )

        # İstatistikleri hesapla
        result = {}
        for regime, stats in regime_stats.items():
            result[regime] = {
                "scan_count": stats["scan_count"],
                "total_opportunities": stats["total_opportunities"],
                "total_signals": stats["total_signals"],
                "avg_duration_ms": round(np.mean(stats["durations"]), 2),
                "avg_hit_rate": round(np.mean(stats["hit_rates"]), 4),
            }

        return result

    def get_signal_accuracy(self, signal_type: str = None) -> Dict[str, Any]:
        """Sinyal doğruluğu.

        Args:
            signal_type: Sinyal türü filtresi

        Returns:
            Doğruluk istatistikleri
        """
        if signal_type:
            outcomes = [o for o in self._signal_outcomes if o.signal_type == signal_type]
        else:
            outcomes = self._signal_outcomes

        if not outcomes:
            return {
                "total_signals": 0,
                "signal_type": signal_type or "all",
            }

        total = len(outcomes)
        correct = sum(1 for o in outcomes if o.correct)
        returns = [o.return_pct for o in outcomes]

        return {
            "total_signals": total,
            "correct_signals": correct,
            "accuracy_pct": round(correct / total * 100, 2),
            "avg_return_pct": round(np.mean(returns), 2),
            "median_return_pct": round(np.median(returns), 2),
            "win_rate_pct": round(sum(1 for r in returns if r > 0) / total * 100, 2),
            "avg_win_pct": round(np.mean([r for r in returns if r > 0]), 2) if any(r > 0 for r in returns) else 0,
            "avg_loss_pct": round(np.mean([r for r in returns if r < 0]), 2) if any(r < 0 for r in returns) else 0,
            "signal_type": signal_type or "all",
        }

    def get_top_performing_filters(self, limit: int = 10) -> List[Dict[str, Any]]:
        """En iyi performans gösteren filtreler.

        Args:
            limit: Maksimum sonuç

        Returns:
            En iyi filtreler
        """
        filter_stats = {}

        for outcome in self._signal_outcomes:
            sig = outcome.signal_type
            if sig not in filter_stats:
                filter_stats[sig] = {
                    "count": 0,
                    "correct": 0,
                    "total_return": 0.0,
                    "returns": [],
                }

            stats = filter_stats[sig]
            stats["count"] += 1
            if outcome.correct:
                stats["correct"] += 1
            stats["total_return"] += outcome.return_pct
            stats["returns"].append(outcome.return_pct)

        # Performansa göre sırala
        ranked = []
        for sig, stats in filter_stats.items():
            if stats["count"] < 3:  # Minimum 3 sinyal
                continue

            accuracy = stats["correct"] / stats["count"] * 100
            avg_return = np.mean(stats["returns"])
            sharpe = (
                np.mean(stats["returns"]) / np.std(stats["returns"])
                if np.std(stats["returns"]) > 0 else 0
            )

            ranked.append({
                "signal_type": sig,
                "total_signals": stats["count"],
                "accuracy_pct": round(accuracy, 2),
                "avg_return_pct": round(avg_return, 2),
                "total_return_pct": round(stats["total_return"], 2),
                "sharpe_ratio": round(sharpe, 2),
            })

        # Sharpe ratio'ya göre sırala
        ranked.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

        return ranked[:limit]

    def get_scan_type_comparison(self) -> Dict[str, Dict[str, Any]]:
        """Tarama türü karşılaştırması.

        Returns:
            Tarama türü → performans
        """
        comparison = {}

        for scan_type in ["batch", "live", "event", "manual"]:
            stats = self.get_stats(scan_type)
            if stats["total_scans"] > 0:
                comparison[scan_type] = stats

        return comparison

    def get_hourly_distribution(self) -> Dict[int, int]:
        """Saatlik tarama dağılımı.

        Returns:
            Saat → tarama sayısı
        """
        distribution = {h: 0 for h in range(24)}

        for metric in self._scan_metrics:
            dt = datetime.fromtimestamp(metric.timestamp, tz=timezone.utc)
            distribution[dt.hour] += 1

        return distribution

    def get_summary(self) -> Dict[str, Any]:
        """Genel özet.

        Returns:
            Performans özeti
        """
        return {
            "total_scans": len(self._scan_metrics),
            "total_signal_outcomes": len(self._signal_outcomes),
            "scan_types": self.get_scan_type_comparison(),
            "regime_performance": self.get_regime_performance(),
            "signal_accuracy": self.get_signal_accuracy(),
            "top_filters": self.get_top_performing_filters(limit=5),
        }

    def clear(self):
        """Tüm geçmişi temizle."""
        self._scan_metrics.clear()
        self._signal_outcomes.clear()
        logger.info("Performance tracker cleared")


# Singleton
performance_tracker = ScanPerformanceTracker()
