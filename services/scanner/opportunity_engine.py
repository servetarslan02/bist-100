"""
ALPHA BIST — Opportunity Discovery Engine v1.0

BIST'in tamamından en güçlü fırsatları bulur:
- Candidate filtering (likidite, veri kalitesi)
- Technical filter (momentum, trend, breakout)
- Fundamental filter (değerleme, kalite, büyüme)
- Macro compatibility (rejim uyumu)
- Sentiment (haber, KAP, sosyal)
- AI evidence (agent sonuçları)
- Risk filter (volatilite, korelasyon)
- Opportunity score (risk-adjusted)
- Ranking

FAZ 8: Opportunity Discovery Engine
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class OpportunityScore:
    """Fırsat skoru — çok boyutlu."""
    ticker: str
    timestamp: datetime

    # Bileşen skorları (0-100)
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    volatility_score: float = 0.0
    sentiment_score: float = 0.0
    valuation_score: float = 0.0
    macro_score: float = 0.0
    regime_score: float = 0.0
    risk_score: float = 0.0

    # Ağırlıklı toplam
    opportunity_score: float = 0.0
    risk_adjusted_score: float = 0.0

    # Ranking
    rank: int = 0

    # Meta
    price: float = 0.0
    change_1d_pct: float = 0.0
    signal_type: str = ""
    signal_direction: str = ""
    confidence: float = 0.0

    # Decomposition
    decomposition: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


class OpportunityDiscoveryEngine:
    """Fırsat keşif motoru.

    800+ hisseyi tarar, fırsatları risk-adjusted şekilde sıralar.
    """

    # Ağırlıklar (rejime göre değişebilir)
    DEFAULT_WEIGHTS = {
        "technical": 0.15,
        "fundamental": 0.10,
        "momentum": 0.20,
        "volume": 0.10,
        "volatility": 0.05,
        "sentiment": 0.08,
        "valuation": 0.10,
        "macro": 0.07,
        "regime": 0.10,
        "risk": 0.05,
    }

    REGIME_WEIGHTS = {
        "BULL": {"momentum": 0.25, "technical": 0.20, "risk": 0.03},
        "BEAR": {"risk": 0.15, "fundamental": 0.15, "momentum": 0.10},
        "SIDEWAYS": {"fundamental": 0.15, "valuation": 0.15, "momentum": 0.10},
        "HIGH-VOLATILITY": {"risk": 0.15, "volatility": 0.10, "momentum": 0.10},
        "RISK-ON": {"momentum": 0.25, "technical": 0.20, "sentiment": 0.10},
        "RISK-OFF": {"risk": 0.15, "fundamental": 0.15, "valuation": 0.12},
        "CRISIS": {"risk": 0.20, "fundamental": 0.15, "momentum": 0.05},
        "RECOVERY": {"momentum": 0.20, "technical": 0.15, "sentiment": 0.10},
    }

    def compute_opportunity_score(
        self,
        ticker: str,
        features: dict[str, float],
        market_regime: str = "RANGE",
        ml_score: float = 50.0,
        event_score: float = 50.0,
        sentiment_score: float = 50.0,
        fundamental_score: float = 50.0,
        valuation_score: float = 50.0,
        macro_score: float = 50.0,
    ) -> OpportunityScore:
        """Tek hisse için fırsat skoru hesapla."""
        score = OpportunityScore(
            ticker=ticker,
            timestamp=datetime.now(UTC),
            price=features.get("price", 0) or features.get("close", 0),
            change_1d_pct=features.get("return_1d", 0),
        )

        # Bileşen skorları
        score.technical_score = self._compute_technical_score(features)
        score.fundamental_score = fundamental_score
        score.momentum_score = self._compute_momentum_score(features)
        score.volume_score = self._compute_volume_score(features)
        score.volatility_score = self._compute_volatility_score(features)
        score.sentiment_score = sentiment_score
        score.valuation_score = valuation_score
        score.macro_score = macro_score
        score.regime_score = self._compute_regime_fit(features, market_regime)
        score.risk_score = self._compute_risk_score(features)

        # Ağırlıkları belirle (rejime göre)
        weights = dict(self.DEFAULT_WEIGHTS)
        regime_overrides = self.REGIME_WEIGHTS.get(market_regime, {})
        weights.update(regime_overrides)

        # Ağırlıklı toplam
        score.opportunity_score = (
            score.technical_score * weights.get("technical", 0.15)
            + score.fundamental_score * weights.get("fundamental", 0.10)
            + score.momentum_score * weights.get("momentum", 0.20)
            + score.volume_score * weights.get("volume", 0.10)
            + score.volatility_score * weights.get("volatility", 0.05)
            + score.sentiment_score * weights.get("sentiment", 0.08)
            + score.valuation_score * weights.get("valuation", 0.10)
            + score.macro_score * weights.get("macro", 0.07)
            + score.regime_score * weights.get("regime", 0.10)
            + score.risk_score * weights.get("risk", 0.05)
        )

        # Risk-adjusted score
        risk_penalty = max(0, (100 - score.risk_score) / 100) * 0.2
        score.risk_adjusted_score = score.opportunity_score * (1 - risk_penalty)

        # Decomposition
        score.decomposition = {
            "technical": round(float(score.technical_score) * weights.get("technical", 0.15), 1),
            "fundamental": round(float(score.fundamental_score) * weights.get("fundamental", 0.10), 1),
            "momentum": round(float(score.momentum_score) * weights.get("momentum", 0.20), 1),
            "volume": round(float(score.volume_score) * weights.get("volume", 0.10), 1),
            "volatility": round(float(score.volatility_score) * weights.get("volatility", 0.05), 1),
            "sentiment": round(float(score.sentiment_score) * weights.get("sentiment", 0.08), 1),
            "valuation": round(float(score.valuation_score) * weights.get("valuation", 0.10), 1),
            "macro": round(float(score.macro_score) * weights.get("macro", 0.07), 1),
            "regime": round(float(score.regime_score) * weights.get("regime", 0.10), 1),
            "risk": round(float(score.risk_score) * weights.get("risk", 0.05), 1),
        }

        # Signal type belirle
        score.signal_type, score.signal_direction = self._determine_signal(score, features)

        # Confidence
        score.confidence = min(score.opportunity_score / 100, 0.95)

        # Evidence ve risks
        score.evidence = self._generate_evidence(score, features)
        score.risks = self._generate_risks(score, features)

        return score

    def _compute_technical_score(self, f: dict) -> float:
        """Teknik skor (0-100)."""
        score = 50.0

        # RSI
        rsi = f.get("rsi_14", 50)
        if rsi > 70:
            score -= 10  # Aşırı alım
        elif rsi < 30:
            score += 10  # Aşırı satım (fırsat)
        elif 40 < rsi < 60:
            score += 5  # Nötr bölge

        # MACD
        macd = f.get("macd_histogram", 0)
        if macd > 0:
            score += 5
        elif macd < 0:
            score -= 5

        # Bollinger position
        bb = f.get("bb_position", 0.5)
        if bb > 0.9:
            score -= 5  # Üst banda yakın
        elif bb < 0.1:
            score += 10  # Alt banda yakın (fırsat)

        # ADX (trend gücü)
        adx = f.get("adx", 0)
        if adx > 25:
            score += 5  # Güçlü trend

        return max(0, min(100, score))

    def _compute_momentum_score(self, f: dict) -> float:
        """Momentum skoru (0-100)."""
        score = 50.0

        roc_5d = f.get("roc_5d", 0)
        roc_20d = f.get("roc_20d", 0) or f.get("momentum_20d", 0)

        if roc_5d > 3:
            score += min(roc_5d * 3, 20)
        elif roc_5d < -3:
            score += max(roc_5d * 3, -20)

        if roc_20d > 5:
            score += min(roc_20d, 15)
        elif roc_20d < -5:
            score += max(roc_20d, -15)

        # Hızlanma
        accel = f.get("price_acceleration", 0)
        if accel > 0:
            score += 5
        elif accel < 0:
            score -= 5

        return max(0, min(100, score))

    def _compute_volume_score(self, f: dict) -> float:
        """Hacim skoru (0-100)."""
        score = 50.0

        vol_z = f.get("volume_zscore", 0)
        if vol_z > 3:
            score += 25
        elif vol_z > 2:
            score += 15
        elif vol_z > 1:
            score += 5
        elif vol_z < -1:
            score -= 10

        # Volume ratio
        vol_ratio = f.get("volume_ratio_20d", 1)
        if vol_ratio > 2:
            score += 10
        elif vol_ratio > 1.5:
            score += 5

        return max(0, min(100, score))

    def _compute_volatility_score(self, f: dict) -> float:
        """Volatilite skoru (0-100). Düşük volatilite = yüksek skor."""
        score = 70.0

        atr_pct = f.get("atr_14_pct", 2)
        if atr_pct > 5:
            score -= 25
        elif atr_pct > 3:
            score -= 10
        elif atr_pct < 1.5:
            score += 10

        vol_20d = f.get("realized_vol_20d", 20)
        if vol_20d > 40:
            score -= 20
        elif vol_20d > 25:
            score -= 5
        elif vol_20d < 15:
            score += 10

        return max(0, min(100, score))

    def _compute_regime_fit(self, f: dict, regime: str) -> float:
        """Rejim uyumu (0-100)."""
        mom = f.get("momentum_20d", 0) or f.get("roc_20d", 0)

        regime_fit = {
            "BULL": {"LONG": 85, "SHORT": 15},
            "BEAR": {"LONG": 15, "SHORT": 85},
            "SIDEWAYS": {"LONG": 50, "SHORT": 50},
            "HIGH-VOLATILITY": {"LONG": 40, "SHORT": 60},
            "LOW-VOLATILITY": {"LONG": 60, "SHORT": 40},
            "RISK-ON": {"LONG": 80, "SHORT": 20},
            "RISK-OFF": {"LONG": 20, "SHORT": 80},
            "CRISIS": {"LONG": 10, "SHORT": 90},
            "RECOVERY": {"LONG": 70, "SHORT": 30},
            "MOMENTUM-EXPANSION": {"LONG": 90, "SHORT": 10},
            "MOMENTUM-CONTRACTION": {"LONG": 10, "SHORT": 90},
        }

        direction = "LONG" if mom > 0 else "SHORT"
        fit = regime_fit.get(regime, {"LONG": 50, "SHORT": 50})
        return fit.get(direction, 50)

    def _compute_risk_score(self, f: dict) -> float:
        """Risk skoru (0-100). Yüksek = güvenli."""
        score = 70.0

        vol_20d = f.get("realized_vol_20d", 20)
        if vol_20d > 40:
            score -= 25
        elif vol_20d > 30:
            score -= 15
        elif vol_20d < 15:
            score += 10

        amihud = f.get("amihud_illiquidity", 0)
        if amihud > 0.01:
            score -= 20
        elif amihud > 0.005:
            score -= 10

        corr = abs(f.get("correlation_to_index", 0.5))
        if corr > 0.9:
            score -= 10

        return max(0, min(100, score))

    def _determine_signal(self, score: OpportunityScore, f: dict) -> tuple[str, str]:
        """Sinyal türü ve yönünü belirle."""
        if score.opportunity_score < 50:
            return "", "NEUTRAL"

        # Sinyal türü
        if score.volume_score > 70 and score.momentum_score > 70:
            signal_type = "MOMENTUM"
        elif score.volume_score > 80:
            signal_type = "VOLUME_ANOMALY"
        elif score.technical_score > 75:
            signal_type = "BREAKOUT"
        elif score.regime_score > 75:
            signal_type = "REGIME"
        else:
            signal_type = "SPEC"

        # Yön
        mom = f.get("momentum_20d", 0) or f.get("roc_20d", 0)
        direction = "LONG" if mom > 0 else "SHORT"

        return signal_type, direction

    def _generate_evidence(self, score: OpportunityScore, f: dict) -> list[str]:
        """Gerekçe üret."""
        evidence = []

        if score.momentum_score > 65:
            evidence.append(f"Momentum güçlü: {score.momentum_score:.0f}")
        if score.volume_score > 65:
            vol_z = f.get("volume_zscore", 0)
            evidence.append(f"Hacim anomalisi: {vol_z:.1f}σ")
        if score.technical_score > 65:
            evidence.append(f"Teknik pozitif: {score.technical_score:.0f}")
        if score.regime_score > 70:
            evidence.append(f"Rejim uyumu yüksek: {score.regime_score:.0f}")
        if score.sentiment_score > 65:
            evidence.append("Sentiment pozitif")
        if score.valuation_score > 65:
            evidence.append("Değerleme cazip")

        return evidence

    def _generate_risks(self, score: OpportunityScore, f: dict) -> list[str]:
        """Risk üret."""
        risks = []

        if score.risk_score < 50:
            risks.append(f"Yüksek risk: {score.risk_score:.0f}")
        if score.volatility_score < 40:
            vol_20d = f.get("realized_vol_20d", 0)
            risks.append(f"Yüksek volatilite: %{vol_20d:.0f}")
        rsi = f.get("rsi_14", 50)
        if rsi > 75:
            risks.append(f"Aşırı alım: RSI={rsi:.0f}")
        if rsi < 25:
            risks.append(f"Aşırı satım: RSI={rsi:.0f}")

        return risks

    def scan_universe(
        self,
        universe: list[str],
        features_map: dict[str, dict[str, float]],
        market_regime: str = "RANGE",
        ml_scores: dict[str, float] | None = None,
        event_scores: dict[str, float] | None = None,
        sentiment_scores: dict[str, float] | None = None,
        fundamental_scores: dict[str, float] | None = None,
        valuation_scores: dict[str, float] | None = None,
        macro_scores: dict[str, float] | None = None,
    ) -> list[OpportunityScore]:
        """Tüm BIST'i tara ve fırsatları sırala."""
        results = []

        for ticker in universe:
            features = features_map.get(ticker)
            if not features:
                continue

            score = self.compute_opportunity_score(
                ticker=ticker,
                features=features,
                market_regime=market_regime,
                ml_score=(ml_scores or {}).get(ticker, 50),
                event_score=(event_scores or {}).get(ticker, 50),
                sentiment_score=(sentiment_scores or {}).get(ticker, 50),
                fundamental_score=(fundamental_scores or {}).get(ticker, 50),
                valuation_score=(valuation_scores or {}).get(ticker, 50),
                macro_score=(macro_scores or {}).get(ticker, 50),
            )
            results.append(score)

        # Sırala (risk-adjusted)
        results.sort(key=lambda r: r.risk_adjusted_score, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        logger.info("Universe scan completed",
                    total=len(results),
                    top_score=results[0].risk_adjusted_score if results else 0)

        return results

    def get_top_opportunities(
        self,
        results: list[OpportunityScore],
        limit: int = 20,
        min_score: float = 50.0,
    ) -> list[dict[str, Any]]:
        """En iyi fırsatları getir."""
        filtered = [r for r in results if r.risk_adjusted_score >= min_score]

        return [
            {
                "rank": r.rank,
                "ticker": r.ticker,
                "score": round(float(r.risk_adjusted_score), 1),
                "signal": r.signal_type,
                "direction": r.signal_direction,
                "confidence": round(float(r.confidence), 2),
                "price": r.price,
                "change_1d": r.change_1d_pct,
                "decomposition": r.decomposition,
                "evidence": r.evidence,
                "risks": r.risks,
            }
            for r in filtered[:limit]
        ]


# Singleton
opportunity_engine = OpportunityDiscoveryEngine()


# =====================================================
# Scanner Modül Bağlantıları
# =====================================================
def run_full_scan(universe: list[str], market_data: dict = None) -> list[dict]:
    """Tüm scanner modüllerini çalıştır."""
    results = []
    try:
        from .alpha_engine import AlphaEngine
        alpha = AlphaEngine()
        if hasattr(alpha, 'scan'):
            scan_result = alpha.scan(universe, market_data)
            results.append({"engine": "alpha", "status": "ok", "results": scan_result})
        else:
            results.append({"engine": "alpha", "status": "available"})
    except ImportError:
        logger.debug("Optional import not available in run_full_scan", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="AlphaEngine", error=str(e))
    try:
        from .alpha_scanner import AlphaScanner
        scanner = AlphaScanner()
        if hasattr(scanner, 'scan'):
            scan_result = scanner.scan(universe, market_data or {})
            results.append({"engine": "alpha_scanner", "status": "ok", "results": scan_result})
        else:
            results.append({"engine": "alpha_scanner", "status": "available"})
    except ImportError:
        logger.debug("Optional import not available in run_full_scan", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="AlphaScanner", error=str(e))
    try:
        from .event_scanner import EventScanner
        scanner = EventScanner()
        if hasattr(scanner, 'scan'):
            scan_result = scanner.scan(universe, market_data)
            results.append({"engine": "event_scanner", "status": "ok", "results": scan_result})
        else:
            results.append({"engine": "event_scanner", "status": "available"})
    except ImportError:
        logger.debug("Optional import not available in run_full_scan", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="EventScanner", error=str(e))
    try:
        from .live_scanner import LiveScanner
        scanner = LiveScanner()
        if hasattr(scanner, 'scan'):
            scan_result = scanner.scan(universe, market_data)
            results.append({"engine": "live_scanner", "status": "ok", "results": scan_result})
        else:
            results.append({"engine": "live_scanner", "status": "available"})
    except ImportError:
        logger.debug("Optional import not available in run_full_scan", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="LiveScanner", error=str(e))
    try:
        from .tiered_scanner import TieredScanner
        scanner = TieredScanner()
        if hasattr(scanner, 'scan'):
            scan_result = scanner.scan(universe, market_data)
            results.append({"engine": "tiered_scanner", "status": "ok", "results": scan_result})
        else:
            results.append({"engine": "tiered_scanner", "status": "available"})
    except ImportError:
        logger.debug("Optional import not available in run_full_scan", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="TieredScanner", error=str(e))
    try:
        from .event_queue import EventQueue
        EventQueue()
        results.append({"engine": "event_queue", "status": "available"})
    except ImportError:
        logger.debug("Optional import not available in run_full_scan", exc_info=True)
    except Exception as e:
        logger.warning("Failed to load module", module="EventQueue", error=str(e))
    return results
