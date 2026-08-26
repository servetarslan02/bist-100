"""
ALPHA BIST — Feature Engine v2.0
=================================
Sadece gerçekten çalışan ve predictive olan feature'lar.

KURAL:
- Hiçbir feature sabit 0 döndürmez.
- Her feature için veri yoksa np.nan döner, 0 değil.
- Model nan'ları 0 ile doldurur (LightGBM handle eder).
- Cross-sectional feature'lar her gün tüm BIST100'e göre hesaplanır.

FEATURE GRUPLARI:
  A) Price Context     — hissenin kendi fiyat geçmişi
  B) Relative Strength — XU100 ve sektöre göre göreceli güç
  C) Trend Quality     — trendin gücü ve tutarlılığı
  D) Volume            — hacim anomalileri
  E) Risk              — volatilite ve drawdown
  F) Cross-Sectional   — tüm evrene göre z-score ve rank
  G) Fundamental Proxy — temel veri yokken fiyat kaldıraç proxy'si
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
from typing import Dict, List, Optional
import structlog

logger = structlog.get_logger()


def _safe_float(v) -> float:
    if v is None:
        return np.nan
    if hasattr(v, 'iloc'):
        v = v[-1] if len(v) > 0 else np.nan
    try:
        val = float(v)
        return np.nan if np.isnan(val) else val
    except Exception:
        return np.nan


class FeatureEngine:
    """
    Tüm feature hesaplamalarının tek kaynağı.
    
    Kullanım:
        engine = FeatureEngine()
        features = engine.compute_all(
            ticker="AKBNK",
            df=stock_df,             # OHLCV DataFrame, DatetimeIndex
            benchmark_df=xu100_df,   # XU100 OHLCV
            sector_dfs={"BANKA": bank_avg_df},  # sektör ortalaması
            universe_returns={"AKBNK": 0.02, ...},  # aynı günkü tüm hisseler
        )
    """

    # ------------------------------------------------------------------ #
    # Hesaplama pencereleri
    # ------------------------------------------------------------------ #
    LOOKBACK = {
        "short":  5,
        "medium": 20,
        "long":   60,
        "xlong":  120,
        "annual": 252,
    }

    def _normalize_index(self, df: pl.DataFrame) -> pl.DataFrame:
        """Tüm DataFrame index'lerini timezone-naive'e dönüştür ve MultiIndex sütunları düzleştir."""
        if df is None or df.empty:
            return df
        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        idx = pl.Series(df.index)
        if getattr(idx, 'tz', None) is not None:
            idx = idx.tz_convert(None)
        df.index = idx
        return df

    def compute_all(
        self,
        ticker: str,
        df: pl.DataFrame,
        benchmark_df: Optional[pl.DataFrame] = None,
        sector_returns: Optional[pl.Series] = None,     # günlük sektör return serisi
        universe_returns: Optional[Dict[str, float]] = None,  # {ticker: son_gün_return}
    ) -> Dict[str, float]:
        """
        Tüm feature'ları hesapla ve tek dict olarak döndür.
        Eksik veri → np.nan (asla 0 değil).
        """
        if df is None or len(df) < 20:
            return {}

        df = self._normalize_index(df)
        df = df.sort_index()

        if benchmark_df is not None:
            benchmark_df = self._normalize_index(benchmark_df)

        if sector_returns is not None and hasattr(sector_returns, 'index'):
            idx = pl.Series(sector_returns.index)
            if getattr(idx, 'tz', None) is not None:
                idx = idx.tz_convert(None)
            sector_returns = sector_returns.copy()
            sector_returns.index = idx

        close_raw = df["Close"]
        close = (close_raw.squeeze() if hasattr(close_raw, 'squeeze') else close_raw).astype(float)
        
        vol_raw = df["Volume"] if "Volume" in df else pl.Series(dtype=float)
        volume = (vol_raw.squeeze() if hasattr(vol_raw, 'squeeze') else vol_raw).astype(float)
        
        high_raw = df["High"] if "High" in df else close
        high = (high_raw.squeeze() if hasattr(high_raw, 'squeeze') else high_raw).astype(float)
        
        low_raw = df["Low"] if "Low" in df else close
        low = (low_raw.squeeze() if hasattr(low_raw, 'squeeze') else low_raw).astype(float)

        features: Dict[str, float] = {}

        # --- A) Price Context ---
        features.update(self._price_context(close, high, low))

        # --- B) Relative Strength ---
        if benchmark_df is not None and len(benchmark_df) >= 20:
            bm_raw = benchmark_df["Close"]
            bm_s = (bm_raw.squeeze() if hasattr(bm_raw, 'squeeze') else bm_raw).astype(float)
            bm_close = bm_s.reindex(close.index, method="ffill")
            features.update(self._relative_strength_vs_bm(close, bm_close))

        if sector_returns is not None and len(sector_returns) >= 5:
            sect = sector_returns.reindex(close.index, method="ffill")
            features.update(self._relative_strength_vs_sector(close, sect))

        # --- C) Trend Quality ---
        features.update(self._trend_quality(close))

        # --- D) Volume ---
        if not volume.empty and volume.sum() > 0:
            features.update(self._volume_features(close, volume))

        # --- E) Risk ---
        features.update(self._risk_features(close, high, low))

        # --- F) Cross-Sectional (universe bazlı) ---
        if universe_returns:
            features.update(self._cross_sectional(ticker, close, universe_returns))

        # --- G) Fundamental Proxy (price-implied) ---
        features.update(self._fundamental_proxy(close, volume))

        # NaN olmayan sayılara çevir; gerçek NaN'lar kalır
        return {k: _safe_float(v) for k, v in features.items() if v is not None}

    # ------------------------------------------------------------------ #
    # A) Price Context
    # ------------------------------------------------------------------ #
    def _price_context(self, close: pl.Series, high: pl.Series, low: pl.Series) -> Dict:
        f = {}
        n = len(close)

        # Getiri / momentum
        for label, w in [("5d", 5), ("20d", 20), ("60d", 60), ("120d", 120)]:
            if n > w:
                f[f"roc_{label}"] = _safe_float(close.pct_change(w)[-1])

        # SMA uzaklık
        for label, w in [("sma20", 20), ("sma50", 50), ("sma200", 200)]:
            if n > w:
                sma = close.rolling(w).mean()[-1]
                f[f"dist_{label}"] = _safe_float((close[-1] / sma) - 1)

        # 52-haftalık yüksekten uzaklık
        if n > 100:
            high_52w = high.rolling(252).max()[-1] if n >= 252 else high.max()
            low_52w  = low.rolling(252).min()[-1]  if n >= 252 else low.min()
            f = f.with_columns(pl.lit(_safe_float((close[-1] / high_52w) - 1)).alias('pct_from_52w_high'))
            f = f.with_columns(pl.lit(_safe_float((close[-1] / low_52w) - 1)).alias('pct_from_52w_low'))

        # RSI-14
        if n > 20:
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = (100 - 100 / (1 + rs))[-1]
            f = f.with_columns(pl.lit(_safe_float(rsi)).alias('rsi_14'))

        # Momentum acceleration (roc_5 vs roc_20 farkı — trend ivmesi)
        if "roc_5d" in f and "roc_20d" in f:
            f = f.with_columns(pl.lit(f["roc_5d"] - f["roc_20d"] / 4).alias('momentum_accel'))

        # Kısa dönem mean reversion potansiyeli
        if n > 20:
            std = close.pct_change().rolling(20).std()[-1]
            f = f.with_columns(pl.lit(_safe_float(
                (close[-1] - close.rolling(20).mean()[-1]) / (std * close.rolling(20).mean()[-1] + 1e-9)
            )).alias('zscore_vs_sma20'))

        return f

    # ------------------------------------------------------------------ #
    # B) Relative Strength
    # ------------------------------------------------------------------ #
    def _relative_strength_vs_bm(self, close: pl.Series, bm_close: pl.Series) -> Dict:
        f = {}
        stock_ret = close.pct_change()
        bm_ret    = bm_close.pct_change()

        for label, w in [("1d", 1), ("5d", 5), ("20d", 20), ("60d", 60)]:
            try:
                s = (1 + stock_ret.tail(w)).prod() - 1
                b = (1 + bm_ret.tail(w)).prod() - 1
                f[f"rs_vs_bist_{label}"] = _safe_float(s - b)
            except Exception:
                logger.warning("Caught Exception in _relative_strength_vs_bm", exc_info=True)

        # RS trend (rolling 5d RS değişimi)
        if len(stock_ret) > 25:
            rs_series = stock_ret - bm_ret
            rs_5d = rs_series.rolling(5).sum()
            f = f.with_columns(pl.lit(_safe_float(rs_5d.diff(5)[-1]) if len(rs_5d) > 5 else np.nan).alias('rs_trend_5d'))

        return f

    def _relative_strength_vs_sector(self, close: pl.Series, sect: pl.Series) -> Dict:
        f = {}
        stock_ret = close.pct_change()
        sect_ret  = sect

        for label, w in [("5d", 5), ("20d", 20)]:
            try:
                s = (1 + stock_ret.tail(w)).prod() - 1
                b = (1 + sect_ret.tail(w)).prod() - 1
                f[f"rs_vs_sector_{label}"] = _safe_float(s - b)
            except Exception:
                logger.warning("Caught Exception in _relative_strength_vs_sector", exc_info=True)

        return f

    # ------------------------------------------------------------------ #
    # C) Trend Quality
    # ------------------------------------------------------------------ #
    def _trend_quality(self, close: pl.Series) -> Dict:
        f = {}
        n = len(close)
        if n < 20:
            return f

        # Linear regression slope + R² (20 günlük)
        for label, w in [("20d", 20), ("60d", 60)]:
            if n > w:
                y = close.to_numpy()[-w:]
                x = np.arange(w)
                try:
                    slope, intercept = np.polyfit(x, y, 1)
                    y_pred = slope * x + intercept
                    ss_res = np.sum((y - y_pred) ** 2)
                    ss_tot = np.sum((y - y.mean()) ** 2)
                    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                    f[f"trend_slope_{label}"] = float(slope / close[-w])  # normalize
                    f[f"trend_r2_{label}"]    = float(r2)
                except Exception:
                    logger.warning("Caught Exception in _trend_quality", exc_info=True)

        # SMA alignment score (SMA20 > SMA50 > SMA200)
        if n >= 200:
            sma20  = close.rolling(20).mean()[-1]
            sma50  = close.rolling(50).mean()[-1]
            sma200 = close.rolling(200).mean()[-1]
            alignment = 0
            if sma20 > sma50:  alignment += 1
            if sma50 > sma200: alignment += 1
            if close[-1] > sma20: alignment += 1
            f = f.with_columns(pl.lit(float(alignment)).alias('sma_alignment'))  # 0-3

        # Higher highs / Higher lows (trend integrity)
        if n >= 20:
            highs = close.rolling(5).max().dropna()
            lows  = close.rolling(5).min().dropna()
            if len(highs) >= 4:
                f = f.with_columns(pl.lit(float(int(highs[-1] > highs[-3]))).alias('higher_highs'))
                f = f.with_columns(pl.lit(float(int(lows[-1]  > lows[-3]))).alias('higher_lows'))

        # Drawdown from recent peak
        if n >= 20:
            peak = close.rolling(20).max()[-1]
            f = f.with_columns(pl.lit(float((close[-1] / peak) - 1)).alias('drawdown_20d'))

        if n >= 60:
            peak60 = close.rolling(60).max()[-1]
            f = f.with_columns(pl.lit(float((close[-1] / peak60) - 1)).alias('drawdown_60d'))

        return f

    # ------------------------------------------------------------------ #
    # D) Volume
    # ------------------------------------------------------------------ #
    def _volume_features(self, close: pl.Series, volume: pl.Series) -> Dict:
        f = {}
        n = len(volume)
        if n < 20:
            return f

        vol_mean = volume.rolling(20).mean()
        vol_std  = volume.rolling(20).std()

        # Z-score
        z = (volume[-1] - vol_mean[-1]) / (vol_std[-1] + 1)
        f = f.with_columns(pl.lit(float(z)).alias('volume_zscore_20d'))

        # Percentile (yıllık)
        if n >= 60:
            pct = (volume.rolling(min(n, 252)).rank() / min(n, 252))[-1]
            f = f.with_columns(pl.lit(float(pct)).alias('volume_percentile'))

        # Volume trend (son 5 gün ortalaması / son 20 gün ortalaması)
        if n >= 20:
            short_avg = volume.rolling(5).mean()[-1]
            long_avg  = volume.rolling(20).mean()[-1]
            f = f.with_columns(pl.lit(float(short_avg / (long_avg + 1))).alias('volume_trend_ratio'))

        # Price-volume divergence (fiyat yükselirken hacim düşüyor mu?)
        if n >= 10:
            price_change = close.pct_change(5)[-1]
            vol_change   = volume.rolling(5).mean().pct_change(5)[-1]
            if not np.isnan(price_change) and not np.isnan(vol_change):
                f = f.with_columns(pl.lit(float(
                    1 if (price_change > 0 and vol_change < -0.2) else
                    (-1 if (price_change < 0 and vol_change > 0.2) else 0)
                )).alias('price_vol_divergence'))

        # On-Balance Volume direction
        if n >= 20:
            direction = (close.diff() > 0).astype(float) * 2 - 1
            obv = (volume * direction).cumsum()
            obv_20d_change = (obv[-1] - obv[-21]) / (abs(obv[-21]) + 1)
            f = f.with_columns(pl.lit(float(obv_20d_change)).alias('obv_trend_20d'))

        return f

    # ------------------------------------------------------------------ #
    # E) Risk
    # ------------------------------------------------------------------ #
    def _risk_features(self, close: pl.Series, high: pl.Series, low: pl.Series) -> Dict:
        f = {}
        n = len(close)
        returns = close.pct_change().dropna()

        if len(returns) >= 20:
            f = f.with_columns(pl.lit(float(returns.rolling(20).std()[-1] * np.sqrt(252))).alias('volatility_20d'))
        if len(returns) >= 60:
            f = f.with_columns(pl.lit(float(returns.rolling(60).std()[-1] * np.sqrt(252))).alias('volatility_60d'))

        # ATR %
        if n >= 14 and not high.empty and not low.empty:
            tr = pl.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr_pct = (tr.rolling(14).mean() / close)[-1]
            f = f.with_columns(pl.lit(float(atr_pct)).alias('atr_pct'))

        # Downside volatility
        if len(returns) >= 20:
            downside = returns[returns < 0].rolling(20, min_periods=5).std()
            if len(downside.dropna()) > 0:
                f = f.with_columns(pl.lit(float(downside[-1] * np.sqrt(252))).alias('downside_vol_20d'))

        # Beta approximation needs benchmark — skipped here, done in RS section
        return f

    # ------------------------------------------------------------------ #
    # F) Cross-Sectional
    # ------------------------------------------------------------------ #
    def _cross_sectional(
        self, ticker: str,
        close: pl.Series,
        universe_returns: Dict[str, float],
    ) -> Dict:
        f = {}
        all_rets = list(universe_returns.values())
        if len(all_rets) < 5:
            return f

        this_ret = universe_returns.get(ticker)
        if this_ret is None:
            return f

        arr = np.array(all_rets)
        mean = arr.mean()
        std  = arr.std()

        if std > 1e-9:
            f = f.with_columns(pl.lit(float((this_ret - mean) / std)).alias('cs_zscore_ret_1d'))

        # Percentile rank
        rank = float(np.mean(arr <= this_ret))
        f = f.with_columns(pl.lit(rank).alias('cs_rank_ret_1d'))

        return f

    # ------------------------------------------------------------------ #
    # G) Fundamental Proxy (fiyat bazlı, bilanço verisi gerektirmez)
    # ------------------------------------------------------------------ #
    def _fundamental_proxy(self, close: pl.Series, volume: pl.Series) -> Dict:
        f = {}
        n = len(close)

        # Price momentum persistency (kazananlar kazanmaya devam eder mi?)
        # Basit fikir: 6 aylık getirinin son 1 aylık getirisini ne kadar tahmin ettiği
        if n >= 130:
            ret_6m  = float(close.pct_change(120)[-1])
            ret_1m  = float(close.pct_change(20)[-1])
            # 6 aylık güçlü + son ay zayıf = orta dönem momentum devam edebilir
            f = f.with_columns(pl.lit(float(
                1 if (ret_6m > 0.15 and ret_1m < -0.05) else
                (-1 if (ret_6m < -0.15 and ret_1m > 0.05) else 0)
            )).alias('momentum_reversal_risk'))

        # Liquidity score (yüksek hacim = işlem yapılabilirlik)
        if not volume.empty and n >= 20:
            avg_vol = volume.rolling(20).mean()[-1]
            f = f.with_columns(pl.lit(float(min(1.0, np.log1p(avg_vol) / 15))).alias('liquidity_score'))  # normalize log scale

        return f


# ------------------------------------------------------------------ #
# Helper: Tüm evreni tek seferde hesapla
# ------------------------------------------------------------------ #
def compute_universe_features(
    market_data: Dict[str, pl.DataFrame],
    benchmark_df: pl.DataFrame,
    sector_map: Dict[str, str],  # ticker -> sektör adı
) -> Dict[str, Dict[str, float]]:
    """
    Tüm hisseler için feature'ları hesapla.
    Cross-sectional feature'lar universe'in tamamını gerektirir.
    
    Returns:
        {ticker: {feature_name: value}}
    """
    engine = FeatureEngine()

    # 0. Tüm DataFrame'lerin index'ini timezone-naive'e normalize et
    normalized_data: Dict[str, pl.DataFrame] = {}
    for ticker, df in market_data.items():
        if df is not None and not df.empty:
            normalized_data[ticker] = engine._normalize_index(df)
    market_data = normalized_data

    if benchmark_df is not None:
        benchmark_df = engine._normalize_index(benchmark_df)

    # 1. Her hisse için son günlük return hesapla (cross-sectional için)
    universe_returns: Dict[str, float] = {}
    for ticker, df in market_data.items():
        if df is not None and len(df) >= 2:
            try:
                ret = float(df["Close"].pct_change()[-1])
                if not np.isnan(ret):
                    universe_returns[ticker] = ret
            except Exception:
                logger.warning("Caught Exception in compute_universe_features", exc_info=True)

    # 2. Sektör bazlı ortalama return serisi (tz-naive)
    sector_series: Dict[str, pl.Series] = {}
    if sector_map:
        sector_dfs: Dict[str, List] = {}
        for ticker, df in market_data.items():
            if df is None or df.empty:
                continue
            sect = sector_map.get(ticker, "OTHER")
            if sect not in sector_dfs:
                sector_dfs[sect] = []
            s = df["Close"].pct_change()
            # Ensure tz-naive
            if hasattr(s.index, 'tz') and s.index.tz is not None:
                s.index = s.index.tz_convert(None)
            sector_dfs[sect].append(s)
        
        for sect, series_list in sector_dfs.items():
            if series_list:
                try:
                    combined = pl.concat(series_list, axis=1)
                    sector_series[sect] = combined.mean(axis=1)
                except Exception:
                    logger.warning("Caught Exception in compute_universe_features", exc_info=True)


    # 3. Her hisse için hesapla
    result: Dict[str, Dict[str, float]] = {}
    for ticker, df in market_data.items():
        if df is None or df.empty:
            continue
        try:
            sect = sector_map.get(ticker, "OTHER")
            sect_ret = sector_series.get(sect)

            features = engine.compute_all(
                ticker=ticker,
                df=df,
                benchmark_df=benchmark_df,
                sector_returns=sect_ret,
                universe_returns=universe_returns,
            )
            result[ticker] = features
        except Exception as e:
            logger.warning("Feature computation failed", ticker=ticker, error=str(e))
            result[ticker] = {}

    logger.info(
        "Universe features computed",
        tickers=len(result),
        avg_features=np.mean([len(v) for v in result.values()]) if result else 0,
    )
    return result
