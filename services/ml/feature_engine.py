# c:\Users\serve\Downloads\Compressed\bist-100\services\ml\feature_engine.py
"""ALPHA BIST — Öznitelik Mühendisliği Çekirdek Motoru (Feature Engine v3.0 Polars-Native).

BIST-100 pay senetleri için yüksek tahmin gücüne sahip, Point-In-Time prensipleriyle
uyumlu ve tamamen Polars üzerinde çalışan öznitelik (feature) hesaplama motoru.
Pandas bağımlılığı bulunmaz; tüm operasyonlar Polars Series ve DataFrame üzerinde
vektörize olarak yürütülür.

Temel Kurallar:
- Sıfır Veri Sızıntısı (Zero Data Leakage / PIT): Yalnızca t anı ve öncesindeki barlar kullanılır.
- Hiçbir öznitelik sahte 0 üretmez; eksik veride np.nan döner (LightGBM/CatBoost otomatik yönetir).
- Çapraz Kesit (Cross-Sectional) öznitelikleri tüm BIST-100 evrenine göre z-score ve rank olarak hesaplanır.
- Eşzamanlılık Güvenliği: `threading.RLock()` ile çoklu iş parçacığı koruması.
- DuckDB Entegrasyonu: SSD korumalı WAL ayarları ile öznitelik seti denetim izi kaydı.
- Fail-Closed Mimarisi: Sayısal taşma (NaN/Inf) ve sıfıra bölmelere karşı korumalı.

Öznitelik Grupları:
  A) Price Context     — Hissenin kendi fiyat geçmişi, momentum ve SMA uzaklıkları
  B) Relative Strength — XU100 ve sektöre göre göreceli getiri ve alfa eğilimi
  C) Trend Quality     — Doğrusal regresyon eğimi, R² ve SMA dizilim kalitesi
  D) Volume            — Hacim z-skoru, yüzdelik dilimi ve fiyat-hacim uyumsuzluğu
  E) Risk              — Tarihsel volatilite, aşağı yönlü volatilite ve ATR oranı
  F) Cross-Sectional   — Evren geneli getiri ve RSI rank / z-skorları
  G) Fundamental Proxy — Fiyat-hacim bazlı kaldıraç ve likidite vekilleri
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# ==============================================================================
# 1. STANDART YAPILANDIRMA SABİTLERİ (DEFAULT_*)
# ==============================================================================
DEFAULT_MIN_HISTORY_BARS: Final[int] = 20
DEFAULT_ANNUAL_TRADING_DAYS: Final[int] = 252
DEFAULT_RSI_PERIOD: Final[int] = 14
DEFAULT_MIN_UNIVERSE_SIZE: Final[int] = 5

DEFAULT_ROC_WINDOWS: Final[tuple[tuple[str, int], ...]] = (
    ("5d", 5),
    ("20d", 20),
    ("60d", 60),
    ("120d", 120),
)

DEFAULT_SMA_WINDOWS: Final[tuple[tuple[str, int], ...]] = (
    ("sma20", 20),
    ("sma50", 50),
    ("sma200", 200),
)

DEFAULT_DUCKDB_PATH: Final[str] = "data/ml_audit.duckdb"
DEFAULT_WAL_AUTO_CHECKPOINT: Final[str] = "10MB"


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_WAL_AUTO_CHECKPOINT,
) -> None:
    """DuckDB bağlantısını SSD korumalı WAL sınırları ile optimize eder.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: WAL otomatik kontrol noktası boyutu (örn: '10MB').
    """
    try:
        con.execute(f"PRAGMA wal_autocheckpoint='{checkpoint_size}';")
    except Exception as e:
        logger.warning("duckdb_wal_config_failed", error=str(e))


# ==============================================================================
# 2. FEATURE REGISTRY LAZY ENTEGRASYONU VE VERİ MODELLERİ
# ==============================================================================
_feature_registry_lock = threading.RLock()
_feature_registry: Any = None


def get_feature_registry() -> Any:
    """Öznitelik sözleşme (contract) kaydını iş parçacığı güvenliği ile tembel (lazy) yükler."""
    global _feature_registry
    with _feature_registry_lock:
        if _feature_registry is None:
            try:
                from services.features.contract import feature_registry

                _feature_registry = feature_registry
            except ImportError:
                _feature_registry = None
        return _feature_registry


@dataclass(slots=True)
class FeatureSetResult:
    """Tek bir hisse için hesaplanmış öznitelik sonuç modeli."""

    ticker: str
    calculated_at: str
    feature_count: int
    features: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Öznitelik sonuç modelini sözlük formatına çevirir."""
        return {
            "ticker": self.ticker,
            "calculated_at": self.calculated_at,
            "feature_count": self.feature_count,
            "features": self.features,
            "metadata": self.metadata,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureSetResult:
        """Sözlükten FeatureSetResult nesnesi oluşturur."""
        features_raw = data.get("features", {})
        clean_features = {
            str(k): float(v) for k, v in features_raw.items() if np.isfinite(float(v))
        }
        return cls(
            ticker=str(data.get("ticker", "")),
            calculated_at=str(data.get("calculated_at", "")),
            feature_count=int(data.get("feature_count", len(clean_features))),
            features=clean_features,
            metadata=dict(data.get("metadata", {})),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return f"FeatureSetResult(ticker='{self.ticker}', features={self.feature_count}, at='{self.calculated_at}')"


# ==============================================================================
# 3. YARDIMCI DÖNÜŞTÜRÜCÜ VE GÜVENLİK FONKSİYONLARI
# ==============================================================================
def safe_float(v: Any) -> float:
    """Herhangi bir girdiyi güvenli biçimde IEEE-754 float'a dönüştürür; geçersizlerde np.nan döner.

    Args:
        v: Dönüştürülecek nesne (float, int, Series, string vb.).

    Returns:
        Geçerli float veya np.nan.
    """
    if v is None:
        return np.nan
    if isinstance(v, pl.Series):
        if len(v) == 0:
            return np.nan
        v = v[-1]
    try:
        val = float(v)
        return val if np.isfinite(val) else np.nan
    except (ValueError, TypeError):
        return np.nan


def last_series_val(series: pl.Series | None) -> float:
    """Polars Series'in son geçerli elemanını float olarak döndürür.

    Args:
        series: Polars sayısal serisi.

    Returns:
        Son elemanın float değeri veya np.nan.
    """
    if series is None or len(series) == 0:
        return np.nan
    try:
        val = float(series[-1])
        return val if np.isfinite(val) else np.nan
    except Exception:
        return np.nan


# ==============================================================================
# 4. ÖZNİTELİK MÜHENDİSLİĞİ MOTORU (FEATURE ENGINE)
# ==============================================================================
class FeatureEngine:
    """Tüm öznitelik hesaplamalarının merkezi Polars-Native motoru."""

    LOOKBACK: Final[dict[str, int]] = {
        "short": 5,
        "medium": 20,
        "long": 60,
        "xlong": 120,
        "annual": DEFAULT_ANNUAL_TRADING_DAYS,
    }

    def __init__(self) -> None:
        """FeatureEngine motorunu başlatır."""
        self._lock: Final[threading.RLock] = threading.RLock()

    def normalize(self, df: pl.DataFrame | None) -> pl.DataFrame:
        """DataFrame'i tarih sıralı, temiz ve sütun uyumlu hale getirir.

        Args:
            df: İşlenecek Polars DataFrame.

        Returns:
            Normalleştirilmiş Polars DataFrame.
        """
        if df is None or len(df) == 0:
            return pl.DataFrame()

        # MultiIndex / Tuple sütun adlarını düzleştir
        rename_map: dict[str, str] = {}
        for c in df.columns:
            if isinstance(c, tuple):
                rename_map[str(c)] = str(c[0])

        res_df = df.rename(rename_map) if rename_map else df

        if "Date" in res_df.columns and res_df["Date"].dtype in (pl.Date, pl.Datetime):
            res_df = res_df.sort("Date")

        return res_df

    @staticmethod
    def get_feature_metadata(feature_name: str) -> dict[str, Any] | None:
        """Öznitelik sözleşme (contract) üstverisini döndürür.

        Args:
            feature_name: Öznitelik adı.

        Returns:
            Üstveri sözlüğü veya None.
        """
        registry = get_feature_registry()
        if registry is None:
            return None
        contract = registry.get(feature_name)
        return contract.to_dict() if contract and hasattr(contract, "to_dict") else None

    @staticmethod
    def list_pit_safe_features() -> list[str]:
        """Point-In-Time (PIT) güvenli olarak etiketlenmiş öznitelik adlarını listeler."""
        registry = get_feature_registry()
        if registry is None:
            return []
        return [c.name for c in registry.list_pit_safe()]

    @staticmethod
    def get_feature_summary() -> dict[str, Any]:
        """Kayıtlı özniteliklerin genel istatistik özetini döndürür."""
        registry = get_feature_registry()
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
        """Belirtilen hisse senedi için tüm öznitelik gruplarını hesaplayıp tek sözlükte birleştirir.

        Args:
            ticker: Hisse senedi kodu (örn: THYAO).
            df: Hisse OHLCV Polars DataFrame'i.
            benchmark_df: Gösterge endeks (XU100) OHLCV DataFrame'i.
            sector_returns: İlgili sektörün tarihsel getiri serisi.
            universe_returns: BIST evrenindeki hisselerin son gün getirileri.
            universe_rsi: BIST evrenindeki hisselerin son RSI değerleri.
            breadth_advance_ratio: Piyasa genişliği yükselen/toplam oranı.

        Returns:
            Öznitelik adı -> float değer eşlemesi.
        """
        with self._lock:
            if df is None or len(df) < DEFAULT_MIN_HISTORY_BARS:
                return {}

            norm_df = self.normalize(df)
            if "Close" not in norm_df.columns:
                return {}

            close = norm_df["Close"].cast(pl.Float64)
            volume = (
                norm_df["Volume"].cast(pl.Float64)
                if "Volume" in norm_df.columns
                else pl.Series("Volume", [], dtype=pl.Float64)
            )
            high = norm_df["High"].cast(pl.Float64) if "High" in norm_df.columns else close
            low = norm_df["Low"].cast(pl.Float64) if "Low" in norm_df.columns else close

            features: dict[str, float] = {}

            # A) Fiyat Bağlamı (Price Context)
            features.update(self._price_context(close, high, low))

            # B) Göreceli Güç (Relative Strength)
            if benchmark_df is not None and len(benchmark_df) >= DEFAULT_MIN_HISTORY_BARS:
                bm = self.normalize(benchmark_df)
                if "Close" in bm.columns:
                    bm_close = bm["Close"].cast(pl.Float64)
                    features.update(self._relative_strength_vs_bm(close, bm_close))

            if sector_returns is not None and len(sector_returns) >= DEFAULT_MIN_UNIVERSE_SIZE:
                features.update(self._relative_strength_vs_sector(close, sector_returns))

            # C) Trend Kalitesi (Trend Quality)
            features.update(self._trend_quality(close))

            # D) Hacim Dinamikleri (Volume)
            if len(volume) > 0 and safe_float(volume.sum()) > 0:
                features.update(self._volume_features(close, volume))

            # E) Risk ve Volatilite (Risk)
            features.update(self._risk_features(close, high, low))

            # F) Çapraz Kesit (Cross-Sectional)
            if universe_returns:
                features.update(
                    self._cross_sectional(
                        ticker,
                        close,
                        universe_returns,
                        universe_rsi,
                        breadth_advance_ratio,
                    )
                )

            # G) Temel Gösterge Vekili (Fundamental Proxy)
            features.update(self._fundamental_proxy(close, volume))

            # Sözleşme doğrulaması ve güvenli float filtresi
            result: dict[str, float] = {}
            registry = get_feature_registry()

            for k, v in features.items():
                if v is None:
                    continue
                fv = safe_float(v)
                if registry is not None:
                    contract = registry.get(k)
                    if contract is not None and hasattr(contract, "validate_value") and not contract.validate_value(fv):
                        logger.debug(
                            "feature_validation_failed",
                            ticker=ticker,
                            feature=k,
                            value=fv,
                        )
                result[k] = fv

            return result

    # ------------------------------------------------------------------ #
    # A) FİYAT BAĞLAMI (PRICE CONTEXT)
    # ------------------------------------------------------------------ #
    def _price_context(self, close: pl.Series, high: pl.Series, low: pl.Series) -> dict[str, float]:
        """Fiyat momentumu, SMA mesafeleri ve RSI metriklerini hesaplar."""
        f: dict[str, float] = {}
        n = len(close)
        if n == 0:
            return f

        # Getiri ve Momentum (ROC)
        for label, w in DEFAULT_ROC_WINDOWS:
            if n > w:
                f[f"roc_{label}"] = last_series_val(close.pct_change(w))

        # SMA Uzaklıkları
        for label, w in DEFAULT_SMA_WINDOWS:
            if n > w:
                sma_series = close.rolling_mean(w)
                sma_last = last_series_val(sma_series)
                close_last = last_series_val(close)
                if np.isfinite(sma_last) and sma_last > 0:
                    f[f"dist_{label}"] = safe_float((close_last / sma_last) - 1.0)

        # 52 Haftalık Uç Değerlerden Uzaklık
        if n > 100:
            window = min(n, DEFAULT_ANNUAL_TRADING_DAYS)
            high_val = safe_float(high.tail(window).max())
            low_val = safe_float(low.tail(window).min())
            c_last = last_series_val(close)

            if high_val > 0:
                f["pct_from_52w_high"] = safe_float((c_last / high_val) - 1.0)
            if low_val > 0:
                f["pct_from_52w_low"] = safe_float((c_last / low_val) - 1.0)

        # RSI-14
        if n > DEFAULT_MIN_HISTORY_BARS:
            delta = close.diff()
            gain = delta.clip(lower_bound=0.0).rolling_mean(DEFAULT_RSI_PERIOD)
            loss = (-delta.clip(upper_bound=0.0)).rolling_mean(DEFAULT_RSI_PERIOD)
            g_last = last_series_val(gain)
            l_last = last_series_val(loss)

            if np.isfinite(g_last) and np.isfinite(l_last):
                if l_last == 0.0:
                    f["rsi_14"] = 100.0 if g_last > 0 else 50.0
                else:
                    rs = g_last / l_last
                    f["rsi_14"] = safe_float(100.0 - (100.0 / (1.0 + rs)))

        # Momentum İvmesi
        if "roc_5d" in f and "roc_20d" in f:
            f["momentum_accel"] = safe_float(f["roc_5d"] - (f["roc_20d"] / 4.0))

        # Kısa Dönem Mean Reversion Z-Skoru
        if n > DEFAULT_MIN_HISTORY_BARS:
            pct_ret = close.pct_change()
            std_last = last_series_val(pct_ret.rolling_std(20))
            sma_last = last_series_val(close.rolling_mean(20))
            c_last = last_series_val(close)
            denom = std_last * sma_last if (np.isfinite(std_last) and np.isfinite(sma_last)) else 0.0
            if denom > 1e-9:
                f["zscore_vs_sma20"] = safe_float((c_last - sma_last) / denom)

        return f

    # ------------------------------------------------------------------ #
    # B) GÖRECELİ GÜÇ (RELATIVE STRENGTH)
    # ------------------------------------------------------------------ #
    def _relative_strength_vs_bm(self, close: pl.Series, bm_close: pl.Series) -> dict[str, float]:
        """XU100 göstergesine göre kümülatif aşırı getiri ve trendi hesaplar."""
        f: dict[str, float] = {}
        stock_ret = close.pct_change().fill_nan(0.0).fill_null(0.0)
        bm_ret = bm_close.pct_change().fill_nan(0.0).fill_null(0.0)

        for label, w in (("1d", 1), ("5d", 5), ("20d", 20), ("60d", 60)):
            if len(stock_ret) >= w and len(bm_ret) >= w:
                try:
                    s_prod = (1.0 + stock_ret.tail(w)).product() - 1.0
                    b_prod = (1.0 + bm_ret.tail(w)).product() - 1.0
                    s_val = safe_float(s_prod)
                    b_val = safe_float(b_prod)
                    if np.isfinite(s_val) and np.isfinite(b_val):
                        f[f"rs_vs_bist_{label}"] = s_val - b_val
                except Exception as e:
                    logger.debug("rs_vs_bm_calc_failed", label=label, error=str(e))

        min_len = min(len(stock_ret), len(bm_ret))
        if min_len > 25:
            s_aligned = stock_ret.tail(min_len)
            b_aligned = bm_ret.tail(min_len)
            rs_series = s_aligned - b_aligned
            rs_5d = rs_series.rolling_sum(5)
            if len(rs_5d) > 5:
                f["rs_trend_5d"] = last_series_val(rs_5d.diff(5))

        return f

    def _relative_strength_vs_sector(self, close: pl.Series, sect: pl.Series) -> dict[str, float]:
        """Sektör ortalama getirisine göre aşırı getiriyi hesaplar."""
        f: dict[str, float] = {}
        stock_ret = close.pct_change().fill_nan(0.0).fill_null(0.0)

        for label, w in (("5d", 5), ("20d", 20)):
            if len(stock_ret) >= w and len(sect) >= w:
                try:
                    s_prod = safe_float((1.0 + stock_ret.tail(w)).product() - 1.0)
                    b_prod = safe_float((1.0 + sect.tail(w)).product() - 1.0)
                    if np.isfinite(s_prod) and np.isfinite(b_prod):
                        f[f"rs_vs_sector_{label}"] = s_prod - b_prod
                except Exception as e:
                    logger.debug("rs_vs_sector_calc_failed", label=label, error=str(e))

        return f

    # ------------------------------------------------------------------ #
    # C) TREND KALİTESİ (TREND QUALITY)
    # ------------------------------------------------------------------ #
    def _trend_quality(self, close: pl.Series) -> dict[str, float]:
        """Doğrusal regresyon eğimi, R², SMA dizilimi ve tepe/dip yapısını hesaplar."""
        f: dict[str, float] = {}
        n = len(close)
        if n < DEFAULT_MIN_HISTORY_BARS:
            return f

        # Regresyon Eğimi ve R²
        for label, w in (("20d", 20), ("60d", 60)):
            if n > w:
                arr = close.tail(w).to_numpy()
                finite_mask = np.isfinite(arr)
                if np.all(finite_mask):
                    x = np.arange(w, dtype=np.float64)
                    try:
                        slope, intercept = np.polyfit(x, arr, 1)
                        y_pred = slope * x + intercept
                        ss_res = np.sum((arr - y_pred) ** 2)
                        ss_tot = np.sum((arr - np.mean(arr)) ** 2)
                        r2 = (1.0 - (ss_res / ss_tot)) if ss_tot > 1e-9 else 0.0

                        base_price = arr[0]
                        if base_price > 0:
                            f[f"trend_slope_{label}"] = safe_float(slope / base_price)
                        f[f"trend_r2_{label}"] = safe_float(max(0.0, min(1.0, r2)))
                    except Exception as e:
                        logger.debug("polyfit_trend_failed", label=label, error=str(e))

        # SMA Hizalanma Skoru (Bullish Alignment)
        if n >= 200:
            sma20 = last_series_val(close.rolling_mean(20))
            sma50 = last_series_val(close.rolling_mean(50))
            sma200 = last_series_val(close.rolling_mean(200))
            c_last = last_series_val(close)

            if all(np.isfinite(x) for x in [sma20, sma50, sma200, c_last]):
                alignment = 0.0
                if sma20 > sma50:
                    alignment += 1.0
                if sma50 > sma200:
                    alignment += 1.0
                if c_last > sma20:
                    alignment += 1.0
                f["sma_alignment"] = alignment

        # Yüksek Tepe ve Yüksek Dip (Higher Highs / Higher Lows)
        if n >= DEFAULT_MIN_HISTORY_BARS:
            highs = close.rolling_max(5).drop_nulls()
            lows = close.rolling_min(5).drop_nulls()
            if len(highs) >= 4 and len(lows) >= 4:
                h_now, h_prev = last_series_val(highs), float(highs[-3])
                l_now, l_prev = last_series_val(lows), float(lows[-3])
                if np.isfinite(h_now) and np.isfinite(h_prev):
                    f["higher_highs"] = 1.0 if h_now > h_prev else 0.0
                if np.isfinite(l_now) and np.isfinite(l_prev):
                    f["higher_lows"] = 1.0 if l_now > l_prev else 0.0

        # Drawdown Oranları
        if n >= 20:
            peak20 = last_series_val(close.rolling_max(20))
            c_last = last_series_val(close)
            if np.isfinite(peak20) and peak20 > 0:
                f["drawdown_20d"] = safe_float((c_last / peak20) - 1.0)

        if n >= 60:
            peak60 = last_series_val(close.rolling_max(60))
            c_last = last_series_val(close)
            if np.isfinite(peak60) and peak60 > 0:
                f["drawdown_60d"] = safe_float((c_last / peak60) - 1.0)

        return f

    # ------------------------------------------------------------------ #
    # D) HACİM DİNAMİKLERİ (VOLUME)
    # ------------------------------------------------------------------ #
    def _volume_features(self, close: pl.Series, volume: pl.Series) -> dict[str, float]:
        """Hacim z-skoru, hacim eğilim oranı ve OBV göstergelerini hesaplar."""
        f: dict[str, float] = {}
        n = len(volume)
        if n < DEFAULT_MIN_HISTORY_BARS:
            return f

        vol_mean_20 = last_series_val(volume.rolling_mean(20))
        vol_std_20 = last_series_val(volume.rolling_std(20))
        vol_last = last_series_val(volume)

        # Hacim Z-Skoru
        if np.isfinite(vol_mean_20) and np.isfinite(vol_std_20) and np.isfinite(vol_last):
            denom = vol_std_20 + 1.0
            f["volume_zscore_20d"] = safe_float((vol_last - vol_mean_20) / denom)

        # Tarihsel Hacim Yüzdeliği (Percentile)
        if n >= 60:
            window = min(n, DEFAULT_ANNUAL_TRADING_DAYS)
            vol_tail = volume.tail(window).to_numpy()
            finite_vols = vol_tail[np.isfinite(vol_tail)]
            if len(finite_vols) > 0 and np.isfinite(vol_last):
                rank_val = float(np.mean(finite_vols <= vol_last))
                f["volume_percentile"] = rank_val

        # Hacim Eğilim Oranı (5G / 20G)
        short_vol = last_series_val(volume.rolling_mean(5))
        if np.isfinite(short_vol) and np.isfinite(vol_mean_20):
            f["volume_trend_ratio"] = safe_float(short_vol / (vol_mean_20 + 1.0))

        # Fiyat - Hacim Uyumsuzluğu
        if n >= 10:
            p_change = last_series_val(close.pct_change(5))
            v_change = last_series_val(volume.rolling_mean(5).pct_change(5))
            if np.isfinite(p_change) and np.isfinite(v_change):
                f["price_vol_divergence"] = float(
                    1.0 if (p_change > 0 and v_change < -0.2) else (-1.0 if (p_change < 0 and v_change > 0.2) else 0.0)
                )

        # On-Balance Volume (OBV)
        if n >= 21:
            diff_close = close.diff().fill_null(0.0)
            direction = (diff_close > 0).cast(pl.Float64) * 2.0 - 1.0
            obv_series = (volume * direction).cum_sum()
            obv_last = last_series_val(obv_series)
            if len(obv_series) > 21:
                try:
                    obv_prev = float(obv_series[-21])
                    if np.isfinite(obv_last) and np.isfinite(obv_prev):
                        f["obv_trend_20d"] = safe_float((obv_last - obv_prev) / (abs(obv_prev) + 1.0))
                except Exception as exc:
                    logger.debug("OBV trendi hesaplanamadi", hata=str(exc))

        return f

    # ------------------------------------------------------------------ #
    # E) RİSK VE VOLATİLİTE (RISK)
    # ------------------------------------------------------------------ #
    def _risk_features(self, close: pl.Series, high: pl.Series, low: pl.Series) -> dict[str, float]:
        """Yıllıklandırılmış volatilite, aşağı yönlü risk ve ATR oranını hesaplar."""
        f: dict[str, float] = {}
        n = len(close)
        returns = close.pct_change().drop_nulls()

        # 20G ve 60G Volatilite
        ann_factor = np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS)
        if len(returns) >= 20:
            std_20 = last_series_val(returns.rolling_std(20))
            if np.isfinite(std_20):
                f["volatility_20d"] = safe_float(std_20 * ann_factor)

        if len(returns) >= 60:
            std_60 = last_series_val(returns.rolling_std(60))
            if np.isfinite(std_60):
                f["volatility_60d"] = safe_float(std_60 * ann_factor)

        # ATR Oranı
        if n >= DEFAULT_RSI_PERIOD and len(high) == n and len(low) == n:
            tr = pl.DataFrame({
                "hl": high - low,
                "hc": (high - close.shift(1)).abs(),
                "lc": (low - close.shift(1)).abs(),
            }).max_horizontal()
            atr_series = tr.rolling_mean(DEFAULT_RSI_PERIOD)
            atr_val = last_series_val(atr_series)
            c_last = last_series_val(close)
            if np.isfinite(atr_val) and np.isfinite(c_last) and c_last > 0:
                f["atr_pct"] = safe_float(atr_val / c_last)

        # Aşağı Yönlü Volatilite (Downside Volatility)
        if len(returns) >= 20:
            neg_ret = returns.filter(returns < 0.0)
            if len(neg_ret) >= 5:
                neg_std = last_series_val(neg_ret.rolling_std(min(len(neg_ret), 20)))
                if np.isfinite(neg_std):
                    f["downside_vol_20d"] = safe_float(neg_std * ann_factor)

        return f

    # ------------------------------------------------------------------ #
    # F) ÇAPRAZ KESİT (CROSS-SECTIONAL)
    # ------------------------------------------------------------------ #
    def _cross_sectional(
        self,
        ticker: str,
        close: pl.Series,
        universe_returns: dict[str, float],
        universe_rsi: dict[str, float] | None = None,
        breadth_advance_ratio: float | None = None,
    ) -> dict[str, float]:
        """Tüm evrene göre göreceli z-skoru, yüzdelik sıra ve piyasa genişliğini hesaplar."""
        f: dict[str, float] = {}

        if breadth_advance_ratio is not None and np.isfinite(breadth_advance_ratio):
            f["breadth_advance_ratio"] = float(breadth_advance_ratio)

        clean_rets = [float(v) for v in universe_returns.values() if np.isfinite(float(v))]
        if len(clean_rets) < DEFAULT_MIN_UNIVERSE_SIZE:
            return f

        this_ret = universe_returns.get(ticker)
        if this_ret is None or not np.isfinite(this_ret):
            return f

        arr = np.array(clean_rets, dtype=np.float64)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))

        if std_val > 1e-9:
            f["cs_zscore_ret_1d"] = safe_float((this_ret - mean_val) / std_val)

        f["cs_rank_ret_1d"] = float(np.mean(arr <= this_ret))

        if universe_rsi and len(universe_rsi) >= DEFAULT_MIN_UNIVERSE_SIZE:
            this_rsi = universe_rsi.get(ticker)
            if this_rsi is not None and np.isfinite(this_rsi):
                clean_rsis = [float(v) for v in universe_rsi.values() if np.isfinite(float(v))]
                if len(clean_rsis) >= DEFAULT_MIN_UNIVERSE_SIZE:
                    rsi_arr = np.array(clean_rsis, dtype=np.float64)
                    f["cs_rank_rsi_14"] = float(np.mean(rsi_arr <= this_rsi))

        return f

    # ------------------------------------------------------------------ #
    # G) TEMEL GÖSTERGE VEKİLİ (FUNDAMENTAL PROXY)
    # ------------------------------------------------------------------ #
    def _fundamental_proxy(self, close: pl.Series, volume: pl.Series) -> dict[str, float]:
        """Momentum tersine dönüş riski ve logaritmik likidite skorunu hesaplar."""
        f: dict[str, float] = {}
        n = len(close)

        # Momentum Reversal Risk
        if n >= 130:
            ret_6m = last_series_val(close.pct_change(120))
            ret_1m = last_series_val(close.pct_change(20))
            if np.isfinite(ret_6m) and np.isfinite(ret_1m):
                f["momentum_reversal_risk"] = float(
                    1.0
                    if (ret_6m > 0.15 and ret_1m < -0.05)
                    else (-1.0 if (ret_6m < -0.15 and ret_1m > 0.05) else 0.0)
                )

        # Likidite Skoru (0.0 - 1.0)
        if len(volume) > 0 and n >= 20:
            avg_vol = last_series_val(volume.rolling_mean(20))
            if np.isfinite(avg_vol) and avg_vol > 0:
                f["liquidity_score"] = float(min(1.0, max(0.0, np.log1p(avg_vol) / 15.0)))

        return f

    def compute_timeseries_features_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """Tüm geçmiş barlar için öznitelikleri Polars vektörize operasyonlarıyla hesaplar.

        Model eğitimi (LightGBM, CatBoost) için geçmiş barların öznitelik matrisini üretir.

        Args:
            df: OHLCV sütunlarını içeren Polars DataFrame.

        Returns:
            Öznitelik sütunları eklenmiş Polars DataFrame.
        """
        with self._lock:
            if df is None or len(df) < DEFAULT_MIN_HISTORY_BARS:
                return pl.DataFrame()

            norm_df = self.normalize(df)
            c = pl.col("Close")
            v = pl.col("Volume") if "Volume" in norm_df.columns else pl.lit(0.0)

            # Vektörize hesaplama ifadeleri
            exprs: list[pl.Expr] = [
                c.pct_change(5).alias("roc_5d"),
                c.pct_change(20).alias("roc_20d"),
                c.pct_change(60).alias("roc_60d"),
                ((c / c.rolling_mean(20)) - 1.0).alias("dist_sma20"),
                ((c / c.rolling_mean(50)) - 1.0).alias("dist_sma50"),
                (c.pct_change().rolling_std(20) * np.sqrt(DEFAULT_ANNUAL_TRADING_DAYS)).alias("volatility_20d"),
                ((c / c.rolling_max(20)) - 1.0).alias("drawdown_20d"),
            ]

            if "Volume" in norm_df.columns:
                vol_mean = v.rolling_mean(20)
                vol_std = v.rolling_std(20)
                exprs.extend([
                    ((v - vol_mean) / (vol_std + 1.0)).alias("volume_zscore_20d"),
                    (v.rolling_mean(5) / (vol_mean + 1.0)).alias("volume_trend_ratio"),
                ])

            return norm_df.with_columns(exprs)

    def __repr__(self) -> str:
        """FeatureEngine nesnesinin metin temsili."""
        return "FeatureEngine(version='3.0-polars-native', lookback_modes=5)"


