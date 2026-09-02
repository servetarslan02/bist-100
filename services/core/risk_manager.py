from typing import Any

import numpy as np
import polars as pl
import structlog
from opentelemetry import trace
from services.core.otel import otel_trace
from services.core.risk_config import risk_config

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.risk_manager")

class RiskManager:
    """
    Phase 17 - Dinamik Pozisyon ve Risk Yonetimi (Polars-Native)
    """

    def __init__(self, config=None):
        cfg = config or risk_config
        self.max_position_pct = cfg.max_position_pct
        self.max_sector_pct = cfg.max_sector_pct
        self.max_drawdown_pct = cfg.max_drawdown_pct
        self.stop_loss_pct = cfg.stop_loss_pct
        self.trailing_stop_pct = cfg.trailing_stop_pct
        self.max_open_positions = cfg.max_open_positions
        self.min_cash_ratio = cfg.min_cash_ratio
        self.volatility_cap = cfg.volatility_cap
        self.correlation_threshold = cfg.correlation_threshold
        self._risk_state = {
            "current_drawdown": 0.0,
            "peak_equity": 0.0,
            "positions": {},
            "sector_exposure": {},
        }

    @otel_trace("risk_manager.calculate_weights")
    def calculate_weights(
        self, predictions: list[dict[str, Any]], method: str = "equal", max_weight: float = 0.20
    ) -> dict[str, float]:
        """
        Tahmin edilen TOP N hisse icin agirlik (weight) hesaplar.
        """
        if not predictions:
            return {}

        weights = {}
        tickers = [p["ticker"] for p in predictions]

        if method == "equal":
            w = 1.0 / len(predictions)
            for t in tickers:
                weights[t] = min(w, max_weight)

        elif method == "inverse_volatility":
            inv_vols = []
            for p in predictions:
                vol = p.get("features", {}).get("volatility_20d", 0.0)
                if vol is None or vol <= 0 or (isinstance(vol, float) and np.isnan(vol)):
                    vol = 0.40
                inv_vols.append(1.0 / vol)

            total_inv_vol = sum(inv_vols)
            for p, inv_v in zip(predictions, inv_vols, strict=False):
                w = inv_v / total_inv_vol if total_inv_vol > 0 else 1.0 / len(predictions)
                weights[p["ticker"]] = min(w, max_weight)

        elif method == "score_weighted":
            scores = np.array([p["score"] for p in predictions])
            scores = np.nan_to_num(scores, nan=0.0)
            scores = np.clip(scores, a_min=0, a_max=None)

            if scores.sum() == 0:
                w = 1.0 / len(predictions)
                for t in tickers:
                    weights[t] = min(w, max_weight)
            else:
                raw_weights = scores / scores.sum()
                for p, w in zip(predictions, raw_weights, strict=False):
                    weights[p["ticker"]] = min(float(w), max_weight)

        else:
            raise ValueError(f"Unknown weight method: {method}")

        # Normalize weights to sum to 1.0 if they were capped
        total_w = sum(weights.values())
        if total_w > 0:
            for t in weights:
                weights[t] = weights[t] / total_w

        return weights

    @otel_trace("risk_manager.get_market_regime")
    def get_market_regime(self, bm_df: pl.DataFrame, target_date) -> float:
        """
        BIST100'un durumuna gore pazar rejimini dondurur.
        Çoklu rejim tespiti: trend + volatilite + momentum.
        1.0 = Tamamen Bull (100% yatirim)
        0.0 = Tamamen Bear (100% nakit)
        0.25-0.75 = Ara rejimler (kısmi yatirim)
        """
        # Date sütunu varsa filtrele, yoksa index'e göre
        if "Date" in bm_df.columns:
            sub_bm = bm_df.filter(pl.col("Date") <= target_date)
        else:
            sub_bm = bm_df.head(len(bm_df))  # Fallback: tüm veri

        if len(sub_bm) < 200:
            return 1.0

        closes = sub_bm["Close"].cast(pl.Float64)
        current_close = float(closes[-1])
        ma_50 = float(closes.rolling_mean(50)[-1]) if len(closes) >= 50 else current_close
        ma_200 = float(closes.rolling_mean(200)[-1]) if len(closes) >= 200 else current_close

        # Volatilite (20 günlük)
        if len(closes) > 20:
            returns = closes.pct_change().drop_nulls()
            vol_20d = float(returns.tail(20).std()) if len(returns) >= 20 else 0.20
        else:
            vol_20d = 0.20

        # Momentum (20 günlük getiri)
        if len(closes) > 20:
            prev_close = float(closes[-21])
            momentum_20d = (current_close / prev_close - 1) if prev_close > 0 else 0
        else:
            momentum_20d = 0

        # Trend skoru (0-1)
        trend_score = 0.5
        if current_close > ma_200:
            trend_score += 0.3
        else:
            trend_score -= 0.3
        if current_close > ma_50:
            trend_score += 0.2
        else:
            trend_score -= 0.2

        # Volatilite ayarlaması
        vol_factor = 1.0
        if vol_20d > 0.35:
            vol_factor = 0.5
        elif vol_20d > 0.25:
            vol_factor = 0.7
        elif vol_20d < 0.15:
            vol_factor = 1.1

        # Momentum ayarlaması
        momentum_factor = 1.0
        if momentum_20d > 0.10:
            momentum_factor = 1.15
        elif momentum_20d > 0.03:
            momentum_factor = 1.05
        elif momentum_20d < -0.10:
            momentum_factor = 0.6
        elif momentum_20d < -0.03:
            momentum_factor = 0.8

        regime_score = max(0.0, min(1.0, trend_score * vol_factor * momentum_factor))
        return round(regime_score, 2)
