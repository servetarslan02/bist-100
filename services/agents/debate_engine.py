"""
ALPHA BIST — Debate Engine v1.0

Bull/Bear debate — CGX protokolü (MDPI 2026).

Kurallar:
- Maksimum 3 tur (sonsuz döngü yok)
- Structured output (JSON argümanlar)
- Confidence damping (her turda *= 0.9)
- Consensus Gate: anlaşma yoksa NO_TRADE

FAZ 2: Bull/Bear Debate
"""

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from .agent_system import AgentResult, AgentRole, AgentTask, BaseAgent
from .llm_client import BaseLLMClient

logger = structlog.get_logger()


@dataclass
class DebateRound:
    """Tek tur tartışma sonucu."""

    round_num: int
    bull_direction: str = "NEUTRAL"
    bull_confidence: float = 0.0
    bull_reasoning: str = ""
    bull_evidence: list[str] = field(default_factory=list)
    bear_direction: str = "NEUTRAL"
    bear_confidence: float = 0.0
    bear_reasoning: str = ""
    bear_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """DebateRound sonucunu dict'e çevir."""
        return {
            "round": self.round_num,
            "bull": {
                "direction": self.bull_direction,
                "confidence": self.bull_confidence,
                "reasoning": self.bull_reasoning[:300],
            },
            "bear": {
                "direction": self.bear_direction,
                "confidence": self.bear_confidence,
                "reasoning": self.bear_reasoning[:300],
            },
        }


@dataclass
class DebateResult:
    """Tartışma sonucu."""

    consensus: str  # LONG, SHORT, NEUTRAL, NO_TRADE
    consensus_confidence: float
    rounds: list[DebateRound]
    agreement: bool
    total_rounds: int
    total_duration_ms: float = 0.0
    bull_final_confidence: float = 0.0
    bear_final_confidence: float = 0.0

    def to_dict(self) -> dict:
        """to_dict metodu."""
        return {
            "consensus": self.consensus,
            "consensus_confidence": self.consensus_confidence,
            "agreement": self.agreement,
            "total_rounds": self.total_rounds,
            "total_duration_ms": self.total_duration_ms,
            "bull_final_confidence": self.bull_final_confidence,
            "bear_final_confidence": self.bear_final_confidence,
            "rounds": [r.to_dict() for r in self.rounds],
        }


