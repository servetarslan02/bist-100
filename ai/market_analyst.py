"""
ALPHA BIST — Market Analyst

ML modellerinin çıktılarını insan-okunabilir analize dönüştüren agent.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class MarketAnalyst:
    """ML destekli piyasa analiz agent'ı."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def analyze_ticker(self, ticker: str, features: Optional[Dict[str, float]] = None,
                       model_score: Optional[float] = None) -> Dict[str, Any]:
        """Tek hisse için analiz üret."""
        result = {
            "ticker": ticker,
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "sections": {},
        }

        if features:
            result["sections"]["technical"] = self._interpret_technical(features)

        if model_score is not None:
            result["sections"]["model"] = self._interpret_model_score(model_score)

        if features:
            result["sections"]["risk"] = self._assess_risk(features)

        result["summary"] = self._generate_summary(result["sections"])
        self._cache[ticker] = result
        return result

    def summarize_market(self, bist100_change: float = 0.0) -> Dict[str, Any]:
        """Piyasa geneli özet."""
        result = {
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "bist100_change_pct": bist100_change,
        }

        if bist100_change <= -3.0:
            result["regime"] = "STRONG_BEARISH"
            result["regime_tr"] = "Güçlü düşüş trendi"
            result["advice"] = "Defansif pozisyon önerilir."
        elif bist100_change <= -1.0:
            result["regime"] = "BEARISH"
            result["regime_tr"] = "Düşüş trendi"
            result["advice"] = "Dikkatli olun."
        elif bist100_change <= 1.0:
            result["regime"] = "NEUTRAL"
            result["regime_tr"] = "Yatay seyir"
            result["advice"] = "Seçici hisse alımı yapılabilir."
        elif bist100_change <= 3.0:
            result["regime"] = "BULLISH"
            result["regime_tr"] = "Yükseliş trendi"
            result["advice"] = "Momentum hisseleri değerlendirilebilir."
        else:
            result["regime"] = "STRONG_BULLISH"
            result["regime_tr"] = "Güçlü yükseliş trendi"
            result["advice"] = "Kar realizasyonu düşünülebilir."

        return result

    def _interpret_technical(self, features: Dict[str, float]) -> Dict[str, Any]:
        signals = []
        rsi = features.get("rsi_14")
        if rsi is not None:
            if rsi > 70:
                signals.append({"indicator": "RSI", "signal": "SATIŞ", "value": rsi})
            elif rsi < 30:
                signals.append({"indicator": "RSI", "signal": "ALIŞ", "value": rsi})
        return {"signals": signals}

    def _interpret_model_score(self, score: float) -> Dict[str, Any]:
        if score > 0.05:
            direction = "YUKARI"
            confidence = min(abs(score) * 10, 1.0)
        elif score < -0.05:
            direction = "AŞAĞI"
            confidence = min(abs(score) * 10, 1.0)
        else:
            direction = "NÖTR"
            confidence = 0.3
        return {"score": round(score, 4), "direction": direction, "confidence": round(confidence, 2)}

    def _assess_risk(self, features: Dict[str, float]) -> Dict[str, Any]:
        risk_factors = []
        atr = features.get("atr_pct", 0)
        if atr > 3.0:
            risk_factors.append({"factor": "Yüksek volatilite", "level": "HIGH"})
        return {"risk_factors": risk_factors, "overall_risk": "YÜKSEK" if len(risk_factors) >= 2 else "ORTA" if risk_factors else "DÜŞÜK"}

    def _generate_summary(self, sections: Dict[str, Any]) -> str:
        model = sections.get("model", {})
        risk = sections.get("risk", {})
        parts = []
        if model.get("direction") == "YUKARI":
            parts.append(f"Model yukarı yön işaret ediyor (güven: %{model.get('confidence', 0)*100:.0f})")
        elif model.get("direction") == "AŞAĞI":
            parts.append(f"Model aşağı yön işaret ediyor")
        else:
            parts.append("Model belirgin yön göstermiyor")
        if risk.get("overall_risk") == "YÜKSEK":
            parts.append("⚠️ Yüksek risk")
        return ". ".join(parts) + "."

    def get_cached_analysis(self, ticker: str) -> Optional[Dict[str, Any]]:
        return self._cache.get(ticker)


market_analyst = MarketAnalyst()
