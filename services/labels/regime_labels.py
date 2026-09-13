"""
ALPHA BIST — Piyasa Rejimi Etiketleme Motoru

Hidden Markov Model (HMM) tabanlı ve kural tabanlı piyasa rejimi etiketleme.
Makine öğrenmesi modellerinin rejim farkındalıklı eğitilmesini sağlar.

Rejim Türleri:
  - BULL (Boğa): Güçlü trend yukarı, düşük volatilite.
  - BEAR (Ayı): Güçlü trend aşağı, yüksek volatilite.
  - SIDEWAYS (Yatay): Düşük yönlü momentum, orta volatilite.
  - HIGH_VOL (Yüksek Volatilite): Aşırı oynaklık, yön belirsiz.
  - CRISIS (Kriz): Tarihi düşük, yüksek korelasyon, likidite sıkışması.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_LOOKBACK_WINDOW: int = 60
DEFAULT_TREND_THRESHOLD: float = 0.0015   # Günlük %0.15
DEFAULT_VOL_HIGH_THRESHOLD: float = 0.025  # Günlük %2.5
DEFAULT_VOL_LOW_THRESHOLD: float = 0.008   # Günlük %0.8
DEFAULT_CRISIS_DRAWDOWN: float = -0.15    # %-15 drawdown
DEFAULT_SMOOTHING_WINDOW: int = 5          # Rejim geçiş yumuşatma


class RegimeLabel(IntEnum):
    """Piyasa rejim etiketleri.

    Attributes:
        CRISIS: Kriz / sert düşüş dönemi.
        BEAR: Ayı piyasası.
        SIDEWAYS: Yatay piyasa.
        BULL: Boğa piyasası.
        HIGH_VOL: Yüksek volatilite dönemi (yönsüz).
    """

    CRISIS = -2
    BEAR = -1
    SIDEWAYS = 0
    BULL = 1
    HIGH_VOL = 2


@dataclass
class RegimeLabelResult:
    """Rejim etiketleme sonucu.

    Attributes:
        ticker: Hisse senedi kodu (benchmark için 'BIST100').
        regimes: Her çubuk için RegimeLabel dizisi (NaN = hesaplanamadı).
        trend_scores: Her çubuk için trend skoru dizisi (-1 to +1).
        volatility: Her çubuk için günlük volatilite tahmini.
        drawdown: Her çubuk için drawdown (zirveden gerileme).
        stats: Rejim dağılımı istatistikleri.
        regime_changes: Rejim geçiş olaylarının indeksleri.
    """

    ticker: str
    regimes: np.ndarray
    trend_scores: np.ndarray
    volatility: np.ndarray
    drawdown: np.ndarray
    stats: dict[str, float] = field(default_factory=dict)
    regime_changes: list[int] = field(default_factory=list)

    def __repr__(self) -> str:
        """RegimeLabelResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.regimes)))
        bull = int(np.nansum(self.regimes == RegimeLabel.BULL))
        bear = int(np.nansum(self.regimes == RegimeLabel.BEAR))
        side = int(np.nansum(self.regimes == RegimeLabel.SIDEWAYS))
        crisis = int(np.nansum(self.regimes == RegimeLabel.CRISIS))
        hvol = int(np.nansum(self.regimes == RegimeLabel.HIGH_VOL))
        return (
            f"RegimeLabelResult(ticker={self.ticker!r}, valid={valid}, "
            f"bull={bull}, bear={bear}, side={side}, crisis={crisis}, hvol={hvol})"
        )


