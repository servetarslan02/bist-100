"""
ALPHA BIST — Triple Barrier Etiketleme Motoru

López de Prado (Advances in Financial Machine Learning, 2018) metodolojisine
dayanan üçlü bariyer etiketleme sistemi. Geleneksel forward-return etiketlemenin
ötesinde, gerçekçi trade çıkış koşullarını modelleyen kurumsal düzeyde etiketleme
sağlar.

Bariyer Türleri:
  - Üst Bariyer: Kâr alma (profit take) eşiği aşıldığında +1 etiketi.
  - Alt Bariyer: Zarar kes (stop loss) eşiği aşıldığında -1 etiketi.
  - Zaman Bariyeri: Süre dolduğunda 0 etiketi (nötr/belirsiz).

Meta-Labeling:
  - Birincil modelin tahminlerini ikincil bir meta-model ile filtreler.
  - Pozisyon büyüklüğünü güven skoruyla orantılar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_PROFIT_TAKE_MULTIPLIER: float = 2.0
DEFAULT_STOP_LOSS_MULTIPLIER: float = 1.0
DEFAULT_MAX_HOLDING_DAYS: int = 20
DEFAULT_VOLATILITY_WINDOW: int = 20
DEFAULT_MIN_VOLATILITY: float = 1e-6
DEFAULT_ANNUAL_TRADING_DAYS: int = 252


class BarrierHit(NamedTuple):
    """Bir bariyerin isabet ettiği an ve türü.

    Attributes:
        bar_index: Bariyerin isabet ettiği çubuk indeksi.
        label: Bariyer türü (+1 üst, -1 alt, 0 zaman).
        return_pct: İlk bardan bu ana kadar elde edilen getiri (%).
        days_held: Pozisyonun tutulduğu gün sayısı.
    """

    bar_index: int
    label: int
    return_pct: float
    days_held: int


@dataclass
class TripleBarrierResult:
    """Triple Barrier yönteminin tek bir örnek için sonucu.

    Attributes:
        start_index: Pozisyonun açıldığı çubuk indeksi.
        ticker: Hisse senedi kodu.
        label: Etiket değeri (+1, -1, 0).
        return_pct: Çıkıştaki toplam getiri (%).
        days_held: Pozisyonun tutulduğu gün sayısı.
        upper_barrier: Üst bariyer fiyatı.
        lower_barrier: Alt bariyer fiyatı.
        time_barrier_index: Zaman bariyerinin çubuk indeksi.
        hit: Hangi bariyerin isabet ettiği.
        volatility: Hesaplama sırasındaki günlük volatilite tahmini.
    """

    start_index: int
    ticker: str
    label: int
    return_pct: float
    days_held: int
    upper_barrier: float
    lower_barrier: float
    time_barrier_index: int
    hit: str  # "upper" | "lower" | "time"
    volatility: float

    def __repr__(self) -> str:
        """TripleBarrierResult kısa temsili."""
        return (
            f"TripleBarrierResult(ticker={self.ticker!r}, idx={self.start_index}, "
            f"label={self.label:+d}, ret={self.return_pct:.2f}%, hit={self.hit!r})"
        )


@dataclass
class TripleBarrierLabels:
    """Bir hissenin tüm Triple Barrier etiketleri.

    Attributes:
        ticker: Hisse senedi kodu.
        labels: Her çubuk için etiket dizisi (NaN = hesaplanamadı).
        returns: Her çubuk için çıkış getirisi dizisi (NaN = hesaplanamadı).
        days_held: Her çubuk için tutulan gün sayısı dizisi.
        results: Her hesaplanabilir örnek için TripleBarrierResult nesneleri.
        stats: Özet istatistikler.
    """

    ticker: str
    labels: np.ndarray
    returns: np.ndarray
    days_held: np.ndarray
    results: list[TripleBarrierResult] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """TripleBarrierLabels kısa temsili."""
        valid = int(np.sum(~np.isnan(self.labels)))
        pos = int(np.sum(self.labels == 1)) if valid > 0 else 0
        neg = int(np.sum(self.labels == -1)) if valid > 0 else 0
        neu = int(np.sum(self.labels == 0)) if valid > 0 else 0
        return (
            f"TripleBarrierLabels(ticker={self.ticker!r}, valid={valid}, "
            f"+1={pos}, -1={neg}, 0={neu})"
        )


@dataclass
class MetaLabelResult:
    """Meta-labeling sonucu.

    Attributes:
        ticker: Hisse senedi kodu.
        meta_labels: İkincil etiket dizisi (1 = birincil modeli destekle, 0 = geç).
        position_sizes: Güven skoruna göre önerilen pozisyon büyüklükleri (0-1).
        primary_labels: Birincil model etiketleri.
        confidence_scores: Birincil modelin güven skorları.
    """

    ticker: str
    meta_labels: np.ndarray
    position_sizes: np.ndarray
    primary_labels: np.ndarray
    confidence_scores: np.ndarray

    def __repr__(self) -> str:
        """MetaLabelResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.meta_labels)))
        accept = int(np.nansum(self.meta_labels == 1))
        return (
            f"MetaLabelResult(ticker={self.ticker!r}, valid={valid}, "
            f"accept={accept}, reject={valid - accept})"
        )


