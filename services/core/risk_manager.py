import numpy as np
import polars as pl
from typing import List, Dict, Any

class RiskManager:
    """
    Phase 17 - Dinamik Pozisyon ve Risk Yonetimi
    """
    def __init__(self):
        # Risk parametreleri
        self.max_position_pct = 0.10       # Tek hisse max %10
        self.max_sector_pct = 0.25         # Tek sektör max %25
        self.max_drawdown_pct = 0.15       # Max drawdown %15
        self.stop_loss_pct = 0.07          # Stop loss %7
        self.trailing_stop_pct = 0.05      # Trailing stop %5
        self.max_open_positions = 15       # Max açık pozisyon
        self.min_cash_ratio = 0.10         # Min nakit oranı %10
        self.volatility_cap = 0.50         # Max volatilite %50
        self.correlation_threshold = 0.70  # Korelasyon eşiği
        self._risk_state = {
            "current_drawdown": 0.0,
            "peak_equity": 0.0,
            "positions": {},
            "sector_exposure": {},
        }

    def calculate_weights(self, predictions: List[Dict[str, Any]], method: str = "equal", max_weight: float = 0.20) -> Dict[str, float]:
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
            # volatilitesi dusuk olana daha cok agirlik
            inv_vols = []
            for p in predictions:
                vol = p.get("features", {}).get("volatility_20d", 0.0)
                if vol <= 0 or pl.Expr.is_null(vol):
                    vol = 0.40 # default
                inv_vols.append(1.0 / vol)
                
            total_inv_vol = sum(inv_vols)
            for p, inv_v in zip(predictions, inv_vols):
                w = inv_v / total_inv_vol if total_inv_vol > 0 else 1.0 / len(predictions)
                weights[p["ticker"]] = min(w, max_weight)
                
        elif method == "score_weighted":
            # LightGBM skoru yuksek olana daha cok agirlik
            # Softmax on scores
            scores = np.array([p["score"] for p in predictions])
            scores = np.nan_to_num(scores, nan=0.0)
            
            # Clip negative scores to 0 to avoid short selling weights
            scores = np.clip(scores, a_min=0, a_max=None)
            
            if scores.sum() == 0:
                # Fallback to equal
                w = 1.0 / len(predictions)
                for t in tickers: weights[t] = min(w, max_weight)
            else:
                raw_weights = scores / scores.sum()
                for p, w in zip(predictions, raw_weights):
                    weights[p["ticker"]] = min(float(w), max_weight)
                    
        else:
            raise ValueError(f"Unknown weight method: {method}")
            
        # Normalize weights to sum to 1.0 if they were capped
        total_w = sum(weights.values())
        if total_w > 0:
            for t in weights:
                weights[t] = weights[t] / total_w
                
        return weights

    def get_market_regime(self, bm_df: pl.DataFrame, target_date: pl.Series) -> float:
        """
        BIST100'un durumuna gore pazar rejimini dondurur.
        Çoklu rejim tespiti: trend + volatilite + momentum.
        1.0 = Tamamen Bull (100% yatirim)
        0.0 = Tamamen Bear (100% nakit)
        0.25-0.75 = Ara rejimler (kısmi yatirim)
        """
        sub_bm = bm_df[bm_df.index <= target_date]
        if len(sub_bm) < 200:
            return 1.0

        closes = sub_bm["Close"]
        current_close = closes[-1]
        ma_50 = closes.rolling(50).mean()[-1]
        ma_200 = closes.rolling(200).mean()[-1]

        # Volatilite (20 günlük)
        if len(closes) > 20:
            returns = closes.pct_change().drop_nulls()
            vol_20d = float(returns.tail(20).std()) if len(returns) >= 20 else 0.20
        else:
            vol_20d = 0.20

        # Momentum (20 günlük getiri)
        if len(closes) > 20:
            momentum_20d = (current_close / closes[-21] - 1) if closes[-21] > 0 else 0
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

        # Volatilite ayarlaması (yüksek vol → risk azalt)
        vol_factor = 1.0
        if vol_20d > 0.35:      # Çok yüksek volatilite
            vol_factor = 0.5
        elif vol_20d > 0.25:    # Yüksek volatilite
            vol_factor = 0.7
        elif vol_20d < 0.15:    # Düşük volatilite
            vol_factor = 1.1

        # Momentum ayarlaması
        momentum_factor = 1.0
        if momentum_20d > 0.10:     # Güçlü yukarı momentum
            momentum_factor = 1.15
        elif momentum_20d > 0.03:   # Hafif yukarı
            momentum_factor = 1.05
        elif momentum_20d < -0.10:  # Güçlü aşağı momentum
            momentum_factor = 0.6
        elif momentum_20d < -0.03:  # Hafif aşağı
            momentum_factor = 0.8

        # Final skor
        regime_score = max(0.0, min(1.0, trend_score * vol_factor * momentum_factor))
        return round(regime_score, 2)
