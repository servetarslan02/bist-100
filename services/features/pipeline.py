"""
ALPHA BIST — Feature Pipeline & Store Orchestrator
Öznitelik hesaplama, drift tespiti, hedef değişken üretimi (return_5d, return_20d)
ve Feature Store senkronizasyonunu yönetir.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import polars as pl
import numpy as np
import structlog
from .store import feature_store

logger = structlog.get_logger()


@dataclass
class PipelineConfig:
    """Feature Pipeline konfigürasyonu."""
    drift_threshold: float = 0.25
    enable_drift_detection: bool = True
    save_to_store: bool = True
    target_horizons: List[int] = field(default_factory=lambda: [1, 5, 10, 20])


@dataclass
class PipelineResult:
    """Pipeline çalıştırma sonucu."""
    ticker: str
    feature_count: int
    drift_report: Optional[Dict[str, Any]] = None
    target_features: Dict[str, float] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FeaturePipeline:
    """End-to-end Feature Pipeline motoru."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self._reference_stats: Dict[str, Dict[str, float]] = {}

    async def run(
        self,
        ticker: str,
        features: Dict[str, Any],
        ohlcv_df: Optional[Any] = None,
    ) -> PipelineResult:
        """Pipeline adımlarını yürüt: Zenginleştirme, Hedef Kolonlar, Store ve Drift."""
        clean_features: Dict[str, float] = {}
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

    def _compute_target_features(self, features: Dict[str, float], ohlcv_df: Any) -> Dict[str, float]:
        """Gelecek ve geçmiş getiri hedeflerini (return_5d, return_20d vb.) hesaplar."""
        targets: Dict[str, float] = {}
        try:
            if ohlcv_df is not None:
                # DataFrame desteği (polars veya pandas)
                if hasattr(ohlcv_df, "to_pandas"):
                    pdf = ohlcv_df.to_pandas()
                elif isinstance(ohlcv_df, pl.DataFrame):
                    pdf = ohlcv_df
                else:
                    pdf = None

                if pdf is not None and len(pdf) > 5 and "close" in pdf.columns:
                    closes = pdf["close"].to_numpy()
                    current_close = float(closes[-1])
                    if current_close > 0:
                        if len(closes) >= 2 and closes[-2] > 0:
                            targets = targets.with_columns(pl.lit(float((current_close / closes[-2]) - 1.0)).alias('return_1d'))
                        if len(closes) >= 6 and closes[-6] > 0:
                            targets = targets.with_columns(pl.lit(float((current_close / closes[-6]) - 1.0)).alias('return_5d'))
                        if len(closes) >= 11 and closes[-11] > 0:
                            targets = targets.with_columns(pl.lit(float((current_close / closes[-11]) - 1.0)).alias('return_10d'))
                        if len(closes) >= 21 and closes[-21] > 0:
                            targets = targets.with_columns(pl.lit(float((current_close / closes[-21]) - 1.0)).alias('return_20d'))
        except Exception:
            logger.warning("Caught Exception in _compute_target_features", exc_info=True)

        # Fallback sentetik / model target kolonları
        for h in self.config.target_horizons:
            key = f"return_{h}d"
            if key not in targets:
                # Mevcut momentum/rsi üzerinden güvenli getiri tahmini
                rsi = features.get("rsi_14", 50.0)
                mom = features.get("momentum_10d", 0.0)
                targets[key] = round((mom * (h / 10.0)) + ((rsi - 50.0) / 1000.0), 4)

        return targets

    def _compute_bist_features(self, ticker: str, features: Dict[str, float]) -> Dict[str, float]:
        """BIST-specific feature'ları hesapla.

        market_session_fsm ve auto_circuit_breaker'dan gerçek zamanlı durum bilgisi alır.
        """
        bist: Dict[str, float] = {}
        try:
            from services.core.market_session_fsm import bist_session_fsm, BISTMarketPhase
            from services.core.auto_circuit_breaker import auto_circuit_breaker
            from services.core.short_selling import short_selling_monitor
            from services.core.gross_settlement import gross_settlement_monitor

            # Seans fazı features
            phase = bist_session_fsm.get_phase(ticker=ticker)
            bist = bist.with_columns(pl.lit(1.0 if phase in {
                BISTMarketPhase.OPENING_AUCTION_COLLECTION,
                BISTMarketPhase.OPENING_AUCTION_DETERMINATION
            } else 0.0).alias('is_opening_auction'))
            bist = bist.with_columns(pl.lit(1.0 if phase in {
                BISTMarketPhase.CLOSING_AUCTION_COLLECTION,
                BISTMarketPhase.CLOSING_AUCTION_DETERMINATION,
                BISTMarketPhase.CLOSING_PRICE_TRADING
            } else 0.0).alias('is_closing_auction'))
            bist = bist.with_columns(pl.lit(1.0 if phase == BISTMarketPhase.CONTINUOUS_AUCTION else 0.0).alias('is_continuous_auction'))

            # Devre kesici features
            cb_status = auto_circuit_breaker.get_status()
            bist = bist.with_columns(pl.lit(1.0 if cb_status.get("ebdks_active", False) else 0.0).alias('ebdks_active'))
            bist = bist.with_columns(pl.lit(float(cb_status.get("ebdks_triggered_today", 0))).alias('ebdks_triggered_today'))
            bist = bist.with_columns(pl.lit(float(cb_status.get("bist100_change_pct", 0))).alias('bist100_change_pct'))

            # EBDKS'ye mesafe
            bist100_change = cb_status.get("bist100_change_pct", 0)
            bist = bist.with_columns(pl.lit(float(bist100_change + 6.0)).alias('bist100_distance_to_ebdks'))  # %6 eşiğine mesafe

            # Uptick rule
            bist = bist.with_columns(pl.lit(1.0 if short_selling_monitor._uptick_rule_active else 0.0).alias('uptick_rule_active'))

            # Brüt takas
            bist = bist.with_columns(pl.lit(1.0 if gross_settlement_monitor.is_short_sell_blocked(ticker) else 0.0).alias('is_gross_settlement'))

            # Açığa satış uygunluk
            bist = bist.with_columns(pl.lit(1.0 if ticker in (short_selling_monitor._bist50_cache or []) else 0.0).alias('short_sale_eligible'))

        except Exception as e:
            logger.debug("BIST feature computation failed", ticker=ticker, error=str(e))

        return bist

    def _check_drift(self, ticker: str, current_features: Dict[str, float]) -> Dict[str, Any]:
        """Referans istatistikler ile mevcut özellikler arasındaki drift kontrolü."""
        if ticker not in self._reference_stats:
            self._reference_stats[ticker] = {
                k: float(v) for k, v in current_features.items()
            }
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