class TripleBarrierLabeler:
    """López de Prado Triple Barrier etiketleme motoru.

    Her gözlem noktası için üç bariyerden hangisinin önce isabet ettiğini
    tespit ederek etiketi belirler. Volatilite tabanlı dinamik bariyer
    genişliği, kâr/zarar oranını sabit tutarak overfitting riskini azaltır.

    Kullanım:
        labeler = TripleBarrierLabeler(
            profit_take_mult=2.0,
            stop_loss_mult=1.0,
            max_holding_days=20,
        )
        result = labeler.label(ticker="THYAO", close=prices, mask=tradable)
    """

    def __init__(
        self,
        profit_take_mult: float = DEFAULT_PROFIT_TAKE_MULTIPLIER,
        stop_loss_mult: float = DEFAULT_STOP_LOSS_MULTIPLIER,
        max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
        volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
        min_volatility: float = DEFAULT_MIN_VOLATILITY,
    ) -> None:
        """Triple Barrier etiketleyiciyi başlatır.

        Args:
            profit_take_mult: Üst bariyer genişliği = mult × günlük_vol × sqrt(holding).
            stop_loss_mult: Alt bariyer genişliği = mult × günlük_vol × sqrt(holding).
            max_holding_days: Maksimum pozisyon tutma süresi (gün).
            volatility_window: Volatilite tahmini için geriye bakış penceresi.
            min_volatility: Sıfır volatilite koruması için alt sınır.

        Raises:
            ValueError: Çarpanlar veya pencere boyutu geçersizse.
        """
        if profit_take_mult <= 0:
            raise ValueError(f"profit_take_mult pozitif olmalıdır: {profit_take_mult}")
        if stop_loss_mult <= 0:
            raise ValueError(f"stop_loss_mult pozitif olmalıdır: {stop_loss_mult}")
        if max_holding_days < 1:
            raise ValueError(f"max_holding_days >= 1 olmalıdır: {max_holding_days}")
        if volatility_window < 2:
            raise ValueError(f"volatility_window >= 2 olmalıdır: {volatility_window}")

        self.profit_take_mult = profit_take_mult
        self.stop_loss_mult = stop_loss_mult
        self.max_holding_days = max_holding_days
        self.volatility_window = volatility_window
        self.min_volatility = min_volatility

    def __repr__(self) -> str:
        """TripleBarrierLabeler kısa temsili."""
        return (
            f"TripleBarrierLabeler(pt={self.profit_take_mult}, sl={self.stop_loss_mult}, "
            f"hold={self.max_holding_days}d, vol_win={self.volatility_window})"
        )

    def _estimate_volatility(self, close: np.ndarray, index: int) -> float:
        """Verilen indeks için geriye dönük günlük volatilite tahmini.

        Args:
            close: Kapanış fiyatları dizisi.
            index: Referans çubuk indeksi.

        Returns:
            Günlük volatilite tahmini (log-return standart sapması).
        """
        start = max(0, index - self.volatility_window)
        window = close[start : index + 1]
        if len(window) < 2:
            return self.min_volatility

        log_rets = np.diff(np.log(np.maximum(window, 1e-10)))
        valid = log_rets[np.isfinite(log_rets)]
        if len(valid) < 2:
            return self.min_volatility

        vol = float(np.std(valid))
        return max(vol, self.min_volatility)

    def _find_barrier_hit(
        self,
        close: np.ndarray,
        mask: np.ndarray,
        start: int,
        upper: float,
        lower: float,
    ) -> BarrierHit:
        """Bir başlangıç noktasından üç bariyerden hangisinin önce isabet ettiğini bulur.

        Args:
            close: Kapanış fiyatları dizisi.
            mask: Tradability maskesi.
            start: Pozisyon açılış indeksi.
            upper: Üst bariyer fiyatı (profit take).
            lower: Alt bariyer fiyatı (stop loss).

        Returns:
            İlk isabet eden bariyere ait BarrierHit nesnesi.
        """
        entry_price = close[start]
        n = len(close)
        time_bar = min(start + self.max_holding_days, n - 1)

        for i in range(start + 1, time_bar + 1):
            if mask[i] == 0:
                continue
            price = close[i]
            ret = (price / entry_price - 1.0) * 100.0
            days = i - start

            if price >= upper:
                return BarrierHit(bar_index=i, label=1, return_pct=ret, days_held=days)
            if price <= lower:
                return BarrierHit(bar_index=i, label=-1, return_pct=ret, days_held=days)

        # Zaman bariyeri
        final_price = close[time_bar] if mask[time_bar] == 1 else entry_price
        ret = (final_price / entry_price - 1.0) * 100.0
        return BarrierHit(
            bar_index=time_bar,
            label=0,
            return_pct=ret,
            days_held=time_bar - start,
        )

    def label(
        self,
        ticker: str,
        close: np.ndarray,
        mask: np.ndarray,
        purge_days: int = 0,
    ) -> TripleBarrierLabels:
        """Bir hisse için tüm triple barrier etiketlerini hesaplar.

        Args:
            ticker: Hisse senedi kodu.
            close: Kapanış fiyatları dizisi.
            mask: İşlem görebilirlik maskesi (1 = geçerli, 0 = geçersiz).
            purge_days: Son N barı NaN yap (lookahead koruması).

        Returns:
            Tüm etiket dizilerini ve özet istatistikleri içeren TripleBarrierLabels.

        Raises:
            ValueError: Dizi uzunlukları uyuşmuyorsa veya dizi boşsa.
        """
        if len(close) != len(mask):
            raise ValueError(
                f"close ({len(close)}) ve mask ({len(mask)}) boyutları eşleşmelidir.",
            )
        if len(close) == 0:
            raise ValueError("close dizisi boş olamaz.")

        n = len(close)
        labels_arr = np.full(n, np.nan)
        returns_arr = np.full(n, np.nan)
        days_arr = np.full(n, np.nan)
        results: list[TripleBarrierResult] = []

        effective_end = n - self.max_holding_days - purge_days
        if effective_end <= 0:
            logger.warning(
                "Triple barrier için yeterli veri yok.",
                ticker=ticker,
                n=n,
                max_holding=self.max_holding_days,
                purge=purge_days,
            )
            return TripleBarrierLabels(
                ticker=ticker,
                labels=labels_arr,
                returns=returns_arr,
                days_held=days_arr,
                results=[],
                stats={},
            )

        for i in range(effective_end):
            if mask[i] == 0:
                continue
            if close[i] <= 0 or not math.isfinite(close[i]):
                continue

            vol = self._estimate_volatility(close, i)
            # Bariyer genişliği: volatilite × çarpan × sqrt(tutma süresi)
            horizon_factor = math.sqrt(self.max_holding_days)
            price = close[i]
            upper = price * (1.0 + self.profit_take_mult * vol * horizon_factor)
            lower = price * (1.0 - self.stop_loss_mult * vol * horizon_factor)

            hit = self._find_barrier_hit(close, mask, i, upper, lower)

            labels_arr[i] = float(hit.label)
            returns_arr[i] = hit.return_pct
            days_arr[i] = float(hit.days_held)

            hit_name = {1: "upper", -1: "lower", 0: "time"}[hit.label]
            results.append(
                TripleBarrierResult(
                    start_index=i,
                    ticker=ticker,
                    label=hit.label,
                    return_pct=hit.return_pct,
                    days_held=hit.days_held,
                    upper_barrier=upper,
                    lower_barrier=lower,
                    time_barrier_index=min(i + self.max_holding_days, n - 1),
                    hit=hit_name,
                    volatility=vol,
                ),
            )

        # İstatistikler
        valid = labels_arr[~np.isnan(labels_arr)]
        stats: dict[str, float] = {}
        if len(valid) > 0:
            stats["total_samples"] = float(len(valid))
            stats["positive_rate"] = float(np.mean(valid == 1))
            stats["negative_rate"] = float(np.mean(valid == -1))
            stats["neutral_rate"] = float(np.mean(valid == 0))
            valid_rets = returns_arr[~np.isnan(returns_arr)]
            if len(valid_rets) > 0:
                stats["mean_return_pct"] = float(np.mean(valid_rets))
                stats["std_return_pct"] = float(np.std(valid_rets))
            valid_days = days_arr[~np.isnan(days_arr)]
            if len(valid_days) > 0:
                stats["mean_days_held"] = float(np.mean(valid_days))

        logger.info(
            "Triple barrier etiketleme tamamlandı.",
            ticker=ticker,
            total=len(results),
            positive=stats.get("positive_rate", 0.0),
            negative=stats.get("negative_rate", 0.0),
            neutral=stats.get("neutral_rate", 0.0),
        )

        return TripleBarrierLabels(
            ticker=ticker,
            labels=labels_arr,
            returns=returns_arr,
            days_held=days_arr,
            results=results,
            stats=stats,
        )


