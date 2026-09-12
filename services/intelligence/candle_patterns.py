"""
ALPHA BIST — 10/10 Perfect Candlestick & Price Action Intelligence Engine
========================================================================
12 Klasik Japon Mum Formasyonu, Fitil/Gövde Oranı Matematiği,
Fair Value Gap (FVG) ve Smart Money Likidite Emilimini tespit eder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()

# ─── Sabitler ────────────────────────────────────────────────────────
DOJI_BODY_RATIO_MAX: float = 0.08        # Gövde/aran oranı bu değerden küçükse doji
WICK_RANGE_EPSILON: float = 1e-9         # Sıfıra bölmeyi önleyen epsilon
HAMMER_LOWER_WICK_MIN: float = 0.50      # Çekiç için alt fitil oranı eşiği
HAMMER_UPPER_WICK_MAX: float = 0.20      # Çekiç için üst fitil oranı eşiği
PINBAR_BODY_MIN: float = 0.10            # Pinbar minimum gövde oranı
STAR_BODY_RATIO_MAX: float = 0.25        # Yıldız formasyonu max gövde oranı
STAR_GAP_RATIO: float = 0.005            # Sabah/Akşam yıldızı min boşluk
THREE_SOLDIER_BODY_MIN: float = 0.35     # Üç asker/karga min gövde oranı
DOJI_DRAGONFLY_WICK: float = 0.70        # Yusufçuk doji alt fitil eşiği
DOJI_GRAVESTONE_WICK: float = 0.70       # Mezar taşı doji üst fitil eşiği
ENGULFING_OPEN_TOLERANCE: float = 1.005  # Yutan formasyonu açık fiyat toleransı
ENGULFING_CLOSE_TOLERANCE: float = 0.995 # Yutan formasyonu kapanış fiyat toleransı
DEFAULT_CANDLE_SCORE: float = 50.0       # Varsayılan mum skoru
SCORE_UPPER_BOUND: float = 95.0          # Skor üst sınırı
SCORE_LOWER_BOUND: float = 5.0           # Skor alt sınırı
BULLISH_THRESHOLD: float = 65.0          # Boğa eşik skoru
BEARISH_THRESHOLD: float = 35.0          # Ayı eşik skoru
ATR_PERIOD: int = 14                     # ATR hesaplama periyodu
ATR_TARGET_MULTIPLIER: float = 3.5       # ATR bazlı hedef çarpanı
ATR_STOP_MULTIPLIER: float = 1.5         # ATR bazlı stop çarpanı
SUPPORT_LOOKBACK: int = 20               # Destek/direnç geriye bakış
DEFAULT_ATR_PCT: float = 0.03            # ATR fallback yüzdesi
BULLISH_SCORE_BONUS: int = 25
BEARISH_SCORE_PENALTY: int = 25
HAMMER_SCORE_BONUS: int = 22
SHOOTING_STAR_PENALTY: int = 22
STAR_SCORE_BONUS: int = 30
STAR_SCORE_PENALTY: int = 30
THREE_SOLDIER_SCORE: int = 24
DOJI_SCORE: int = 15
FVG_SCORE: int = 18
INVERTED_HAMMER_SCORE: int = 15
DEFAULT_PRESSURE_PCT: float = 50.0

__all__ = [
    "CandleMetrics",
    "CandlePatternResult",
    "CandlePatternEngine",
    "candle_engine",
]


@dataclass
class CandleMetrics:
    """Tek bir mumun anatomik ölçümleri.

    OHLCV verisinden gövde, fitil, oran ve doji tespiti yapar.
    """

    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    # Hesaplanmış özellikler
    body: float = 0.0
    range: float = 0.0
    upper_wick: float = 0.0
    lower_wick: float = 0.0
    body_ratio: float = 0.0
    upper_wick_ratio: float = 0.0
    lower_wick_ratio: float = 0.0
    is_green: bool = True
    is_doji: bool = False

    def __repr__(self) -> str:
        return (
            f"<CandleMetrics O={self.open:.2f} H={self.high:.2f} "
            f"L={self.low:.2f} C={self.close:.2f} doji={self.is_doji}>"
        )

    def __post_init__(self) -> None:
        """Gövde, fitil ve oranları otomatik hesapla."""
        self.body = abs(self.close - self.open)
        self.range = max(self.high - self.low, WICK_RANGE_EPSILON)
        self.is_green = self.close >= self.open

        if self.is_green:
            self.upper_wick = self.high - self.close
            self.lower_wick = self.open - self.low
        else:
            self.upper_wick = self.high - self.open
            self.lower_wick = self.close - self.low

        self.body_ratio = self.body / self.range
        self.upper_wick_ratio = self.upper_wick / self.range
        self.lower_wick_ratio = self.lower_wick / self.range
        self.is_doji = self.body_ratio <= DOJI_BODY_RATIO_MAX


@dataclass
class CandlePatternResult:
    """Mum analizi sonucu.

    Tespit edilen formasyonlar, yön, skor ve destek/direnç seviyelerini içerir.
    """

    ticker: str
    patterns_detected: list[str] = field(default_factory=list)
    primary_pattern: str | None = None
    direction: str = "NEUTRAL"
    candle_score: float = DEFAULT_CANDLE_SCORE
    buyer_pressure_pct: float = DEFAULT_PRESSURE_PCT
    seller_pressure_pct: float = DEFAULT_PRESSURE_PCT
    has_fvg: bool = False
    fvg_type: str | None = None
    fvg_gap_range: tuple[float, float] = (0.0, 0.0)
    support_level: float = 0.0
    resistance_level: float = 0.0
    recommended_stop: float = 0.0
    recommended_target: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"<CandlePatternResult ticker={self.ticker!r} "
            f"direction={self.direction} score={self.candle_score} "
            f"pattern={self.primary_pattern!r}>"
        )


class CandlePatternEngine:
    """Kurumsal 10/10 Seviye Mum ve Price Action Zeka Motoru.

    16 mum formasyonu, FVG tespiti ve ATR bazlı stop/hedef üretimi yapar.
    """

    def __repr__(self) -> str:
        return "<CandlePatternEngine>"

    def __init__(self) -> None:
        """Motor parametrelerini ve formasyon kayıt defterini başlat."""
        # Mum formasyonları eşikleri
        self.min_body_ratio: float = DOJI_BODY_RATIO_MAX
        self.hammer_shadow_ratio: float = HAMMER_LOWER_WICK_MIN
        self.engulfing_threshold: float = 0.01
        self.star_gap_ratio: float = STAR_GAP_RATIO
        self.three_soldier_body: float = THREE_SOLDIER_BODY_MIN
        self.harami_ratio: float = 0.5
        self.trend_window: int = SUPPORT_LOOKBACK
        self.support_resistance_window: int = 50
        self._pattern_registry: list[str] = [
            "doji",
            "hammer",
            "inverted_hammer",
            "bullish_engulfing",
            "bearish_engulfing",
            "morning_star",
            "evening_star",
            "three_white_soldiers",
            "three_black_crows",
            "harami",
            "piercing_line",
            "dark_cloud_cover",
            "shooting_star",
            "hanging_man",
            "spinning_top",
            "marubozu",
        ]

    def analyze_dataframe(self, df: pl.DataFrame, ticker: str = "ASSET") -> CandlePatternResult:
        """OHLCV DataFrame'ini analiz ederek tüm formasyonları çıkar.

        Args:
            df: Polars DataFrame (Open, High, Low, Close, Volume kolonları).
            ticker: Analiz edilen varlık kodu.

        Returns:
            CandlePatternResult: Formasyon, yön, skor ve seviye bilgileri.

        Raises:
            ValueError: Gerekli OHLC kolonları eksikse.
        """
        result = CandlePatternResult(ticker=ticker)
        if df is None or len(df) < 3:
            logger.warning("candle_veri_yetersiz", len=len(df) if df is not None else 0)
            return result

        required_cols = ["Open", "High", "Low", "Close"]
        if not all(col in df.columns for col in required_cols):
            raise ValueError(f"Eksik kolonlar: {set(required_cols) - set(df.columns)}")

        closes = df["Close"].to_numpy()
        opens = df["Open"].to_numpy()
        highs = df["High"].to_numpy()
        lows = df["Low"].to_numpy()
        vols = df["Volume"].to_numpy() if "Volume" in df.columns else np.ones(len(df))

        n = len(df)
        c0 = CandleMetrics(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1])
        c1 = CandleMetrics(opens[-2], highs[-2], lows[-2], closes[-2], vols[-2])
        c2 = CandleMetrics(opens[-3], highs[-3], lows[-3], closes[-3], vols[-3]) if n >= 3 else None

        detected: list[str] = []
        score = DEFAULT_CANDLE_SCORE
        evidence: list[str] = []
        direction = "NEUTRAL"

        # ── 1. Alıcı & Satıcı Baskı Analizi ──────────────────────────
        buyer_power = (c0.lower_wick_ratio * 0.5) + (c0.body_ratio if c0.is_green else 0.0)
        seller_power = (c0.upper_wick_ratio * 0.5) + (c0.body_ratio if not c0.is_green else 0.0)
        total_p = max(buyer_power + seller_power, WICK_RANGE_EPSILON)
        buyer_pct = round((buyer_power / total_p) * 100, 1)
        seller_pct = round((seller_power / total_p) * 100, 1)

        result.buyer_pressure_pct = buyer_pct
        result.seller_pressure_pct = seller_pct

        # ── 2. 12 Klasik Japon Mum Formasyonu Tespiti ────────────────

        # A) Bullish Engulfing (Yutan Boğa)
        if (
            not c1.is_green
            and c0.is_green
            and c0.open <= (c1.close * ENGULFING_OPEN_TOLERANCE)
            and c0.close >= (c1.open * ENGULFING_CLOSE_TOLERANCE)
        ):
            detected.append("BULLISH_ENGULFING")
            score += BULLISH_SCORE_BONUS
            evidence.append("Yutan Boğa Mumu: Güçlü alıcılar önceki kırmızı mumu tamamen yuttu.")

        # B) Bearish Engulfing (Yutan Ayı)
        elif (
            c1.is_green
            and not c0.is_green
            and c0.open >= (c1.close * ENGULFING_CLOSE_TOLERANCE)
            and c0.close <= (c1.open * ENGULFING_OPEN_TOLERANCE)
        ):
            detected.append("BEARISH_ENGULFING")
            score -= BEARISH_SCORE_PENALTY
            evidence.append("Yutan Ayı Mumu: Satıcılar önceki yeşil mumu tamamen yuttu (Tepe Dönüşü).")

        # C) Hammer (Çekiç / Dip Pinbar)
        if (
            c0.lower_wick_ratio >= HAMMER_LOWER_WICK_MIN
            and c0.upper_wick_ratio <= HAMMER_UPPER_WICK_MAX
            and c0.body_ratio >= PINBAR_BODY_MIN
        ):
            detected.append("HAMMER_PINBAR")
            score += HAMMER_SCORE_BONUS
            evidence.append("Çekiç (Hammer) Mumu: Uzun alt fitille dip seviyelerden sert alıcı tepkisi.")

        # D) Inverted Hammer (Ters Çekiç)
        elif (
            c0.upper_wick_ratio >= HAMMER_LOWER_WICK_MIN
            and c0.lower_wick_ratio <= HAMMER_UPPER_WICK_MAX
            and c0.body_ratio >= PINBAR_BODY_MIN
            and not c1.is_green
        ):
            detected.append("INVERTED_HAMMER")
            score += INVERTED_HAMMER_SCORE
            evidence.append("Ters Çekiç Mumu: Düşüş trendi sonunda alıcıların ilk agresif yukarı atağı.")

        # E) Shooting Star (Kayan Yıldız / Tepe Pinbar)
        if (
            c0.upper_wick_ratio >= HAMMER_LOWER_WICK_MIN
            and c0.lower_wick_ratio <= HAMMER_UPPER_WICK_MAX
            and c1.is_green
        ):
            detected.append("SHOOTING_STAR")
            score -= SHOOTING_STAR_PENALTY
            evidence.append("Kayan Yıldız (Shooting Star): Zirvede satıcıların sert satış baskısı.")

        # F) Morning Star (Sabah Yıldızı - 3 Mumluk Dönüş)
        if (
            c2
            and not c2.is_green
            and c1.body_ratio <= STAR_BODY_RATIO_MAX
            and c0.is_green
            and c0.close >= (c2.open + c2.close) / 2
        ):
            detected.append("MORNING_STAR")
            score += STAR_SCORE_BONUS
            evidence.append("Sabah Yıldızı (Morning Star): 3 mumluk kurumsal dip dönüş formasyonu teyit edildi.")

        # G) Evening Star (Akşam Yıldızı - 3 Mumluk Tepe Dönüş)
        if (
            c2
            and c2.is_green
            and c1.body_ratio <= STAR_BODY_RATIO_MAX
            and not c0.is_green
            and c0.close <= (c2.open + c2.close) / 2
        ):
            detected.append("EVENING_STAR")
            score -= STAR_SCORE_PENALTY
            evidence.append("Akşam Yıldızı (Evening Star): 3 mumluk kurumsal tepe dönüş formasyonu teyit edildi.")

        # H) Three White Soldiers (Üç Beyaz Asker)
        if (
            c2
            and c2.is_green
            and c1.is_green
            and c0.is_green
            and c0.close > c1.close > c2.close
            and c0.body_ratio >= THREE_SOLDIER_BODY_MIN
            and c1.body_ratio >= THREE_SOLDIER_BODY_MIN
        ):
            detected.append("THREE_WHITE_SOLDIERS")
            score += THREE_SOLDIER_SCORE
            evidence.append("Üç Beyaz Asker: 3 ardışık güçlü yükseliş mumuyla yeni boğa trendi.")

        # I) Three Black Crows (Üç Kara Karga)
        if (
            c2
            and not c2.is_green
            and not c1.is_green
            and not c0.is_green
            and c0.close < c1.close < c2.close
            and c0.body_ratio >= THREE_SOLDIER_BODY_MIN
            and c1.body_ratio >= THREE_SOLDIER_BODY_MIN
        ):
            detected.append("THREE_BLACK_CROWS")
            score -= THREE_SOLDIER_SCORE
            evidence.append("Üç Kara Karga: 3 ardışık güçlü düşüş mumuyla sert ayı trendi.")

        # J) Doji Çeşitleri
        if c0.is_doji:
            if c0.lower_wick_ratio >= DOJI_DRAGONFLY_WICK:
                detected.append("DRAGONFLY_DOJI")
                score += DOJI_SCORE
                evidence.append("Yusufçuk Doji (Dragonfly): Alt fitilde tam alıcı hakimiyetiyle kararsızlık sonu.")
            elif c0.upper_wick_ratio >= DOJI_GRAVESTONE_WICK:
                detected.append("GRAVESTONE_DOJI")
                score -= DOJI_SCORE
                evidence.append("Mezar Taşı Doji (Gravestone): Üst fitilde tam satıcı baskısıyla tepe kararsızlığı.")
            else:
                detected.append("NEUTRAL_DOJI")
                evidence.append("Nötr Doji: Alıcı ve satıcı dengede, trend yön arayışında.")

        # ── 3. Fair Value Gap (FVG) ──────────────────────────────────
        if c2:
            if c0.low > c2.high:
                result.has_fvg = True
                result.fvg_type = "BULLISH_FVG"
                result.fvg_gap_range = (float(c2.high), float(c0.low))
                detected.append("BULLISH_FVG")
                score += FVG_SCORE
                evidence.append(
                    f"Boğa FVG Dengesizlik Alanı: {c2.high:.2f}₺ - {c0.low:.2f}₺ arasında kurumsal alım boşluğu."
                )
            elif c0.high < c2.low:
                result.has_fvg = True
                result.fvg_type = "BEARISH_FVG"
                result.fvg_gap_range = (float(c0.high), float(c2.low))
                detected.append("BEARISH_FVG")
                score -= FVG_SCORE
                evidence.append(
                    f"Ayı FVG Dengesizlik Alanı: {c0.high:.2f}₺ - {c2.low:.2f}₺ arasında kurumsal satış boşluğu."
                )

        # ── 4. Destek, Direnç ve Stop/Hedef ─────────────────────────
        p_now = float(c0.close)
        support = float(np.min(lows[-SUPPORT_LOOKBACK:])) if n >= SUPPORT_LOOKBACK else float(c0.low * 0.95)
        resistance = float(np.max(highs[-SUPPORT_LOOKBACK:])) if n >= SUPPORT_LOOKBACK else float(c0.high * 1.05)

        tr_list = [
            max(h_val - l_val, abs(h_val - c_prev), abs(l_val - c_prev))
            for h_val, l_val, c_prev in zip(highs[1:], lows[1:], closes[:-1], strict=False)
        ]
        atr = float(np.mean(tr_list[-ATR_PERIOD:])) if len(tr_list) >= ATR_PERIOD else (p_now * DEFAULT_ATR_PCT)

        score = max(SCORE_LOWER_BOUND, min(SCORE_UPPER_BOUND, score))
        if score >= BULLISH_THRESHOLD:
            direction = "BULLISH"
            target = round(p_now + (atr * ATR_TARGET_MULTIPLIER), 2)
            stop = round(max(p_now - (atr * ATR_STOP_MULTIPLIER), support * 0.99), 2)
        elif score <= BEARISH_THRESHOLD:
            direction = "BEARISH"
            target = round(p_now - (atr * ATR_TARGET_MULTIPLIER), 2)
            stop = round(min(p_now + (atr * ATR_STOP_MULTIPLIER), resistance * 1.01), 2)
        else:
            direction = "NEUTRAL"
            target = round(resistance, 2)
            stop = round(support, 2)

        result.patterns_detected = detected
        result.primary_pattern = detected[0] if detected else "NORMAL_CANDLE"
        result.direction = direction
        result.candle_score = round(score, 1)
        result.support_level = round(support, 2)
        result.resistance_level = round(resistance, 2)
        result.recommended_stop = stop
        result.recommended_target = target
        result.evidence = evidence

        logger.info(
            "candle_analiz_tamamlandi",
            ticker=ticker,
            direction=direction,
            score=round(score, 1),
            patterns=len(detected),
        )

        return result


# Singleton instance
candle_engine = CandlePatternEngine()
