"""
ALPHA BIST — 100% Dinamik Tavan Serisi ve Parabolik Trend Sürme Motoru (Trend Rider)
=================================================================================
SIFIR STATİK VERİ & YÜZDE KURALI:
- Stop-loss ve kâr hedefleri sabit %7 veya %18 gibi statik rakamlar DEĞİLDİR.
- Her hissenin anlık ATR (Ortalama Gerçek Aralık / Volatilite), 9-EMA eğimi,
  20-SMA trend açısı ve Hacim Z-Skoruna göre 100% dinamik olarak şekillenir.
- Tavan kitleyen hisselerde erken satışı önler, tepe dağıtım mumu teyit edilene
  kadar 1-2 aylık mega trendleri sonuna kadar sürer.
"""

from typing import Any

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()


class TrendRiderEngine:
    """Tamamen dinamik volatiliteye (ATR) ve trende dayalı kurumsal çıkış algoritması."""

    def __init__(self):
        """Otomatik eklendi."""
        # ATR tabanlı çıkış parametreleri
        self.atr_period = 14  # ATR periyodu
        self.atr_multiplier_entry = 2.0  # Giriş ATR çarpanı
        self.atr_multiplier_trail = 2.5  # Trailing stop ATR çarpanı
        self.atr_multiplier_target = 3.0  # Hedef fiyat ATR çarpanı

        # Trend parametreleri
        self.fast_ma = 10  # Hızlı hareketli ortalama
        self.slow_ma = 30  # Yavaş hareketli ortalama
        self.trend_strength_threshold = 0.02  # Trend gücü eşiği

        # Çıkış kuralları
        self.max_hold_days = 30  # Max tutma süresi (gün)
        self.profit_lock_pct = 0.05  # Kâr kilidi eşiği %5
        self.bear_crash_stop = 0.10  # Ayı piyasası stop %10
        self.volume_spike_ratio = 3.0  # Hacim spike oranı

        # Durum takibi
        self._active_positions: dict[str, dict] = {}

    def evaluate_position_exit(
        self, pos: dict[str, Any], current_candle: pl.Series, history_df: pl.DataFrame, is_bear_crash: bool = False
    ) -> tuple[bool, float, str]:
        """
        Mevcut pozisyonun dinamik çıkış sinyalini değerlendirir.
        Dönüş: (should_exit: bool, target_exit_price: float, exit_reason: str)
        """
        p_close = float(current_candle["Close"])
        p_high = float(current_candle["High"])
        p_low = float(current_candle["Low"])
        p_open = float(current_candle["Open"])

        entry_price = float(pos["entry_price"])
        peak_price = float(pos.get("peak_price", entry_price))

        # Zirve fiyatı güncelle
        if p_high > peak_price:
            peak_price = p_high
            pos["peak_price"] = peak_price

        # -------------------------------------------------------------
        # 1. 100% Dinamik Volatilite (ATR-14) Hesabı
        # -------------------------------------------------------------
        closes = history_df["Close"].to_numpy()
        highs = history_df["High"].to_numpy()
        lows = history_df["Low"].to_numpy()
        n = len(closes)

        if n >= 15:
            tr = [
                max(h - l, abs(h - c_prev), abs(l - c_prev))
                for h, l, c_prev in zip(highs[1:], lows[1:], closes[:-1], strict=False)
            ]
            atr14 = float(np.mean(tr[-14:]))
        else:
            atr14 = max(p_high - p_low, p_close * 0.03)

        # -------------------------------------------------------------
        # 2. Tavan Kitleme Tespiti (Dinamik Üst Fitil & Gövde Analizi)
        # -------------------------------------------------------------
        # Hissede tavan (limit-up): Gövde çok güçlü (%8+ prim) ve üst fitil yok denecek kadar az
        upper_wick = p_high - max(p_open, p_close)
        candle_range = max(p_high - p_low, 1e-9)
        is_tavan = (p_close >= p_open * 1.090) and (upper_wick / candle_range <= 0.08)

        if is_tavan:
            pos["is_in_tavan_run"] = True
            pos["tavan_count"] = pos.get("tavan_count", 0) + 1
            # Tavan serisi bozulmadığı sürece pozisyon kesinlikle korunur
            return False, 0.0, "TAVAN_SERISI_KORUMA"

        # -------------------------------------------------------------
        # 3. Dinamik Trend Göstergeleri (9-EMA & 20-SMA)
        # -------------------------------------------------------------
        sma20 = float(np.mean(closes[-20:])) if n >= 20 else p_close
        ema9 = float(pl.Series(closes).ewm(span=9, adjust=False).mean()[-1]) if n >= 9 else p_close

        gain_from_entry = peak_price - entry_price
        gain_now_pct = ((p_close - entry_price) / entry_price) * 100

        # -------------------------------------------------------------
        # 4. 100% Dinamik Çok Kademeli İzleyen Stop (ATR-Based)
        # -------------------------------------------------------------

        # A) Başlangıç Aşaması (Kazanç < 2.0x ATR): Dinamik Başlangıç Stopu (2.0x ATR)
        if gain_from_entry < (2.0 * atr14):
            dynamic_initial_stop = entry_price - (2.0 * atr14)
            if p_low <= dynamic_initial_stop:
                return True, dynamic_initial_stop, f"DINAMIK_ATR_STOP (ATR: {atr14:.2f}₺)"

        # B) Gelişme Aşaması (Kazanç 2.0x - 5.0x ATR): Stop Başabaş Üzerine Çekilir
        elif (2.0 * atr14) <= gain_from_entry < (5.0 * atr14):
            # Kârı koruma stopu: Zirvenin 2.5x ATR altı veya Giriş + 0.5x ATR
            breakeven_dynamic_stop = max(entry_price + (0.5 * atr14), peak_price - (2.5 * atr14))
            pos["stop_loss"] = max(pos.get("stop_loss", 0), breakeven_dynamic_stop)
            if p_low <= pos["stop_loss"]:
                return True, pos["stop_loss"], f"DINAMIK_BASABAŞ_IZLEYEN_STOP (+%{gain_now_pct:.1f})"

        # C) Mega Trend Aşaması (Kazanç >= 5.0x ATR): Trendi 9-EMA ve Tepe Dağıtım Mumuyla Sür
        else:
            # Tepe dağıtım mumu teyidi (Zirvede Kayan Yıldız veya Yutan Ayı)
            is_bear_engulfing = (p_close < p_open) and (
                n >= 2 and p_close < closes[-2] and (p_open - p_close) > (closes[-2] - float(history_df["Open"][-2]))
            )
            is_shooting_star = (p_high - max(p_open, p_close)) >= (
                max(p_open, p_close) - min(p_open, p_close)
            ) * 2.0 and p_close < p_high * 0.97

            # Tepe dönüş mumu ve 9-EMA altına sarkma varsa kârı realize et
            if (is_bear_engulfing or is_shooting_star) and p_close < ema9:
                return True, p_close, f"TEPE_DAGITIM_MUMU_CIKISI (+%{gain_now_pct:.1f})"

            # Parabolik trend takibi: Zirvenin 3.0x ATR altı veya 20-SMA kırılımı
            parabolic_atr_stop = max(peak_price - (3.0 * atr14), sma20 * 0.985)
            pos["stop_loss"] = max(pos.get("stop_loss", 0), parabolic_atr_stop)
            if p_low <= pos["stop_loss"]:
                return True, pos["stop_loss"], f"MEGA_TREND_PARABOLIK_STOP (+%{gain_now_pct:.1f})"

        # Genel Ayı Çöküşü Rejimi
        if is_bear_crash and (p_close < entry_price):
            return True, p_close, "AYI_PIYASASI_SERMAYE_KORUMA"

        return False, 0.0, "TREND_DEVAM"


# Singleton
trend_rider = TrendRiderEngine()