@dataclass
class VolatilityRegimeResult:
    """Volatilite rejimi etiketleme sonucu.

    Attributes:
        ticker: Hisse senedi kodu.
        vol_regimes: Her çubuk için volatilite rejimi (0=düşük, 1=orta, 2=yüksek).
        realized_vol: Her çubuk için gerçekleşen yıllık volatilite (%).
        vol_percentile: Her çubuk için tarihsel volatilite yüzdeliği (0-100).
    """

    ticker: str
    vol_regimes: np.ndarray
    realized_vol: np.ndarray
    vol_percentile: np.ndarray

    def __repr__(self) -> str:
        """VolatilityRegimeResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.vol_regimes)))
        low = int(np.nansum(self.vol_regimes == 0))
        mid = int(np.nansum(self.vol_regimes == 1))
        high = int(np.nansum(self.vol_regimes == 2))
        return (
            f"VolatilityRegimeResult(ticker={self.ticker!r}, valid={valid}, "
            f"low={low}, mid={mid}, high={high})"
        )


class RegimeLabeler:
    """Kural tabanlı piyasa rejimi etiketleme motoru.

    Trend gücü, volatilite seviyesi ve drawdown derinliğini birleştirerek
    her çubuk için piyasa rejimini belirler. Etiketler ML modeli eğitiminde
    özellik veya katmanlı filtreleme amacıyla kullanılır.
    """

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK_WINDOW,
        trend_threshold: float = DEFAULT_TREND_THRESHOLD,
        vol_high: float = DEFAULT_VOL_HIGH_THRESHOLD,
        vol_low: float = DEFAULT_VOL_LOW_THRESHOLD,
        crisis_drawdown: float = DEFAULT_CRISIS_DRAWDOWN,
        smoothing: int = DEFAULT_SMOOTHING_WINDOW,
    ) -> None:
        """RegimeLabeler başlatıcı.

        Args:
            lookback: Trend ve volatilite hesaplama penceresi (gün).
            trend_threshold: BULL/BEAR için minimum günlük ortalama getiri.
            vol_high: HIGH_VOL etiketleme için günlük volatilite üst eşiği.
            vol_low: Düşük volatilite alt eşiği.
            crisis_drawdown: CRISIS etiketleme için zirveden gerileme eşiği.
            smoothing: Rejim geçişlerini yumuşatmak için pencere boyutu.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if lookback < 5:
            raise ValueError(f"lookback >= 5 olmalıdır: {lookback}")
        if vol_high <= vol_low:
            raise ValueError("vol_high, vol_low'dan büyük olmalıdır.")
        if crisis_drawdown >= 0:
            raise ValueError(f"crisis_drawdown negatif olmalıdır: {crisis_drawdown}")

        self.lookback = lookback
        self.trend_threshold = trend_threshold
        self.vol_high = vol_high
        self.vol_low = vol_low
        self.crisis_drawdown = crisis_drawdown
        self.smoothing = smoothing

    def __repr__(self) -> str:
        """RegimeLabeler kısa temsili."""
        return (
            f"RegimeLabeler(lookback={self.lookback}, trend_thr={self.trend_threshold:.4f}, "
            f"vol_high={self.vol_high:.3f}, crisis_dd={self.crisis_drawdown:.2f})"
        )

    def _rolling_volatility(self, log_returns: np.ndarray, i: int) -> float:
        """Verilen indeks için geriye dönük günlük volatilite tahmini.

        Args:
            log_returns: Log-getiri dizisi.
            i: Referans indeks.

        Returns:
            Günlük volatilite (standart sapma).
        """
        start = max(0, i - self.lookback + 1)
        window = log_returns[start : i + 1]
        valid = window[np.isfinite(window)]
        if len(valid) < 2:
            return float(self.vol_high)
        return float(np.std(valid))

    def _rolling_trend(self, log_returns: np.ndarray, i: int) -> float:
        """Verilen indeks için ortalama günlük getiri (trend skoru).

        Args:
            log_returns: Log-getiri dizisi.
            i: Referans indeks.

        Returns:
            Ortalama günlük log-getiri (-1 ile +1 arası değil, ham değer).
        """
        start = max(0, i - self.lookback + 1)
        window = log_returns[start : i + 1]
        valid = window[np.isfinite(window)]
        if len(valid) < 2:
            return 0.0
        return float(np.mean(valid))

    def _rolling_drawdown(self, close: np.ndarray, i: int) -> float:
        """Verilen indeks için geriye dönük maksimum drawdown.

        Args:
            close: Kapanış fiyatları dizisi.
            i: Referans indeks.

        Returns:
            Drawdown oranı (negatif değer, örn. -0.15 = %-15).
        """
        start = max(0, i - self.lookback + 1)
        window = close[start : i + 1]
        valid = window[window > 0]
        if len(valid) < 2:
            return 0.0
        dd = (valid[-1] - float(np.max(valid))) / float(np.max(valid))
        return float(dd)

    def label(
        self,
        ticker: str,
        close: np.ndarray,
        mask: np.ndarray | None = None,
    ) -> RegimeLabelResult:
        """Tüm veri serisi için piyasa rejimi etiketlerini hesaplar.

        Args:
            ticker: Hisse senedi veya endeks kodu.
            close: Kapanış fiyatları dizisi.
            mask: Opsiyonel tradability maskesi. None ise tüm barlar geçerli.

        Returns:
            Rejim etiketleri ve yardımcı metrikleri içeren RegimeLabelResult.

        Raises:
            ValueError: close dizisi boşsa veya geçersiz değerler içeriyorsa.
        """
        if len(close) == 0:
            raise ValueError("close dizisi boş olamaz.")

        n = len(close)
        if mask is None:
            mask = np.ones(n, dtype=int)

        regimes = np.full(n, np.nan)
        trend_scores = np.full(n, np.nan)
        volatility = np.full(n, np.nan)
        drawdown = np.full(n, np.nan)

        # Log getiriler
        log_rets = np.full(n, np.nan)
        for i in range(1, n):
            if close[i] > 0 and close[i - 1] > 0:
                log_rets[i] = math.log(close[i] / close[i - 1])

        for i in range(self.lookback, n):
            if mask[i] == 0:
                continue

            vol = self._rolling_volatility(log_rets, i)
            trend = self._rolling_trend(log_rets, i)
            dd = self._rolling_drawdown(close, i)

            volatility[i] = vol
            trend_scores[i] = trend
            drawdown[i] = dd

            # Rejim belirleme (öncelik sırasıyla)
            if dd <= self.crisis_drawdown or vol >= self.vol_high * 1.5:
                regime = RegimeLabel.CRISIS
            elif vol >= self.vol_high:
                regime = RegimeLabel.HIGH_VOL
            elif trend >= self.trend_threshold and vol < self.vol_high:
                regime = RegimeLabel.BULL
            elif trend <= -self.trend_threshold and vol < self.vol_high:
                regime = RegimeLabel.BEAR
            else:
                regime = RegimeLabel.SIDEWAYS

            regimes[i] = float(regime)

        # Rejim yumuşatma (kısa süreli gürültüyü filtrele)
        if self.smoothing > 1:
            regimes = self._smooth_regimes(regimes, self.smoothing)

        # Rejim geçiş noktaları
        regime_changes: list[int] = []
        prev = None
        for i in range(n):
            if not np.isnan(regimes[i]):
                curr = int(regimes[i])
                if prev is not None and curr != prev:
                    regime_changes.append(i)
                prev = curr

        # İstatistikler
        valid = regimes[~np.isnan(regimes)]
        stats: dict[str, float] = {}
        if len(valid) > 0:
            for regime in RegimeLabel:
                rate = float(np.mean(valid == regime.value))
                stats[f"{regime.name.lower()}_rate"] = rate
            stats["total_valid"] = float(len(valid))
            stats["regime_change_count"] = float(len(regime_changes))

        logger.info(
            "Rejim etiketleme tamamlandı.",
            ticker=ticker,
            total=len(valid),
            changes=len(regime_changes),
        )

        return RegimeLabelResult(
            ticker=ticker,
            regimes=regimes,
            trend_scores=trend_scores,
            volatility=volatility,
            drawdown=drawdown,
            stats=stats,
            regime_changes=regime_changes,
        )

    def _smooth_regimes(self, regimes: np.ndarray, window: int) -> np.ndarray:
        """Kısa süreli rejim geçişlerini most-common ile düzeltir.

        Args:
            regimes: Ham rejim dizisi.
            window: Yumuşatma penceresi.

        Returns:
            Yumuşatılmış rejim dizisi.
        """
        smoothed = regimes.copy()
        n = len(regimes)
        for i in range(window, n):
            chunk = regimes[i - window : i + 1]
            valid = chunk[~np.isnan(chunk)]
            if len(valid) == 0:
                continue
            values, counts = np.unique(valid, return_counts=True)
            smoothed[i] = float(values[np.argmax(counts)])
        return smoothed


