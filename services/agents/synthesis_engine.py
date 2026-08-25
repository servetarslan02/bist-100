"""
ALPHA BIST — Synthesis Engine v1.0

Tüm agent sonuçlarını birleştiren gelişmiş sentez.
LLM destekli sentez (varsa).
Confidence-weighted scoring.

FAZ 4: Synthesis Engine
"""

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import structlog

from .agent_system import AgentRole, AgentResult
from .llm_client import BaseLLMClient
from .debate_engine import DebateResult
from .communication_bus import Resolution
from .agent_memory import AgentMemory
from .prompts import PromptFactory

logger = structlog.get_logger()


@dataclass
class SynthesisResult:
    """Sentez sonucu."""
    ticker: str
    final_direction: str  # LONG, SHORT, NEUTRAL, NO_TRADE
    final_confidence: float
    weighted_score: float
    consensus_reached: bool
    debate_occurred: bool
    risk_approved: bool
    agent_summary: Dict[str, Any] = field(default_factory=dict)
    conflict_analysis: Dict[str, Any] = field(default_factory=dict)
    debate_result: Optional[Dict] = None
    resolution: Optional[Dict] = None
    reasoning: str = ""
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    memory_context: Optional[Dict] = None

    def to_dict(self) -> Dict:
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
        }


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
        agent_results: Dict[AgentRole, AgentResult],
        debate_result: Optional[DebateResult] = None,
        resolution: Optional[Resolution] = None,
        risk_approved: bool = True,
        agent_memory: Optional[AgentMemory] = None,
        llm_client: Optional[BaseLLMClient] = None,
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
                ticker, agent_results, debate_result, resolution,
                risk_approved, llm_client,
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

        # Risk ve nedenleri topla
        all_reasons = llm_reasons or self._collect_reasons(agent_results)
        all_risks = llm_risks or self._collect_risks(agent_results)

        duration = (time.monotonic() - start) * 1000

        result = SynthesisResult(
            ticker=ticker,
            final_direction=final_direction,
            final_confidence=round(final_confidence, 4),
            weighted_score=round(weighted_score, 2),
            consensus_reached=resolution is not None and not resolution.conflict if resolution else True,
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

    def _create_agent_summary(
        self, results: Dict[AgentRole, AgentResult]
    ) -> Dict[str, Any]:
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

    def _analyze_conflicts(
        self, results: Dict[AgentRole, AgentResult]
    ) -> Dict[str, Any]:
        """Çelişki analizi."""
        valid = {r: res for r, res in results.items() if res.success}
        directions = {}
        for role, result in valid.items():
            d = result.output.get("direction", "NEUTRAL")
            if d not in directions:
                directions[d] = []
            directions[d].append(role.value)

        long_count = len(directions.get("LONG", []))
        short_count = len(directions.get("SHORT", []))
        has_conflict = long_count > 0 and short_count > 0

        return {
            "directions": directions,
            "long_count": long_count,
            "short_count": short_count,
            "has_conflict": has_conflict,
            "is_unanimous": len(directions) == 1,
        }

    def _weighted_score(
        self, results: Dict[AgentRole, AgentResult]
    ) -> float:
        """Confidence-weighted ortalama skor."""
        valid = {r: res for r, res in results.items() if res.success}
        if not valid:
            return 50.0

        total_weight = 0
        weighted_sum = 0
        for role, result in valid.items():
            score = result.output.get("score", 50)
            confidence = result.confidence
            weighted_sum += score * confidence
            total_weight += confidence

        return weighted_sum / total_weight if total_weight > 0 else 50.0

    def _simple_majority(
        self, results: Dict[AgentRole, AgentResult]
    ) -> str:
        """Basit çoğunluk oyu."""
        valid = {r: res for r, res in results.items() if res.success}
        directions = {}
        for role, result in valid.items():
            d = result.output.get("direction", "NEUTRAL")
            directions[d] = directions.get(d, 0) + 1

        if not directions:
            return "NO_TRADE"

        max_dir = max(directions, key=directions.get)
        # LONG veya SHORT çoğunlukta değilse NO_TRADE
        if max_dir in ["LONG", "SHORT"]:
            return max_dir
        return "NEUTRAL"

    def _simple_confidence(
        self, results: Dict[AgentRole, AgentResult]
    ) -> float:
        """Basit ortalama güven."""
        valid = [res for r, res in results.items() if res.success]
        if not valid:
            return 0.0
        return sum(r.confidence for r in valid) / len(valid)

    def _collect_reasons(
        self, results: Dict[AgentRole, AgentResult]
    ) -> List[str]:
        """Tüm nedenleri topla."""
        reasons = []
        for role, result in results.items():
            if result.success:
                for reason in result.evidence[:2]:
                    reasons.append(f"[{role.value}] {reason}")
        return reasons[:10]

    def _collect_risks(
        self, results: Dict[AgentRole, AgentResult]
    ) -> List[str]:
        """Tüm riskleri topla."""
        risks = []
        for role, result in results.items():
            if result.success:
                for risk in result.output.get("risks", [])[:2]:
                    risks.append(f"[{role.value}] {risk}")
        return risks[:10]

    async def _llm_synthesize(
        self,
        ticker: str,
        agent_results: Dict[AgentRole, AgentResult],
        debate_result: Optional[DebateResult],
        resolution: Optional[Resolution],
        risk_approved: bool,
        llm_client: BaseLLMClient,
    ) -> Dict[str, Any]:
        """LLM ile sentez yap."""
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

        # LLM çağrısı
        try:
            system_prompt, user_prompt = PromptFactory.get_prompts(
                template_name="synthesis",
                ticker=ticker,
                context={},
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
