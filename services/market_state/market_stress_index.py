"""
ALPHA BIST — BIST Piyasa Stres Endeksi (MSI)

VIX benzeri BIST'e özgü kompozit piyasa stres endeksi. Volatilite,
spread, korelasyon ve yabancı çıkışı bileşenlerini birleştirerek
piyasanın genel stres seviyesini 0-100 arasında ölçer.

Bileşenler:
  1. Volatilite bileşeni: Gerçekleşen vol / tarihsel medyan vol (normalize edilmiş)
  2. Spread bileşeni: Yüksek-düşük spread trendi (Corwin-Schultz)
  3. Korelasyon bileşeni: Hisseler arası korelasyon (kriz = yüksek korelasyon)
  4. Momentum bileşeni: Aşağı yönlü momentum gücü (crash momentum)
  5. Breadth bileşeni: Düşen hisse oranı (piyasa genişliği)

Referans:
  - FRED STLFSI (St. Louis Financial Stress Index) metodolojisi
  - VIX CBOE volatilite metodolojisi (basitleştirilmiş)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_VOL_WINDOW: int = 20
DEFAULT_HIST_WINDOW: int = 252      # 1 yıllık tarihsel baseline
DEFAULT_CORR_WINDOW: int = 30       # Korelasyon hesaplama penceresi
DEFAULT_EWMA_SPAN: int = 10         # EWMA yumuşatma
DEFAULT_HIGH_STRESS: float = 75.0   # Yüksek stres eşiği (0-100)
DEFAULT_ELEVATED_STRESS: float = 50.0  # Yükselmekte stres eşiği


class StressLevel(IntEnum):
    """Piyasa stres seviyeleri.

    Attributes:
        CRISIS: Sistemik kriz (MSI >= 85).
        HIGH: Yüksek stres (75 <= MSI < 85).
        ELEVATED: Yükselmiş stres (50 <= MSI < 75).
        NORMAL: Normal (25 <= MSI < 50).
        LOW: Düşük stres (MSI < 25).
    """

    CRISIS = 4
    HIGH = 3
    ELEVATED = 2
    NORMAL = 1
    LOW = 0


@dataclass
class MarketStressSnapshot:
    """Anlık piyasa stres okuması.

    Attributes:
        msi: Piyasa Stres İndeksi değeri (0-100).
        level: Stres seviyesi kategorisi.
        vol_component: Volatilite bileşeni katkısı (0-100).
        spread_component: Spread bileşeni katkısı (0-100).
        correlation_component: Korelasyon bileşeni katkısı (0-100).
        momentum_component: Momentum bileşeni katkısı (0-100).
        breadth_component: Breadth bileşeni katkısı (0-100).
        bar_index: İlgili çubuk indeksi.
    """

    msi: float
    level: StressLevel
    vol_component: float
    spread_component: float
    correlation_component: float
    momentum_component: float
    breadth_component: float
    bar_index: int

    def __repr__(self) -> str:
        """MarketStressSnapshot kısa temsili."""
        return (
            f"MarketStressSnapshot(MSI={self.msi:.1f}, "
            f"level={self.level.name}, idx={self.bar_index})"
        )


@dataclass
class MarketStressIndexResult:
    """Piyasa Stres Endeksi tam sonucu.

    Attributes:
        msi: Piyasa Stres İndeksi dizisi (0-100).
        levels: Stres seviyesi dizisi.
        vol_component: Volatilite bileşeni dizisi.
        spread_component: Spread bileşeni dizisi.
        correlation_component: Korelasyon bileşeni dizisi.
        momentum_component: Momentum bileşeni dizisi.
        breadth_component: Breadth bileşeni dizisi.
        crisis_dates: Kriz seviyesine ulaşılan çubuk indeksleri.
        stats: Özet istatistikler.
    """

    msi: np.ndarray
    levels: np.ndarray
    vol_component: np.ndarray
    spread_component: np.ndarray
    correlation_component: np.ndarray
    momentum_component: np.ndarray
    breadth_component: np.ndarray
    crisis_dates: list[int] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """MarketStressIndexResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.msi)))
        crisis = int(np.nansum(self.levels == StressLevel.CRISIS))
        return (
            f"MarketStressIndexResult(valid={valid}, "
            f"mean_msi={np.nanmean(self.msi):.1f}, crisis_bars={crisis})"
        )

    def latest(self) -> MarketStressSnapshot | None:
        """En son geçerli stres okumasını döndürür.

        Returns:
            Son MarketStressSnapshot veya None (veri yoksa).
        """
        for i in range(len(self.msi) - 1, -1, -1):
            if not np.isnan(self.msi[i]):
                return MarketStressSnapshot(
                    msi=float(self.msi[i]),
                    level=StressLevel(int(self.levels[i])),
                    vol_component=float(self.vol_component[i]),
                    spread_component=float(self.spread_component[i]),
                    correlation_component=float(self.correlation_component[i]),
                    momentum_component=float(self.momentum_component[i]),
                    breadth_component=float(self.breadth_component[i]),
                    bar_index=i,
                )
        return None