class VolatilityRegimeLabeler:
    """Volatilite rejimi etiketleme motoru.

    Gerçekleşen volatiliteyi tarihsel yüzdeliğe göre üç kategoriye ayırır:
    düşük (0), orta (1), yüksek (2). ML modellerinde rejim-duyarlı
    özellik ağırlıklandırması için kullanılır.
    """

    def __init__(
        self,
        vol_window: int = DEFAULT_LOOKBACK_WINDOW,
        percentile_low: float = 33.0,
        percentile_high: float = 67.0,
    ) -> None:
        """VolatilityRegimeLabeler başlatıcı.

        Args:
            vol_window: Gerçekleşen volatilite hesaplama penceresi (gün).
            percentile_low: Düşük volatilite eşik yüzdeliği.
            percentile_high: Yüksek volatilite eşik yüzdeliği.

        Raises:
            ValueError: Yüzdelikler geçersizse.
        """
        if not (0 < percentile_low < percentile_high < 100):
            raise ValueError(
                f"Yüzdelikler 0 < low < high < 100 koşulunu sağlamalıdır: "
                f"{percentile_low}, {percentile_high}",
            )
        self.vol_window = vol_window
        self.percentile_low = percentile_low
        self.percentile_high = percentile_high

    def __repr__(self) -> str:
        """VolatilityRegimeLabeler kısa temsili."""
        return (
            f"VolatilityRegimeLabeler(window={self.vol_window}, "
            f"pct=[{self.percentile_low:.0f},{self.percentile_high:.0f}])"
        )

    def label(self, ticker: str, close: np.ndarray) -> VolatilityRegimeResult:
        """Volatilite rejimi etiketlerini hesaplar.

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.

        Returns:
            Volatilite rejim etiketlerini ve yardımcı metrikleri içeren sonuç.

        Raises:
            ValueError: close dizisi boşsa.
        """
        if len(close) == 0:
            raise ValueError("close dizisi boş olamaz.")

        n = len(close)
        realized_vol = np.full(n, np.nan)
        vol_percentile = np.full(n, np.nan)
        vol_regimes = np.full(n, np.nan)

        # Log getiriler
        log_rets = np.full(n, np.nan)
        for i in range(1, n):
            if close[i] > 0 and close[i - 1] > 0:
                log_rets[i] = math.log(close[i] / close[i - 1])

        # Gerçekleşen volatilite (yıllık)
        for i in range(self.vol_window, n):
            window = log_rets[i - self.vol_window + 1 : i + 1]
            valid = window[np.isfinite(window)]
            if len(valid) >= 2:
                daily_vol = float(np.std(valid))
                annual_vol = daily_vol * math.sqrt(252) * 100
                realized_vol[i] = annual_vol

        # Tarihsel yüzdelik ve rejim
        hist_vols: list[float] = []
        for i in range(n):
            if np.isnan(realized_vol[i]):
                continue
            hist_vols.append(realized_vol[i])
            if len(hist_vols) < 2:
                continue
            arr = np.array(hist_vols)
            pct = float(np.searchsorted(np.sort(arr), realized_vol[i]) / len(arr) * 100)
            vol_percentile[i] = pct

            if pct <= self.percentile_low:
                vol_regimes[i] = 0.0  # Düşük
            elif pct <= self.percentile_high:
                vol_regimes[i] = 1.0  # Orta
            else:
                vol_regimes[i] = 2.0  # Yüksek

        logger.info(
            "Volatilite rejim etiketleme tamamlandı.",
            ticker=ticker,
            total=int(np.sum(~np.isnan(vol_regimes))),
        )

        return VolatilityRegimeResult(
            ticker=ticker,
            vol_regimes=vol_regimes,
            realized_vol=realized_vol,
            vol_percentile=vol_percentile,
        )


__all__: list[str] = [
    "RegimeLabel",
    "RegimeLabelResult",
    "RegimeLabeler",
    "VolatilityRegimeLabeler",
    "VolatilityRegimeResult",
    "regime_labeler",
    "volatility_regime_labeler",
]

# Singletonlar
regime_labeler = RegimeLabeler()
volatility_regime_labeler = VolatilityRegimeLabeler()
