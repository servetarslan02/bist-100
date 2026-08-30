from __future__ import annotations

from typing import Any

"""
ALPHA BIST — Feature Engine v3.0 (Polars-Native)
==================================================
Sadece gerçekten çalışan ve predictive olan feature'lar.
Tüm hesaplamalar Polars ile yapılır — pandas bağımlılığı yoktur.

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


import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()

# Feature contract integration (lazy import to avoid circular dependency)
_feature_registry = None


def _get_feature_registry() -> Any:
    """Feature registry'i lazy yükle."""
    global _feature_registry
    if _feature_registry is None:
        try:
            from services.features.contract import feature_registry

            _feature_registry = feature_registry
        except ImportError:
            _feature_registry = None
    return _feature_registry


def _safe_float(v) -> float:
    """Güvenli float dönüşümü — None/NaN → np.nan."""
    if v is None:
        return np.nan
    if isinstance(v, pl.Series):
        if len(v) == 0:
            return np.nan
        v = v[-1]
    try:
        val = float(v)
        return np.nan if (val != val) else val  # NaN check without numpy
    except Exception:
        return np.nan


def _last(series: pl.Series) -> float:
    """Polars Series'ın son elemanını güvenli float olarak döndür."""
    if series is None or len(series) == 0:
        return np.nan
    try:
        return float(series[-1])
    except Exception:
        return np.nan


