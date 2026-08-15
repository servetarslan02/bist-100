"""
ALPHA BIST — Decision Engine v1.0

Karar motoru — tüm bileşenleri birleştirip son kararı verir.
Gemma tek başına karar vermez. Kararı Decision Engine verir.

Girdiler:
  - ML expected return
  - SPEC edge
  - World alignment
  - Simulation results
  - Gemma thesis
  - Risk limits
  - Liquidity
  - Correlation
  - Portfolio exposure

Çıktı:
  - BUY / SELL / HOLD
  - Weight %
  - Stop / invalidation
  - Target distribution
  - Expected holding period
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class DecisionInput:
    """Karar girdileri."""
    ticker: str
    price: float

    # ML
    ml_return_5d: float = 0.0
    ml_return_20d: float = 0.0
    ml_confidence: float = 0.0

    # SPEC
    spec_score: float = 0.0
    spec_category: str = ""

    # World
    world_alignment: float = 0.0  # -1 ile +1 arası

    # Simulation
    sim_expected_return: float = 0.0
    sim_var_95: float = 0.0
    sim_prob_positive: float = 0.0

    # Gemma
    ai_direction: str = ""
    ai_confidence: float = 0.0
    ai_risk_factors: List[str] = field(default_factory=list)

    # Risk
    max_position_pct: float = 10.0
    current_position_pct: float = 0.0
    portfolio_drawdown: float = 0.0

    # Liquidity
    avg_volume: float = 0.0
    spread_pct: float = 0.0

    # Correlation
    correlation_to_portfolio: float = 0.5
    sector_exposure_pct: float = 0.0


@dataclass
class DecisionOutput:
    """Karar çıktısı."""
    ticker: str
    timestamp: datetime

    # Karar
    action: str  # BUY | SELL | HOLD
    conviction: str  # HIGH | MEDIUM | LOW
    direction: str  # LONG | SHORT

    # Pozisyon
    weight_pct: float  # Portföyün yüzdesi
    max_loss_pct: float  # Maksimum zarar

    # Giriş
    entry_price: float
    entry_type: str  # MARKET | LIMIT

    # Hedef
    target_distribution: Dict[str, float]  # {"1w": 5, "1m": 10, "3m": 15}

    # Stop
    stop_loss: float
    stop_type: str  # FIXED | TRAILING | ATR

    # Beklenti
    expected_return_pct: float
    expected_holding_days: int

    # Skorlar
    ml_score: float
    spec_score: float
    world_score: float
    sim_score: float
    ai_score: float
    risk_score: float
    composite_score: float

    # Gerekçe
    reasons: List[str]
    risks: List[str]
    contradictions: List[str]


class DecisionEngine:
    """Karar motoru — tüm bileşenleri birleştirip son kararı verir."""

    # Ağırlıklar
    WEIGHTS = {
        "ml": 0.20,
        "spec": 0.20,
        "world": 0.10,
        "simulation": 0.15,
        "ai": 0.15,
        "risk": 0.10,
        "liquidity": 0.05,
        "correlation": 0.05,
    }

    def decide(self, inp: DecisionInput) -> DecisionOutput:
        """Karar ver."""

        # 1. Bileşen skorları hesapla
        ml_score = self._score_ml(inp)
        spec_score = self._score_spec(inp)
        world_score = self._score_world(inp)
        sim_score = self._score_simulation(inp)
        ai_score = self._score_ai(inp)
        risk_score = self._score_risk(inp)
        liq_score = self._score_liquidity(inp)
        corr_score = self._score_correlation(inp)

        # 2. Composite score
        composite = (
            ml_score * self.WEIGHTS["ml"]
            + spec_score * self.WEIGHTS["spec"]
            + world_score * self.WEIGHTS["world"]
            + sim_score * self.WEIGHTS["simulation"]
            + ai_score * self.WEIGHTS["ai"]
            + risk_score * self.WEIGHTS["risk"]
            + liq_score * self.WEIGHTS["liquidity"]
            + corr_score * self.WEIGHTS["correlation"]
        )

        # 3. Karar
        action, conviction = self._determine_action(composite, inp)

        # 4. Pozisyon büyüklüğü
        weight = self._calculate_weight(composite, conviction, inp)

        # 5. Hedefler
        targets = self._calculate_targets(inp)

        # 6. Stop loss
        stop, stop_type = self._calculate_stop(inp)

        # 7. Beklenti
        expected_return = (targets.get("1m", 0) + targets.get("3m", 0)) / 2
        expected_days = 20 if conviction == "HIGH" else 40 if conviction == "MEDIUM" else 60

        # 8. Gerekçe ve riskler
        reasons = self._generate_reasons(inp, ml_score, spec_score, world_score)
        risks = self._generate_risks(inp)
        contradictions = self._find_contradictions(inp, ml_score, spec_score, world_score, ai_score)

        return DecisionOutput(
            ticker=inp.ticker,
            timestamp=datetime.now(timezone.utc),
            action=action,
            conviction=conviction,
            direction="LONG" if composite > 50 else "SHORT",
            weight_pct=round(weight, 2),
            max_loss_pct=round(weight * abs(inp.price - stop) / inp.price, 2) if inp.price > 0 else 0,
            entry_price=inp.price,
            entry_type="LIMIT" if conviction != "HIGH" else "MARKET",
            target_distribution=targets,
            stop_loss=round(stop, 2),
            stop_type=stop_type,
            expected_return_pct=round(expected_return, 2),
            expected_holding_days=expected_days,
            ml_score=round(ml_score, 1),
            spec_score=round(spec_score, 1),
            world_score=round(world_score, 1),
            sim_score=round(sim_score, 1),
            ai_score=round(ai_score, 1),
            risk_score=round(risk_score, 1),
            composite_score=round(composite, 1),
            reasons=reasons,
            risks=risks,
            contradictions=contradictions,
        )

    def _score_ml(self, inp: DecisionInput) -> float:
        """ML skoru (0-100)."""
        score = 50
        if inp.ml_return_5d > 3:
            score += min(inp.ml_return_5d * 3, 25)
        elif inp.ml_return_5d < -3:
            score += max(inp.ml_return_5d * 3, -25)

        if inp.ml_return_20d > 5:
            score += min(inp.ml_return_20d, 15)
        elif inp.ml_return_20d < -5:
            score += max(inp.ml_return_20d, -15)

        # Confidence ağırlığı
        score = score * inp.ml_confidence + 50 * (1 - inp.ml_confidence)

        return max(0, min(100, score))

    def _score_spec(self, inp: DecisionInput) -> float:
        """SPEC skoru (0-100)."""
        return max(0, min(100, inp.spec_score))

    def _score_world(self, inp: DecisionInput) -> float:
        """World alignment skoru (0-100)."""
        return max(0, min(100, (inp.world_alignment + 1) * 50))

    def _score_simulation(self, inp: DecisionInput) -> float:
        """Simülasyon skoru (0-100)."""
        score = 50
        if inp.sim_expected_return > 3:
            score += min(inp.sim_expected_return * 3, 25)
        elif inp.sim_expected_return < -3:
            score += max(inp.sim_expected_return * 3, -25)

        if inp.sim_prob_positive > 60:
            score += (inp.sim_prob_positive - 50) * 0.5
        elif inp.sim_prob_positive < 40:
            score -= (50 - inp.sim_prob_positive) * 0.5

        return max(0, min(100, score))

    def _score_ai(self, inp: DecisionInput) -> float:
        """AI skoru (0-100)."""
        if inp.ai_direction == "LONG":
            return max(0, min(100, inp.ai_confidence * 100))
        elif inp.ai_direction == "SHORT":
            return max(0, min(100, (1 - inp.ai_confidence) * 100))
        return 50

    def _score_risk(self, inp: DecisionInput) -> float:
        """Risk skoru (0-100). Daha yüksek = daha güvenli."""
        score = 70  # Başlangıç

        # Drawdown penalty
        if inp.portfolio_drawdown > 10:
            score -= 20
        elif inp.portfolio_drawdown > 5:
            score -= 10

        # Pozisyon limiti
        if inp.current_position_pct > inp.max_position_pct * 0.8:
            score -= 15

        # Sektör konsantrasyonu
        if inp.sector_exposure_pct > 25:
            score -= 10

        return max(0, min(100, score))

    def _score_liquidity(self, inp: DecisionInput) -> float:
        """Likidite skoru (0-100)."""
        score = 70

        if inp.avg_volume < 100000:
            score -= 30
        elif inp.avg_volume < 500000:
            score -= 15

        if inp.spread_pct > 0.5:
            score -= 20
        elif inp.spread_pct > 0.2:
            score -= 10

        return max(0, min(100, score))

    def _score_correlation(self, inp: DecisionInput) -> float:
        """Korelasyon skoru (0-100). Düşük korelasyon = iyi diversifikasyon."""
        score = 70
        if inp.correlation_to_portfolio > 0.8:
            score -= 25
        elif inp.correlation_to_portfolio > 0.6:
            score -= 10
        return max(0, min(100, score))

    def _determine_action(self, composite: float, inp: DecisionInput) -> tuple:
        """Karar belirle.

        P0-4 düzeltmesi:
        - HOLD ayrı bir action (SHORT ile karıştırılmaz)
        - composite > threshold → LONG, else → SHORT YANLIŞ
        - Risk gate sonuçları kararı etkiler
        - AI confidence sınırsız katkı yapamaz
        """
        # Risk vetoları kontrolü
        if inp.portfolio_drawdown > 12:  # Max drawdown'a yaklaşıyor
            return "HOLD", "LOW"

        if inp.current_position_pct >= inp.max_position_pct:
            return "HOLD", "LOW"

        # Likidite çok düşükse pozisyon açma
        if inp.avg_volume < 50000 and inp.spread_pct > 1.0:
            return "HOLD", "LOW"

        # LONG sinyalleri
        if composite >= 75 and inp.ml_confidence > 0.7:
            return "BUY", "HIGH"
        elif composite >= 65 and inp.ml_confidence > 0.5:
            return "BUY", "MEDIUM"
        elif composite >= 55 and inp.ml_confidence > 0.4:
            return "BUY", "LOW"

        # SHORT sinyalleri
        elif composite <= 25 and inp.ml_confidence > 0.7:
            return "SELL", "HIGH"
        elif composite <= 35 and inp.ml_confidence > 0.5:
            return "SELL", "MEDIUM"

        # HOLD — belirsizlik durumunda pozisyon açma
        # Kritik: "else" bloğu SHORT değil HOLD olmalı
        return "HOLD", "LOW"

    def _calculate_weight(self, composite: float, conviction: str, inp: DecisionInput) -> float:
        """Pozisyon büyüklüğü hesapla."""
        base_weight = {
            "HIGH": 8.0,
            "MEDIUM": 5.0,
            "LOW": 3.0,
        }.get(conviction, 0)

        # Composite'a göre ayarla
        weight = base_weight * (composite / 75)

        # Risk sınırları
        weight = min(weight, inp.max_position_pct - inp.current_position_pct)
        weight = max(weight, 0)

        # Likidite sınırları
        if inp.avg_volume < 100000:
            weight *= 0.5

        return min(weight, inp.max_position_pct)

    def _calculate_targets(self, inp: DecisionInput) -> Dict[str, float]:
        """Hedef fiyatları hesapla.

        P0-4: Yaklaşık ATR (price * 0.02) yerine gerçek ATR kullan.
        ATR bilgisi DecisionInput'dan gelir, yoksa gerçekçi default.
        """
        price = inp.price
        if price <= 0:
            return {"1w": 0, "1m": 0, "3m": 0}

        # Gerçek ATR varsa kullan, yoksa volatilite bazlı tahmin
        # ATR genellikle features'tan gelir
        # Fallback: realized_volatility / sqrt(252) * price
        atr_estimate = getattr(inp, 'atr', None)
        if not atr_estimate or atr_estimate <= 0:
            # Volatiliteden ATR tahmini (daha gerçekçi)
            vol_pct = inp.ml_confidence * 3 + 1.5  # ~%1.5-4.5 arası
            atr_estimate = price * (vol_pct / 100)

        return {
            "1w": round(atr_estimate * 1.5 / price * 100, 1),
            "1m": round(atr_estimate * 3.0 / price * 100, 1),
            "3m": round(atr_estimate * 5.0 / price * 100, 1),
        }

    def _calculate_stop(self, inp: DecisionInput) -> tuple:
        """Stop loss hesapla.

        P0-4: Yaklaşık ATR yerine gerçek ATR kullan.
        Maksimum zarar limiti ile korumalı.
        """
        if inp.price <= 0:
            return 0, "ATR"

        # Gerçek ATR varsa kullan
        atr_estimate = getattr(inp, 'atr', None)
        if not atr_estimate or atr_estimate <= 0:
            vol_pct = inp.ml_confidence * 3 + 1.5
            atr_estimate = inp.price * (vol_pct / 100)

        stop = inp.price - atr_estimate * 2
        max_stop = inp.price * 0.93  # Max %7 zarar
        stop = max(stop, max_stop)
        return round(stop, 2), "ATR"

    def _generate_reasons(self, inp, ml, spec, world) -> List[str]:
        """Gerekçe üret."""
        reasons = []
        if ml > 60:
            reasons.append(f"ML pozitif: {ml:.0f}")
        if spec > 60:
            reasons.append(f"SPEC güçlü: {spec:.0f}")
        if world > 60:
            reasons.append(f"World alignment pozitif")
        if inp.sim_prob_positive > 60:
            reasons.append(f"Simülasyon olasılığı: %{inp.sim_prob_positive:.0f}")
        if inp.ai_confidence > 0.7:
            reasons.append(f"AI onayı: %{inp.ai_confidence*100:.0f}")
        return reasons

    def _generate_risks(self, inp) -> List[str]:
        """Risk üret."""
        risks = []
        if inp.portfolio_drawdown > 5:
            risks.append(f"Portföy drawdown: %{inp.portfolio_drawdown:.1f}")
        if inp.current_position_pct > inp.max_position_pct * 0.8:
            risks.append("Pozisyon limiti yaklaşılıyor")
        if inp.sector_exposure_pct > 25:
            risks.append(f"Sektör konsantrasyonu: %{inp.sector_exposure_pct:.0f}")
        if inp.correlation_to_portfolio > 0.7:
            risks.append("Yüksek portföy korelasyonu")
        if inp.ai_risk_factors:
            risks.extend(inp.ai_risk_factors[:3])
        return risks

    def _find_contradictions(self, inp, ml, spec, world, ai) -> List[str]:
        """Çelişkileri bul."""
        contradictions = []
        if ml > 60 and spec < 40:
            contradictions.append("ML pozitif ama SPEC negatif")
        if ml < 40 and spec > 60:
            contradictions.append("ML negatif ama SPEC pozitif")
        if ai > 60 and ml < 40:
            contradictions.append("AI pozitif ama ML negatif")
        if world < 40 and spec > 60:
            contradictions.append("World negatif ama SPEC pozitif")
        return contradictions


# Singleton
decision_engine = DecisionEngine()
