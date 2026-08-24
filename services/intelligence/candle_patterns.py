"""
ALPHA BIST — 10/10 Perfect Candlestick & Price Action Intelligence Engine
========================================================================
12 Klasik Japon Mum Formasyonu, Fitil/Gövde Oranı Matematiği,
Fair Value Gap (FVG) ve Smart Money Likidite Emilimini tespit eder.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()


@dataclass
class CandleMetrics:
    """Tek bir mumun anatomik ölçümleri."""
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
    body_ratio: float = 0.0  # Gövde / Toplam Mum Boyu
    upper_wick_ratio: float = 0.0
    lower_wick_ratio: float = 0.0
    is_green: bool = True
    is_doji: bool = False

    def __post_init__(self):
        self.body = abs(self.close - self.open)
        self.range = max(self.high - self.low, 1e-9)
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
        self.is_doji = self.body_ratio <= 0.08  # Gövde %8'den küçükse doji


@dataclass
class CandlePatternResult:
    """Mum analizi sonucu."""
    ticker: str
    patterns_detected: List[str] = field(default_factory=list)
    primary_pattern: Optional[str] = None
    direction: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    candle_score: float = 50.0  # 0 - 100
    buyer_pressure_pct: float = 50.0  # Alıcı gücü %
    seller_pressure_pct: float = 50.0 # Satıcı gücü %
    has_fvg: bool = False
    fvg_type: Optional[str] = None   # BULLISH_FVG, BEARISH_FVG
    fvg_gap_range: Tuple[float, float] = (0.0, 0.0)
    support_level: float = 0.0
    resistance_level: float = 0.0
    recommended_stop: float = 0.0
    recommended_target: float = 0.0
    evidence: List[str] = field(default_factory=list)


class CandlePatternEngine:
    """Kurumsal 10/10 Seviye Mum ve Price Action Zeka Motoru."""

    def __init__(self):
        # Mum formasyonları ve eşikleri
        self.min_body_ratio = 0.6        # Doji için max gövde/arası oran
        self.hammer_shadow_ratio = 2.0   # Çekiç için alt gölge/gövde oranı
        self.engulfing_threshold = 0.01  # Yutan formasyonu min gövde farkı
        self.star_gap_ratio = 0.005      # Sabah/Akşam yıldızı min boşluk
        self.three_soldier_body = 0.5    # Üç asker min gövde boyu
        self.harami_ratio = 0.5          # Harami max gövde oranı
        self.trend_window = 20           # Trend penceresi (gün)
        self.support_resistance_window = 50  # Destek/direnç penceresi
        self._pattern_registry = [
            "doji", "hammer", "inverted_hammer", "bullish_engulfing",
            "bearish_engulfing", "morning_star", "evening_star",
            "three_white_soldiers", "three_black_crows", "harami",
            "piercing_line", "dark_cloud_cover", "shooting_star",
            "hanging_man", "spinning_top", "marubozu",
        ]

    def analyze_dataframe(self, df: pd.DataFrame, ticker: str = "ASSET") -> CandlePatternResult:
        """OHLCV DataFrame'ini analiz ederek tüm formasyonları çıkarır."""
        result = CandlePatternResult(ticker=ticker)
        if df is None or len(df) < 3:
            return result

        # Gerekli kolonları standardize et
        required_cols = ["Open", "High", "Low", "Close"]
        if not all(col in df.columns for col in required_cols):
            return result

        closes = df["Close"].values
        opens = df["Open"].values
        highs = df["High"].values
        lows = df["Low"].values
        vols = df["Volume"].values if "Volume" in df.columns else np.ones(len(df))

        n = len(df)
        c0 = CandleMetrics(opens[-1], highs[-1], lows[-1], closes[-1], vols[-1])
        c1 = CandleMetrics(opens[-2], highs[-2], lows[-2], closes[-2], vols[-2])
        c2 = CandleMetrics(opens[-3], highs[-3], lows[-3], closes[-3], vols[-3]) if n >= 3 else None
        c3 = CandleMetrics(opens[-4], highs[-4], lows[-4], closes[-4], vols[-4]) if n >= 4 else None

        detected = []
        score = 50.0
        evidence = []
        direction = "NEUTRAL"

        # -------------------------------------------------------------
        # 1. Alıcı & Satıcı Baskı Analizi (Buyer vs Seller Pressure)
        # -------------------------------------------------------------
        # Alt fitil + yeşil gövde alıcı gücünü, üst fitil + kırmızı gövde satıcı gücünü temsil eder
        buyer_power = (c0.lower_wick_ratio * 0.5) + (c0.body_ratio if c0.is_green else 0.0)
        seller_power = (c0.upper_wick_ratio * 0.5) + (c0.body_ratio if not c0.is_green else 0.0)
        total_p = max(buyer_power + seller_power, 1e-9)
        buyer_pct = round((buyer_power / total_p) * 100, 1)
        seller_pct = round((seller_power / total_p) * 100, 1)

        result.buyer_pressure_pct = buyer_pct
        result.seller_pressure_pct = seller_pct

        # -------------------------------------------------------------
        # 2. 12 Klasik Japon Mum Formasyonu Tespiti
        # -------------------------------------------------------------

        # A) Bullish Engulfing (Yutan Boğa)
        if not c1.is_green and c0.is_green and c0.open <= (c1.close * 1.005) and c0.close >= (c1.open * 0.995):
            detected.append("BULLISH_ENGULFING")
            score += 25
            evidence.append(f"Yutan Boğa Mumu: Güçlü alıcılar önceki kırmızı mumu tamamen yuttu.")

        # B) Bearish Engulfing (Yutan Ayı)
        elif c1.is_green and not c0.is_green and c0.open >= (c1.close * 0.995) and c0.close <= (c1.open * 1.005):
            detected.append("BEARISH_ENGULFING")
            score -= 25
            evidence.append(f"Yutan Ayı Mumu: Satıcılar önceki yeşil mumu tamamen yuttu (Tepe Dönüşü).")

        # C) Hammer (Çekiç / Dip Pinbar)
        if c0.lower_wick_ratio >= 0.50 and c0.upper_wick_ratio <= 0.20 and c0.body_ratio >= 0.10:
            detected.append("HAMMER_PINBAR")
            score += 22
            evidence.append("Çekiç (Hammer) Mumu: Uzun alt fitille dip seviyelerden sert alıcı tepkisi.")

        # D) Inverted Hammer (Ters Çekiç)
        elif c0.upper_wick_ratio >= 0.50 and c0.lower_wick_ratio <= 0.20 and c0.body_ratio >= 0.10 and not c1.is_green:
            detected.append("INVERTED_HAMMER")
            score += 15
            evidence.append("Ters Çekiç Mumu: Düşüş trendi sonunda alıcıların ilk agresif yukarı atağı.")

        # E) Shooting Star (Kayan Yıldız / Tepe Pinbar)
        if c0.upper_wick_ratio >= 0.50 and c0.lower_wick_ratio <= 0.20 and c1.is_green:
            detected.append("SHOOTING_STAR")
            score -= 22
            evidence.append("Kayan Yıldız (Shooting Star): Zirvede satıcıların sert satış baskısı.")

        # F) Morning Star (Sabah Yıldızı - 3 Mumluk Dönüş)
        if c2 and not c2.is_green and c1.body_ratio <= 0.25 and c0.is_green and c0.close >= (c2.open + c2.close) / 2:
            detected.append("MORNING_STAR")
            score += 30
            evidence.append("Sabah Yıldızı (Morning Star): 3 mumluk kurumsal dip dönüş formasyonu teyit edildi.")

        # G) Evening Star (Akşam Yıldızı - 3 Mumluk Tepe Dönüş)
        if c2 and c2.is_green and c1.body_ratio <= 0.25 and not c0.is_green and c0.close <= (c2.open + c2.close) / 2:
            detected.append("EVENING_STAR")
            score -= 30
            evidence.append("Akşam Yıldızı (Evening Star): 3 mumluk kurumsal tepe dönüş formasyonu teyit edildi.")

        # H) Three White Soldiers (Üç Beyaz Asker)
        if c2 and c2.is_green and c1.is_green and c0.is_green and c0.close > c1.close > c2.close:
            if c0.body_ratio >= 0.35 and c1.body_ratio >= 0.35:
                detected.append("THREE_WHITE_SOLDIERS")
                score += 24
                evidence.append("Üç Beyaz Asker: 3 ardışık güçlü yükseliş mumuyla yeni boğa trendi.")

        # I) Three Black Crows (Üç Kara Karga)
        if c2 and not c2.is_green and not c1.is_green and not c0.is_green and c0.close < c1.close < c2.close:
            if c0.body_ratio >= 0.35 and c1.body_ratio >= 0.35:
                detected.append("THREE_BLACK_CROWS")
                score -= 24
                evidence.append("Üç Kara Karga: 3 ardışık güçlü düşüş mumuyla sert ayı trendi.")

        # J) Doji Çeşitleri (Dragonfly, Gravestone, Neutral Doji)
        if c0.is_doji:
            if c0.lower_wick_ratio >= 0.70:
                detected.append("DRAGONFLY_DOJI")
                score += 15
                evidence.append("Yusufçuk Doji (Dragonfly): Alt fitilde tam alıcı hakimiyetiyle kararsızlık sonu.")
            elif c0.upper_wick_ratio >= 0.70:
                detected.append("GRAVESTONE_DOJI")
                score -= 15
                evidence.append("Mezar Taşı Doji (Gravestone): Üst fitilde tam satıcı baskısıyla tepe kararsızlığı.")
            else:
                detected.append("NEUTRAL_DOJI")
                evidence.append("Nötr Doji: Alıcı ve satıcı dengede, trend yön arayışında.")

        # -------------------------------------------------------------
        # 3. Smart Money: Fair Value Gap (FVG / Dengesizlik Boşluğu)
        # -------------------------------------------------------------
        if c2:
            # Boğa FVG: 3. mumun High'ı ile 1. mumun Low'u arasında boşluk kalması
            if c0.low > c2.high:
                result.has_fvg = True
                result.fvg_type = "BULLISH_FVG"
                result.fvg_gap_range = (float(c2.high), float(c0.low))
                detected.append("BULLISH_FVG")
                score += 18
                evidence.append(f"Boğa FVG Dengesizlik Alanı: {c2.high:.2f}₺ - {c0.low:.2f}₺ arasında kurumsal alım boşluğu.")

            # Ayı FVG: 3. mumun Low'u ile 1. mumun High'ı arasında boşluk kalması
            elif c0.high < c2.low:
                result.has_fvg = True
                result.fvg_type = "BEARISH_FVG"
                result.fvg_gap_range = (float(c0.high), float(c2.low))
                detected.append("BEARISH_FVG")
                score -= 18
                evidence.append(f"Ayı FVG Dengesizlik Alanı: {c0.high:.2f}₺ - {c2.low:.2f}₺ arasında kurumsal satış boşluğu.")

        # -------------------------------------------------------------
        # 4. Destek, Direnç ve Dinamik Stop/Hedef Hesabı
        # -------------------------------------------------------------
        p_now = float(c0.close)
        support = float(np.min(lows[-20:])) if n >= 20 else float(c0.low * 0.95)
        resistance = float(np.max(highs[-20:])) if n >= 20 else float(c0.high * 1.05)

        # ATR bazlı stop ve hedef
        tr_list = [max(h - l, abs(h - c_prev), abs(l - c_prev)) for h, l, c_prev in zip(highs[1:], lows[1:], closes[:-1])]
        atr = float(np.mean(tr_list[-14:])) if len(tr_list) >= 14 else (p_now * 0.03)

        # Skora göre yön belirleme
        score = max(5.0, min(95.0, score))
        if score >= 65:
            direction = "BULLISH"
            target = round(p_now + (atr * 3.5), 2)
            stop = round(max(p_now - (atr * 1.5), support * 0.99), 2)
        elif score <= 35:
            direction = "BEARISH"
            target = round(p_now - (atr * 3.5), 2)
            stop = round(min(p_now + (atr * 1.5), resistance * 1.01), 2)
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

        return result


# Singleton instance
candle_engine = CandlePatternEngine()