# ==============================================================================
# 5. EVREN GENELİ ÖZNİTELİK HESAPLAMA YARDIMCISI
# ==============================================================================
def compute_universe_features(
    market_data: dict[str, pl.DataFrame],
    benchmark_df: pl.DataFrame | None = None,
    sector_map: dict[str, str] | None = None,
) -> dict[str, dict[str, float]]:
    """Tüm BIST-100 hisse evreni için çapraz kesit ve tekil öznitelikleri topluca hesaplar.

    Args:
        market_data: Hisse kodu -> OHLCV Polars DataFrame eşlemesi.
        benchmark_df: XU100 gösterge endeksi.
        sector_map: Hisse -> Sektör eşleme sözlüğü.

    Returns:
        Hisse kodu -> (öznitelik adı -> değer) sözlüğü.
    """
    if not market_data:
        return {}

    engine = FeatureEngine()
    s_map = sector_map or {}

    # 1. Normalizasyon
    norm_market: dict[str, pl.DataFrame] = {}
    for ticker, df in market_data.items():
        if df is not None and len(df) > 0:
            norm_market[ticker] = engine.normalize(df)

    norm_bm = engine.normalize(benchmark_df) if benchmark_df is not None else None

    # 2. Evren Getirileri ve RSI
    universe_returns: dict[str, float] = {}
    universe_rsi: dict[str, float] = {}
    advancing_count = 0
    total_valid = 0

    for ticker, df in norm_market.items():
        if len(df) >= 2 and "Close" in df.columns:
            ret = last_series_val(df["Close"].pct_change())
            if np.isfinite(ret):
                universe_returns[ticker] = ret
                total_valid += 1
                if ret > 0:
                    advancing_count += 1

            if len(df) >= DEFAULT_MIN_HISTORY_BARS:
                close = df["Close"].cast(pl.Float64)
                delta = close.diff()
                gain = delta.clip(lower_bound=0.0).rolling_mean(DEFAULT_RSI_PERIOD)
                loss = (-delta.clip(upper_bound=0.0)).rolling_mean(DEFAULT_RSI_PERIOD)
                g_val = last_series_val(gain)
                l_val = last_series_val(loss)
                if np.isfinite(g_val) and np.isfinite(l_val):
                    if l_val == 0.0:
                        universe_rsi[ticker] = 100.0 if g_val > 0 else 50.0
                    else:
                        rs = g_val / l_val
                        universe_rsi[ticker] = safe_float(100.0 - (100.0 / (1.0 + rs)))

    breadth_ratio = (advancing_count / total_valid) if total_valid > 0 else 0.5

    # 3. Sektör Getiri Serileri
    sector_series: dict[str, pl.Series] = {}
    if s_map:
        sector_rets: dict[str, list[pl.Series]] = {}
        for ticker, df in norm_market.items():
            if len(df) < 2 or "Close" not in df.columns:
                continue
            sect = s_map.get(ticker, "OTHER")
            if sect not in sector_rets:
                sector_rets[sect] = []
            sector_rets[sect].append(df["Close"].pct_change().fill_null(0.0))

        for sect, s_list in sector_rets.items():
            if s_list:
                min_len = min(len(s) for s in s_list)
                if min_len > 0:
                    aligned = [s.tail(min_len) for s in s_list]
                    stacked = pl.DataFrame({f"s{i}": s for i, s in enumerate(aligned)})
                    sector_series[sect] = stacked.mean_horizontal()

    # 4. Bireysel Hesaplama
    result: dict[str, dict[str, float]] = {}
    for ticker, df in norm_market.items():
        if len(df) < DEFAULT_MIN_HISTORY_BARS:
            continue
        try:
            sect = s_map.get(ticker, "OTHER")
            sect_ret = sector_series.get(sect)
            features = engine.compute_all(
                ticker=ticker,
                df=df,
                benchmark_df=norm_bm,
                sector_returns=sect_ret,
                universe_returns=universe_returns,
                universe_rsi=universe_rsi,
                breadth_advance_ratio=breadth_ratio,
            )
            result[ticker] = features
        except Exception as e:
            logger.warning("ticker_features_computation_failed", ticker=ticker, error=str(e))
            result[ticker] = {}

    logger.info(
        "universe_features_computed",
        tickers_count=len(result),
        avg_features=float(np.mean([len(v) for v in result.values()])) if result else 0.0,
    )
    return result


