"""
ALPHA BIST — 7 Motor Feature Engine v1.0

Her hisse için 7 ayrı motor çalıştırır:
1. Relatif Güç Motoru
2. Momentum + Trend Motoru
3. Hacim + Mikroyapı Motoru
4. Fundamental Motor
5. KAP + Haber Motoru
6. Katalizör Motoru
7. "Neden Düşüyor?" Motoru

Her motor bağımsız çalışır, birbirinin sonucunu etkilemez.
Motor çıktıları ranking modeline girdi olarak kullanılır.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


# =====================================================
# MOTOR 1: RELATİF GÜÇ
# =====================================================

class RelativeStrengthMotor:
    """Hisse vs BIST + sektör karşılaştırması (çok ufuklu)."""

    HORIZONS = [1, 5, 20, 60, 120]

    def compute(
        self,
        ticker: str,
        stock_close: np.ndarray,
        benchmark_close: np.ndarray,
        sector_close: Optional[np.ndarray] = None,
        peer_closes: Optional[Dict[str, np.ndarray]] = None,
    ) -> Dict[str, float]:
        """Relatif güç feature'ları hesapla."""
        features = {}

        # Her horizon için relatif getiri
        for h in self.HORIZONS:
            if len(stock_close) > h and len(benchmark_close) > h:
                stock_ret = (stock_close[-1] / stock_close[-h] - 1) * 100
                bench_ret = (benchmark_close[-1] / benchmark_close[-h] - 1) * 100

                # vs BIST
                features[f"rs_vs_bist_{h}d"] = round(stock_ret - bench_ret, 4)
                features[f"rs_ratio_{h}d"] = round(stock_ret / bench_ret, 4) if bench_ret != 0 else 0

                # vs sektör
                if sector_close is not None and len(sector_close) > h:
                    sector_ret = (sector_close[-1] / sector_close[-h] - 1) * 100
                    features[f"rs_vs_sector_{h}d"] = round(stock_ret - sector_ret, 4)

        # Relatif güç trendi (son 5 gün vs önceki 5 gün)
        if len(stock_close) > 10 and len(benchmark_close) > 10:
            rs_recent = (stock_close[-1] / stock_close[-5] - 1) - (benchmark_close[-1] / benchmark_close[-5] - 1)
            rs_prev = (stock_close[-5] / stock_close[-10] - 1) - (benchmark_close[-5] / benchmark_close[-10] - 1)
            features["rs_trend"] = round(rs_recent - rs_prev, 4)  # Pozitif = güçleniyor

        # Peer relatif gücü
        if peer_closes:
            peer_5d_returns = []
            for peer_ticker, peer_close in peer_closes.items():
                if len(peer_close) > 5:
                    peer_5d_returns.append((peer_close[-1] / peer_close[-5] - 1) * 100)

            if peer_5d_returns and len(stock_close) > 5:
                stock_5d = (stock_close[-1] / stock_close[-5] - 1) * 100
                peer_mean = np.mean(peer_5d_returns)
                features["rs_vs_peers_5d"] = round(stock_5d - peer_mean, 4)
                features["rs_peer_rank"] = round(
                    sum(1 for p in peer_5d_returns if p <= stock_5d) / len(peer_5d_returns), 4
                )

        return features


# =====================================================
# MOTOR 2: MOMENTUM + TREND
# =====================================================