class DebateEngine:
    """Bull/Bear debate — CGX protokolü.

    Akış:
    1. Bull argüman sunar
    2. Bear cevap verir
    3. Bear yeni argüman sunar
    4. Bull cevap verir
    5. Her iki son pozisyon
    6. Consensus kontrolü

    Confidence Damping:
    - Tur 1: confidence * 1.0
    - Tur 2: confidence * 0.9
    - Tur 3: confidence * 0.81
    """

    def __init__(
        self,
        max_rounds: int = 3,
        confidence_damping: float = 0.9,
    ):
        """metod metodu."""
        self.max_rounds = max_rounds
        self.confidence_damping = confidence_damping

    async def run_debate(
        self,
        ticker: str,
        context: dict[str, Any],
        bull_agent: BaseAgent | None = None,
        bear_agent: BaseAgent | None = None,
        llm_client: BaseLLMClient | None = None,
    ) -> DebateResult:
        """Bull/Bear tartışması çalıştır.

        Args:
            ticker: Hisse kodu
            context: Bağlam (features, price, news, vb.)
            bull_agent: Bull agent (opsiyonel, yoksa oluşturulur)
            bear_agent: Bear agent (opsiyonel, yoksa oluşturulur)
            llm_client: LLM client

        Returns:
            DebateResult
        """
        start = time.monotonic()

        # Agent'ları oluştur (yoksa)
        if bull_agent is None:
            bull_agent = BaseAgent(AgentRole.BULL, llm_client=llm_client)
        if bear_agent is None:
            bear_agent = BaseAgent(AgentRole.BEAR, llm_client=llm_client)

        history: list[DebateRound] = []
        bull_arg = None
        bear_arg = None

        for round_num in range(self.max_rounds):
            round_result = await self._run_round(
                round_num=round_num,
                ticker=ticker,
                context=context,
                bull_agent=bull_agent,
                bear_agent=bear_agent,
                llm_client=llm_client,
                bull_arg=bull_arg,
                bear_arg=bear_arg,
                history=history,
            )

            history.append(round_result)

            # Son argümanları güncelle (bir sonraki tur için)
            # Her iki taraf da kendi son pozisyonunu korumalı
            bull_arg = round_result  # Bull'ın son argümanı
            bear_arg = round_result  # Bear'ın son argümanı

            # Erken konsensüs kontrolü
            if round_result.bull_direction == round_result.bear_direction:
                logger.info(
                    "Early consensus reached",
                    round=round_num,
                    direction=round_result.bull_direction,
                )
                break

        # Consensus belirle — confidence damping dahil
        final_bull = history[-1].bull_direction
        final_bear = history[-1].bear_direction
        final_bull_conf = history[-1].bull_confidence
        final_bear_conf = history[-1].bear_confidence

        if final_bull == final_bear:
            consensus = final_bull
            # Damping uygulanmış confidence'ları kullan
            consensus_confidence = (final_bull_conf + final_bear_conf) / 2
            agreement = True
        else:
            # Anlaşma yok — daha yüksek damping'li confidence'a sahip tarafın yönünü seç
            # ama düşük güvenle → NO_TRADE
            if final_bull_conf > 0.5 and final_bear_conf < 0.3:
                consensus = final_bull
                consensus_confidence = final_bull_conf * 0.7
                agreement = False
            elif final_bear_conf > 0.5 and final_bull_conf < 0.3:
                consensus = final_bear
                consensus_confidence = final_bear_conf * 0.7
                agreement = False
            else:
                consensus = "NO_TRADE"
                consensus_confidence = 0.0
                agreement = False

        total_duration = (time.monotonic() - start) * 1000

        result = DebateResult(
            consensus=consensus,
            consensus_confidence=round(consensus_confidence, 4),
            rounds=history,
            agreement=agreement,
            total_rounds=len(history),
            total_duration_ms=round(total_duration, 2),
            bull_final_confidence=round(final_bull_conf, 4),
            bear_final_confidence=round(final_bear_conf, 4),
        )

        logger.info(
            "Debate completed",
            ticker=ticker,
            consensus=consensus,
            agreement=agreement,
            rounds=len(history),
            duration_ms=round(total_duration, 2),
        )

        return result

    async def _run_round(
        self,
        round_num: int,
        ticker: str,
        context: dict[str, Any],
        bull_agent: BaseAgent,
        bear_agent: BaseAgent,
        llm_client: BaseLLMClient | None,
        bull_arg: DebateRound | None,
        bear_arg: DebateRound | None,
        history: list[DebateRound],
    ) -> DebateRound:
        """Tek tur tartışma çalıştır."""

        # Confidence damping
        damping = self.confidence_damping**round_num

        # === BULL ARGÜMAN ===
        bull_prompt_vars = self._create_bull_prompt_vars(round_num, ticker, context, bear_arg, history)
        # Template adı: tur 1-3 için özel, sonrası için genel
        bull_template = f"bull_tur{round_num + 1}" if round_num < 3 else "bull_tur3"
        bull_task = AgentTask(
            task_id=f"bull-{ticker}-r{round_num}-{int(time.time())}",
            agent_role=AgentRole.BULL,
            ticker=ticker,
            prompt=f"[Tur {round_num + 1}] {ticker} için BULL argümanı",
            context={**context, "prompt_vars": bull_prompt_vars},
            template_name=bull_template,
        )
        bull_result = await bull_agent.execute(bull_task, llm_client)

        # Confidence damping uygula — orijinali bozmamak için kopyala
        bull_confidence = round(bull_result.confidence * damping, 4)

        # === BEAR CEVAP ===
        # Bear, bull'ın bu turdaki argümanına cevap verir
        bear_prompt_vars = self._create_bear_prompt_vars(round_num, ticker, context, bull_result, history)
        bear_template = f"bear_tur{round_num + 1}" if round_num < 3 else "bear_tur3"
        bear_task = AgentTask(
            task_id=f"bear-{ticker}-r{round_num}-{int(time.time())}",
            agent_role=AgentRole.BEAR,
            ticker=ticker,
            prompt=f"[Tur {round_num + 1}] {ticker} için BEAR argümanı",
            context={**context, "prompt_vars": bear_prompt_vars},
            template_name=bear_template,
        )
        bear_result = await bear_agent.execute(bear_task, llm_client)

        # Confidence damping uygula — orijinali bozmamak için kopyala
        bear_confidence = round(bear_result.confidence * damping, 4)

        return DebateRound(
            round_num=round_num,
            bull_direction=bull_result.output.get("direction") or bull_result.output.get("position", "NEUTRAL"),
            bull_confidence=bull_confidence,
            bull_reasoning=bull_result.reasoning,
            bull_evidence=bull_result.evidence,
            bear_direction=bear_result.output.get("direction") or bear_result.output.get("position", "NEUTRAL"),
            bear_confidence=bear_confidence,
            bear_reasoning=bear_result.reasoning,
            bear_evidence=bear_result.evidence,
        )

    def _create_bull_prompt_vars(
        self,
        round_num: int,
        ticker: str,
        context: dict[str, Any],
        bear_arg: DebateRound | None,
        history: list[DebateRound],
    ) -> dict[str, str]:
        """Bull prompt değişkenlerini oluştur."""
        if round_num == 0:
            return {}  # Template kendi prompt'unu oluşturur
        elif round_num == 1 and bear_arg:
            return {"bear_argument": bear_arg.bear_reasoning}
        else:
            return {"debate_summary": self._summarize_history(history)}

    def _create_bear_prompt_vars(
        self,
        round_num: int,
        ticker: str,
        context: dict[str, Any],
        bull_result: AgentResult,
        history: list[DebateRound],
    ) -> dict[str, str]:
        """Bear prompt değişkenlerini oluştur."""
        if round_num <= 1:
            bull_reasoning = bull_result.reasoning if bull_result else ""
            return {"bull_argument": bull_reasoning}
        else:
            return {"debate_summary": self._summarize_history(history)}

    def _summarize_history(self, history: list[DebateRound]) -> str:
        """Tartışma geçmişini özetle."""
        lines = []
        for r in history:
            lines.append(f"Tur {r.round_num + 1}:")
            lines.append(f"  Bull: {r.bull_direction} (güven: {r.bull_confidence:.2f})")
            lines.append(f"    {r.bull_reasoning[:150]}...")
            lines.append(f"  Bear: {r.bear_direction} (güven: {r.bear_confidence:.2f})")
            lines.append(f"    {r.bear_reasoning[:150]}...")
        return "\n".join(lines)
