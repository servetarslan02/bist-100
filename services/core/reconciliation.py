from typing import Any
"""
ALPHA BIST — Cross-Source Reconciliation v1.0

Aynı veri birden fazla kaynaktan geldiğinde:
- Fiyat uyuşmazlığı tespiti
- Kaynak güvenilirliği bazlı seçim
- Anomali tespiti (sahte veri)
- Quality score hesaplama

Kaynak: Monte Carlo Data Quality Testing, Confluent streaming quality
"""

import functools
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.reconciliation")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass
class ReconciledData:
    """Uzlaştırılmış veri."""

    value: float
    source: str
    confidence: float  # 0-1
    quality_score: float  # 0-100
    all_sources: dict[str, float]
    discrepancy_pct: float  # Kaynaklar arası fark %
    is_consistent: bool
    anomaly_detected: bool


class CrossSourceReconciliation:
    """Çapraz kaynak doğrulama motoru."""

    # Kaynak güvenilirlik sıralaması (yüksek = daha güvenilir)
    SOURCE_RELIABILITY = {
        "borsaistanbul.com": 0.99,
        "kap.org.tr": 0.98,
        "yfinance": 0.90,
        "matriks": 0.95,
        "is_yatirim": 0.95,
        "bloomberg": 0.97,
        "reuters": 0.97,
        "dunya.com": 0.85,
        "borsagundem": 0.80,
        "aa": 0.85,
        "bloomberght": 0.90,
        "rss_feed": 0.75,
        "social_media": 0.40,
    }

    # Uyuşmazlık eşikleri
    TOLERANCE_PCT = 0.5  # %0.5 — normal
    WARNING_PCT = 2.0  # %2 — uyarı
    ANOMALY_PCT = 5.0  # %5 — anomali

    @otel_trace("reconciliation.reconcile_price")
    def reconcile_price(
        self,
        sources: dict[str, float],
        timestamp: datetime | None = None,
    ) -> ReconciledData:
        """Fiyat kaynaklarını uzlaştır.

        Args:
            sources: {"yfinance": 305.25, "matriks": 305.30, "kap": 305.20}
        """
        if not sources:
            return ReconciledData(
                value=0,
                source="none",
                confidence=0,
                quality_score=0,
                all_sources={},
                discrepancy_pct=0,
                is_consistent=False,
                anomaly_detected=True,
            )

        values = list(sources.values())
        list(sources.keys())

        # Temel istatistikler
        mean_val = np.mean(values)
        std_val = np.std(values) if len(values) > 1 else 0
        min_val = min(values)
        max_val = max(values)

        # Uyuşmazlık yüzdesi
        discrepancy_pct = ((max_val - min_val) / mean_val * 100) if mean_val > 0 else 0

        # Anomali tespiti (Z-score)
        anomaly_detected = False
        if len(values) >= 3 and std_val > 0:
            for val in values:
                zscore = abs(val - mean_val) / std_val
                if zscore > 3.0:
                    anomaly_detected = True
                    break

        # Tutarlılık
        is_consistent = discrepancy_pct < self.WARNING_PCT

        # En güvenilir kaynağı seç
        best_source = self._select_best_source(sources, mean_val)

        # Quality score
        quality_score = self._compute_quality_score(discrepancy_pct, anomaly_detected, len(sources), std_val)

        # Confidence
        confidence = self._compute_confidence(discrepancy_pct, anomaly_detected, len(sources))

        return ReconciledData(
            value=round(best_source[1], 4),
            source=best_source[0],
            confidence=round(confidence, 4),
            quality_score=round(quality_score, 1),
            all_sources=sources,
            discrepancy_pct=round(discrepancy_pct, 2),
            is_consistent=is_consistent,
            anomaly_detected=anomaly_detected,
        )

    @otel_trace("reconciliation.reconcile_multi_field")
    def reconcile_multi_field(
        self,
        ticker: str,
        data_per_source: dict[str, dict[str, float]],
    ) -> dict[str, ReconciledData]:
        """Çoklu alan uzlaştırması (price, volume, bid, ask)."""
        results = {}

        # Tüm alanları topla
        all_fields = set()
        for source_data in data_per_source.values():
            all_fields.update(source_data.keys())

        for field_name in all_fields:
            sources = {}
            for source_name, source_data in data_per_source.items():
                val = source_data.get(field_name)
                if val is not None:
                    sources[source_name] = val

            if sources:
                results[field_name] = self.reconcile_price(sources)

        return results

    def _select_best_source(
        self,
        sources: dict[str, float],
        mean_val: float,
    ) -> tuple[str, float]:
        """En güvenilir kaynağı seç.

        Öncelik:
        1. Güvenilirlik skoru en yüksek
        2. Ortalamaya en yakın
        """
        best_source = None
        best_score = -1

        for source_name, value in sources.items():
            reliability = self.SOURCE_RELIABILITY.get(source_name, 0.5)

            # Ortalamaya yakınlık bonusu
            closeness = 1 - abs(value - mean_val) / mean_val if mean_val > 0 else 1.0

            score = reliability * 0.7 + closeness * 0.3

            if score > best_score:
                best_score = score
                best_source = (source_name, value)

        return best_source or (list(sources.keys())[0], list(sources.values())[0])

    def _compute_quality_score(
        self,
        discrepancy_pct: float,
        anomaly_detected: bool,
        source_count: int,
        std_val: float,
    ) -> float:
        """Quality score hesapla (0-100)."""
        score = 100.0

        # Uyuşmazlık cezası
        if discrepancy_pct > self.ANOMALY_PCT:
            score -= 40
        elif discrepancy_pct > self.WARNING_PCT:
            score -= 20
        elif discrepancy_pct > self.TOLERANCE_PCT:
            score -= 10

        # Anomali cezası
        if anomaly_detected:
            score -= 30

        # Kaynak sayısı bonusu (daha fazla kaynak = daha güvenilir)
        if source_count >= 3:
            score += 5
        elif source_count == 1:
            score -= 10  # Tek kaynak riskli

        return max(0, min(100, score))

    def _compute_confidence(
        self,
        discrepancy_pct: float,
        anomaly_detected: bool,
        source_count: int,
    ) -> float:
        """Confidence hesapla (0-1)."""
        confidence = 0.8  # Varsayılan

        # Uyuşmazlık
        if discrepancy_pct > self.ANOMALY_PCT:
            confidence -= 0.4
        elif discrepancy_pct > self.WARNING_PCT:
            confidence -= 0.2
        elif discrepancy_pct > self.TOLERANCE_PCT:
            confidence -= 0.1

        # Anomali
        if anomaly_detected:
            confidence -= 0.3

        # Kaynak sayısı
        if source_count >= 3:
            confidence += 0.1
        elif source_count == 1:
            confidence -= 0.2

        return max(0, min(1, confidence))

    @otel_trace("reconciliation.detect_price_jump")
    def detect_price_jump(
        self,
        ticker: str,
        current_price: float,
        previous_price: float,
        volatility: float,
        threshold_sigma: float = 4.0,
    ) -> tuple[bool, float]:
        """Ani fiyat sıçraması tespiti.

        Volatiliteye göre normalize edilmiş eşik kullanır.
        """
        if previous_price <= 0:
            return False, 0

        change_pct = abs(current_price / previous_price - 1) * 100

        # Volatilite bazlı eşik
        if volatility > 0:
            expected_move = volatility / np.sqrt(252) * threshold_sigma
            is_jump = change_pct > expected_move
        else:
            is_jump = change_pct > 10  # Varsayılan %10

        return is_jump, change_pct


# Singleton
cross_source_reconciliation = CrossSourceReconciliation()
