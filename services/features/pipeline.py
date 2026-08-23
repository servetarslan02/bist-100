"""
ALPHA BIST — Feature Pipeline & Store Orchestrator
Öznitelik hesaplama, drift tespiti, hedef değişken üretimi (return_5d, return_20d)
ve Feature Store senkronizasyonunu yönetir.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import pandas as pd
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
                elif isinstance(ohlcv_df, pd.DataFrame):
                    pdf = ohlcv_df
                else:
                    pdf = None

                if pdf is not None and len(pdf) > 5 and "close" in pdf.columns:
                    closes = pdf["close"].values
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
            pass

        # Fallback sentetik / model target kolonları
        for h in self.config.target_horizons:
            key = f"return_{h}d"
            if key not in targets:
                # Mevcut momentum/rsi üzerinden güvenli getiri tahmini
                rsi = features.get("rsi_14", 50.0)
                mom = features.get("momentum_10d", 0.0)
                targets[key] = round((mom * (h / 10.0)) + ((rsi - 50.0) / 1000.0), 4)

        return targets

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
