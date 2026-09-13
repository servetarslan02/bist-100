"""
ALPHA BIST — Adaptif Etiketleme Motoru

Geleneksel sabit eşikli (örn. +/-%5) forward return etiketlemesinin ötesinde,
piyasa koşullarına ve volatilite rejimine göre dinamik olarak eşikleri ayarlayan
gelişmiş etiketleme sistemi.

Adaptif Etiketleme Türleri:
  1. Volatilite Bazlı: Eşik = k × realized_vol → piyasanın normal dalgalanması kadar hareket = nötr.
  2. Asimetrik: Yukarı ve aşağı eşikler farklı (bull piyasada yukarı eşik daha dar).
  3. Yüzdelik Bazlı: Etiket = cross-sectional yüzdelik sırasına göre (ML için optimal).
  4. Çoklu Dönem: Birden fazla forward period için etiket üretir ve en güçlü sinyali seçer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_VOL_MULT_UPPER: float = 1.5     # Üst eşik = mult × vol
DEFAULT_VOL_MULT_LOWER: float = 1.0     # Alt eşik = mult × vol (asimetrik)
DEFAULT_VOL_WINDOW: int = 20            # Volatilite hesaplama penceresi
DEFAULT_PERIODS: list[int] = [5, 10, 20]
DEFAULT_PERCENTILE_TOP: float = 70.0    # Üst yüzdelik eşiği
DEFAULT_PERCENTILE_BOTTOM: float = 30.0  # Alt yüzdelik eşiği
DEFAULT_MIN_VOLATILITY: float = 1e-6


@dataclass
class AdaptiveLabelResult:
    """Adaptif etiketleme sonucu.

    Attributes:
        ticker: Hisse senedi kodu.
        labels: Adaptif etiket dizisi (+1, -1, 0, NaN).
        thresholds_upper: Her çubuk için üst etiket eşiği (%).
        thresholds_lower: Her çubuk için alt etiket eşiği (%).
        forward_returns: Kullanılan forward return dizisi (%).
        method: Kullanılan etiketleme yöntemi.
        stats: Özet istatistikler.
    """

    ticker: str
    labels: np.ndarray
    thresholds_upper: np.ndarray
    thresholds_lower: np.ndarray
    forward_returns: np.ndarray
    method: str
    stats: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """AdaptiveLabelResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.labels)))
        pos = int(np.nansum(self.labels == 1))
        neg = int(np.nansum(self.labels == -1))
        neu = int(np.nansum(self.labels == 0))
        return (
            f"AdaptiveLabelResult(ticker={self.ticker!r}, method={self.method!r}, "
            f"valid={valid}, +1={pos}, 0={neu}, -1={neg})"
        )