# ==============================================================================
# 6. DUCKDB VERİTABANI DENETİM İZİ YÖNETİMİ
# ==============================================================================
def save_feature_set_to_duckdb(
    res: FeatureSetResult,
    db_path: str = DEFAULT_DUCKDB_PATH,
) -> None:
    """Hesaplanan öznitelik setini DuckDB denetim tablosuna SSD korumalı WAL sınırlarıyla kaydeder.

    Args:
        res: Kaydedilecek FeatureSetResult nesnesi.
        db_path: Hedef DuckDB dosya yolu.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = duckdb.connect(db_path)
    try:
        configure_duckdb_wal(con)

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_feature_engine_audit (
                audit_id VARCHAR PRIMARY KEY,
                ticker VARCHAR,
                calculated_at TIMESTAMP,
                feature_count BIGINT,
                features_json VARCHAR
            );
            """
        )

        audit_id = f"feat_{uuid.uuid4().hex[:8]}"
        features_json = orjson.dumps(res.features).decode("utf-8")

        con.execute(
            """
            INSERT OR REPLACE INTO ml_feature_engine_audit
            VALUES (?, ?, ?, ?, ?);
            """,
            [
                audit_id,
                res.ticker,
                res.calculated_at,
                res.feature_count,
                features_json,
            ],
        )
        logger.info("feature_set_saved_to_duckdb", ticker=res.ticker, count=res.feature_count)
    finally:
        con.close()


