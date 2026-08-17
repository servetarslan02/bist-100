"""
ALPHA BIST — Feature Calculator v3.0 (Mask-First Design)

ROADMAP v3.0 FAZ 1-2:
- Mask-aware hesaplama (execute edilemeyen fiyatlar görmez)
- Cross-sectional rank features
- Sector relative features
- 7 motor çıktıları ile entegre

KURAL: Mask=0 olan günler feature hesaplamasında KULLANILMAMALI.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import structlog

logger = structlog.get_logger()


class FeatureCalculator:
    """Mask-aware teknik feature hesaplama."""

    def __init__(self):
        self._required_bars = 60
        logger.info("FeatureCalculator v3.0 initialized (Mask-First)")

    def compute_all_features(
        self,
        df: pd.DataFrame,
        mask: Optional[np.ndarray] = None,
        ticker: str = "",
    ) -> Dict[str, Any]:
        """Tüm feature'ları mask-aware hesapla.

        Args:
            df: OHLCV DataFrame
            mask: Tradability mask (1=valid, 0=invalid). None ise tümü valid.
            ticker: Hisse kodu (log için)
        """
        if len(df) < self._required_bars:
            logger.warning(f"[{ticker}] Insufficient data: {len(df)} bars")
            return {}

        # Mask uygula
        if mask is not None:
            if len(mask) != len(df):
                logger.error(f"[{ticker}] Mask length mismatch: {len(mask)} vs {len(df)}")
                mask = np.ones(len(df), dtype=int)
        else:
            mask = np.ones(len(df), dtype=int)

        # Mask-aware veri çıkarımı
        close = df["Close"].values.copy()
        high = df["High"].values.copy()
        low = df["Low"].values.copy()
        open_ = df["Open"].values.copy() if "Open" in df.columns else close.copy()
        volume = df["Volume"].values.copy() if "Volume" in df.columns else np.ones(len(close))

        # Mask uygula: invalid günleri NaN yap
        close = np.where(mask == 1, close, np.nan)
        high = np.where(mask == 1, high, np.nan)
        low = np.where(mask == 1, low, np.nan)
        open_ = np.where(mask == 1, open_, np.nan)
        volume = np.where(mask == 1, volume, np.nan)

        features = {}

        # === TREND (mask-aware) ===
        features["sma_20"] = self._sma_masked(close, 20)
        features["sma_50"] = self._sma_masked(close, 50)
        features["ema_12"] = self._ema_masked(close, 12)
        features["ema_26"] = self._ema_masked(close, 26)

        # === MOMENTUM (mask-aware) ===
        features["roc_5d"] = self._roc_masked(close, 5)
        features["roc_20d"] = self._roc_masked(close, 20)
        features["roc_60d"] = self._roc_masked(close, 60)
        features["roc_120d"] = self._roc_masked(close, 120)
        features["momentum_20d"] = self._momentum_masked(close, 20)

        # === RSI (mask-aware) ===
        features["rsi_14"] = self._rsi_masked(close, 14)
        features["rsi_5"] = self._rsi_masked(close, 5)

        # === MACD (mask-aware) ===
        macd, signal, hist = self._macd_masked(close)
        features["macd"] = macd
        features["macd_signal"] = signal
        features["macd_hist"] = hist

        # === BOLLINGER (mask-aware) ===
        bb_upper, bb_lower, bb_position = self._bollinger_masked(close)
        features["bb_upper"] = bb_upper
        features["bb_lower"] = bb_lower
        features["bb_position"] = bb_position
        features["bb_width"] = bb_upper - bb_lower

        # === STOCHASTIC (mask-aware) ===
        k, d = self._stochastic_masked(high, low, close)
        features["stoch_k"] = k
        features["stoch_d"] = d

        # === ATR (mask-aware) ===
        features["atr_14"] = self._atr_masked(high, low, close, 14)
        features["atr_pct"] = (features["atr_14"] / close[~np.isnan(close)][-1] * 100) if np.any(~np.isnan(close)) else 0

        # === ADX (mask-aware) ===
        features["adx"] = self._adx_masked(high, low, close, 14)

        # === VOLUME (mask-aware) ===
        features["volume_zscore"] = self._volume_zscore_masked(volume)
        features["volume_trend"] = self._volume_trend_masked(volume)
        features["obv"] = self._obv_masked(close, volume)

        # === PRICE RELATIVES ===
        valid_close = close[~np.isnan(close)]
        if len(valid_close) > 0:
            last_close = valid_close[-1]
            features["price_vs_sma20"] = (last_close / features["sma_20"] - 1) * 100 if features["sma_20"] else 0
            features["price_vs_sma50"] = (last_close / features["sma_50"] - 1) * 100 if features["sma_50"] else 0

        # === VOLATILITY (mask-aware) ===
        features["volatility_20d"] = self._volatility_masked(close, 20)
        features["volatility_60d"] = self._volatility_masked(close, 60)
        features["realized_vol_20d"] = features["volatility_20d"]

        # === VOLUME PROFILE (mask-aware) ===
        valid_close_vol = close[~np.isnan(close)]
        valid_volume = volume[~np.isnan(volume)]
        if len(valid_close_vol) >= 20 and len(valid_volume) >= 20:
            vp = self._volume_profile(valid_close_vol, valid_volume)
            # FAZ 4.7: Dict yerine scalar feature'lar (feature contract uyumluluğu)
            features["vp_poc"] = vp.get("poc", 0.0)
            features["vp_value_area_high"] = vp.get("value_area_high", 0.0)
            features["vp_value_area_low"] = vp.get("value_area_low", 0.0)
            features["vp_bins"] = float(vp.get("bins", 0))
            features["poc_price"] = vp.get("poc", valid_close_vol[-1])
            features["value_area_high"] = vp.get("value_area_high", valid_close_vol[-1])
            features["value_area_low"] = vp.get("value_area_low", valid_close_vol[-1])

        # === PRICE ACTION (mask-aware) ===
        features["higher_highs"] = self._higher_highs_masked(high)
        features["lower_lows"] = self._lower_lows_masked(low)
        features["inside_days"] = self._inside_days_masked(high, low)

        # === CROSS-SECTIONAL (evren bazlı - sonradan hesaplanır) ===
        # Bunlar cross_sectional.py'de hesaplanır

        # Round all
        for key in features:
            if isinstance(features[key], float):
                features[key] = round(features[key], 4)

        # Mask stats ekle
        features["_mask_valid_pct"] = round(np.sum(mask) / len(mask) * 100, 1)
        features["_mask_invalid_count"] = int(len(mask) - np.sum(mask))

        # FAZ 4.8: Scalar guard — dict/nested feature'ları filtrele
        features = self._enforce_scalar_features(features, ticker)

        return features

    @staticmethod
    def _enforce_scalar_features(features: Dict[str, Any], ticker: str = "") -> Dict[str, Any]:
        """Dict/nested feature'ları güvenli şekilde filtrele.

        Sadece scalar (int/float) ve finite olan feature'lar korunur.
        Dict, list, array, inf, NaN olan feature'lar atılır.
        """
        result = {}
        dropped = []
        for k, v in features.items():
            if v is None:
                continue
            if isinstance(v, (int, float, np.floating, np.integer)):
                fv = float(v)
                if np.isfinite(fv):
                    result[k] = fv
                else:
                    dropped.append(k)
            elif isinstance(v, np.ndarray) and v.size == 1:
                fv = float(v.flat[0])
                if np.isfinite(fv):
                    result[k] = fv
                else:
                    dropped.append(k)
            else:
                dropped.append(k)

        if dropped:
            logger.debug(f"[{ticker}] Dropped non-scalar features: {dropped}")

        return result

    # === MASK-AWARE HELPER METHODS ===

    def _sma_masked(self, data: np.ndarray, period: int) -> float:
        """Mask-aware SMA."""
        valid = data[~np.isnan(data)]
        if len(valid) < period:
            return valid[-1] if len(valid) > 0 else 0
        return float(np.mean(valid[-period:]))

    def _ema_masked(self, data: np.ndarray, period: int) -> float:
        """Mask-aware EMA."""
        valid = data[~np.isnan(data)]
        if len(valid) < period:
            return valid[-1] if len(valid) > 0 else 0
        alpha = 2 / (period + 1)
        ema = valid[0]
        for price in valid[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return float(ema)

    def _roc_masked(self, data: np.ndarray, period: int) -> float:
        """Mask-aware ROC."""
        valid = data[~np.isnan(data)]
        if len(valid) <= period:
            return 0
        return (valid[-1] / valid[-period - 1] - 1) * 100

    def _momentum_masked(self, data: np.ndarray, period: int) -> float:
        """Mask-aware momentum."""
        valid = data[~np.isnan(data)]
        if len(valid) <= period:
            return 0
        return (valid[-1] - valid[-period - 1]) / valid[-period - 1] * 100

    def _rsi_masked(self, data: np.ndarray, period: int = 14) -> float:
        """Mask-aware RSI."""
        valid = data[~np.isnan(data)]
        if len(valid) < period + 1:
            return 50
        deltas = np.diff(valid)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _macd_masked(self, data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """Mask-aware MACD."""
        valid = data[~np.isnan(data)]
        if len(valid) < slow:
            return 0, 0, 0
        ema_fast = self._ema_on_array(valid, fast)
        ema_slow = self._ema_on_array(valid, slow)
        macd_line = ema_fast - ema_slow
        # Signal line
        macd_series = []
        for i in range(slow, len(valid)):
            ef = self._ema_on_array(valid[:i+1], fast)
            es = self._ema_on_array(valid[:i+1], slow)
            macd_series.append(ef - es)
        signal_line = self._ema_on_array(np.array(macd_series), signal) if len(macd_series) >= signal else macd_series[-1] if macd_series else 0
        hist = macd_line - signal_line
        return float(macd_line), float(signal_line), float(hist)

    def _ema_on_array(self, data: np.ndarray, period: int) -> float:
        """Array üzerinde EMA hesapla."""
        if len(data) < period:
            return data[-1] if len(data) > 0 else 0
        alpha = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema

    def _bollinger_masked(self, data: np.ndarray, period: int = 20, std_dev: int = 2) -> Tuple[float, float, float]:
        """Mask-aware Bollinger Bands."""
        valid = data[~np.isnan(data)]
        if len(valid) < period:
            return valid[-1] if len(valid) > 0 else 0, valid[-1] if len(valid) > 0 else 0, 0.5
        sma = np.mean(valid[-period:])
        std = np.std(valid[-period:])
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        if upper == lower:
            position = 0.5
        else:
            position = (valid[-1] - lower) / (upper - lower)
        return float(upper), float(lower), max(0, min(1, position))

    def _stochastic_masked(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, k_period: int = 14, d_period: int = 3) -> Tuple[float, float]:
        """Mask-aware Stochastic."""
        valid_mask = ~np.isnan(high) & ~np.isnan(low) & ~np.isnan(close)
        h = high[valid_mask]
        l = low[valid_mask]
        c = close[valid_mask]
        if len(c) < k_period:
            return 50, 50
        lowest_low = np.min(l[-k_period:])
        highest_high = np.max(h[-k_period:])
        if highest_high == lowest_low:
            k = 50
        else:
            k = (c[-1] - lowest_low) / (highest_high - lowest_low) * 100
        # D = SMA(K, d_period)
        k_values = []
        for i in range(k_period - 1, len(c)):
            ll = np.min(l[i-k_period+1:i+1])
            hh = np.max(h[i-k_period+1:i+1])
            if hh == ll:
                k_values.append(50)
            else:
                k_values.append((c[i] - ll) / (hh - ll) * 100)
        if len(k_values) >= d_period:
            d = np.mean(k_values[-d_period:])
        else:
            d = k
        return float(k), float(d)

    def _atr_masked(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
        """Mask-aware ATR."""
        valid_mask = ~np.isnan(high) & ~np.isnan(low) & ~np.isnan(close)
        h = high[valid_mask]
        l = low[valid_mask]
        c = close[valid_mask]
        if len(c) < period + 1:
            return 0
        tr_values = []
        for i in range(1, len(c)):
            tr1 = h[i] - l[i]
            tr2 = abs(h[i] - c[i-1])
            tr3 = abs(l[i] - c[i-1])
            tr_values.append(max(tr1, tr2, tr3))
        return float(np.mean(tr_values[-period:]))

    def _adx_masked(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
        """Mask-aware ADX."""
        valid_mask = ~np.isnan(high) & ~np.isnan(low) & ~np.isnan(close)
        h = high[valid_mask]
        l = low[valid_mask]
        c = close[valid_mask]
        if len(c) < period * 2:
            return 25
        plus_dm = []
        minus_dm = []
        tr_list = []
        for i in range(1, len(c)):
            up_move = h[i] - h[i-1]
            down_move = l[i-1] - l[i]
            plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
            minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
            tr_list.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
        atr = np.mean(tr_list[:period])
        dx_values = []
        for i in range(period, len(tr_list)):
            atr = atr * (period - 1) / period + tr_list[i] / period
            pdi = 100 * plus_dm[i] / atr if atr > 0 else 0
            mdi = 100 * minus_dm[i] / atr if atr > 0 else 0
            dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
            dx_values.append(dx)
        if len(dx_values) >= period:
            adx = np.mean(dx_values[-period:])
        elif dx_values:
            adx = np.mean(dx_values)
        else:
            adx = 25
        return float(adx)

    def _volume_zscore_masked(self, volume: np.ndarray) -> float:
        """Mask-aware volume z-score."""
        valid = volume[~np.isnan(volume)]
        if len(valid) < 20:
            return 0
        mean = np.mean(valid[-20:])
        std = np.std(valid[-20:])
        if std == 0:
            return 0
        return float((valid[-1] - mean) / std)

    def _volume_trend_masked(self, volume: np.ndarray) -> float:
        """Mask-aware volume trend."""
        valid = volume[~np.isnan(volume)]
        if len(valid) < 10:
            return 0
        recent = np.mean(valid[-5:])
        prev = np.mean(valid[-10:-5])
        if prev == 0:
            return 0
        return (recent / prev - 1) * 100

    def _obv_masked(self, close: np.ndarray, volume: np.ndarray) -> float:
        """Mask-aware OBV."""
        valid_mask = ~np.isnan(close) & ~np.isnan(volume)
        c = close[valid_mask]
        v = volume[valid_mask]
        if len(c) < 2:
            return 0
        obv = 0
        for i in range(1, len(c)):
            if c[i] > c[i-1]:
                obv += v[i]
            elif c[i] < c[i-1]:
                obv -= v[i]
        return float(obv)

    def _volatility_masked(self, data: np.ndarray, period: int) -> float:
        """Mask-aware volatility."""
        valid = data[~np.isnan(data)]
        if len(valid) < period:
            return 0
        returns = np.diff(valid[-period:]) / valid[-period:-1]
        return float(np.std(returns) * np.sqrt(252) * 100)

    def _volume_profile(self, close: np.ndarray, volume: np.ndarray) -> Dict:
        """Volume profile (dinamik bins)."""
        n = len(close)
        if n < 20:
            return {"poc": close[-1], "value_area_high": close[-1], "value_area_low": close[-1]}
        n_bins = max(10, min(50, int(np.sqrt(n))))
        hist, bin_edges = np.histogram(close, bins=n_bins, weights=volume)
        poc_idx = np.argmax(hist)
        poc = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2
        total_vol = np.sum(hist)
        target_vol = total_vol * 0.7
        sorted_indices = np.argsort(hist)[::-1]
        cum_vol = 0
        va_indices = []
        for idx in sorted_indices:
            cum_vol += hist[idx]
            va_indices.append(idx)
            if cum_vol >= target_vol:
                break
        va_high = bin_edges[max(va_indices) + 1]
        va_low = bin_edges[min(va_indices)]
        return {"poc": poc, "value_area_high": va_high, "value_area_low": va_low, "bins": n_bins}

    def _higher_highs_masked(self, high: np.ndarray) -> int:
        """Mask-aware higher highs."""
        valid = high[~np.isnan(high)]
        if len(valid) < 5:
            return 0
        count = 0
        for i in range(-5, 0):
            if valid[i] > valid[i-1]:
                count += 1
        return count

    def _lower_lows_masked(self, low: np.ndarray) -> int:
        """Mask-aware lower lows."""
        valid = low[~np.isnan(low)]
        if len(valid) < 5:
            return 0
        count = 0
        for i in range(-5, 0):
            if valid[i] < valid[i-1]:
                count += 1
        return count

    def _inside_days_masked(self, high: np.ndarray, low: np.ndarray) -> int:
        """Mask-aware inside days."""
        valid_mask = ~np.isnan(high) & ~np.isnan(low)
        h = high[valid_mask]
        l = low[valid_mask]
        if len(h) < 2:
            return 0
        return 1 if (h[-1] < h[-2] and l[-1] > l[-2]) else 0

    def compute_cross_sectional_features(
        self,
        ticker: str,
        features: Dict[str, float],
        universe_features: Dict[str, Dict[str, float]],
    ) -> Dict[str, float]:
        """Cross-sectional feature'ları hesapla.

        Args:
            ticker: Hisse kodu
            features: Bu hissenin feature'ları
            universe_features: Tüm hisselerin feature'ları
        """
        from services.features.cross_sectional import cross_sectional_engine
        return cross_sectional_engine.compute_rank_features(ticker, features, universe_features)


# Singleton
feature_calculator = FeatureCalculator()


# =====================================================
# Feature Module Bağlantıları — Tüm feature modüllerini birleştir
# =====================================================
def compute_extended_features(prices, highs=None, lows=None, closes=None, volumes=None,
                              fundamentals=None, news_data=None, macro_data=None) -> Dict[str, float]:
    """Tüm feature modüllerini birleştir."""
    features = {}

    # 1. Technical Features
    try:
        from services.features.technical_features import technical_feature_engine
        features.update(technical_feature_engine.compute_trend_features(prices))
        features.update(technical_feature_engine.compute_momentum_features(prices, highs, lows))
        features.update(technical_feature_engine.compute_volatility_features(prices, highs, lows, closes))
        if volumes is not None:
            features.update(technical_feature_engine.compute_volume_features(prices, volumes))
    except Exception as e:
        logger.warning("Technical features failed", error=str(e))

    # 2. Extended Indicators
    try:
        from services.features.extended_indicators import ExtendedIndicators
        ei = ExtendedIndicators()
        if highs is not None and lows is not None:
            features.update(ei.compute_all(prices, highs, lows, closes or prices, volumes or np.ones(len(prices))))
    except: pass

    # 3. Fundamental Features
    try:
        from services.features.fundamental import FundamentalFeatureEngine
        if fundamentals:
            features.update(FundamentalFeatureEngine().compute(fundamentals))
    except: pass

    # 4. Sentiment Features
    try:
        from services.features.sentiment import SentimentFeatureEngine
        if news_data:
            features.update(SentimentFeatureEngine().compute(news_data))
    except: pass

    # 5. Macro Features
    try:
        from services.features.macro import compute_all_macro_features
        if macro_data:
            features.update(compute_all_macro_features(**macro_data))
    except: pass

    # 6. Bar Engine
    try:
        from services.features.bar_engine import BarEngine
        # Bar engine OHLCV bar oluşturma
    except: pass

    # 7. Discovery
    try:
        from services.features.discovery import DiscoveryEngine
        # Discovery engine hisse keşfi
    except: pass

    # 8. Store
    try:
        from services.features.store import FeatureStore
        # Feature store'a yaz
    except: pass

    # 9. Feature Selector
    try:
        from services.features.feature_selector import feature_selector
        # Feature selection opsiyonu
    except: pass

    return features
