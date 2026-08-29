"""
ALPHA BIST — Feature Pipeline & Store Orchestrator
Öznitelik hesaplama, drift tespiti, hedef değişken üretimi (return_5d, return_20d)
ve Feature Store senkronizasyonunu yönetir.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
import structlog

from .contract import feature_registry
from .store import feature_store

logger = structlog.get_logger()


@dataclass
class PipelineConfig:
    """Feature Pipeline konfigürasyonu."""

    drift_threshold: float = 0.25
    enable_drift_detection: bool = True
    save_to_store: bool = True
    target_horizons: list[int] = field(default_factory=lambda: [1, 5, 10, 20])


@dataclass
class PipelineResult:
    """Pipeline çalıştırma sonucu."""

    ticker: str
    feature_count: int
    drift_report: dict[str, Any] | None = None
    target_features: dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FeaturePipeline:
    """End-to-end Feature Pipeline motoru."""

    def __init__(self, config: PipelineConfig | None = None):
        """Otomatik eklendi."""
        self.config = config or PipelineConfig()
        self._reference_stats: dict[str, dict[str, float]] = {}

    async def run(
        self,
        ticker: str,
        features: dict[str, Any],
        ohlcv_df: Any | None = None,
    ) -> PipelineResult:
        """Pipeline adımlarını yürüt: Zenginleştirme, Hedef Kolonlar, Store ve Drift."""
        clean_features: dict[str, float] = {}
        for k, v in features.items():
            if isinstance(v, (int, float)) and not np.isnan(v) and not np.isinf(v):
                clean_features[k] = float(v)

        # 1. Target horizon features (return_1d, return_5d, return_10d, return_20d)
        target_features = self._compute_target_features(clean_features, ohlcv_df)
        clean_features.update(target_features)

        # 1b. BIST-specific feature enrichment
        bist_features = self._compute_bist_features(ticker, clean_features)
        clean_features.update(bist_features)

        # 2. Drift Detection
        drift_report = None
        if self.config.enable_drift_detection:
            drift_report = self._check_drift(ticker, clean_features)

        # 2b. PIT-safety kontrolü — PIT-safe olmayan feature'ları işaretle
        pit_warnings = []
        for fname, fval in clean_features.items():
            contract = feature_registry.get(fname)
            if contract and not contract.pit_safe:
                pit_warnings.append(fname)
            # Feature value validation
            if contract and not contract.validate_value(fval):
                logger.warning(
                    "Feature validation failed",
                    ticker=ticker,
                    feature=fname,
                    value=fval,
                )

        if pit_warnings:
            logger.warning(
                "PIT-unsafe features detected",
                ticker=ticker,
                features=pit_warnings,
            )

        # 3. Store'a kaydet
        if self.config.save_to_store and clean_features:
            try:
                feature_store.set_features(ticker, clean_features)
            except Exception as e:
                logger.debug("Feature store write error", ticker=ticker, error=str(e))

        return PipelineResult(
            ticker=ticker,
            feature_count=len(clean_features),
            drift_report=drift_report,
            target_features=target_features,
        )

    def _compute_target_features(self, features: dict[str, float], ohlcv_df: Any) -> dict[str, float]:
        """Gelecek ve geçmiş getiri hedeflerini (return_5d, return_20d vb.) hesaplar.

        KURAL: Gerçek fiyat verisi yoksa SAHTE/SENTETIK veri ÜRETILMEZ.
        Eksik target'lar üretilmez — downstream bunu 'veri yok' olarak algılar.
        """
        targets: dict[str, float] = {}
        try:
            if ohlcv_df is not None:
                # DataFrame desteği (polars veya pandas)
                if isinstance(ohlcv_df, pl.DataFrame):
                    pdf = ohlcv_df
                elif hasattr(ohlcv_df, "to_pandas"):
                    pdf = pl.from_pandas(ohlcv_df.to_pandas())
                else:
                    pdf = None

                if pdf is not None and len(pdf) > 5:
                    # Kolon adı normalize et (büyük/küçük harf uyumu)
                    close_col = None
                    for col_name in ["close", "Close", "CLOSE"]:
                        if col_name in pdf.columns:
                            close_col = col_name
                            break

                    if close_col:
                        closes = pdf[close_col].to_numpy()
                        current_close = float(closes[-1])
                        if current_close > 0:
                            if len(closes) >= 2 and closes[-2] > 0:
                                targets["return_1d"] = float((current_close / closes[-2]) - 1.0)
                            if len(closes) >= 6 and closes[-6] > 0:
                                targets["return_5d"] = float((current_close / closes[-6]) - 1.0)
                            if len(closes) >= 11 and closes[-11] > 0:
                                targets["return_10d"] = float((current_close / closes[-11]) - 1.0)
                            if len(closes) >= 21 and closes[-21] > 0:
                                targets["return_20d"] = float((current_close / closes[-21]) - 1.0)
        except Exception:
            logger.warning("Target feature computation error", exc_info=True)

        # SAHTE VERI ÜRETILMEZ — eksik target'lar üretilmez
        # Downstream (model, learning) eksik target'ı 'veri yok' olarak algılar

        return targets

    def _compute_bist_features(self, ticker: str, features: dict[str, float]) -> dict[str, float]:
        """BIST-specific feature'ları hesapla.

        market_session_fsm ve auto_circuit_breaker'dan gerçek zamanlı durum bilgisi alır.
        NOT: dict kullanılır — Polars DataFrame değil.
        """
        bist: dict[str, float] = {}
        try:
            from services.core.auto_circuit_breaker import auto_circuit_breaker
            from services.core.gross_settlement import gross_settlement_monitor
            from services.core.market_session_fsm import BISTMarketPhase, bist_session_fsm
            from services.core.short_selling import short_selling_monitor

            # Seans fazı features
            phase = bist_session_fsm.get_phase(ticker=ticker)
            bist["is_opening_auction"] = (
                1.0
                if phase in {BISTMarketPhase.OPENING_AUCTION_COLLECTION, BISTMarketPhase.OPENING_AUCTION_DETERMINATION}
                else 0.0
            )
            bist["is_closing_auction"] = (
                1.0
                if phase
                in {
                    BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
                    BISTMarketPhase.CLOSING_AUCTION_DETERMINATION,
                    BISTMarketPhase.CLOSING_PRICE_TRADING,
                }
                else 0.0
            )
            bist["is_continuous_auction"] = 1.0 if phase == BISTMarketPhase.CONTINUOUS_AUCTION else 0.0

            # Devre kesici features
            cb_status = auto_circuit_breaker.get_status()
            bist["ebdks_active"] = 1.0 if cb_status.get("ebdks_active", False) else 0.0
            bist["ebdks_triggered_today"] = float(cb_status.get("ebdks_triggered_today", 0))
            bist["bist100_change_pct"] = float(cb_status.get("bist100_change_pct", 0))

            # EBDKS'ye mesafe
            bist100_change = cb_status.get("bist100_change_pct", 0)
            bist["bist100_distance_to_ebdks"] = float(bist100_change + 6.0)  # %6 eşiğine mesafe

            # Uptick rule
            bist["uptick_rule_active"] = 1.0 if short_selling_monitor._uptick_rule_active else 0.0

            # Brüt takas
            bist["is_gross_settlement"] = 1.0 if gross_settlement_monitor.is_short_sell_blocked(ticker) else 0.0

            # Açığa satış uygunluk
            bist["short_sale_eligible"] = 1.0 if ticker in (short_selling_monitor._bist50_cache or []) else 0.0

        except Exception as e:
            logger.debug("BIST feature computation failed", ticker=ticker, error=str(e))

        return bist

    def _check_drift(self, ticker: str, current_features: dict[str, float]) -> dict[str, Any]:
        """Referans istatistikler ile mevcut özellikler arasındaki drift kontrolü."""
        if ticker not in self._reference_stats:
            self._reference_stats[ticker] = {k: float(v) for k, v in current_features.items()}
            return {"drifted_features": 0, "status": "baseline_established"}

        ref = self._reference_stats[ticker]
        drifted = 0
        details = {}

        for k, curr_val in current_features.items():
            if k in ref and ref[k] != 0:
                diff_pct = abs(curr_val - ref[k]) / (abs(ref[k]) + 1e-6)
                if diff_pct > self.config.drift_threshold:
                    drifted += 1
                    details[k] = round(diff_pct, 3)

        return {
            "drifted_features": drifted,
            "details": details,
            "status": "drift_detected" if drifted > 0 else "stable",
        }


feature_pipeline = FeaturePipeline()
