"""
ALPHA BIST — Duygu (Sentiment) Feature Mühendisliği

BIST'e özgü çok kaynaklı piyasa duygu ölçümü. Haber sentiment analizi,
sosyal medya sinyalleri, yabancı yatırımcı akışları ve teknik momentum
bileşenlerini birleştirerek bileşik duygu feature'ları üretir.

Özellikler:
  - Put/Call oranı bazlı opsiyoncu duygusu
  - Yabancı yatırımcı akış trendi (BIST yabancı istatistikleri proxy)
  - Haber skoru öğrenme penceresi (news decay — eski haberler azalır)
  - Teknik momentum sentiment (RSI + MACD + CCI bileşik skoru)
  - Aşırı satın alınma/satılma (overbought/oversold) tespiti
  - Contrarian sinyal üretimi (aşırı duygu dönüş sinyali)
  - Piyasa genişlik (breadth) sentiment proxy
  - Point-in-Time (PIT) uyumu: gelecekten veri sızıntısı yoktur
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_WINDOW: int = 20
RSI_OVERBOUGHT: float = 70.0
RSI_OVERSOLD: float = 30.0
EXTREME_BULL_THRESHOLD: float = 0.80  # Bileşik skor üzeri = aşırı iyimser
EXTREME_BEAR_THRESHOLD: float = 0.20  # Bileşik skor altı = aşırı kötümser
EWM_SPAN_SHORT: int = 5
EWM_SPAN_LONG: int = 20
DECAY_HALFLIFE: float = 5.0  # Haber etkisinin yarı ömrü (gün)


@dataclass
class SentimentFeatureVector:
    """Tek günlük duygu feature vektörü.

    Attributes:
        rsi_sentiment: RSI bazlı duygu skoru (0=aşırı satış → 1=aşırı alış).
        macd_sentiment: MACD histogram işareti ve şiddetinden türetilen skor (0-1).
        cci_sentiment: CCI bazlı duygu skoru (0-1).
        put_call_sentiment: P/C oranından türetilen duygu (yüksek P/C = korku = düşük skor).
        foreign_flow_sentiment: Yabancı yatırımcı net alımı trendi (0-1).
        breadth_sentiment: Piyasa genişlik skoru (yükselen/toplam hisse oranı proxy).
        news_sentiment: Ağırlıklı haber skoru (üssel azalan ağırlık).
        composite_sentiment: Tüm bileşenlerin ağırlıklı ortalaması (0-1).
        is_extreme_bull: Bileşik skor aşırı iyimser eşiğini aştı mı?
        is_extreme_bear: Bileşik skor aşırı kötümser eşiğinin altına düştü mü?
        contrarian_signal: Aşırı duygu tersine döndüğünde üretilen sinyal (-1/0/+1).
    """

    rsi_sentiment: float = float("nan")
    macd_sentiment: float = float("nan")
    cci_sentiment: float = float("nan")
    put_call_sentiment: float = float("nan")
    foreign_flow_sentiment: float = float("nan")
    breadth_sentiment: float = float("nan")
    news_sentiment: float = float("nan")
    composite_sentiment: float = float("nan")
    is_extreme_bull: bool = False
    is_extreme_bear: bool = False
    contrarian_signal: int = 0
    extra: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """SentimentFeatureVector kısa temsili."""
        signal_str = {-1: "SELL↓", 0: "NÖTR", 1: "BUY↑"}.get(self.contrarian_signal, "?")
        return (
            f"SentimentFeatureVector("
            f"composite={self.composite_sentiment:.3f}, "
            f"contrarian={signal_str}, "
            f"extreme_bull={self.is_extreme_bull}, "
            f"extreme_bear={self.is_extreme_bear})"
        )

    def to_dict(self) -> dict[str, float]:
        """Tüm feature'ları sözlük olarak döndürür.

        Returns:
            {feature_name: value} sözlüğü.
        """
        return {
            "rsi_sentiment": self.rsi_sentiment,
            "macd_sentiment": self.macd_sentiment,
            "cci_sentiment": self.cci_sentiment,
            "put_call_sentiment": self.put_call_sentiment,
            "foreign_flow_sentiment": self.foreign_flow_sentiment,
            "breadth_sentiment": self.breadth_sentiment,
            "news_sentiment": self.news_sentiment,
            "composite_sentiment": self.composite_sentiment,
            "contrarian_signal": float(self.contrarian_signal),
            "is_extreme_bull": float(self.is_extreme_bull),
            "is_extreme_bear": float(self.is_extreme_bear),
            **self.extra,
        }


class TechnicalSentimentCalculator:
    """Teknik indikatörlerden duygu skoru hesaplar.

    RSI, MACD ve CCI'dan normalize edilmiş 0-1 duygu skorları türetir.
    Yüksek = yükselen baskı/iyimserlik, düşük = düşen baskı/kötümserlik.
    """

    def __repr__(self) -> str:
        """TechnicalSentimentCalculator kısa temsili."""
        return "TechnicalSentimentCalculator(RSI+MACD+CCI)"

    @staticmethod
    def rsi_sentiment(close: np.ndarray, window: int = 14) -> np.ndarray:
        """RSI bazlı duygu skoru hesaplar.

        RSI değerini [0,100] → [0,1] aralığına normalleştirir.
        RSI > 70: aşırı alım (0.7+), RSI < 30: aşırı satım (0.3-)

        Args:
            close: Kapanış fiyatları.
            window: RSI periyodu.

        Returns:
            0-1 arası duygu skoru dizisi.
        """
        n = len(close)
        result = np.full(n, np.nan)
        if n < window + 1:
            return result

        delta = np.diff(close, prepend=np.nan)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)

        # Wilder smoothing
        avg_gain = np.full(n, np.nan)
        avg_loss = np.full(n, np.nan)
        avg_gain[window] = float(np.mean(gain[1 : window + 1]))
        avg_loss[window] = float(np.mean(loss[1 : window + 1]))

        for i in range(window + 1, n):
            avg_gain[i] = (avg_gain[i - 1] * (window - 1) + gain[i]) / window
            avg_loss[i] = (avg_loss[i - 1] * (window - 1) + loss[i]) / window

        with np.errstate(invalid="ignore", divide="ignore"):
            rs = np.where(avg_loss > 0, avg_gain / avg_loss, np.inf)
            rsi = 100.0 - (100.0 / (1.0 + rs))

        result = np.where(np.isnan(avg_gain), np.nan, rsi / 100.0)
        return result

    @staticmethod
    def macd_sentiment(
        close: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> np.ndarray:
        """MACD histogram bazlı duygu skoru hesaplar.

        Histogram işaretini ve normalleştirilmiş şiddetini 0-1 aralığına çevirir.
        Pozitif histogram → skor > 0.5, negatif histogram → skor < 0.5.

        Args:
            close: Kapanış fiyatları.
            fast: Hızlı EMA periyodu.
            slow: Yavaş EMA periyodu.
            signal: Sinyal EMA periyodu.

        Returns:
            0-1 arası MACD duygu skoru dizisi.
        """
        n = len(close)
        if n < slow + signal:
            return np.full(n, np.nan)

        # EWM hesaplama
        def ewm(arr: np.ndarray, span: int) -> np.ndarray:
            alpha = 2.0 / (span + 1)
            out = np.full(len(arr), np.nan)
            for i in range(len(arr)):
                if np.isnan(arr[i]):
                    continue
                if np.isnan(out[i - 1]) if i > 0 else True:
                    out[i] = arr[i]
                else:
                    out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
            return out

        ema_fast = ewm(close, fast)
        ema_slow = ewm(close, slow)
        macd_line = ema_fast - ema_slow
        signal_line = ewm(macd_line, signal)
        histogram = macd_line - signal_line

        # Normalize: rolling standardize → sigmoid
        result = np.full(n, np.nan)
        window_std = 20
        for i in range(window_std, n):
            h = histogram[i - window_std : i + 1]
            valid = h[~np.isnan(h)]
            if len(valid) < 5:
                continue
            std = float(np.std(valid))
            if std < 1e-10:
                result[i] = 0.5
                continue
            z = float(histogram[i]) / std
            result[i] = float(1.0 / (1.0 + np.exp(-z)))  # sigmoid

        return result

    @staticmethod
    def cci_sentiment(
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        window: int = 20,
    ) -> np.ndarray:
        """CCI (Commodity Channel Index) bazlı duygu skoru hesaplar.

        CCI [-200, +200] aralığını [0,1] aralığına çevirir.
        CCI > +100 = aşırı alım = yüksek skor, CCI < -100 = aşırı satım = düşük skor.

        Args:
            high: Günlük yüksek fiyatlar.
            low: Günlük düşük fiyatlar.
            close: Kapanış fiyatları.
            window: CCI periyodu.

        Returns:
            0-1 arası CCI duygu skoru dizisi.
        """
        n = len(close)
        result = np.full(n, np.nan)
        if n < window:
            return result

        tp = (high + low + close) / 3.0

        for i in range(window - 1, n):
            w = tp[i - window + 1 : i + 1]
            mean_tp = float(np.mean(w))
            mad = float(np.mean(np.abs(w - mean_tp)))
            if mad < 1e-10:
                result[i] = 0.5
                continue
            cci = (tp[i] - mean_tp) / (0.015 * mad)
            # CCI [-200, +200] → [0, 1]
            normalized = (cci + 200.0) / 400.0
            result[i] = float(np.clip(normalized, 0.0, 1.0))

        return result


class FlowSentimentCalculator:
    """Akış (flow) bazlı duygu hesaplama.

    Put/Call oranı ve yabancı yatırımcı akışlarından duygu tüketirir.
    """

    def __repr__(self) -> str:
        """FlowSentimentCalculator kısa temsili."""
        return "FlowSentimentCalculator(PC-ratio + Foreign-flow)"

    @staticmethod
    def put_call_sentiment(
        put_call_ratio: np.ndarray,
        window: int = DEFAULT_WINDOW,
    ) -> np.ndarray:
        """Put/Call oranından contrarian duygu skoru hesaplar.

        Yüksek P/C oranı = piyasa korkusu = contrarian BUY sinyali.
        Düşük P/C oranı = aşırı iyimserlik = contrarian SELL sinyali.
        Normalleştirme: Z-skor tabanlı, [0,1] aralığına çevirilir.

        Args:
            put_call_ratio: Günlük put/call oranları.
            window: Normalleştirme penceresi.

        Returns:
            0-1 arası contrarian duygu skoru (yüksek P/C → yüksek skor = alım fırsatı).
        """
        n = len(put_call_ratio)
        result = np.full(n, np.nan)

        for i in range(window - 1, n):
            w = put_call_ratio[i - window + 1 : i + 1]
            valid = w[~np.isnan(w)]
            if len(valid) < 5:
                continue
            mean = float(np.mean(valid))
            std = float(np.std(valid))
            if std < 1e-10:
                result[i] = 0.5
                continue
            z = (float(put_call_ratio[i]) - mean) / std
            # Yüksek P/C (korku) → contrarian bull → yüksek skor
            result[i] = float(np.clip(0.5 + z * 0.15, 0.0, 1.0))

        return result

    @staticmethod
    def foreign_flow_sentiment(
        net_foreign_flow: np.ndarray,
        window: int = DEFAULT_WINDOW,
    ) -> np.ndarray:
        """Yabancı yatırımcı net akış trendinden duygu hesaplar.

        Pozitif net akış (yabancı alımı) = yükselen ilgi = yüksek skor.
        Normalleştirme: EWM trend + Z-skor.

        Args:
            net_foreign_flow: Günlük net yabancı akışı (pozitif = net alım).
            window: Normalleştirme penceresi.

        Returns:
            0-1 arası yabancı akış duygu skoru.
        """
        n = len(net_foreign_flow)
        result = np.full(n, np.nan)

        # EWM trend
        alpha = 2.0 / (window + 1)
        ewm_trend = np.full(n, np.nan)
        for i in range(n):
            val = net_foreign_flow[i]
            if np.isnan(val):
                continue
            if np.isnan(ewm_trend[i - 1]) if i > 0 else True:
                ewm_trend[i] = val
            else:
                ewm_trend[i] = alpha * val + (1 - alpha) * ewm_trend[i - 1]

        for i in range(window - 1, n):
            w = ewm_trend[i - window + 1 : i + 1]
            valid = w[~np.isnan(w)]
            if len(valid) < 5:
                continue
            mean = float(np.mean(valid))
            std = float(np.std(valid))
            if std < 1e-10:
                result[i] = 0.5
                continue
            z = (float(ewm_trend[i]) - mean) / std
            result[i] = float(np.clip(0.5 + z * 0.25, 0.0, 1.0))

        return result


class NewsSentimentCalculator:
    """Haber duygu feature'ları hesaplama.

    Her günün haber skoru üssel azalan (exponential decay) ağırlık ile
    sonraki günlere yansıtılır. Bu sayede eski haberler kademeli etkisini kaybeder.
    """

    def __init__(self, halflife: float = DECAY_HALFLIFE) -> None:
        """NewsSentimentCalculator başlatıcı.

        Args:
            halflife: Haber etkisinin yarı ömrü (gün). Daha küçük = daha hızlı azalma.
        """
        self.halflife = halflife
        self.decay_rate = np.log(2.0) / halflife

    def __repr__(self) -> str:
        """NewsSentimentCalculator kısa temsili."""
        return f"NewsSentimentCalculator(halflife={self.halflife}d)"

    def apply_decay(
        self,
        raw_scores: np.ndarray,
        window: int = DEFAULT_WINDOW,
    ) -> np.ndarray:
        """Ham haber skorlarına üssel azalma ağırlığı uygular.

        Args:
            raw_scores: Günlük ham haber skoru dizisi (0-1 normalleştirilmiş).
            window: Ağırlıklandırma penceresi.

        Returns:
            Decay uygulanmış haber duygu dizisi.
        """
        n = len(raw_scores)
        result = np.full(n, np.nan)

        decay_weights = np.array([np.exp(-self.decay_rate * i) for i in range(window)])
        decay_weights /= decay_weights.sum()

        for i in range(window - 1, n):
            w = raw_scores[i - window + 1 : i + 1][::-1]  # En yeniden eskiye
            valid_mask = ~np.isnan(w)
            if valid_mask.sum() < 3:
                continue
            weighted_sum = float(np.dot(w[valid_mask], decay_weights[valid_mask]))
            weight_total = float(np.sum(decay_weights[valid_mask]))
            if weight_total > 1e-10:
                result[i] = weighted_sum / weight_total

        return result


class SentimentFeatureEngine:
    """Ana duygu feature hesaplama motoru (thread-safe).

    Tüm duygu bileşenlerini birleştirerek bileşik sentiment feature vektörü üretir.
    """

    # Bileşik skor ağırlıkları
    WEIGHTS: dict[str, float] = {
        "rsi": 0.15,
        "macd": 0.15,
        "cci": 0.10,
        "put_call": 0.20,
        "foreign": 0.20,
        "breadth": 0.10,
        "news": 0.10,
    }

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        """SentimentFeatureEngine başlatıcı.

        Args:
            window: Pencere boyutu.

        Raises:
            ValueError: window < 2 ise.
        """
        if window < 2:
            raise ValueError(f"window >= 2 olmalıdır: {window}")

        self.window = window
        self._tech = TechnicalSentimentCalculator()
        self._flow = FlowSentimentCalculator()
        self._news = NewsSentimentCalculator()
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """SentimentFeatureEngine kısa temsili."""
        return f"SentimentFeatureEngine(window={self.window}, weights={self.WEIGHTS})"

    @staticmethod
    def _breadth_sentiment(
        advancing: np.ndarray,
        total: np.ndarray,
        window: int = DEFAULT_WINDOW,
    ) -> np.ndarray:
        """Piyasa genişlik duygu skoru (yükselen hisse oranı).

        Args:
            advancing: Günlük yükselen hisse sayısı.
            total: Toplam işlem gören hisse sayısı.
            window: EWM penceresi.

        Returns:
            0-1 arası piyasa genişlik duygu skoru.
        """
        n = len(advancing)
        if len(total) != n:
            return np.full(n, np.nan)

        raw = np.where(total > 0, advancing / np.maximum(total, 1.0), np.nan)
        alpha = 2.0 / (window + 1)
        result = np.full(n, np.nan)

        for i in range(n):
            if np.isnan(raw[i]):
                continue
            prev = result[i - 1] if i > 0 and not np.isnan(result[i - 1]) else raw[i]
            result[i] = alpha * raw[i] + (1 - alpha) * prev

        return result

    def compute_all(
        self,
        close: np.ndarray,
        high: np.ndarray | None = None,
        low: np.ndarray | None = None,
        put_call_ratio: np.ndarray | None = None,
        net_foreign_flow: np.ndarray | None = None,
        news_scores: np.ndarray | None = None,
        advancing_issues: np.ndarray | None = None,
        total_issues: np.ndarray | None = None,
    ) -> list[SentimentFeatureVector]:
        """Tüm duygu feature'larını hesaplar.

        Args:
            close: Kapanış fiyatları.
            high: Günlük yüksek fiyatlar (None ise close kullanılır).
            low: Günlük düşük fiyatlar (None ise close kullanılır).
            put_call_ratio: P/C oranı (None ise 1.0 nötr proxy kullanılır).
            net_foreign_flow: Net yabancı akışı (None ise 0 nötr proxy).
            news_scores: Ham haber skorları 0-1 (None ise 0.5 nötr).
            advancing_issues: Yükselen hisse sayısı (None ise tahmin yok).
            total_issues: Toplam işlem gören hisse sayısı.

        Returns:
            Her gün için SentimentFeatureVector listesi.
        """
        n = len(close)
        h = high if high is not None else close
        l = low if low is not None else close
        if not (len(h) == len(l) == n):
            raise ValueError("close, high, low uzunlukları eşleşmeli.")

        with self._lock:
            # Proxy dizileri
            pc_ratio = put_call_ratio if put_call_ratio is not None else np.ones(n)
            foreign = net_foreign_flow if net_foreign_flow is not None else np.zeros(n)
            news = news_scores if news_scores is not None else np.full(n, 0.5)
            adv = advancing_issues if advancing_issues is not None else np.full(n, np.nan)
            total = total_issues if total_issues is not None else np.full(n, np.nan)

            # Teknik sentiment
            rsi_arr = self._tech.rsi_sentiment(close)
            macd_arr = self._tech.macd_sentiment(close)
            cci_arr = self._tech.cci_sentiment(h, l, close, self.window)

            # Akış sentiment
            pc_arr = self._flow.put_call_sentiment(pc_ratio, self.window)
            ff_arr = self._flow.foreign_flow_sentiment(foreign, self.window)

            # Genişlik sentiment
            if not np.any(np.isnan(adv)):
                breadth_arr = self._breadth_sentiment(adv, total, self.window)
            else:
                breadth_arr = np.full(n, np.nan)

            # Haber sentiment (decay)
            news_arr = self._news.apply_decay(news, self.window)

            features: list[SentimentFeatureVector] = []
            for i in range(n):
                # Bileşik skor — mevcut bileşenlerin ağırlıklı ortalaması
                components: dict[str, float] = {}
                if not np.isnan(rsi_arr[i]):
                    components["rsi"] = float(rsi_arr[i])
                if not np.isnan(macd_arr[i]):
                    components["macd"] = float(macd_arr[i])
                if not np.isnan(cci_arr[i]):
                    components["cci"] = float(cci_arr[i])
                if not np.isnan(pc_arr[i]):
                    components["put_call"] = float(pc_arr[i])
                if not np.isnan(ff_arr[i]):
                    components["foreign"] = float(ff_arr[i])
                if not np.isnan(breadth_arr[i]):
                    components["breadth"] = float(breadth_arr[i])
                if not np.isnan(news_arr[i]):
                    components["news"] = float(news_arr[i])

                composite = float("nan")
                if components:
                    total_w = sum(self.WEIGHTS.get(k, 0.1) for k in components)
                    weighted_sum = sum(v * self.WEIGHTS.get(k, 0.1) for k, v in components.items())
                    composite = weighted_sum / max(total_w, 1e-10)

                is_bull = composite > EXTREME_BULL_THRESHOLD if not np.isnan(composite) else False
                is_bear = composite < EXTREME_BEAR_THRESHOLD if not np.isnan(composite) else False

                # Contrarian sinyal: aşırı durumun tersi yönünde alım/satım
                contrarian = 0
                if is_bear:
                    contrarian = 1    # Aşırı kötümserlik → alım sinyali
                elif is_bull:
                    contrarian = -1   # Aşırı iyimserlik → satım sinyali

                features.append(SentimentFeatureVector(
                    rsi_sentiment=float(rsi_arr[i]),
                    macd_sentiment=float(macd_arr[i]),
                    cci_sentiment=float(cci_arr[i]),
                    put_call_sentiment=float(pc_arr[i]),
                    foreign_flow_sentiment=float(ff_arr[i]),
                    breadth_sentiment=float(breadth_arr[i]) if not np.isnan(breadth_arr[i]) else float("nan"),
                    news_sentiment=float(news_arr[i]),
                    composite_sentiment=composite,
                    is_extreme_bull=is_bull,
                    is_extreme_bear=is_bear,
                    contrarian_signal=contrarian,
                ))

            # İstatistik log
            valid_composite = [f.composite_sentiment for f in features if not np.isnan(f.composite_sentiment)]
            extreme_bull_count = sum(1 for f in features if f.is_extreme_bull)
            extreme_bear_count = sum(1 for f in features if f.is_extreme_bear)

            logger.info(
                "Duygu feature hesaplandı.",
                n=n,
                valid_composite=len(valid_composite),
                mean_composite=round(float(np.mean(valid_composite)), 3) if valid_composite else None,
                extreme_bull=extreme_bull_count,
                extreme_bear=extreme_bear_count,
            )
            return features

    # API ergonomisi ve uyumluluk için aliaslar
    compute = compute_all
    compute_from_arrays = compute_all


__all__: list[str] = [
    "FlowSentimentCalculator",
    "NewsSentimentCalculator",
    "SentimentFeatureEngine",
    "SentimentFeatureVector",
    "TechnicalSentimentCalculator",
    "sentiment_engine",
]

# Singleton
sentiment_engine = SentimentFeatureEngine()