class MarketStressIndex:
    """BIST Piyasa Stres Endeksi hesaplama motoru.

    5 bileşeni eşit ağırlıkla birleştirerek 0-100 arası bileşik stres skoru
    üretir. Bileşenler tarihsel yüzdeliklerine göre normalize edilir;
    bu sayede mutlak seviye yerine "normalden sapma" ölçülür.
    """

    def __init__(
        self,
        vol_window: int = DEFAULT_VOL_WINDOW,
        hist_window: int = DEFAULT_HIST_WINDOW,
        corr_window: int = DEFAULT_CORR_WINDOW,
        ewma_span: int = DEFAULT_EWMA_SPAN,
        high_stress: float = DEFAULT_HIGH_STRESS,
        elevated_stress: float = DEFAULT_ELEVATED_STRESS,
        vol_weight: float = 0.30,
        spread_weight: float = 0.20,
        corr_weight: float = 0.20,
        momentum_weight: float = 0.20,
        breadth_weight: float = 0.10,
    ) -> None:
        """MarketStressIndex başlatıcı.

        Args:
            vol_window: Gerçekleşen volatilite hesaplama penceresi.
            hist_window: Tarihsel baseline penceresi (yüzdelik için).
            corr_window: Korelasyon hesaplama penceresi.
            ewma_span: MSI yumuşatma için EWMA span.
            high_stress: Yüksek stres eşiği (0-100).
            elevated_stress: Yükselmiş stres eşiği (0-100).
            vol_weight: Volatilite bileşeni ağırlığı.
            spread_weight: Spread bileşeni ağırlığı.
            corr_weight: Korelasyon bileşeni ağırlığı.
            momentum_weight: Momentum bileşeni ağırlığı.
            breadth_weight: Breadth bileşeni ağırlığı.

        Raises:
            ValueError: Ağırlıklar toplamı 1.0 değilse.
        """
        total_w = vol_weight + spread_weight + corr_weight + momentum_weight + breadth_weight
        if abs(total_w - 1.0) > 0.01:
            raise ValueError(f"Ağırlıklar toplamı 1.0 olmalıdır: {total_w:.2f}")

        self.vol_window = vol_window
        self.hist_window = hist_window
        self.corr_window = corr_window
        self.ewma_span = ewma_span
        self.high_stress = high_stress
        self.elevated_stress = elevated_stress
        self.weights = {
            "vol": vol_weight,
            "spread": spread_weight,
            "corr": corr_weight,
            "momentum": momentum_weight,
            "breadth": breadth_weight,
        }

    def __repr__(self) -> str:
        """MarketStressIndex kısa temsili."""
        return (
            f"MarketStressIndex(vol_win={self.vol_window}, hist_win={self.hist_window}, "
            f"high_stress={self.high_stress})"
        )

    def _percentile_score(self, series: np.ndarray, i: int, higher_is_worse: bool = True) -> float:
        """Tarihsel yüzdelik skoru hesaplar (0-100 arası stres katkısı).

        Args:
            series: Zaman serisi.
            i: Referans indeks.
            higher_is_worse: True ise yüksek değer = yüksek stres.

        Returns:
            0-100 arası stres katkı skoru.
        """
        start = max(0, i - self.hist_window)
        hist = series[start:i]
        valid_hist = hist[~np.isnan(hist)]
        if len(valid_hist) < 5 or np.isnan(series[i]):
            return 50.0  # Veri yoksa nötr

        n = len(valid_hist)
        pct = float(np.searchsorted(np.sort(valid_hist), series[i]) / n * 100.0)
        return pct if higher_is_worse else (100.0 - pct)

    def _compute_vol_series(self, log_returns: np.ndarray) -> np.ndarray:
        """Gerçekleşen volatilite zaman serisini hesaplar.

        Args:
            log_returns: Log-getiri dizisi.

        Returns:
            Gerçekleşen günlük volatilite dizisi.
        """
        n = len(log_returns)
        vol_series = np.full(n, np.nan)
        for i in range(self.vol_window, n):
            window = log_returns[i - self.vol_window : i]
            valid = window[np.isfinite(window)]
            if len(valid) >= 2:
                vol_series[i] = float(np.std(valid))
        return vol_series

    def _compute_spread_series(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray
    ) -> np.ndarray:
        """Relative bid-ask spread proxy serisini hesaplar.

        Args:
            high: Yüksek fiyat dizisi.
            low: Düşük fiyat dizisi.
            close: Kapanış fiyatları dizisi.

        Returns:
            Göreli spread dizisi.
        """
        n = len(close)
        spread_series = np.full(n, np.nan)
        for i in range(n):
            if close[i] > 0 and high[i] >= low[i]:
                spread_series[i] = (high[i] - low[i]) / close[i]
        return spread_series

    def _compute_momentum_series(self, log_returns: np.ndarray) -> np.ndarray:
        """Aşağı yönlü momentum serisini hesaplar.

        Sadece negatif getiriler dikkate alınır: crash_momentum = abs(negatif_ret_ortalaması).

        Args:
            log_returns: Log-getiri dizisi.

        Returns:
            Crash momentum dizisi (pozitif, yüksek = yüksek stres).
        """
        n = len(log_returns)
        momentum = np.full(n, np.nan)
        for i in range(self.vol_window, n):
            window = log_returns[i - self.vol_window : i]
            valid = window[np.isfinite(window)]
            neg = valid[valid < 0]
            if len(neg) > 0:
                momentum[i] = float(abs(np.mean(neg)))
            else:
                momentum[i] = 0.0
        return momentum

    def compute(
        self,
        close: np.ndarray,
        volume: np.ndarray | None = None,
        high: np.ndarray | None = None,
        low: np.ndarray | None = None,
        breadth_declining_ratio: np.ndarray | None = None,
        cross_sectional_returns: np.ndarray | None = None,
    ) -> MarketStressIndexResult:
        """Piyasa Stres Endeksini hesaplar.

        Args:
            close: Kapanış fiyatları dizisi (endeks veya hisse).
            volume: Opsiyonel hacim dizisi.
            high: Opsiyonel yüksek fiyat dizisi.
            low: Opsiyonel düşük fiyat dizisi.
            breadth_declining_ratio: Opsiyonel düşen hisse oranı (0-1). Yoksa hacimden tahmin edilir.
            cross_sectional_returns: Opsiyonel çapraz-kesit getiri matrisi (n_bars × n_stocks).
                                     Korelasyon hesabı için kullanılır.

        Returns:
            Tüm bileşenlerle birlikte tam MSI sonucu.

        Raises:
            ValueError: close dizisi boşsa.
        """
        n = len(close)
        if n == 0:
            raise ValueError("close dizisi boş olamaz.")

        if high is None:
            high = close * 1.005
        if low is None:
            low = close * 0.995

        log_returns = np.full(n, np.nan)
        for i in range(1, n):
            if close[i] > 0 and close[i - 1] > 0:
                log_returns[i] = float(np.log(close[i] / close[i - 1]))

        vol_series = self._compute_vol_series(log_returns)
        spread_series = self._compute_spread_series(high, low, close)
        momentum_series = self._compute_momentum_series(log_returns)

        # Korelasyon serisi (cross-sectional verilmemişse vol ile proxy)
        if cross_sectional_returns is not None and cross_sectional_returns.ndim == 2:
            corr_series = np.full(n, np.nan)
            for i in range(self.corr_window, min(n, cross_sectional_returns.shape[0])):
                window = cross_sectional_returns[i - self.corr_window : i, :]
                valid_cols = ~np.all(np.isnan(window), axis=0)
                if int(np.sum(valid_cols)) >= 2:
                    sub = window[:, valid_cols]
                    try:
                        corr_matrix = np.corrcoef(sub.T)
                        mask = ~np.eye(corr_matrix.shape[0], dtype=bool)
                        mean_corr = float(np.nanmean(np.abs(corr_matrix[mask])))
                        corr_series[i] = mean_corr
                    except (ValueError, np.linalg.LinAlgError):
                        pass
        else:
            # Proxy: yüksek vol dönemlerinde korelasyon artma eğilimi
            corr_series = np.full(n, np.nan)
            for i in range(self.hist_window, n):
                if not np.isnan(vol_series[i]):
                    hist_vols = vol_series[max(0, i - self.hist_window) : i]
                    valid_hist = hist_vols[~np.isnan(hist_vols)]
                    if len(valid_hist) >= 2:
                        corr_proxy = (vol_series[i] - float(np.min(valid_hist))) / (
                            float(np.max(valid_hist)) - float(np.min(valid_hist)) + 1e-10
                        )
                        corr_series[i] = float(np.clip(corr_proxy, 0.0, 1.0))

        # Breadth
        if breadth_declining_ratio is not None:
            breadth_series = breadth_declining_ratio
        else:
            # Proxy: hacim + negatif getiri
            breadth_series = np.full(n, np.nan)
            for i in range(1, n):
                if not np.isnan(log_returns[i]):
                    breadth_series[i] = 1.0 if log_returns[i] < 0 else 0.0

        # Bileşen skorları (0-100, yüksek = yüksek stres)
        min_window = self.hist_window

        vol_comp = np.full(n, np.nan)
        spread_comp = np.full(n, np.nan)
        corr_comp = np.full(n, np.nan)
        momentum_comp = np.full(n, np.nan)
        breadth_comp = np.full(n, np.nan)

        for i in range(min_window, n):
            vol_comp[i] = self._percentile_score(vol_series, i, higher_is_worse=True)
            spread_comp[i] = self._percentile_score(spread_series, i, higher_is_worse=True)
            corr_comp[i] = self._percentile_score(corr_series, i, higher_is_worse=True)
            momentum_comp[i] = self._percentile_score(momentum_series, i, higher_is_worse=True)
            breadth_comp[i] = self._percentile_score(breadth_series, i, higher_is_worse=True)

        # Bileşik MSI
        msi_raw = (
            self.weights["vol"] * vol_comp
            + self.weights["spread"] * spread_comp
            + self.weights["corr"] * corr_comp
            + self.weights["momentum"] * momentum_comp
            + self.weights["breadth"] * breadth_comp
        )

        # EWMA yumuşatma
        msi = np.full(n, np.nan)
        alpha = 2.0 / (self.ewma_span + 1.0)
        prev = None
        for i in range(n):
            if not np.isnan(msi_raw[i]):
                if prev is None:
                    msi[i] = msi_raw[i]
                    prev = msi_raw[i]
                else:
                    msi[i] = alpha * msi_raw[i] + (1.0 - alpha) * prev
                    prev = msi[i]

        # Stres seviyeleri
        levels = np.full(n, np.nan)
        crisis_dates: list[int] = []
        for i in range(n):
            if np.isnan(msi[i]):
                continue
            v = float(msi[i])
            if v >= 85.0:
                levels[i] = float(StressLevel.CRISIS)
                crisis_dates.append(i)
            elif v >= self.high_stress:
                levels[i] = float(StressLevel.HIGH)
            elif v >= self.elevated_stress:
                levels[i] = float(StressLevel.ELEVATED)
            elif v >= 25.0:
                levels[i] = float(StressLevel.NORMAL)
            else:
                levels[i] = float(StressLevel.LOW)

        # İstatistikler
        valid_msi = msi[~np.isnan(msi)]
        stats: dict[str, float] = {}
        if len(valid_msi) > 0:
            stats["mean_msi"] = float(np.mean(valid_msi))
            stats["max_msi"] = float(np.max(valid_msi))
            stats["min_msi"] = float(np.min(valid_msi))
            stats["crisis_rate"] = float(np.nanmean(levels == StressLevel.CRISIS))
            stats["high_stress_rate"] = float(np.nanmean(levels == StressLevel.HIGH))
            stats["n_crisis_bars"] = float(len(crisis_dates))

        logger.info(
            "Piyasa Stres İndeksi hesaplandı.",
            valid=len(valid_msi),
            mean_msi=round(stats.get("mean_msi", 0.0), 1),
            max_msi=round(stats.get("max_msi", 0.0), 1),
            n_crisis=len(crisis_dates),
        )

        return MarketStressIndexResult(
            msi=msi,
            levels=levels,
            vol_component=vol_comp,
            spread_component=spread_comp,
            correlation_component=corr_comp,
            momentum_component=momentum_comp,
            breadth_component=breadth_comp,
            crisis_dates=crisis_dates,
            stats=stats,
        )


__all__: list[str] = [
    "MarketStressIndex",
    "MarketStressIndexResult",
    "MarketStressSnapshot",
    "StressLevel",
    "market_stress_index",
]

# Singleton
market_stress_index = MarketStressIndex()