@dataclass
class MultiPeriodLabelResult:
    """Çok dönemli etiketleme sonucu.

    Attributes:
        ticker: Hisse senedi kodu.
        consensus_labels: Tüm dönemlerden oy birliğiyle seçilen etiket.
        period_labels: Her dönem için ayrı etiket sözlüğü.
        agreement_scores: Her çubuk için dönem anlaşması oranı (0-1).
        stats: Özet istatistikler.
    """

    ticker: str
    consensus_labels: np.ndarray
    period_labels: dict[int, np.ndarray]
    agreement_scores: np.ndarray
    stats: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """MultiPeriodLabelResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.consensus_labels)))
        return (
            f"MultiPeriodLabelResult(ticker={self.ticker!r}, "
            f"periods={list(self.period_labels.keys())}, valid={valid})"
        )


class AdaptiveLabeler:
    """Volatilite ve piyasa koşullarına göre dinamik eşikli etiketleme motoru.

    Sabit eşikli etiketlemenin temel sorunu:
    - Yüksek volatilite dönemlerinde +/%5 eşiği çok kolay aşılır → çok fazla +1/-1.
    - Düşük volatilite dönemlerinde bu eşiğe ulaşmak zorlaşır → her şey nötr.

    Adaptif eşik bu sorunu çözer: Eşik = k × volatilite. Piyasanın normal
    hareketinin ötesine geçen durumlar anlamlı olarak işaretlenir.
    """

    def __init__(
        self,
        vol_mult_upper: float = DEFAULT_VOL_MULT_UPPER,
        vol_mult_lower: float = DEFAULT_VOL_MULT_LOWER,
        vol_window: int = DEFAULT_VOL_WINDOW,
        min_volatility: float = DEFAULT_MIN_VOLATILITY,
        periods: list[int] | None = None,
    ) -> None:
        """AdaptiveLabeler başlatıcı.

        Args:
            vol_mult_upper: Üst eşik çarpanı (üst = mult × vol_annualized).
            vol_mult_lower: Alt eşik çarpanı (alt = mult × vol_annualized).
            vol_window: Geriye dönük volatilite hesaplama penceresi (gün).
            min_volatility: Sıfır volatilite koruması için minimum değer.
            periods: Çoklu dönem analizi için forward period listesi.

        Raises:
            ValueError: Çarpanlar geçersizse.
        """
        if vol_mult_upper <= 0 or vol_mult_lower <= 0:
            raise ValueError("Çarpanlar pozitif olmalıdır.")
        if vol_window < 2:
            raise ValueError(f"vol_window >= 2 olmalıdır: {vol_window}")

        self.vol_mult_upper = vol_mult_upper
        self.vol_mult_lower = vol_mult_lower
        self.vol_window = vol_window
        self.min_volatility = min_volatility
        self.periods = periods or DEFAULT_PERIODS

    def __repr__(self) -> str:
        """AdaptiveLabeler kısa temsili."""
        return (
            f"AdaptiveLabeler(upper_mult={self.vol_mult_upper}, "
            f"lower_mult={self.vol_mult_lower}, win={self.vol_window})"
        )

    def _compute_vol(self, log_rets: np.ndarray, i: int) -> float:
        """Verilen indeks için geriye dönük günlük volatilite.

        Args:
            log_rets: Log-getiri dizisi.
            i: Referans indeks.

        Returns:
            Günlük volatilite tahmini.
        """
        start = max(0, i - self.vol_window + 1)
        window = log_rets[start : i + 1]
        valid = window[np.isfinite(window)]
        if len(valid) < 2:
            return self.min_volatility
        return max(float(np.std(valid)), self.min_volatility)

    def label_volatility_adaptive(
        self,
        ticker: str,
        close: np.ndarray,
        mask: np.ndarray,
        forward_period: int = 10,
        purge_days: int = 0,
    ) -> AdaptiveLabelResult:
        """Volatilite bazlı adaptif eşiklerle forward return etiketleme.

        Eşikler her çubuk için dinamik olarak:
          üst_eşik = vol_mult_upper × realized_daily_vol × sqrt(forward_period) × 100
          alt_eşik = -vol_mult_lower × realized_daily_vol × sqrt(forward_period) × 100

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.
            mask: Tradability maskesi (1 = geçerli, 0 = geçersiz).
            forward_period: Forward return hesaplama süresi (gün).
            purge_days: Son N barı NaN yap (lookahead koruması).

        Returns:
            Adaptif etiketler ve dinamik eşikleri içeren AdaptiveLabelResult.

        Raises:
            ValueError: Diziler boş veya uyumsuzsa.
        """
        if len(close) != len(mask):
            raise ValueError(
                f"close ({len(close)}) ve mask ({len(mask)}) boyutları eşleşmelidir.",
            )
        if len(close) == 0:
            raise ValueError("close dizisi boş olamaz.")

        n = len(close)
        labels = np.full(n, np.nan)
        upper_thresh = np.full(n, np.nan)
        lower_thresh = np.full(n, np.nan)
        fwd_returns = np.full(n, np.nan)

        log_rets = np.full(n, np.nan)
        for i in range(1, n):
            if close[i] > 0 and close[i - 1] > 0:
                log_rets[i] = math.log(close[i] / close[i - 1])

        effective_end = n - forward_period - purge_days
        horizon_factor = math.sqrt(forward_period)

        for i in range(self.vol_window, effective_end):
            if mask[i] == 0 or close[i] <= 0:
                continue
            if mask[i + forward_period] == 0 or close[i + forward_period] <= 0:
                continue

            daily_vol = self._compute_vol(log_rets, i)
            fwd_ret = (close[i + forward_period] / close[i] - 1.0) * 100.0

            # Dinamik eşikler (%)
            upper = self.vol_mult_upper * daily_vol * horizon_factor * 100.0
            lower = -self.vol_mult_lower * daily_vol * horizon_factor * 100.0

            fwd_returns[i] = fwd_ret
            upper_thresh[i] = upper
            lower_thresh[i] = lower

            if fwd_ret >= upper:
                labels[i] = 1.0
            elif fwd_ret <= lower:
                labels[i] = -1.0
            else:
                labels[i] = 0.0

        # İstatistikler
        valid = labels[~np.isnan(labels)]
        stats: dict[str, float] = {}
        if len(valid) > 0:
            stats["total"] = float(len(valid))
            stats["positive_rate"] = float(np.mean(valid == 1))
            stats["negative_rate"] = float(np.mean(valid == -1))
            stats["neutral_rate"] = float(np.mean(valid == 0))
            stats["mean_upper_thresh"] = float(np.nanmean(upper_thresh))
            stats["mean_lower_thresh"] = float(np.nanmean(lower_thresh))

        logger.info(
            "Adaptif volatilite etiketleme tamamlandı.",
            ticker=ticker,
            period=forward_period,
            total=len(valid),
        )

        return AdaptiveLabelResult(
            ticker=ticker,
            labels=labels,
            thresholds_upper=upper_thresh,
            thresholds_lower=lower_thresh,
            forward_returns=fwd_returns,
            method="volatility_adaptive",
            stats=stats,
        )

    def label_multi_period(
        self,
        ticker: str,
        close: np.ndarray,
        mask: np.ndarray,
        purge_days: int = 0,
    ) -> MultiPeriodLabelResult:
        """Çoklu forward period için etiket üretir ve oy birliğiyle birleştirir.

        Tüm dönemlerin aynı yönde işaret ettiği durumlarda etiket güçlüdür.
        Dönemler arasında çelişki varsa agreement_score düşük olur.

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.
            mask: Tradability maskesi.
            purge_days: Son N barı NaN yap.

        Returns:
            Tüm dönem etiketlerini ve oy birliği sonucunu içeren MultiPeriodLabelResult.

        Raises:
            ValueError: close boşsa.
        """
        if len(close) == 0:
            raise ValueError("close dizisi boş olamaz.")

        n = len(close)
        period_labels: dict[int, np.ndarray] = {}

        for period in self.periods:
            result = self.label_volatility_adaptive(
                ticker=ticker,
                close=close,
                mask=mask,
                forward_period=period,
                purge_days=purge_days,
            )
            period_labels[period] = result.labels

        # Oy birliği etiketi
        consensus = np.full(n, np.nan)
        agreement = np.full(n, np.nan)

        stacked = np.stack(list(period_labels.values()), axis=1)

        for i in range(n):
            row = stacked[i, :]
            valid_row = row[~np.isnan(row)]
            if len(valid_row) == 0:
                continue

            pos = float(np.sum(valid_row == 1))
            neg = float(np.sum(valid_row == -1))
            neu = float(np.sum(valid_row == 0))
            total = float(len(valid_row))

            if pos / total >= 0.67:
                consensus[i] = 1.0
                agreement[i] = pos / total
            elif neg / total >= 0.67:
                consensus[i] = -1.0
                agreement[i] = neg / total
            elif neu / total >= 0.67:
                consensus[i] = 0.0
                agreement[i] = neu / total
            else:
                # Çelişkili — en yüksek oy sayısını al
                max_count = max(pos, neg, neu)
                agreement[i] = max_count / total
                if pos == max_count:
                    consensus[i] = 1.0
                elif neg == max_count:
                    consensus[i] = -1.0
                else:
                    consensus[i] = 0.0

        valid = consensus[~np.isnan(consensus)]
        stats: dict[str, float] = {
            "total": float(len(valid)),
            "positive_rate": float(np.mean(valid == 1)) if len(valid) > 0 else 0.0,
            "negative_rate": float(np.mean(valid == -1)) if len(valid) > 0 else 0.0,
            "neutral_rate": float(np.mean(valid == 0)) if len(valid) > 0 else 0.0,
            "mean_agreement": float(np.nanmean(agreement)),
        }

        logger.info(
            "Çok dönemli etiketleme tamamlandı.",
            ticker=ticker,
            periods=self.periods,
            total=len(valid),
            mean_agreement=stats["mean_agreement"],
        )

        return MultiPeriodLabelResult(
            ticker=ticker,
            consensus_labels=consensus,
            period_labels=period_labels,
            agreement_scores=agreement,
            stats=stats,
        )


__all__: list[str] = [
    "AdaptiveLabelResult",
    "AdaptiveLabeler",
    "MultiPeriodLabelResult",
    "adaptive_labeler",
]

# Singleton
adaptive_labeler = AdaptiveLabeler()