class MetaLabeler:
    """Meta-labeling motoru — birincil model tahminlerini filtreler.

    Birincil modelin ürettiği sinyalleri gerçek triple barrier sonuçlarıyla
    karşılaştırarak ikincil bir model için eğitim seti oluşturur.
    Meta-model, hangi sinyallerin "güvenilir" olduğunu öğrenir.

    Referans: López de Prado (2018), Bölüm 3.
    """

    def __repr__(self) -> str:
        """MetaLabeler kısa temsili."""
        return "MetaLabeler()"

    def generate_meta_labels(
        self,
        ticker: str,
        primary_labels: np.ndarray,
        triple_barrier_labels: np.ndarray,
        primary_confidence: np.ndarray | None = None,
    ) -> MetaLabelResult:
        """Birincil model tahminleri için meta-etiketleri üretir.

        Meta-label = 1 ise birincil modeli destekle (pozisyon aç).
        Meta-label = 0 ise birincil modeli reddet (pozisyon açma).

        Args:
            ticker: Hisse senedi kodu.
            primary_labels: Birincil modelin tahminleri (+1, -1, 0).
            triple_barrier_labels: Gerçek triple barrier etiketleri (+1, -1, 0).
            primary_confidence: Opsiyonel güven skorları (0-1). Yoksa 0.5 varsayılır.

        Returns:
            Meta-etiketler ve pozisyon büyüklüklerini içeren MetaLabelResult.

        Raises:
            ValueError: Dizi uzunlukları uyuşmuyorsa.
        """
        n = len(primary_labels)
        if len(triple_barrier_labels) != n:
            raise ValueError(
                f"primary_labels ({n}) ve triple_barrier_labels "
                f"({len(triple_barrier_labels)}) boyutları eşleşmelidir.",
            )

        if primary_confidence is None:
            confidence = np.full(n, 0.5)
        else:
            if len(primary_confidence) != n:
                raise ValueError(
                    f"primary_confidence ({len(primary_confidence)}) boyutu {n} olmalıdır.",
                )
            confidence = np.clip(np.array(primary_confidence, dtype=float), 0.0, 1.0)

        meta_labels = np.full(n, np.nan)
        position_sizes = np.full(n, np.nan)

        for i in range(n):
            p = primary_labels[i]
            t = triple_barrier_labels[i]

            if np.isnan(p) or np.isnan(t):
                continue
            if p == 0:
                # Birincil model nötr — meta-label üretme
                continue

            # Meta-label: birincil model ile gerçek yön aynı mı?
            # +1: yön doğru (pozisyon aç), 0: yön yanlış (geç)
            meta = 1.0 if (int(p) == int(t) and int(t) != 0) else 0.0
            meta_labels[i] = meta

            # Pozisyon büyüklüğü: meta=1 ise güven skoru kadar, meta=0 ise 0
            position_sizes[i] = float(confidence[i]) if meta == 1.0 else 0.0

        valid_meta = meta_labels[~np.isnan(meta_labels)]
        accuracy = float(np.mean(valid_meta)) if len(valid_meta) > 0 else 0.0

        logger.info(
            "Meta-labeling tamamlandı.",
            ticker=ticker,
            total=int(np.sum(~np.isnan(meta_labels))),
            accuracy=round(accuracy, 4),
        )

        return MetaLabelResult(
            ticker=ticker,
            meta_labels=meta_labels,
            position_sizes=position_sizes,
            primary_labels=primary_labels.copy(),
            confidence_scores=confidence,
        )


__all__: list[str] = [
    "BarrierHit",
    "MetaLabelResult",
    "MetaLabeler",
    "TripleBarrierLabeler",
    "TripleBarrierLabels",
    "TripleBarrierResult",
    "meta_labeler",
    "triple_barrier_labeler",
]

# Singletonlar
triple_barrier_labeler = TripleBarrierLabeler()
meta_labeler = MetaLabeler()
