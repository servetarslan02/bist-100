"""
ALPHA BIST — Market Analyst

ML modellerinin çıktılarını insan-okunabilir analize dönüştüren agent.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class MarketAnalyst:
    """Kurumsal ML ve Çok Faktörlü Kantitatif Piyasa Analiz Ajanı.

    Yetenekler:
    - Çok Göstergeli Trend ve Momentum Sentezi (EMA 20/50/200, MACD, RSI, Stokastik)
    - Volatilite ve Sıkışma Tespiti (Bollinger Bandı Daralması, Keltner Kanalı, ATR Yüzdeliği)
    - Hacim Onayı ve Para Giriş/Çıkışı (OBV, Hacim/SMA20 Oranı)
    - Çok Boyutlu Risk Değerlendirmesi (Kuyruk Riski, Oynaklık Şoku, Düşüş Marjı)
    - Kurumsal Seviye Piyasa Rejimi Sınıflandırması ve Eylemsel Strateji Önerisi
    """

    def __init__(self) -> None:
        """Piyasa analist önbelleğini ve parametrelerini ilklendirir."""
        self._cache: dict[str, dict[str, Any]] = {}

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"MarketAnalyst(cached_tickers={len(self._cache)})"

    def analyze_ticker(
        self,
        ticker: str,
        features: dict[str, float] | None = None,
        model_score: float | None = None,
    ) -> dict[str, Any]:
        """Tek hisse için çok faktörlü teknik, model ve risk analiz raporu üretir.

        Args:
            ticker: Hisse senedi sembolü.
            features: Hesaplanmış teknik ve volatilite öznitelikleri.
            model_score: Champion ML modelinden gelen yönlü alfa tahmini skoru.

        Returns:
            dict[str, Any]: Yapılandırılmış analiz, teknik sinyaller, model güveni ve kurumsal özet.
        """
        feat = features or {}
        result: dict[str, Any] = {
            "ticker": ticker.upper(),
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "sections": {},
        }

        # 1. Çok Faktörlü Teknik Analiz
        result["sections"]["technical"] = self._interpret_technical(feat)

        # 2. Model Çıktısı ve Alfa Skoru Yorumu
        if model_score is not None:
            result["sections"]["model"] = self._interpret_model_score(model_score)

        # 3. Kapsamlı Risk & Oynaklık Değerlendirmesi
        result["sections"]["risk"] = self._assess_risk(feat)

        # 4. Kurumsal Yönetici Özeti
        result["summary"] = self._generate_summary(result["sections"], ticker=ticker)

        self._cache[ticker.upper()] = result
        return result

    def summarize_market(
        self,
        bist100_change: float = 0.0,
        advancing_count: int | None = None,
        declining_count: int | None = None,
        market_volume_ratio: float | None = None,
    ) -> dict[str, Any]:
        """Piyasa geneli rejim, piyasa genişliği (market breadth) ve stratejik konumlanma analizi.

        Args:
            bist100_change: BIST 100 endeksi günlük yüzde değişimi.
            advancing_count: Yükselen hisse adedi (varsa).
            declining_count: Düşen hisse adedi (varsa).
            market_volume_ratio: Toplam işlem hacminin 20 günlük ortalamaya oranı.

        Returns:
            dict[str, Any]: Rejim tipi, risk iştahı, piyasa derinliği ve operasyonel tavsiye.
        """
        result: dict[str, Any] = {
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "bist100_change_pct": round(bist100_change, 2),
        }

        # Piyasa genişliği analizi (A/D oranı)
        breadth_ratio = None
        if advancing_count is not None and declining_count is not None and (advancing_count + declining_count) > 0:
            breadth_ratio = advancing_count / max(1, declining_count)
            result["market_breadth"] = {
                "advancing": advancing_count,
                "declining": declining_count,
                "advance_decline_ratio": round(breadth_ratio, 2),
                "breadth_confirmation": "BULLISH" if breadth_ratio > 1.5 else ("BEARISH" if breadth_ratio < 0.67 else "NEUTRAL"),
            }

        # Rejim ve Stratejik Konumlanma Belirleme
        if bist100_change <= -3.0:
            regime = "STRONG_BEARISH"
            regime_tr = "Şiddetli Satış / Panik Düşüşü"
            stance = "DEFENSIVE"
            advice = (
                "Sistemik satış baskısı devrede. Yeni uzun pozisyon açılmamalı, "
                "kaldıraçlı pozisyonlar kapatılmalı, VIOP endeks kısa (short) hedge koruması aktifleştirilmelidir."
            )
        elif bist100_change <= -1.0:
            regime = "BEARISH"
            regime_tr = "Düzeltme / Ayı Eğilimli Seyir"
            stance = "CAUTIOUS"
            advice = (
                "Satıcıların ağırlıkta olduğu zayıf piyasa. Sadece yüksek göreceli güç gösteren defansif "
                "hisselerde sınırlı büyüklükle kalınmalı, stop-loss seviyeleri sıkılaştırılmalıdır."
            )
        elif -1.0 < bist100_change < 1.0:
            # Hacim anomalisi varsa konsolidasyon vs tuzak ayrımı yap
            if market_volume_ratio is not None and market_volume_ratio < 0.70:
                regime = "LOW_VOLUME_CONSOLIDATION"
                regime_tr = "Düşük Hacimli Yatay Bant / Kararsızlık"
                stance = "SELECTIVE"
                advice = "Hacimsiz yatay seyir. Destek-direnç bandı içi scalp veya model güveni en yüksek hisselerle sınırlı işlem."
            else:
                regime = "NEUTRAL"
                regime_tr = "Dengeli / Konsolidasyon Rejimi"
                stance = "SELECTIVE"
                advice = "Endeks yatay bant içinde. Seçici hisse ayrışmaları ve sektör rotasyonları takip edilmeli."
        elif bist100_change < 3.0:
            regime = "BULLISH"
            regime_tr = "Pozitif Trend / Alıcılı Seyir"
            stance = "AGGRESSIVE"
            advice = (
                "Alım iştahı güçlü. Model alfa skoru pozitif olan momentum hisselerinde trend takip edilmeli, "
                "trailing-stop ile kâr maksimize edilmelidir."
            )
        else:
            regime = "STRONG_BULLISH"
            regime_tr = "Güçlü Ralli / Aşırı Alım Bölgesi"
            stance = "TACTICAL_PROFIT_TAKING"
            advice = (
                "Endekste coşkulu ralli izleniyor. Yeni giren pozisyonlarda risk/getiri oranı düşmüş olabilir; "
                "kademeli kâr realizasyonu ve direnç seviyelerinde koruyucu collar/put opsiyonları düşünülmelidir."
            )

        result["regime"] = regime
        result["regime_tr"] = regime_tr
        result["stance"] = stance
        result["advice"] = advice
        return result

    def _interpret_technical(self, features: dict[str, float]) -> dict[str, Any]:
        """Tüm teknik göstergeleri (RSI, MACD, Hareketli Ortalamalar, Bollinger, Hacim) sentezler."""
        signals: list[dict[str, Any]] = []
        bullish_count = 0
        bearish_count = 0

        # 1. RSI Değerlendirmesi
        rsi = features.get("rsi_14") or features.get("rsi")
        if rsi is not None:
            if rsi >= 75:
                signals.append({"indicator": "RSI_14", "signal": "AŞIRI_ALIM_SATIŞ_RİSKİ", "value": round(rsi, 2)})
                bearish_count += 1
            elif rsi <= 25:
                signals.append({"indicator": "RSI_14", "signal": "AŞIRI_SATIM_TEPKİ_ALIMI", "value": round(rsi, 2)})
                bullish_count += 1
            elif rsi > 55:
                signals.append({"indicator": "RSI_14", "signal": "POZİTİF_MOMENTUM", "value": round(rsi, 2)})
                bullish_count += 1
            elif rsi < 45:
                signals.append({"indicator": "RSI_14", "signal": "NEGATİF_MOMENTUM", "value": round(rsi, 2)})
                bearish_count += 1

        # 2. MACD Değerlendirmesi
        macd_hist = features.get("macd_hist") or features.get("macd_histogram")
        if macd_hist is not None:
            if macd_hist > 0:
                signals.append({"indicator": "MACD_HIST", "signal": "BOĞA_HIZLANMASI", "value": round(macd_hist, 4)})
                bullish_count += 1
            elif macd_hist < 0:
                signals.append({"indicator": "MACD_HIST", "signal": "AYI_HIZLANMASI", "value": round(macd_hist, 4)})
                bearish_count += 1

        # 3. Hareketli Ortalama Trend Yapısı
        sma_20 = features.get("sma_20") or features.get("ema_20")
        sma_50 = features.get("sma_50") or features.get("ema_50")
        sma_200 = features.get("sma_200") or features.get("ema_200")
        close_price = features.get("close") or features.get("price")

        if close_price and sma_20:
            if close_price > sma_20:
                signals.append({"indicator": "TREND_20D", "signal": "KISA_VADELİ_MOMENTUM_GÜÇLÜ", "value": round(close_price / sma_20, 3)})
                bullish_count += 1
            else:
                signals.append({"indicator": "TREND_20D", "signal": "KISA_VADELİ_BASKI", "value": round(close_price / sma_20, 3)})
                bearish_count += 1

        if close_price and sma_200:
            if close_price > sma_200:
                signals.append({"indicator": "TREND_200D", "signal": "UZUN_VADELİ_BOĞA_TRENDİ", "value": round(close_price / sma_200, 3)})
                bullish_count += 1
            else:
                signals.append({"indicator": "TREND_200D", "signal": "UZUN_VADELİ_AYI_BASKISI", "value": round(close_price / sma_200, 3)})
                bearish_count += 1

        if sma_50 and sma_200:
            if sma_50 > sma_200:
                signals.append({"indicator": "GOLDEN_CROSS", "signal": "POZİTİF_TREND_DİZİLİMİ", "value": round(sma_50 / sma_200, 3)})
                bullish_count += 1
            elif sma_50 < sma_200:
                signals.append({"indicator": "DEATH_CROSS", "signal": "NEGATİF_TREND_DİZİLİMİ", "value": round(sma_50 / sma_200, 3)})
                bearish_count += 1

        # 4. Volatilite Daralması (Bollinger Squeeze)
        bb_width = features.get("bb_width") or features.get("bollinger_bandwidth")
        if bb_width is not None and bb_width < 0.05:
            signals.append({"indicator": "BOLLINGER_SQUEEZE", "signal": "KUVVETLİ_PATLAMA_BEKLENTİSİ", "value": round(bb_width, 4)})

        # 5. Hacim Onayı (Volume / SMA20 Volume)
        vol_ratio = features.get("volume_ratio_20d") or features.get("volume_surge")
        if vol_ratio is not None:
            if vol_ratio > 2.0:
                signals.append({"indicator": "VOLUME_SURGE", "signal": "KURUMSAL_HACİM_GİRİŞİ", "value": round(vol_ratio, 2)})
                bullish_count += 1
            elif vol_ratio < 0.5:
                signals.append({"indicator": "VOLUME_DRY", "signal": "DÜŞÜK_LİKİDİTE_DURGUNLUK", "value": round(vol_ratio, 2)})

        total_signals = bullish_count + bearish_count
        if total_signals > 0:
            net_technical_score = (bullish_count - bearish_count) / total_signals
        else:
            net_technical_score = 0.0

        trend_bias = "BULLISH" if net_technical_score > 0.25 else ("BEARISH" if net_technical_score < -0.25 else "NEUTRAL")

        return {
            "trend_bias": trend_bias,
            "net_score": round(net_technical_score, 3),
            "bullish_indicators": bullish_count,
            "bearish_indicators": bearish_count,
            "signals": signals,
        }

    def _interpret_model_score(self, score: float) -> dict[str, Any]:
        """Model tahmin skorunu yön, beklenen getiri ve güvenilirlik seviyesine dönüştürür."""
        clamped_score = max(-1.0, min(1.0, float(score)))

        if clamped_score > 0.04:
            direction = "YUKARI"
            conviction = "YÜKSEK" if clamped_score > 0.12 else "ORTA"
        elif clamped_score < -0.04:
            direction = "AŞAĞI"
            conviction = "YÜKSEK" if clamped_score < -0.12 else "ORTA"
        else:
            direction = "NÖTR"
            conviction = "DÜŞÜK"

        # Güven düzeyi (0.0 - 1.0)
        confidence = min(1.0, max(0.1, 0.4 + (abs(clamped_score) * 4.0)))

        return {
            "raw_score": round(clamped_score, 4),
            "direction": direction,
            "conviction": conviction,
            "confidence": round(confidence, 3),
            "annualized_alpha_bps": round(clamped_score * 252 * 100, 1),
        }

    def _assess_risk(self, features: dict[str, float]) -> dict[str, Any]:
        """Özniteliklere dayalı çok boyutlu risk ve volatilite değerlendirmesi yapar."""
        risk_factors: list[dict[str, str]] = []

        # ATR Volatilite Riski
        atr_pct = features.get("atr_pct", 0.0) or features.get("atr_14", 0.0)
        if atr_pct > 4.5:
            risk_factors.append({"factor": "Aşırı Günlük Fiyat Oynaklığı (ATR > %4.5)", "level": "HIGH"})
        elif atr_pct > 2.5:
            risk_factors.append({"factor": "Orta-Yüksek Günlük Oynaklık", "level": "MEDIUM"})

        # Tarihsel Volatilite (HV 20d)
        vol_20d = features.get("hist_vol_20d", 0.0)
        if vol_20d > 55.0:
            risk_factors.append({"factor": "Yüksek Yıllıklandırılmış Oynaklık (> %55)", "level": "HIGH"})

        # Göreceli Zirveden Geri Çekilme (Drawdown)
        drawdown_20d = features.get("drawdown_20d", 0.0)
        if drawdown_20d < -15.0:
            risk_factors.append({"factor": "Son 20 Günde Ciddi Değer Kaybı (< -%15)", "level": "HIGH"})

        # Likidite / Bid-Ask Spread Riski
        spread_bps = features.get("spread_bps", 0.0)
        if spread_bps > 25.0:
            risk_factors.append({"factor": "Geniş Alış-Satış Makası (Likidite Baskısı)", "level": "MEDIUM"})

        # Genel Risk Seviyesi Belirleme
        high_risks = sum(1 for r in risk_factors if r["level"] == "HIGH")
        if high_risks >= 2:
            overall_risk = "ÇOK_YÜKSEK"
            action_limit = "Maksimum pozisyon büyüklüğü %50 azaltılmalı."
        elif high_risks == 1 or len(risk_factors) >= 2:
            overall_risk = "YÜKSEK"
            action_limit = "Pozisyon büyüklüğü %25 azaltılmalı, stop-loss daraltılmalı."
        elif len(risk_factors) == 1:
            overall_risk = "ORTA"
            action_limit = "Standart risk parametreleri uygulanmalı."
        else:
            overall_risk = "DÜŞÜK"
            action_limit = "Optimal risk/getiri profili, tam pozisyon açılabilir."

        return {
            "overall_risk": overall_risk,
            "risk_factors": risk_factors,
            "action_guideline": action_limit,
            "estimated_var_95_daily_pct": round(max(atr_pct * 1.645, 1.5), 2),
        }

    def _generate_summary(self, sections: dict[str, Any], ticker: str = "") -> str:
        """Farklı analiz bölümlerini birleştirerek kurumsal yönetici özeti oluşturur."""
        model = sections.get("model", {})
        technical = sections.get("technical", {})
        risk = sections.get("risk", {})

        parts: list[str] = []

        # Model Yönü
        dir_tr = model.get("direction", "NÖTR")
        conf_pct = model.get("confidence", 0.0) * 100
        if dir_tr == "YUKARI":
            parts.append(f"{ticker} için ML Champion model yukarı yönlü getiri sinyali üretiyor (Güven: %{conf_pct:.0f})")
        elif dir_tr == "AŞAĞI":
            parts.append(f"{ticker} için ML Champion model negatif/aşağı yönlü risk öngörüyor (Güven: %{conf_pct:.0f})")
        else:
            parts.append(f"{ticker} için model net bir yön ayrışması göstermiyor")

        # Teknik Teyit
        tech_bias = technical.get("trend_bias", "NEUTRAL")
        if tech_bias == "BULLISH":
            parts.append("teknik göstergeler güçlü alım momentumunu teyit ediyor")
        elif tech_bias == "BEARISH":
            parts.append("teknik indikatörler satış baskısını ve trend zayıflığını işaret ediyor")
        else:
            parts.append("teknik göstergeler dengeli konsolidasyon bölgesinde")

        # Risk Durumu
        overall_risk = risk.get("overall_risk", "ORTA")
        if overall_risk in {"YÜKSEK", "ÇOK_YÜKSEK"}:
            parts.append(f"⚠️ Dikkat: Risk profili '{overall_risk}' seviyesinde ({risk.get('action_guideline')})")
        else:
            parts.append("risk parametreleri kabul edilebilir sınırlar dahilinde")

        return ". ".join(parts) + "."

    def get_cached_analysis(self, ticker: str) -> dict[str, Any] | None:
        """Belirtilen hisse kodu için önbellekte tutulan analizi döndürür."""
        return self._cache.get(ticker.upper())


market_analyst = MarketAnalyst()