class MomentumTrendMotor:
    """Momentum seviyesi değil, ivme ve değişim yönü."""

    def compute(
        self,
        ticker: str,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Dict[str, float]:
        """Momentum + trend feature'ları hesapla."""
        features = {}
        n = len(close)

        if n < 20:
            return features

        # Trend eğimi (lineer regresyon slope + R²)
        x = np.arange(20)
        y = close[-20:]
        if np.std(y) > 0:
            slope = np.polyfit(x, y, 1)[0]
            features["trend_slope_20d"] = round(float(slope / close[-1] * 100), 4)

            # R² (trend sürekliliği)
            y_pred = np.polyval(np.polyfit(x, y, 1), x)
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            features["trend_r2_20d"] = round(float(r_squared), 4)

        # Momentum ivmesi (roc_5d değişim yönü)
        # -12% → -7% → -3% → +1% = pozitif ivme
        if n > 25:
            roc_now = (close[-1] / close[-5] - 1) * 100
            roc_5ago = (close[-5] / close[-10] - 1) * 100
            roc_10ago = (close[-10] / close[-15] - 1) * 100
            roc_15ago = (close[-15] / close[-20] - 1) * 100

            features["roc_5d"] = round(float(roc_now), 4)
            features["momentum_acceleration"] = round(float(roc_now - roc_5ago), 4)

            # İvme trendi (3 periyot boyunca ivme yönü)
            accel_1 = roc_now - roc_5ago
            accel_2 = roc_5ago - roc_10ago
            accel_3 = roc_10ago - roc_15ago
            if accel_1 > accel_2 > accel_3:
                features["momentum_accel_trend"] = 1.0  # Hızlanıyor
            elif accel_1 < accel_2 < accel_3:
                features["momentum_accel_trend"] = -1.0  # Yavaşlıyor
            else:
                features["momentum_accel_trend"] = 0.0

        # Yeni yüksek/düşük tespiti
        for period in [20, 60, 120]:
            if n > period:
                high_n = np.max(high[-period:])
                low_n = np.min(low[-period:])
                features[f"near_{period}d_high"] = 1.0 if close[-1] >= high_n * 0.98 else 0.0
                features[f"near_{period}d_low"] = 1.0 if close[-1] <= low_n * 1.02 else 0.0

        # Breakout başarısızlığı (kırılım sonrası geri dönüş)
        if n > 25:
            high_20 = np.max(high[-25:-5])
            if close[-5] > high_20 and close[-1] < high_20:
                features["breakout_failure"] = 1.0
            else:
                features["breakout_failure"] = 0.0

        # Drawdown + toparlanma gücü
        if n > 20:
            peak = np.max(close[-20:])
            current_dd = (peak - close[-1]) / peak * 100
            features["drawdown_20d"] = round(float(current_dd), 4)

            # Toparlanma gücü (son 5 gün düşüşten ne kadar toparladı)
            if current_dd > 5:
                low_20 = np.min(close[-20:])
                recovery = (close[-1] - low_20) / (peak - low_20) * 100 if (peak - low_20) > 0 else 0
                features["recovery_strength"] = round(float(recovery), 4)

        # Hareketli ortalama konumu
        for period in [20, 50, 200]:
            if n > period:
                sma = np.mean(close[-period:])
                if sma > 0:
                    features[f"price_vs_sma{period}"] = round(float((close[-1] / sma - 1) * 100), 4)

        return features


# =====================================================
# MOTOR 3: HACIM + MİKROYAPI
# =====================================================

class VolumeMicrostructureMotor:
    """Hacim yüksek ≠ anlamlı. Fiyat-hacim ilişkisi kritik."""

    def compute(
        self,
        ticker: str,
        open_: np.ndarray,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Dict[str, float]:
        """Hacim + mikroyapı feature'ları hesapla."""
        features = {}
        n = len(close)

        if n < 20:
            return features

        # Hacim percentile (z-score değil — daha robust)
        vol_20 = volume[-20:]
        if len(vol_20) > 0:
            current_vol = volume[-1]
            percentile = sum(1 for v in vol_20 if v <= current_vol) / len(vol_20)
            features["volume_percentile"] = round(float(percentile), 4)

        # Hacim-fiyat yönü ilişkisi
        # Yükseliş+patlama ≠ düşüş+patlama
        up_vol = []
        down_vol = []
        for i in range(max(1, n - 10), n):
            if close[i] > close[i - 1]:
                up_vol.append(volume[i])
            elif close[i] < close[i - 1]:
                down_vol.append(volume[i])

        if up_vol and down_vol:
            avg_up = np.mean(up_vol)
            avg_down = np.mean(down_vol)
            if avg_down > 0:
                features["volume_up_down_ratio"] = round(float(avg_up / avg_down), 4)
            features["volume_up_avg"] = round(float(avg_up), 0)
            features["volume_down_avg"] = round(float(avg_down), 0)

        # Tick rule (yaklaşık: close > open → alış, close < open → satış)
        buy_ticks = 0
        sell_ticks = 0
        for i in range(max(0, n - 10), n):
            if close[i] > open_[i]:
                buy_ticks += volume[i]
            elif close[i] < open_[i]:
                sell_ticks += volume[i]

        total_ticks = buy_ticks + sell_ticks
        if total_ticks > 0:
            features["tick_rule"] = round(float((buy_ticks - sell_ticks) / total_ticks), 4)

        # VWAP sapması
        if n >= 5:
            typical_price = (high[-5:] + low[-5:] + close[-5:]) / 3
            vwap = np.sum(typical_price * volume[-5:]) / np.sum(volume[-5:]) if np.sum(volume[-5:]) > 0 else close[-1]
            if vwap > 0:
                features["vwap_deviation"] = round(float((close[-1] / vwap - 1) * 100), 4)

        # Hacim anomalisi (zaman bazlı)
        if n >= 20:
            vol_mean = np.mean(volume[-20:])
            vol_std = np.std(volume[-20:])
            if vol_std > 0:
                features["volume_zscore"] = round(float((volume[-1] - vol_mean) / vol_std), 4)

        # Turnover (hisse bazlı likidite)
        if n >= 5:
            avg_vol_5d = np.mean(volume[-5:])
            features["avg_volume_5d"] = round(float(avg_vol_5d), 0)

        return features


# =====================================================
# MOTOR 4: FUNDAMENTAL
# =====================================================

class FundamentalMotor:
    """Sektörel normalize + FCF merkezli."""

    def compute(
        self,
        ticker: str,
        fundamentals: Dict[str, float],
        sector_medians: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Fundamental feature'lar hesapla."""
        features = {}

        if not fundamentals:
            return features

        # Ham çarpanlar
        for key in ["pe_ratio", "pb_ratio", "ev_ebitda", "fcf_yield", "dividend_yield",
                     "roe", "roa", "profit_margin", "debt_to_equity", "current_ratio"]:
            val = fundamentals.get(key)
            if val is not None:
                features[f"raw_{key}"] = round(float(val), 4)

        # Sektörel normalize (sektör medyanına göre)
        if sector_medians:
            for key in ["pe_ratio", "pb_ratio", "ev_ebitda"]:
                val = fundamentals.get(key)
                median = sector_medians.get(key)
                if val and median and median > 0:
                    features[f"sector_norm_{key}"] = round(float(val / median), 4)

        # FCF merkezli (enflasyon muhasebesinden arındırılmış)
        fcf = fundamentals.get("free_cash_flow", 0)
        revenue = fundamentals.get("revenue", 0)
        market_cap = fundamentals.get("market_cap", 0)

        if revenue and revenue > 0 and fcf:
            features["fcf_margin"] = round(float(fcf / revenue * 100), 4)
        if market_cap and market_cap > 0 and fcf:
            features["fcf_yield_pct"] = round(float(fcf / market_cap * 100), 4)

        # Bilanço kalitesi skoru
        debt_eq = fundamentals.get("debt_to_equity", 0)
        current_ratio = fundamentals.get("current_ratio", 0)
        quality_score = 50
        if debt_eq and debt_eq < 0.5:
            quality_score += 20
        elif debt_eq and debt_eq > 2:
            quality_score -= 20
        if current_ratio and current_ratio > 1.5:
            quality_score += 15
        elif current_ratio and current_ratio < 1:
            quality_score -= 15
        features["balance_sheet_quality"] = round(float(min(100, max(0, quality_score))), 0)

        # Kârlılık trendi (marj genişliyor/daralıyor)
        profit_margin = fundamentals.get("profit_margin", 0)
        if profit_margin:
            if abs(profit_margin) < 1:
                profit_margin *= 100
            features["profit_margin_pct"] = round(float(profit_margin), 2)

        return features


# =====================================================
# MOTOR 5: KAP + HABER
# =====================================================

class KAPNewsMotor:
    """Basit pozitif/negatif değil, yapılandırılmış extraction."""

    def compute(
        self,
        ticker: str,
        kap_events: List[Dict],
        news_events: List[Dict],
    ) -> Dict[str, float]:
        """KAP + haber feature'ları hesapla."""
        features = {}

        # KAP olay sınıflandırması
        if kap_events:
            event_types = {}
            for event in kap_events:
                etype = event.get("category", "UNKNOWN")
                event_types[etype] = event_types.get(etype, 0) + 1

            for etype, count in event_types.items():
                features[f"kap_count_{etype.lower()}"] = count

            # Beklenmediklik skoru
            importance_scores = [e.get("importance", 0.5) for e in kap_events]
            features["kap_avg_importance"] = round(float(np.mean(importance_scores)), 4)
            features["kap_max_importance"] = round(float(np.max(importance_scores)), 4)

            # Etki yönü + büyüklüğü
            sentiments = [e.get("sentiment", 0) for e in kap_events]
            features["kap_sentiment_avg"] = round(float(np.mean(sentiments)), 4)
            features["kap_sentiment_latest"] = round(float(sentiments[-1]), 4) if sentiments else 0

        # Haber sentiment
        if news_events:
            sentiments = [n.get("sentiment", 0) for n in news_events]
            importances = [n.get("importance", 0.5) for n in news_events]

            # Ağırlıklı sentiment
            if importances:
                weighted = sum(s * i for s, i in zip(sentiments, importances)) / sum(importances)
                features["news_sentiment_weighted"] = round(float(weighted), 4)

            features["news_count_24h"] = len(news_events)
            features["news_avg_importance"] = round(float(np.mean(importances)), 4)

            # Sentiment momentum (son 3 gün vs önceki 3 gün)
            recent = [s for s, e in zip(sentiments, news_events)
                     if self._is_recent(e.get("timestamp", ""), hours=72)]
            older = [s for s, e in zip(sentiments, news_events)
                    if not self._is_recent(e.get("timestamp", ""), hours=72)]

            if recent and older:
                features["sentiment_momentum"] = round(float(np.mean(recent) - np.mean(older)), 4)

        return features

    def _is_recent(self, ts: str, hours: int = 24) -> bool:
        try:
            from datetime import datetime, timezone, timedelta
            if isinstance(ts, str):
                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                t = ts
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t) < timedelta(hours=hours)
        except:
            return False


# =====================================================
# MOTOR 6: KATALİZÖR
# =====================================================

class CatalystMotor:
    """Yaklaşan olaylar ayrı skor."""

    def compute(
        self,
        ticker: str,
        upcoming_events: List[Dict],
    ) -> Dict[str, float]:
        """Katalizör feature'ları hesapla."""
        features = {}

        if not upcoming_events:
            features["catalyst_count"] = 0
            features["catalyst_importance"] = 0
            features["catalyst_days_nearest"] = 0
            return features

        features["catalyst_count"] = len(upcoming_events)

        # En yakın ve en önemli katalizör
        importances = [e.get("importance", 0.5) for e in upcoming_events]
        features["catalyst_importance"] = round(float(np.max(importances)), 4)
        features["catalyst_avg_importance"] = round(float(np.mean(importances)), 4)

        # En yakın katalizöre gün sayısı
        days_list = [e.get("days_until", 999) for e in upcoming_events]
        features["catalyst_days_nearest"] = min(days_list) if days_list else 999

        # Katalizör türleri
        for event in upcoming_events:
            etype = event.get("type", "unknown")
            features[f"catalyst_{etype}"] = features.get(f"catalyst_{etype}", 0) + 1

        return features


# =====================================================
# MOTOR 7: "NEDEN DÜŞÜYOR?"
# =====================================================

class WhyFallingMotor:
    """Düşen bıçağı tutma hatasını önle."""

    def compute(
        self,
        ticker: str,
        stock_return_5d: float,
        market_return_5d: float,
        sector_return_5d: float,
        volume_change: float,
        news_sentiment: float,
        kap_sentiment: float,
    ) -> Dict[str, float]:
        """Düşüş nedeni sınıflandırması."""
        features = {}

        # Düşüş var mı?
        if stock_return_5d >= -2:
            features["why_falling"] = 0.0  # Düşüş yok
            features["falling_is_temporary"] = 0.5
            return features

        features["why_falling"] = 1.0

        # Market selloff tespiti
        if market_return_5d < -3:
            features["fall_market_selloff"] = 1.0
        else:
            features["fall_market_selloff"] = 0.0

        # Sector selloff tespiti
        if sector_return_5d < -5:
            features["fall_sector_selloff"] = 1.0
        else:
            features["fall_sector_selloff"] = 0.0

        # Company-specific (piyasa ve sektör düşmemişse)
        if market_return_5d > -1 and sector_return_5d > -2 and stock_return_5d < -5:
            features["fall_company_specific"] = 1.0
        else:
            features["fall_company_specific"] = 0.0

        # Liquidity event (hacim patlaması + fiyat düşüşü)
        if volume_change > 2 and stock_return_5d < -5:
            features["fall_liquidity_event"] = 1.0
        else:
            features["fall_liquidity_event"] = 0.0

        # Temporary panic (hızlı düşüş + negatif sentiment düşük)
        if stock_return_5d < -10 and news_sentiment > -0.3:
            features["fall_temporary_panic"] = 1.0
        else:
            features["fall_temporary_panic"] = 0.0

        # Düşüş nedeni geçici mi kalıcı mı?
        # Geçici: piyasa geneli düşüş + şirket-specific değil + yüksek hacim yok
        is_temporary = (
            features.get("fall_market_selloff", 0) == 1.0
            and features.get("fall_company_specific", 0) == 0.0
            and features.get("fall_liquidity_event", 0) == 0.0
        )
        features["falling_is_temporary"] = 1.0 if is_temporary else 0.0

        return features


# =====================================================
# ANA MOTOR — 7 MOTORU BİRLEŞTİR
# =====================================================

class SevenMotorEngine:
    """7 motoru birleştiren ana motor."""

    def __init__(self):
        self.motor1 = RelativeStrengthMotor()
        self.motor2 = MomentumTrendMotor()
        self.motor3 = VolumeMicrostructureMotor()
        self.motor4 = FundamentalMotor()
        self.motor5 = KAPNewsMotor()
        self.motor6 = CatalystMotor()
        self.motor7 = WhyFallingMotor()

    def compute_all(
        self,
        ticker: str,
        close: np.ndarray,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
        benchmark_close: Optional[np.ndarray] = None,
        sector_close: Optional[np.ndarray] = None,
        peer_closes: Optional[Dict[str, np.ndarray]] = None,
        fundamentals: Optional[Dict[str, float]] = None,
        sector_medians: Optional[Dict[str, float]] = None,
        kap_events: Optional[List[Dict]] = None,
        news_events: Optional[List[Dict]] = None,
        upcoming_events: Optional[List[Dict]] = None,
        market_return_5d: float = 0,
        sector_return_5d: float = 0,
        market_regime: str = "UNKNOWN",
    ) -> Dict[str, float]:
        """Tüm 7 motoru çalıştır ve feature'ları birleştir."""
        all_features = {}

        # Motor 1: Relatif Güç
        if benchmark_close is not None:
            m1 = self.motor1.compute(ticker, close, benchmark_close, sector_close, peer_closes)
            all_features.update(m1)

        # Motor 2: Momentum + Trend
        m2 = self.motor2.compute(ticker, close, high, low, volume)
        all_features.update(m2)

        # Motor 3: Hacim + Mikroyapı
        m3 = self.motor3.compute(ticker, open_, close, high, low, volume)
        all_features.update(m3)

        # Motor 4: Fundamental
        if fundamentals:
            m4 = self.motor4.compute(ticker, fundamentals, sector_medians)
            all_features.update(m4)

        # Motor 5: KAP + Haber
        m5 = self.motor5.compute(ticker, kap_events or [], news_events or [])
        all_features.update(m5)

        # Motor 6: Katalizör
        m6 = self.motor6.compute(ticker, upcoming_events or [])
        all_features.update(m6)

        # Motor 7: Neden Düşüyor?
        stock_ret_5d = all_features.get("roc_5d", 0)
        vol_change = all_features.get("volume_zscore", 0)
        news_sent = all_features.get("news_sentiment_weighted", 0)
        kap_sent = all_features.get("kap_sentiment_avg", 0)
        m7 = self.motor7.compute(
            ticker, stock_ret_5d, market_return_5d, sector_return_5d,
            vol_change, news_sent, kap_sent
        )
        all_features.update(m7)

        # NaN/Inf temizle
        cleaned = {}
        for k, v in all_features.items():
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                cleaned[k] = 0.0
            else:
                cleaned[k] = v

        # Regime bilgisi ekle
        cleaned["regime"] = market_regime

        return cleaned


# Singleton
seven_motor_engine = SevenMotorEngine()