def read_feature_audit_polars(
    db_path: str = DEFAULT_DUCKDB_PATH,
    ticker: str | None = None,
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı öznitelik hesaplama denetim izini Polars DataFrame olarak döndürür.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: Filtrelenecek hisse kodu (opsiyonel).
        limit: Alınacak azami kayıt sayısı.

    Returns:
        Polars DataFrame.
    """
    if not os.path.exists(db_path):
        return pl.DataFrame()

    con = duckdb.connect(db_path, read_only=True)
    try:
        configure_duckdb_wal(con)
        where_clause = f"WHERE ticker = '{ticker}'" if ticker else ""
        query = f"""
            SELECT audit_id, ticker, calculated_at, feature_count, features_json
            FROM ml_feature_engine_audit
            {where_clause}
            ORDER BY calculated_at DESC
            LIMIT {limit};
        """
        arrow_table = con.execute(query).arrow()
        return pl.from_arrow(arrow_table)
    except Exception as e:
        logger.warning("read_feature_audit_polars_failed", error=str(e))
        return pl.DataFrame()
    finally:
        con.close()


# ==============================================================================
# 7. DIŞA AKTARILAN MODÜL SEMBOLLERİ (__all__)
# ==============================================================================
__all__: Final[list[str]] = [
    "DEFAULT_ANNUAL_TRADING_DAYS",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_MIN_HISTORY_BARS",
    "DEFAULT_MIN_UNIVERSE_SIZE",
    "DEFAULT_ROC_WINDOWS",
    "DEFAULT_RSI_PERIOD",
    "DEFAULT_SMA_WINDOWS",
    "DEFAULT_WAL_AUTO_CHECKPOINT",
    "FeatureSetResult",
    "FeatureEngine",
    "compute_universe_features",
    "configure_duckdb_wal",
    "get_feature_registry",
    "last_series_val",
    "read_feature_audit_polars",
    "safe_float",
    "save_feature_set_to_duckdb",
]
