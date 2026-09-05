"""
ALPHA BIST — Synthesis Engine v2.1

Tüm agent sonuçlarını birleştiren gelişmiş sentez.
LLM destekli sentez (varsa).
Confidence-weighted scoring.

v2.1 değişiklikleri:
- _analyze_conflicts is_unanimous düzeltmesi (sadece directional)
- _llm_synthesize context eksikliği giderildi
- _simple_majority değişken gölgeleme düzeltmesi
- consensus_reached mantığı basitleştirildi
- to_dict() docstring düzeltmesi

FAZ 4: Synthesis Engine
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .agent_memory import AgentMemory
from .agent_system import AgentResult, AgentRole
from .communication_bus import Resolution
from .debate_engine import DebateResult
from .llm_client import BaseLLMClient
from .prompts import PromptFactory

logger = logging.getLogger(__name__)


@dataclass
class SynthesisResult:
    """Sentez sonucu — nihai yön, güven, skor ve tüm analiz detayları."""

    ticker: str
    final_direction: str  # LONG, SHORT, NEUTRAL, NO_TRADE
    final_confidence: float
    weighted_score: float
    consensus_reached: bool
    debate_occurred: bool
    risk_approved: bool
    agent_summary: dict[str, Any] = field(default_factory=dict)
    conflict_analysis: dict[str, Any] = field(default_factory=dict)
    debate_result: dict | None = None
    resolution: dict | None = None
    reasoning: str = ""
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    memory_context: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "ticker": self.ticker,
            "final_direction": self.final_direction,
            "final_confidence": self.final_confidence,
            "weighted_score": self.weighted_score,
            "consensus_reached": self.consensus_reached,
            "debate_occurred": self.debate_occurred,
            "risk_approved": self.risk_approved,
            "agent_summary": self.agent_summary,
            "conflict_analysis": self.conflict_analysis,
            "debate_result": self.debate_result,
            "resolution": self.resolution,
            "reasoning": self.reasoning,
            "reasons": self.reasons,
            "risks": self.risks,
            "memory_context": self.memory_context,
        }

    def __repr__(self) -> str:
        return (
            f"SynthesisResult(ticker={self.ticker!r}, direction={self.final_direction!r}, "
            f"confidence={self.final_confidence:.2f}, score={self.weighted_score:.1f})"
        )


class SynthesisEngine:
    """Tüm agent sonuçlarını birleştiren gelişmiş sentez.

    Pipeline:
    1. Agent sonuçlarını topla
    2. Conflict analysis yap
    3. Confidence-weighted scoring hesapla
    4. Memory-based adjustment uygula
    5. LLM synthesis çalıştır (varsa)
    6. Final direction ve confidence belirle
    """

    async def synthesize(
        self,
        ticker: str,
        agent_results: dict[AgentRole, AgentResult],
        debate_result: DebateResult | None = None,
        resolution: Resolution | None = None,
        risk_approved: bool = True,
        agent_memory: AgentMemory | None = None,
        llm_client: BaseLLMClient | None = None,
        context: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        """Gelişmiş sentez.

        Args:
            ticker: Hisse kodu
            agent_results: Tüm agent sonuçları
            debate_result: Debate sonucu (varsa)
            resolution: Conflict resolution sonucu
            risk_approved: Risk onayı
            agent_memory: Agent hafızası
            llm_client: LLM client (opsiyonel)
            context: Ek bağlam (features, regime, price, vb.)

        Returns:
            SynthesisResult
        """
        start = time.monotonic()

        # 1. Agent özeti
        agent_summary = self._create_agent_summary(agent_results)

        # 2. Conflict analysis
        conflict_analysis = self._analyze_conflicts(agent_results)

        # 3. Confidence-weighted scoring
        weighted_score = self._weighted_score(agent_results)

        # 4. Memory context
        memory_context = None
        if agent_memory:
            memory_context = agent_memory.get_context_for_task(ticker)

        # 5. LLM synthesis (varsa)
        llm_reasoning = ""
        llm_reasons = []
        llm_risks = []
        if llm_client:
            llm_result = await self._llm_synthesize(
                ticker,
                agent_results,
                debate_result,
                resolution,
                risk_approved,
                llm_client,
                context or {},
            )
            llm_reasoning = llm_result.get("reasoning", "")
            llm_reasons = llm_result.get("reasons", [])
            llm_risks = llm_result.get("risks", [])

        # 6. Final decision
        if not risk_approved:
            final_direction = "NO_TRADE"
            final_confidence = 0.0
            reasoning = "Risk agent veto etti"
        elif resolution:
            final_direction = resolution.direction
            final_confidence = resolution.confidence
            reasoning = llm_reasoning or f"Resolution method: {resolution.method}"
        else:
            # Basit çoğunluk
            final_direction = self._simple_majority(agent_results)
            final_confidence = self._simple_confidence(agent_results)
            reasoning = llm_reasoning or "Simple majority vote"

        # Consensus: resolution varsa ve çelişki yoksa consensus var
        if resolution:
            consensus_reached = not resolution.conflict
        else:
            # Resolution yoksa conflict_analysis'den kontrol et
            consensus_reached = not conflict_analysis.get("has_conflict", False)

        # Risk ve nedenleri topla
        all_reasons = llm_reasons or self._collect_reasons(agent_results)
        all_risks = llm_risks or self._collect_risks(agent_results)

        duration = (time.monotonic() - start) * 1000

        result = SynthesisResult(
            ticker=ticker,
            final_direction=final_direction,
            final_confidence=round(final_confidence, 4),
            weighted_score=round(weighted_score, 2),
            consensus_reached=consensus_reached,
            debate_occurred=debate_result is not None,
            risk_approved=risk_approved,
            agent_summary=agent_summary,
            conflict_analysis=conflict_analysis,
            debate_result=debate_result.to_dict() if debate_result else None,
            resolution=resolution.to_dict() if resolution else None,
            reasoning=reasoning,
            reasons=all_reasons,
            risks=all_risks,
            memory_context=memory_context,
        )

        logger.info(
            "Synthesis completed",
            ticker=ticker,
            direction=final_direction,
            confidence=final_confidence,
            duration_ms=round(duration, 2),
        )

        return result

    def _create_agent_summary(self, results: dict[AgentRole, AgentResult]) -> dict[str, Any]:
        """Agent özetini oluştur."""
        summary = {}
        for role, result in results.items():
            summary[role.value] = {
                "direction": result.output.get("direction", "NEUTRAL"),
                "confidence": result.confidence,
                "score": result.output.get("score", 50),
                "success": result.success,
                "duration_ms": result.duration_ms,
                "reasoning": result.reasoning[:200] if result.reasoning else "",
            }
        return summary

    def _analyze_conflicts(self, results: dict[AgentRole, AgentResult]) -> dict[str, Any]:
        """Çelişki analizi — sadece directional (LONG/SHORT) agent'lar üzerinden."""
        valid = {r: res for r, res in results.items() if res.success}
        directions: dict[str, list[str]] = {}
        for role, result in valid.items():
            d = result.output.get("direction", "NEUTRAL")
            if d not in directions:
                directions[d] = []
            directions[d].append(role.value)

        long_count = len(directions.get("LONG", []))
        short_count = len(directions.get("SHORT", []))
        has_conflict = long_count > 0 and short_count > 0

        # Unanimous = tüm directional agent'lar aynı yönde
        directional_count = long_count + short_count
        is_unanimous = (
            directional_count > 0
            and (long_count == directional_count or short_count == directional_count)
        )

        return {
            "directions": directions,
            "long_count": long_count,
            "short_count": short_count,
            "has_conflict": has_conflict,
            "is_unanimous": is_unanimous,
        }

    def _weighted_score(self, results: dict[AgentRole, AgentResult]) -> float:
        """Confidence-weighted ortalama skor."""
        valid = {r: res for r, res in results.items() if res.success}
        if not valid:
            return 50.0

        total_weight = 0
        weighted_sum = 0
        for _role, result in valid.items():
            score = result.output.get("score", 50)
            confidence = result.confidence
            weighted_sum += score * confidence
            total_weight += confidence

        return weighted_sum / total_weight if total_weight > 0 else 50.0

    def _simple_majority(self, results: dict[AgentRole, AgentResult]) -> str:
        """Basit çoğunluk oyu — beraberlik durumunda confidence'a bak."""
        valid = {r: res for r, res in results.items() if res.success}
        direction_counts: dict[str, int] = {}
        for _role, result in valid.items():
            d = result.output.get("direction", "NEUTRAL")
            direction_counts[d] = direction_counts.get(d, 0) + 1

        if not direction_counts:
            return "NO_TRADE"

        # Sadece LONG/SHORT oylarını say
        directional = {d: c for d, c in direction_counts.items() if d in ["LONG", "SHORT"]}
        if not directional:
            return "NEUTRAL"

        max_votes = max(directional.values())
        top_dirs = [d for d, v in directional.items() if v == max_votes]

        # Beraberlik varsa confidence'a bak
        if len(top_dirs) > 1:
            best_dir: str | None = None
            best_conf = -1.0
            for d in top_dirs:
                matching = [res for res in valid.values() if res.output.get("direction") == d]
                avg_conf = sum(res.confidence for res in matching) / len(matching) if matching else 0
                if avg_conf > best_conf:
                    best_conf = avg_conf
                    best_dir = d
            return best_dir or "NO_TRADE"

        return top_dirs[0]

    def _simple_confidence(self, results: dict[AgentRole, AgentResult]) -> float:
        """Basit ortalama güven."""
        valid = [res for _role, res in results.items() if res.success]
        if not valid:
            return 0.0
        return sum(r.confidence for r in valid) / len(valid)

    def _collect_reasons(self, results: dict[AgentRole, AgentResult]) -> list[str]:
        """Tüm nedenleri topla (her agent'tan en fazla 2, toplam en fazla 10)."""
        reasons = []
        for role, result in results.items():
            if result.success:
                for reason in result.evidence[:2]:
                    reasons.append(f"[{role.value}] {reason}")
        return reasons[:10]

    def _collect_risks(self, results: dict[AgentRole, AgentResult]) -> list[str]:
        """Tüm riskleri topla (her agent'tan en fazla 2, toplam en fazla 10)."""
        risks = []
        for role, result in results.items():
            if result.success:
                for risk in result.output.get("risks", [])[:2]:
                    risks.append(f"[{role.value}] {risk}")
        return risks[:10]

    async def _llm_synthesize(
        self,
        ticker: str,
        agent_results: dict[AgentRole, AgentResult],
        debate_result: DebateResult | None,
        resolution: Resolution | None,
        risk_approved: bool,
        llm_client: BaseLLMClient,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """LLM ile sentez yap.

        Args:
            ticker: Hisse kodu
            agent_results: Agent sonuçları
            debate_result: Debate sonucu
            resolution: Resolution sonucu
            risk_approved: Risk onayı
            llm_client: LLM client
            context: Bağlam (features, regime, price, vb.)

        Returns:
            LLM çıktısı (parsed dict) veya boş dict
        """
        try:
            # Agent sonuçlarını formatla
            agent_text = []
            for role, result in agent_results.items():
                if result.success:
                    agent_text.append(
                        f"{role.value}: {result.output.get('direction')} "
                        f"(güven: {result.confidence:.2f}) - {result.reasoning[:150]}"
                    )

            debate_text = ""
            if debate_result:
                debate_text = f"Debate: {debate_result.consensus} (anlaşma: {debate_result.agreement})"

            risk_text = "Onaylandı" if risk_approved else "Reddedildi"

            system_prompt, user_prompt = PromptFactory.get_prompts(
                template_name="synthesis",
                ticker=ticker,
                context=context,
                agent_results="\n".join(agent_text),
                debate_result=debate_text,
                risk_assessment=risk_text,
                conflict_analysis=str(resolution.to_dict() if resolution else {}),
            )

            response = await llm_client.generate_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            if response.success:
                from .llm_client import parse_llm_json

                parsed = parse_llm_json(response.content)
                if parsed:
                    return parsed

        except Exception as e:
            logger.warning("LLM synthesis failed", error=str(e))

        return {}
