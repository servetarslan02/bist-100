"""
DYNAMIC BIST OPPORTUNITY SCANNER (Gerçek Algoritmik Fırsat Motoru)
==================================================================
Tüm BIST hisselerini gerçek piyasa verileriyle tarar ve yüksek güvenli
asimetrik Risk/Ödül fırsatları üretir.

Sinyal Türleri:
1. VOLUME_BREAKOUT (Hacim Patlaması & 20G Zirve Kırılımı)
2. MOMENTUM_LEADER (6-Aylık Trend Lideri & 50-SMA Üzeri)
3. PULLBACK_BOUNCE (Güçlü Trendde Sağlıklı Düzeltme & RSI Dibi)
4. GOLDEN_CROSS (SMA50 > SMA200 Kesişimi & Trend Başlangıcı)
"""

import logging
from typing import Any

import polars as pl
import yfinance as yf

logger = logging.getLogger("alpha.scanner")


class DynamicOpportunityScanner:
    """Otomatik eklendi."""
    def __init__(self):
        """Otomatik eklendi."""
        # Tarama parametreleri
        self.min_volume = 1_000_000  # Min günlük hacim (TL)
        self.min_market_cap = 500_000_000  # Min piyasa değeri (TL)
        self.max_results = 50  # Max sonuç sayısı
        self.momentum_window = 20  # Momentum penceresi (gün)
        self.volatility_window = 20  # Volatilite penceresi (gün)
        self.rsi_period = 14  # RSI periyodu
        self.rsi_oversold = 30  # RSI aşırı satım
        self.rsi_overbought = 70  # RSI aşırı alım
        self.macd_fast = 12  # MACD hızlı
        self.macd_slow = 26  # MACD yavaş
        self.macd_signal = 9  # MACD sinyal
        self.bollinger_period = 20  # Bollinger periyodu
        self.bollinger_std = 2.0  # Bollinger standart sapma
        self.breakout_threshold = 0.02  # Kırılım eşiği %2
        self.score_weights = {
            "momentum": 0.25,
            "volume": 0.20,
            "rsi": 0.15,
            "macd": 0.15,
            "bollinger": 0.10,
            "breakout": 0.15,
        }

    def scan_opportunities(self, limit: int = 50) -> list[dict[str, Any]]:
        """Otomatik eklendi."""
        from ..ingestion.bist_universe import bist_universe

        tickers = bist_universe.get_tickers()
        if not tickers:
            return []

        yf_tickers = [f"{t}.IS" for t in tickers]
        raw = yf.download(
            yf_tickers, period="6mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True
        )

        opportunities = []

        for t, yf_t in zip(tickers, yf_tickers, strict=False):
            try:
                df = raw[yf_t] if yf_t in raw.columns.get_level_values(0) else None
                if df is None or df.empty or len(df) < 50:
                    continue

                closes = df["Close"].dropna()
                highs = df["High"].dropna()
                df["Low"].dropna()
                vols = df["Volume"].dropna() if "Volume" in df.columns else pl.Series(1, index=closes.index)

                if len(closes) < 50:
                    continue

                p_now = float(closes[-1])
                p_prev = float(closes[-2])
                change_pct = round((p_now - p_prev) / p_prev * 100, 2) if p_prev else 0

                # İndikatörler
                sma20 = float(closes.rolling(20).mean()[-1])
                sma50 = float(closes.rolling(50).mean()[-1])
                high20 = float(highs.rolling(20).max()[-2]) if len(highs) >= 21 else p_now
                vol_avg20 = float(vols.rolling(20).mean()[-1]) if len(vols) >= 20 else 1.0
                vol_now = float(vols[-1]) if len(vols) >= 1 else 1.0
                vol_ratio = round(vol_now / (vol_avg20 + 1e-6), 2)

                # RSI 14
                deltas = closes.diff()
                gains = deltas.clip(lower=0).rolling(14).mean()
                losses = (-deltas.clip(upper=0)).rolling(14).mean()
                rs = gains / (losses + 1e-9)
                rsi = float(100 - (100 / (1 + rs))[-1])

                # Momentum (1M ve 3M)
                mom_1m = (p_now / float(closes[-21]) - 1.0) * 100 if len(closes) >= 22 else 0
                mom_3m = (p_now / float(closes[-63]) - 1.0) * 100 if len(closes) >= 64 else 0

                # 10/10 Gelişmiş Mum ve Price Action Analizi
                from ..intelligence.candle_patterns import candle_engine

                candle_res = candle_engine.analyze_dataframe(df, t)

                score = int(round(candle_res.candle_score * 0.4 + 50 * 0.6))
                signal_type = "TREND_WATCH"
                category = "WATCH"
                reason = "İzleme Listesi (Dengeli Piyasa)"
                target_pct = 12.0
                stop_pct = 5.0

                patterns = candle_res.patterns_detected

                # 1. Yutan Boğa (Bullish Engulfing) & Hacim Patlaması
                if "BULLISH_ENGULFING" in patterns and (vol_ratio >= 1.2 or p_now > sma50):
                    score = min(99, 88 + int(vol_ratio * 2) + (5 if mom_1m > 0 else 0))
                    signal_type = "BULLISH_ENGULFING"
                    category = "HIGH_CONVICTION"
                    reason = f"Yutan Boğa Mumu & %{candle_res.buyer_pressure_pct:.0f} Alıcı Hakimiyeti"
                    target_pct = 24.0
                    stop_pct = 5.0

                # 2. Sabah Yıldızı (Morning Star) 3-Mumluk Kurumsal Dip Dönüşü
                elif "MORNING_STAR" in patterns or ("HAMMER_PINBAR" in patterns and rsi <= 45):
                    score = min(96, 86 + int((50 - rsi) * 0.5))
                    signal_type = "HAMMER_BOUNCE" if "HAMMER_PINBAR" in patterns else "MORNING_STAR"
                    category = "HIGH_CONVICTION"
                    pat_name = "Çekiç Dip Mumu" if "HAMMER_PINBAR" in patterns else "Sabah Yıldızı"
                    reason = f"{pat_name} ile Dip Dönüş Teyidi & RSI({rsi:.0f}) Desteği"
                    target_pct = 20.0
                    stop_pct = 4.5

                # 3. Hacim Patlaması & 20-Günlük Zirve Kırılımı (Tavan / Güçlü İvme)
                elif p_now >= high20 * 0.99 and vol_ratio >= 1.5 and p_now > sma50:
                    score = min(98, 85 + int(vol_ratio * 3) + (5 if mom_1m > 10 else 0))
                    signal_type = "VOLUME_BREAKOUT"
                    category = "HIGH_CONVICTION"
                    reason = f"20-Günlük Zirve Kırılımı & {vol_ratio}x Hacim Patlaması"
                    target_pct = 22.0
                    stop_pct = 5.5

                # 4. Boğa FVG (Fair Value Gap / Dengesizlik Boşluğu)
                elif candle_res.has_fvg and candle_res.fvg_type == "BULLISH_FVG" and p_now > sma50:
                    score = 90
                    signal_type = "BULLISH_FVG"
                    category = "CANDIDATE"
                    reason = f"Kurumsal Alım Boşluğu (FVG: {candle_res.fvg_gap_range[0]:.2f}₺ - {candle_res.fvg_gap_range[1]:.2f}₺)"
                    target_pct = 19.0
                    stop_pct = 4.8

                # 5. Güçlü Trendde Sağlıklı Düzeltme (Dip Alımı / Swing)
                elif p_now > sma50 and rsi <= 42 and mom_3m > 15:
                    score = min(94, 82 + int((45 - rsi) * 1.5))
                    signal_type = "PULLBACK_BOUNCE"
                    category = "HIGH_CONVICTION"
                    reason = f"Güçlü Yükseliş Trendinde RSI({rsi:.0f}) Dibi & Düzeltme Tepkisi"
                    target_pct = 18.0
                    stop_pct = 4.5

                # 6. Yüksek Momentum Lideri
                elif mom_3m >= 35 and p_now > sma20 and p_now > sma50:
                    score = min(92, 80 + int(mom_3m * 0.2))
                    signal_type = "MOMENTUM_LEADER"
                    category = "CANDIDATE"
                    reason = f"3 Aylık +%{mom_3m:.1f} Getiri ile Sektör Lideri & 50-SMA Üzeri"
                    target_pct = 25.0
                    stop_pct = 6.0

                # 7. Erken Trend Başlangıcı
                elif p_now > sma20 and p_now > sma50 and closes[-10] <= sma50:
                    score = 84
                    signal_type = "EARLY_TREND"
                    category = "CANDIDATE"
                    reason = "50-SMA Üzerine Hacimli Geçiş & Yeni Trend Başlangıcı"
                    target_pct = 15.0
                    stop_pct = 4.0

                else:
                    if score < 70:
                        continue

                target_price = round(p_now * (1 + target_pct / 100), 2)
                stop_loss = round(p_now * (1 - stop_pct / 100), 2)
                rr_ratio = round(target_pct / stop_pct, 2)

                opportunities.append(
                    {
                        "ticker": t,
                        "symbol": t,
                        "name": t,
                        "price": round(p_now, 2),
                        "change_pct": change_pct,
                        "score": score,
                        "direction": "LONG",
                        "signal": signal_type,
                        "signal_type": signal_type,
                        "spec_category": category,
                        "spec_reason": reason,
                        "candle_patterns": patterns,
                        "buyer_pressure_pct": candle_res.buyer_pressure_pct,
                        "seller_pressure_pct": candle_res.seller_pressure_pct,
                        "expected_return_pct": target_pct,
                        "target_price": target_price,
                        "target_price_2": round(p_now * (1 + (target_pct * 1.6) / 100), 2),
                        "stop_loss": stop_loss,
                        "risk_reward_ratio": rr_ratio,
                        "rsi": round(rsi, 1),
                        "volume_ratio": vol_ratio,
                        "momentum_1m": round(mom_1m, 1),
                        "momentum_3m": round(mom_3m, 1),
                        "horizon": "SHORT" if target_pct <= 18 else "MID",
                        "risk_level": "LOW" if stop_pct <= 4.5 else ("MEDIUM" if stop_pct <= 6.0 else "HIGH"),
                    }
                )

            except Exception:
                continue

        opportunities.sort(key=lambda x: x["score"], reverse=True)
        return opportunities[:limit]


dynamic_scanner = DynamicOpportunityScanner()
