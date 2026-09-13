"""
ALPHA BIST — Piyasa Duygu Toplayıcı (Sentiment Aggregator)

Put/call oranı, yabancı yatırımcı net alımları, kısa satış oranı ve
short interest gibi piyasa katılımcı duygu göstergelerini bütünleşik
bir duygu skoru altında toplar.

BIST'e Özgü Göstergeler:
  - Yabancı yatırımcı net alım/satım akışları (BDDK/MKK verileri)
  - BIST100 P/E ve F/K oranı değerleme bandı
  - Short interest ratio (borsa'da kısa satış oranı)
  - VIOP'ta put/call ratio (türev piyasası duygu sinyali)
  - BİST'e özgü TCMB faiz kararı sonrası duygu şokları
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_SMOOTHING_WINDOW: int = 5
DEFAULT_Z_WINDOW: int = 60           # Z-skoru baseline penceresi
DEFAULT_EXTREME_BULL: float = 0.80   # Aşırı iyimserlik eşiği
DEFAULT_EXTREME_BEAR: float = 0.20   # Aşırı kötümserlik eşiği
DEFAULT_CONTRARIAN_SIGNAL: bool = True  # Aşırı uçlarda zıt sinyal üret


@dataclass
class SentimentReading:
    """Tek çubuk için duygu okuması.

    Attributes:
        composite_score: Bileşik duygu skoru (0=aşırı kötümser, 1=aşırı iyimser).
        put_call_score: Put/call oranından türetilen duygu skoru.
        foreign_flow_score: Yabancı yatırımcı akış skoru.
        short_interest_score: Kısa satış oranı skoru.
        valuation_score: Değerleme bandı skoru.
        is_extreme_bull: Aşırı iyimserlik bayrağı.
        is_extreme_bear: Aşırı kötümserlik bayrağı.
        contrarian_signal: +1 (al sinyali: aşırı kötümserlik), -1 (sat: aşırı iyimserlik), 0 (nötr).
    """

    composite_score: float
    put_call_score: float
    foreign_flow_score: float
    short_interest_score: float
    valuation_score: float
    is_extreme_bull: bool
    is_extreme_bear: bool
    contrarian_signal: int

    def __repr__(self) -> str:
        """SentimentReading kısa temsili."""
        if self.is_extreme_bull:
            extreme = "EXTREME_BULL⚠️"
        elif self.is_extreme_bear:
            extreme = "EXTREME_BEAR⚠️"
        else:
            extreme = "NORMAL"
        return f"SentimentReading(score={self.composite_score:.2f}, {extreme})"


@dataclass
class SentimentAggregatorResult:
    """Sentiment aggregator tam sonucu.

    Attributes:
        composite_scores: Bileşik duygu skoru dizisi (0-1).
        put_call_scores: Put/call skor dizisi.
        foreign_flow_scores: Yabancı akış skor dizisi.
        short_interest_scores: Kısa satış skor dizisi.
        valuation_scores: Değerleme skor dizisi.
        extreme_bull_flags: Aşırı iyimserlik bayrak dizisi.
        extreme_bear_flags: Aşırı kötümserlik bayrak dizisi.
        contrarian_signals: Zıt sinyal dizisi (+1/-1/0).
        stats: Özet istatistikler.
    """

    composite_scores: np.ndarray
    put_call_scores: np.ndarray
    foreign_flow_scores: np.ndarray
    short_interest_scores: np.ndarray
    valuation_scores: np.ndarray
    extreme_bull_flags: np.ndarray
    extreme_bear_flags: np.ndarray
    contrarian_signals: np.ndarray
    stats: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """SentimentAggregatorResult kısa temsili."""
        valid = int(np.sum(~np.isnan(self.composite_scores)))
        ext_bull = int(np.nansum(self.extreme_bull_flags))
        ext_bear = int(np.nansum(self.extreme_bear_flags))
        return (
            f"SentimentAggregatorResult(valid={valid}, "
            f"extreme_bull={ext_bull}, extreme_bear={ext_bear})"
        )

    def latest(self) -> SentimentReading | None:
        """En son geçerli duygu okumasını döndürür.

        Returns:
            Son SentimentReading veya None (veri yoksa).
        """
        for i in range(len(self.composite_scores) - 1, -1, -1):
            if not np.isnan(self.composite_scores[i]):
                return SentimentReading(
                    composite_score=float(self.composite_scores[i]),
                    put_call_score=float(self.put_call_scores[i]),
                    foreign_flow_score=float(self.foreign_flow_scores[i]),
                    short_interest_score=float(self.short_interest_scores[i]),
                    valuation_score=float(self.valuation_scores[i]),
                    is_extreme_bull=bool(self.extreme_bull_flags[i]),
                    is_extreme_bear=bool(self.extreme_bear_flags[i]),
                    contrarian_signal=int(self.contrarian_signals[i]),
                )
        return None


class SentimentAggregator:
    """Çoklu duygu göstergelerini bütünleşik skor altında toplayan motor.

    Her gösterge 0-1 arasında normalize edilir ve ağırlıklı ortalamayla
    bileşik skor oluşturulur. Aşırı uçlarda contrarian (zıt) sinyal üretilir:
    - Aşırı iyimserlik (score > 0.80) → sat sinyali (kontraryen)
    - Aşırı kötümserlik (score < 0.20) → al sinyali (kontraryen)
    """

    def __init__(
        self,
        smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
        z_window: int = DEFAULT_Z_WINDOW,
        extreme_bull: float = DEFAULT_EXTREME_BULL,
        extreme_bear: float = DEFAULT_EXTREME_BEAR,
        contrarian: bool = DEFAULT_CONTRARIAN_SIGNAL,
        put_call_weight: float = 0.30,
        foreign_flow_weight: float = 0.35,
        short_interest_weight: float = 0.20,
        valuation_weight: float = 0.15,
    ) -> None:
        """SentimentAggregator başlatıcı.

        Args:
            smoothing_window: Bileşik skor yumuşatma penceresi.
            z_window: Normalize etmek için baseline Z-skor penceresi.
            extreme_bull: Aşırı iyimserlik eşiği (0-1).
            extreme_bear: Aşırı kötümserlik eşiği (0-1).
            contrarian: True ise aşırı uçlarda zıt sinyal üret.
            put_call_weight: Put/call gösterge ağırlığı.
            foreign_flow_weight: Yabancı akış ağırlığı.
            short_interest_weight: Kısa satış oranı ağırlığı.
            valuation_weight: Değerleme ağırlığı.

        Raises:
            ValueError: Ağırlıklar toplamı 1.0 değilse.
        """
        total_w = put_call_weight + foreign_flow_weight + short_interest_weight + valuation_weight
        if abs(total_w - 1.0) > 0.01:
            raise ValueError(f"Ağırlıklar toplamı 1.0 olmalıdır: {total_w:.2f}")
        if not (0.0 < extreme_bear < extreme_bull < 1.0):
            raise ValueError("extreme_bear < extreme_bull koşulu sağlanmalıdır.")

        self.smoothing_window = smoothing_window
        self.z_window = z_window
        self.extreme_bull = extreme_bull
        self.extreme_bear = extreme_bear
        self.contrarian = contrarian
        self.weights = {
            "put_call": put_call_weight,
            "foreign_flow": foreign_flow_weight,
            "short_interest": short_interest_weight,
            "valuation": valuation_weight,
        }

    def __repr__(self) -> str:
        """SentimentAggregator kısa temsili."""
        return (
            f"SentimentAggregator(extreme_bull={self.extreme_bull}, "
            f"extreme_bear={self.extreme_bear}, contrarian={self.contrarian})"
        )

    def _normalize_to_score(self, series: np.ndarray, invert: bool = False) -> np.ndarray:
        """Bir seriyi 0-1 arasında normalize eder (min-max normalizasyonu).

        Args:
            series: Normalize edilecek seri.
            invert: True ise yüksek değer = düşük skor (örn. yüksek P/C ratio = düşük iyimserlik).

        Returns:
            0-1 arasında normalize edilmiş dizi (NaN korunur).
        """
        valid_mask = ~np.isnan(series)
        if int(np.sum(valid_mask)) < 2:
            return np.full(len(series), 0.5)

        valid = series[valid_mask]
        min_val = float(np.min(valid))
        max_val = float(np.max(valid))

        result = np.full(len(series), np.nan)
        if max_val > min_val:
            result[valid_mask] = (valid - min_val) / (max_val - min_val)
        else:
            result[valid_mask] = 0.5

        if invert:
            result = 1.0 - result

        return result

    def _smooth(self, series: np.ndarray, window: int) -> np.ndarray:
        """Hareketli ortalama ile yumuşatır.

        Args:
            series: Yumuşatılacak seri.
            window: Hareketli ortalama penceresi.

        Returns:
            Yumuşatılmış dizi (NaN korunur).
        """
        smoothed = np.full(len(series), np.nan)
        for i in range(window - 1, len(series)):
            chunk = series[i - window + 1 : i + 1]
            valid = chunk[~np.isnan(chunk)]
            if len(valid) > 0:
                smoothed[i] = float(np.mean(valid))
        return smoothed

    def aggregate(
        self,
        put_call_ratio: np.ndarray | None = None,
        foreign_flow_net: np.ndarray | None = None,
        short_interest_ratio: np.ndarray | None = None,
        pe_ratio: np.ndarray | None = None,
        n: int = 0,
    ) -> SentimentAggregatorResult:
        """Çoklu duygu göstergelerini birleştirerek bileşik skor üretir.

        En az bir gösterge sağlanmalıdır. Eksik göstergeler 0.5 (nötr) ile doldurulur.

        Args:
            put_call_ratio: Put/Call oranı dizisi (yüksek = daha kötümser).
            foreign_flow_net: Yabancı yatırımcı net alım/satım (pozitif = net alım).
            short_interest_ratio: Kısa satış oranı (0-1, yüksek = daha kötümser).
            pe_ratio: F/K oranı dizisi (yüksek = pahalı = negatif duygu).
            n: Dizi uzunluğu. None verilirse sağlanan dizilerden çıkarılır.

        Returns:
            Bileşik duygu skoru ve sinyal dizilerini içeren SentimentAggregatorResult.

        Raises:
            ValueError: Hiç gösterge sağlanmamışsa veya uzunluklar uyuşmuyorsa.
        """
        provided = [a for a in [put_call_ratio, foreign_flow_net, short_interest_ratio, pe_ratio] if a is not None]
        if not provided:
            raise ValueError("En az bir duygu göstergesi sağlanmalıdır.")

        # Boyut belirleme
        lengths = [len(a) for a in provided]
        if len(set(lengths)) > 1:
            raise ValueError(f"Tüm diziler aynı boyutta olmalıdır: {lengths}")
        n = lengths[0]

        # Her göstergeyi skora dönüştür (yüksek iyimserlik = yüksek skor)
        if put_call_ratio is not None:
            pc_score = self._normalize_to_score(put_call_ratio, invert=True)  # Yüksek PC = kötümser
        else:
            pc_score = np.full(n, 0.5)

        if foreign_flow_net is not None:
            ff_score = self._normalize_to_score(foreign_flow_net, invert=False)  # Yüksek net alım = iyimser
        else:
            ff_score = np.full(n, 0.5)

        if short_interest_ratio is not None:
            si_score = self._normalize_to_score(short_interest_ratio, invert=True)  # Yüksek SI = kötümser
        else:
            si_score = np.full(n, 0.5)

        if pe_ratio is not None:
            val_score = self._normalize_to_score(pe_ratio, invert=True)  # Yüksek F/K = pahalı = negatif
        else:
            val_score = np.full(n, 0.5)

        # Bileşik skor
        composite = (
            self.weights["put_call"] * pc_score
            + self.weights["foreign_flow"] * ff_score
            + self.weights["short_interest"] * si_score
            + self.weights["valuation"] * val_score
        )

        # Yumuşat
        composite = self._smooth(composite, self.smoothing_window)

        # Aşırı uç tespiti
        extreme_bull = composite >= self.extreme_bull
        extreme_bear = composite <= self.extreme_bear

        # Zıt sinyal
        contrarian_signals = np.zeros(n, dtype=int)
        if self.contrarian:
            contrarian_signals[extreme_bull] = -1   # Aşırı iyimser = sat sinyali
            contrarian_signals[extreme_bear] = 1    # Aşırı kötümser = al sinyali

        # İstatistikler
        valid_comp = composite[~np.isnan(composite)]
        stats: dict[str, float] = {}
        if len(valid_comp) > 0:
            stats["mean_score"] = float(np.mean(valid_comp))
            stats["extreme_bull_rate"] = float(np.nanmean(extreme_bull))
            stats["extreme_bear_rate"] = float(np.nanmean(extreme_bear))
            stats["contrarian_buy_signals"] = float(np.sum(contrarian_signals == 1))
            stats["contrarian_sell_signals"] = float(np.sum(contrarian_signals == -1))

        logger.info(
            "Duygu toplayıcı tamamlandı.",
            valid=len(valid_comp),
            ext_bull=stats.get("extreme_bull_rate", 0.0),
            ext_bear=stats.get("extreme_bear_rate", 0.0),
        )

        return SentimentAggregatorResult(
            composite_scores=composite,
            put_call_scores=pc_score,
            foreign_flow_scores=ff_score,
            short_interest_scores=si_score,
            valuation_scores=val_score,
            extreme_bull_flags=extreme_bull,
            extreme_bear_flags=extreme_bear,
            contrarian_signals=contrarian_signals,
            stats=stats,
        )


__all__: list[str] = [
    "SentimentAggregator",
    "SentimentAggregatorResult",
    "SentimentReading",
    "sentiment_aggregator",
]

# Singleton
sentiment_aggregator = SentimentAggregator()