class FeatureEngine:
    """
    Tüm feature hesaplamalarının tek kaynağı — Polars-Native.

    Kullanım:
        engine = FeatureEngine()
        features = engine.compute_all(
            ticker="AKBNK",
            df=stock_df,             # OHLCV Polars DataFrame
            benchmark_df=xu100_df,   # XU100 OHLCV
            sector_returns=sect_ret, # sektör return serisi
            universe_returns={"AKBNK": 0.02, ...},
        )
    """

    LOOKBACK = {
        "short": 5,
        "medium": 20,
        "long": 60,
        "xlong": 120,
        "annual": 252,
    }

    def _normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """Timezone-naive ve temiz DataFrame."""
        if df is None or len(df) == 0:
            return df
        # MultiIndex sütun düzleştirme (yfinance'dan gelen)
        if any(isinstance(c, tuple) for c in df.columns):
            df = df.rename({c: c[0] if isinstance(c, tuple) else c for c in df.columns})
        # Date sütunu varsa index olarak kullan
        if "Date" in df.columns and df["Date"].dtype in (pl.Date, pl.Datetime):
            df = df.sort("Date")
        return df

    @staticmethod
    def get_feature_metadata(feature_name: str) -> dict | None:
        """Feature contract metadata'sını döndür.

        Args:
            feature_name: Feature adı

        Returns:
            Feature metadata dict veya None
        """
        registry = _get_feature_registry()
        if registry is None:
            return None
        contract = registry.get(feature_name)
        return contract.to_dict() if contract else None

    @staticmethod
    def list_pit_safe_features() -> list[str]:
        """PIT-safe feature isimlerini döndür."""
        registry = _get_feature_registry()
        if registry is None:
            return []
        return [c.name for c in registry.list_pit_safe()]

    @staticmethod
    def get_feature_summary() -> dict:
        """Feature registry özet istatistikleri."""
        registry = _get_feature_registry()
        if registry is None:
            return {"error": "registry not available"}
        return registry.get_summary()

    def compute_all(
        self,
        ticker: str,
        df: pl.DataFrame,
        benchmark_df: pl.DataFrame | None = None,
        sector_returns: pl.Series | None = None,
        universe_returns: dict[str, float] | None = None,
        universe_rsi: dict[str, float] | None = None,
        breadth_advance_ratio: float | None = None,
    ) -> dict[str, float]:
        """Tüm feature'ları hesapla ve tek dict olarak döndür."""
        if df is None or len(df) < 20:
            return {}

        df = self._normalize(df)

        close = df["Close"].cast(pl.Float64)
        volume = df["Volume"].cast(pl.Float64) if "Volume" in df.columns else pl.Series("Volume", [], dtype=pl.Float64)
        high = df["High"].cast(pl.Float64) if "High" in df.columns else close
        low = df["Low"].cast(pl.Float64) if "Low" in df.columns else close

        features: dict[str, float] = {}

        # A) Price Context
        features.update(self._price_context(close, high, low))

        # B) Relative Strength
        if benchmark_df is not None and len(benchmark_df) >= 20:
            bm = self._normalize(benchmark_df)
            bm_close = bm["Close"].cast(pl.Float64)
            features.update(self._relative_strength_vs_bm(close, bm_close))

        if sector_returns is not None and len(sector_returns) >= 5:
            features.update(self._relative_strength_vs_sector(close, sector_returns))

        # C) Trend Quality
        features.update(self._trend_quality(close))

        # D) Volume
        if len(volume) > 0 and volume.sum() > 0:
            features.update(self._volume_features(close, volume))

        # E) Risk
        features.update(self._risk_features(close, high, low))

        # F) Cross-Sectional
        if universe_returns:
            features.update(self._cross_sectional(ticker, close, universe_returns, universe_rsi, breadth_advance_ratio))

        # G) Fundamental Proxy
        features.update(self._fundamental_proxy(close, volume))

        # Contract-based validation
        result = {}
        registry = _get_feature_registry()
        for k, v in features.items():
            if v is None:
                continue
            fv = _safe_float(v)
            # Contract validation (varsa)
            if registry is not None:
                contract = registry.get(k)
                if contract is not None and not contract.validate_value(fv):
                    logger.debug(
                        "feature_validation_failed",
                        ticker=ticker,
                        feature=k,
                        value=fv,
                        range=contract.value_range,
                    )
                    # Validation fail olsa bile degeri koru — sadece log
                    # Model zaten NaN'ları handle ediyor
            result[k] = fv
        return result

    # ------------------------------------------------------------------ #
    # A) Price Context
    # ------------------------------------------------------------------ #
    def _price_context(self, close: pl.Series, high: pl.Series, low: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        n = len(close)

        # Getiri / momentum
        for label, w in [("5d", 5), ("20d", 20), ("60d", 60), ("120d", 120)]:
            if n > w:
                f[f"roc_{label}"] = _last(close.pct_change(w))

        # SMA uzaklık
        for label, w in [("sma20", 20), ("sma50", 50), ("sma200", 200)]:
            if n > w:
                sma = close.rolling_mean(w)[-1]
                f[f"dist_{label}"] = _safe_float((close[-1] / sma) - 1)

        # 52-haftalık yüksekten uzaklık
        if n > 100:
            high_52w = high.rolling_max(252)[-1] if n >= 252 else high.max()
            low_52w = low.rolling_min(252)[-1] if n >= 252 else low.min()
            f["pct_from_52w_high"] = _safe_float((close[-1] / high_52w) - 1)
            f["pct_from_52w_low"] = _safe_float((close[-1] / low_52w) - 1)

        # RSI-14
        if n > 20:
            delta = close.diff()
            gain = delta.clip(lower_bound=0).rolling_mean(14)
            loss = (-delta.clip(upper_bound=0)).rolling_mean(14)
            # Polars'da 0'a bölünmeyi None yap
            rs = gain / loss.replace(0, None)
            rsi = (100 - 100 / (1 + rs))[-1]
            f["rsi_14"] = _safe_float(rsi)

        # Momentum acceleration
        if "roc_5d" in f and "roc_20d" in f:
            f["momentum_accel"] = f["roc_5d"] - f["roc_20d"] / 4

        # Kısa dönem mean reversion
        if n > 20:
            std = close.pct_change().rolling_std(20)[-1]
            sma20 = close.rolling_mean(20)[-1]
            f["zscore_vs_sma20"] = _safe_float((close[-1] - sma20) / (std * sma20 + 1e-9))

        return f

    # ------------------------------------------------------------------ #
    # B) Relative Strength
    # ------------------------------------------------------------------ #
    def _relative_strength_vs_bm(self, close: pl.Series, bm_close: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        stock_ret = close.pct_change()
        bm_ret = bm_close.pct_change()

        for label, w in [("1d", 1), ("5d", 5), ("20d", 20), ("60d", 60)]:
            try:
                s = (1 + stock_ret.tail(w)).product() - 1
                b = (1 + bm_ret.tail(w)).product() - 1
                f[f"rs_vs_bist_{label}"] = _safe_float(s - b)
            except Exception:
                logger.warning("Caught Exception in _relative_strength_vs_bm", exc_info=True)

        # RS trend
        min_len = min(len(stock_ret), len(bm_ret))
        if min_len > 25:
            s_aligned = stock_ret.tail(min_len)
            b_aligned = bm_ret.tail(min_len)
            rs_series = s_aligned - b_aligned
            rs_5d = rs_series.rolling_sum(5)
            f["rs_trend_5d"] = _safe_float(rs_5d.diff(5)[-1] if len(rs_5d) > 5 else np.nan)

        return f

    def _relative_strength_vs_sector(self, close: pl.Series, sect: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        stock_ret = close.pct_change()

        for label, w in [("5d", 5), ("20d", 20)]:
            try:
                s = (1 + stock_ret.tail(w)).product() - 1
                b = (1 + sect.tail(w)).product() - 1
                f[f"rs_vs_sector_{label}"] = _safe_float(s - b)
            except Exception:
                logger.warning("Caught Exception in _relative_strength_vs_sector", exc_info=True)

        return f

    # ------------------------------------------------------------------ #
    # C) Trend Quality
    # ------------------------------------------------------------------ #
    def _trend_quality(self, close: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        n = len(close)
        if n < 20:
            return f

        # Linear regression slope + R²
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
                    f[f"trend_slope_{label}"] = float(slope / close[-w])
                    f[f"trend_r2_{label}"] = float(r2)
                except Exception:
                    logger.warning("Caught Exception in _trend_quality", exc_info=True)

        # SMA alignment score
        if n >= 200:
            sma20 = close.rolling_mean(20)[-1]
            sma50 = close.rolling_mean(50)[-1]
            sma200 = close.rolling_mean(200)[-1]
            alignment = 0
            if sma20 > sma50:
                alignment += 1
            if sma50 > sma200:
                alignment += 1
            if close[-1] > sma20:
                alignment += 1
            f["sma_alignment"] = float(alignment)

        # Higher highs / Higher lows
        if n >= 20:
            highs = close.rolling_max(5).drop_nulls()
            lows = close.rolling_min(5).drop_nulls()
            if len(highs) >= 4:
                f["higher_highs"] = float(int(highs[-1] > highs[-3]))
                f["higher_lows"] = float(int(lows[-1] > lows[-3]))

        # Drawdown
        if n >= 20:
            peak = close.rolling_max(20)[-1]
            f["drawdown_20d"] = float((close[-1] / peak) - 1)
        if n >= 60:
            peak60 = close.rolling_max(60)[-1]
            f["drawdown_60d"] = float((close[-1] / peak60) - 1)

        return f

    # ------------------------------------------------------------------ #
    # D) Volume
    # ------------------------------------------------------------------ #
    def _volume_features(self, close: pl.Series, volume: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        n = len(volume)
        if n < 20:
            return f

        vol_mean = volume.rolling_mean(20)
        vol_std = volume.rolling_std(20)

        # Z-score
        z = (volume[-1] - vol_mean[-1]) / (vol_std[-1] + 1)
        f["volume_zscore_20d"] = float(z)

        # Percentile (rank-based)
        if n >= 60:
            window = min(n, 252)
            vol_tail = volume.tail(window)
            rank_val = (vol_tail <= volume[-1]).sum() / window
            f["volume_percentile"] = float(rank_val)

        # Volume trend
        if n >= 20:
            short_avg = volume.rolling_mean(5)[-1]
            long_avg = volume.rolling_mean(20)[-1]
            f["volume_trend_ratio"] = float(short_avg / (long_avg + 1))

        # Price-volume divergence
        if n >= 10:
            price_change = close.pct_change(5)[-1]
            vol_change = volume.rolling_mean(5).pct_change(5)[-1]
            if price_change is not None and vol_change is not None:
                pc = float(price_change)
                vc = float(vol_change)
                if not np.isnan(pc) and not np.isnan(vc):
                    f["price_vol_divergence"] = float(
                        1 if (pc > 0 and vc < -0.2) else (-1 if (pc < 0 and vc > 0.2) else 0)
                    )

        # On-Balance Volume
        if n >= 20:
            direction = (close.diff() > 0).cast(pl.Float64) * 2 - 1
            obv = (volume * direction).cum_sum()
            obv_20d_change = (obv[-1] - obv[-21]) / (abs(obv[-21]) + 1)
            f["obv_trend_20d"] = float(obv_20d_change)

        return f

    # ------------------------------------------------------------------ #
    # E) Risk
    # ------------------------------------------------------------------ #
    def _risk_features(self, close: pl.Series, high: pl.Series, low: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        n = len(close)
        returns = close.pct_change().drop_nulls()

        if len(returns) >= 20:
            f["volatility_20d"] = float(returns.rolling_std(20)[-1] * np.sqrt(252))
        if len(returns) >= 60:
            f["volatility_60d"] = float(returns.rolling_std(60)[-1] * np.sqrt(252))

        # ATR %
        if n >= 14 and len(high) > 0 and len(low) > 0:
            tr = pl.DataFrame({
                "a": high - low,
                "b": (high - close.shift(1)).abs(),
                "c": (low - close.shift(1)).abs(),
            }).max_horizontal()
            atr_pct = (tr.rolling_mean(14) / close)[-1]
            f["atr_pct"] = float(atr_pct)

        # Downside volatility
        if len(returns) >= 20:
            neg_returns = returns.filter(returns < 0)
            if len(neg_returns) >= 5:
                f["downside_vol_20d"] = float(neg_returns.rolling_std(20)[-1] * np.sqrt(252))

        return f

    # ------------------------------------------------------------------ #
    # F) Cross-Sectional
    # ------------------------------------------------------------------ #
    def _cross_sectional(
        self,
        ticker: str,
        close: pl.Series,
        universe_returns: dict[str, float],
        universe_rsi: dict[str, float] | None = None,
        breadth_advance_ratio: float | None = None,
    ) -> dict:
        """Otomatik eklendi."""
        f = {}
        if breadth_advance_ratio is not None:
            f["breadth_advance_ratio"] = breadth_advance_ratio

        all_rets = list(universe_returns.values())
        if len(all_rets) < 5:
            return f

        this_ret = universe_returns.get(ticker)
        if this_ret is None:
            return f

        arr = np.array(all_rets)
        mean = arr.mean()
        std = arr.std()

        if std > 1e-9:
            f["cs_zscore_ret_1d"] = float((this_ret - mean) / std)

        rank = float(np.mean(arr <= this_ret))
        f["cs_rank_ret_1d"] = rank

        if universe_rsi and len(universe_rsi) >= 5:
            this_rsi = universe_rsi.get(ticker)
            if this_rsi is not None:
                rsi_arr = np.array(list(universe_rsi.values()))
                rsi_rank = float(np.mean(rsi_arr <= this_rsi))
                f["cs_rank_rsi_14"] = rsi_rank

        return f

    # ------------------------------------------------------------------ #
    # G) Fundamental Proxy
    # ------------------------------------------------------------------ #
    def _fundamental_proxy(self, close: pl.Series, volume: pl.Series) -> dict:
        """Otomatik eklendi."""
        f = {}
        n = len(close)

        if n >= 130:
            ret_6m = float(close.pct_change(120)[-1])
            ret_1m = float(close.pct_change(20)[-1])
            f["momentum_reversal_risk"] = float(
                1 if (ret_6m > 0.15 and ret_1m < -0.05) else (-1 if (ret_6m < -0.15 and ret_1m > 0.05) else 0)
            )

        if len(volume) > 0 and n >= 20:
            avg_vol = volume.rolling_mean(20)[-1]
            f["liquidity_score"] = float(min(1.0, np.log1p(avg_vol) / 15))

        return f


# ------------------------------------------------------------------ #
# Helper: Tüm evreni tek seferde hesapla
# ------------------------------------------------------------------ #
def compute_universe_features(
    market_data: dict[str, pl.DataFrame],
    benchmark_df: pl.DataFrame,
    sector_map: dict[str, str],
) -> dict[str, dict[str, float]]:
    """Tüm hisseler için feature'ları hesapla."""
    engine = FeatureEngine()

    # Normalize
    normalized_data: dict[str, pl.DataFrame] = {}
    for ticker, df in market_data.items():
        if df is not None and len(df) > 0:
            normalized_data[ticker] = engine._normalize(df)
    market_data = normalized_data

    if benchmark_df is not None:
        benchmark_df = engine._normalize(benchmark_df)

    # Her hisse için son günlük return ve RSI (B23 Fix)
    universe_returns: dict[str, float] = {}
    universe_rsi: dict[str, float] = {}
    advancing = 0
    total = 0
    for ticker, df in market_data.items():
        if df is not None and len(df) >= 2:
            try:
                ret = float(df["Close"].pct_change()[-1])
                if not np.isnan(ret):
                    universe_returns[ticker] = ret
                    total += 1
                    if ret > 0:
                        advancing += 1

                if len(df) >= 20:
                    close = df["Close"].cast(pl.Float64)
                    delta = close.diff()
                    gain = delta.clip(lower_bound=0).rolling_mean(14)
                    loss = (-delta.clip(upper_bound=0)).rolling_mean(14)
                    rs = gain / loss.replace(0, None)
                    rsi = float((100 - 100 / (1 + rs))[-1])
                    if not np.isnan(rsi):
                        universe_rsi[ticker] = rsi
            except Exception:
                logger.warning("Caught Exception in compute_universe_features", exc_info=True)

    breadth_advance_ratio = advancing / total if total > 0 else 0.5

    # Sektör bazlı ortalama return
    sector_series: dict[str, pl.Series] = {}
    if sector_map:
        sector_dfs: dict[str, list] = {}
        for ticker, df in market_data.items():
            if df is None or len(df) == 0:
                continue
            sect = sector_map.get(ticker, "OTHER")
            if sect not in sector_dfs:
                sector_dfs[sect] = []
            sector_dfs[sect].append(df["Close"].pct_change())

        for sect, series_list in sector_dfs.items():
            if series_list:
                try:
                    # En kısa seri uzunluğuna göre hizala ve ortalamayı al
                    min_len = min(len(s) for s in series_list)
                    if min_len > 0:
                        aligned = [s.tail(min_len) for s in series_list]
                        stacked = pl.DataFrame({f"s{i}": s for i, s in enumerate(aligned)})
                        sector_series[sect] = stacked.mean_horizontal()
                except Exception:
                    logger.warning("Sector series computation failed", sector=sect, exc_info=True)

    # Her hisse için hesapla
    result: dict[str, dict[str, float]] = {}
    for ticker, df in market_data.items():
        if df is None or len(df) == 0:
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
                universe_rsi=universe_rsi,
                breadth_advance_ratio=breadth_advance_ratio,
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
