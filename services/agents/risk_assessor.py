"""
ALPHA BIST — Risk Assessor Agent v2.1

Risk agent — tüm sonuçları değerlendirir.
Veto yetkisi var (CRITICAL risk = işlem durdur).

v2.1 değişiklikleri:
- Risk seviye eşik mantığı düzeltmesi (boundary hatası)
- regime kaynağı düzeltmesi (features → context)
- Veto log'u eklendi
- RiskAssessment.__repr__ eklendi
- Pozisyon boyutu minimum sınırı ayarlandı

FAZ 6: Risk Assessment
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

from .agent_system import AgentResult, AgentRole
from .llm_client import BaseLLMClient
from .prompts import PromptFactory

logger = logging.getLogger(__name__)


@dataclass
class RiskAssessment:
    """Risk değerlendirme sonucu — onay durumu, seviye, pozisyon limitleri."""

    approved: bool
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    risk_score: float  # 0-100
    max_position_pct: float  # Maksimum pozisyon yüzdesi
    stop_loss_pct: float  # Stop-loss yüzdesi
    risk_factors: list[str]
    veto_reason: str | None = None
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "approved": self.approved,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "max_position_pct": self.max_position_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "risk_factors": self.risk_factors,
            "veto_reason": self.veto_reason,
            "reasoning": self.reasoning[:300],
        }

    def __repr__(self) -> str:
        return (
            f"RiskAssessment(level={self.risk_level!r}, score={self.risk_score:.1f}, "
            f"approved={self.approved}, max_pos={self.max_position_pct:.1f}%)"
        )


class RiskAssessor:
    """Risk değerlendirme agent'ı.

    Kurallar:
    - Volatilite riski (ATR, standart sapma)
    - Likidite riski (düşük hacim)
    - Konsantrasyon riski (portföydeki pay)
    - Makro risk (rejim, CDS)
    - CRITICAL = veto (işlem durdur)
    """

    # Risk seviye eşikleri (üst sınır dahil)
    # LOW: 0-30, MEDIUM: 30-50, HIGH: 50-70, CRITICAL: 70+
    RISK_THRESHOLDS = {
        "LOW": 30,
        "MEDIUM": 50,
        "HIGH": 70,
        "CRITICAL": 85,
    }

    # Veto koşulları
    VETO_CONDITIONS = [
        "extreme_volatility",
        "liquidity_crisis",
        "halt_risk",
        "regulatory_risk",
    ]

    async def assess(
        self,
        ticker: str,
        agent_results: dict[AgentRole, AgentResult],
        features: dict[str, float],
        portfolio_info: dict | None = None,
        llm_client: BaseLLMClient | None = None,
        context: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        """Risk değerlendirmesi yap.

        Args:
            ticker: Hisse kodu
            agent_results: Agent sonuçları
            features: Feature'lar (teknik göstergeler)
            portfolio_info: Portföy bilgisi
            llm_client: LLM client
            context: Ek bağlam (regime, sector, vb.)

        Returns:
            RiskAssessment
        """
        start = time.monotonic()

        risk_factors = []
        risk_score = 0.0

        # 1. Volatilite riski
        atr_pct = features.get("atr_pct", 0)
        if atr_pct > 5:
            risk_score += 25
            risk_factors.append(f"Yüksek volatilite: ATR %{atr_pct:.1f}")
        elif atr_pct > 3:
            risk_score += 15
            risk_factors.append(f"Orta volatilite: ATR %{atr_pct:.1f}")

        # 2. Likidite riski
        volume_zscore = features.get("volume_zscore", 0)
        avg_volume = features.get("avg_volume_5d", 0)
        if avg_volume < 100000:
            risk_score += 20
            risk_factors.append(f"Düşük hacim: {avg_volume:,.0f}")
        if volume_zscore < -2:
            risk_score += 10
            risk_factors.append(f"Hacim anomalisi (düşük): {volume_zscore:.1f}σ")

        # 3. Çelişki riski
        valid_results = {r: res for r, res in agent_results.items() if res.success}
        directions = [res.output.get("direction") for res in valid_results.values()]
        long_count = directions.count("LONG")
        short_count = directions.count("SHORT")
        if long_count > 0 and short_count > 0:
            risk_score += 15
            risk_factors.append(f"Agent çelişkisi: {long_count} LONG, {short_count} SHORT")

        # 4. Düşük güven riski
        avg_confidence = sum(r.confidence for r in valid_results.values()) / len(valid_results) if valid_results else 0
        if avg_confidence < 0.4:
            risk_score += 15
            risk_factors.append(f"Düşük ortalama güven: {avg_confidence:.2f}")

        # 5. Konsantrasyon riski
        if portfolio_info:
            current_positions = portfolio_info.get("position_count", 0)
            if current_positions > 10:
                risk_score += 10
                risk_factors.append(f"Yüksek pozisyon sayısı: {current_positions}")

        # 6. Makro risk — context'ten gelir (features'tan değil)
        regime = (context or {}).get("regime", "UNKNOWN")
        if regime == "RISK_OFF":
            risk_score += 15
            risk_factors.append("Risk-off rejimi")

        # Risk seviyesi belirle
        risk_score = min(100, risk_score)
        risk_level = self._determine_risk_level(risk_score)

        # Veto kontrolü
        approved = True
        veto_reason = None

        if risk_level == "CRITICAL":
            approved = False
            veto_reason = f"CRITICAL risk seviyesi: {risk_score}"
            logger.warning(
                "Risk VETO applied",
                ticker=ticker,
                risk_score=risk_score,
                risk_factors=risk_factors,
            )

        # Pozisyon boyutu ve stop-loss
        max_position_pct = self._calculate_max_position(risk_level, risk_score)
        stop_loss_pct = self._calculate_stop_loss(risk_level, atr_pct)

        # LLM risk değerlendirmesi (varsa)
        llm_reasoning = ""
        if llm_client:
            llm_result = await self._llm_risk_assessment(ticker, agent_results, features, portfolio_info, llm_client)
            if llm_result:
                llm_reasoning = llm_result.get("reasoning", "")
                # LLM veto kontrolü
                if llm_result.get("risk_level") == "CRITICAL" and approved:
                    approved = False
                    veto_reason = f"LLM CRITICAL: {llm_result.get('veto_reason', '')}"
                    logger.warning(
                        "Risk VETO applied by LLM",
                        ticker=ticker,
                        llm_risk_level=llm_result.get("risk_level"),
                    )

        duration = (time.monotonic() - start) * 1000

        assessment = RiskAssessment(
            approved=approved,
            risk_level=risk_level,
            risk_score=round(risk_score, 2),
            max_position_pct=max_position_pct,
            stop_loss_pct=stop_loss_pct,
            risk_factors=risk_factors,
            veto_reason=veto_reason,
            reasoning=llm_reasoning or f"Rule-based risk assessment: {risk_level}",
        )

        logger.info(
            "Risk assessment completed",
            ticker=ticker,
            risk_level=risk_level,
            risk_score=risk_score,
            approved=approved,
            duration_ms=round(duration, 2),
        )

        return assessment

    @staticmethod
    def _determine_risk_level(risk_score: float) -> str:
        """Risk skorundan seviye belirle.

        Eşikler (üst sınır exclusive):
        - LOW: 0 ≤ score < 30
        - MEDIUM: 30 ≤ score < 50
        - HIGH: 50 ≤ score < 70
        - CRITICAL: score ≥ 70
        """
        if risk_score >= 70:
            return "CRITICAL"
        elif risk_score >= 50:
            return "HIGH"
        elif risk_score >= 30:
            return "MEDIUM"
        else:
            return "LOW"

    def _calculate_max_position(self, risk_level: str, risk_score: float) -> float:
        """Maksimum pozisyon yüzdesi hesapla.

        Risk skoru arttıkça pozisyon kademeli azalır:
        - LOW (0-30): 8-10%
        - MEDIUM (30-50): 5-8%
        - HIGH (50-70): 2-5%
        - CRITICAL (70+): 0% (veto)
        """
        if risk_level == "CRITICAL":
            return 0.0

        # Her seviye için üst ve alt sınır
        level_bounds = {
            "LOW": (10.0, 8.0, 0, 30),
            "MEDIUM": (7.0, 5.0, 30, 50),
            "HIGH": (4.0, 1.0, 50, 70),
        }

        base, level_min, low, high = level_bounds.get(risk_level, (5.0, 1.0, 50, 70))

        # Lineer interpolasyon
        if high > low:
            t = max(0.0, min(1.0, (risk_score - low) / (high - low)))
        else:
            t = 0.0

        position = base - (base - level_min) * t
        return round(max(0.5, position), 1)

    def _calculate_stop_loss(self, risk_level: str, atr_pct: float) -> float:
        """Stop-loss yüzdesi hesapla.

        ATR'ye göre dinamik, minimum seviye bazlı.
        """
        base = {
            "LOW": 3.0,
            "MEDIUM": 5.0,
            "HIGH": 7.0,
            "CRITICAL": 10.0,
        }.get(risk_level, 5.0)

        # ATR'ye göre ayarla (en az 2× ATR)
        if atr_pct > 0:
            return round(max(base, atr_pct * 2), 1)
        return base

    async def _llm_risk_assessment(
        self,
        ticker: str,
        agent_results: dict[AgentRole, AgentResult],
        features: dict[str, float],
        portfolio_info: dict | None,
        llm_client: BaseLLMClient,
    ) -> dict | None:
        """LLM ile risk değerlendirmesi.

        Returns:
            LLM çıktısı (parsed dict) veya None
        """
        try:
            # Agent sonuçlarını formatla
            agent_text = []
            for role, result in agent_results.items():
                if result.success:
                    agent_text.append(
                        f"{role.value}: {result.output.get('direction')} (güven: {result.confidence:.2f})"
                    )

            system_prompt, user_prompt = PromptFactory.get_prompts(
                template_name="risk",
                ticker=ticker,
                context=features,
                agent_results="\n".join(agent_text),
                portfolio_info=str(portfolio_info or {}),
            )

            response = await llm_client.generate_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            if response.success:
                from .llm_client import parse_llm_json

                return parse_llm_json(response.content)

        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("LLM risk assessment connection error", error=str(e))
        except Exception as e:
            logger.error("LLM risk assessment unexpected error", error=str(e), exc_info=True)

        return None
