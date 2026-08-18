"""
ALPHA BIST — Agent Pipeline Orchestrator v1.0

Tüm agent fazlarını birleştiren ana pipeline.
Bu, mevcut MasterOrchestrator'a entegre edilen üst katmandır.

Akış:
1. Parallel Research → agent'ları paralel çalıştır
2. Conflict Detection → çelişki var mı?
3. Bull/Bear Debate → varsa tartış
4. Risk Assessment → risk agent değerlendir
5. Synthesis → sonuçları birleştir
6. Memory Update → hafızayı güncelle
7. Self-Evaluation → periyodik kontrol

FAZ 6: Full Pipeline Integration
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from .agent_system import AgentRole, BaseAgent, AgentOrchestrator
from .llm_client import BaseLLMClient, LLMClientFactory, LLMConfig
from .parallel_runner import ParallelAgentRunner, ParallelRunResult
from .conflict_detector import ConflictDetector, ConflictReport
from .debate_engine import DebateEngine, DebateResult
from .risk_assessor import RiskAssessor, RiskAssessment
from .synthesis_engine import SynthesisEngine, SynthesisResult
from .agent_memory import AgentMemory, MemoryConsolidator
from .self_evaluator import AgentSelfEvaluator, MultiAgentEvaluator
from .communication_bus import AgentCommunicationBus, ConflictResolver, Resolution

logger = structlog.get_logger()


@dataclass
class PipelineResult:
    """Agent pipeline sonucu."""
    ticker: str
    timestamp: str
    synthesis: SynthesisResult
    parallel_result: ParallelRunResult
    conflict_report: ConflictReport
    debate_result: Optional[DebateResult]
    risk_assessment: RiskAssessment
    resolution: Resolution
    total_duration_ms: float

    def to_dict(self) -> Dict:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "synthesis": self.synthesis.to_dict(),
            "parallel": {
                "success_count": self.parallel_result.success_count,
                "failure_count": self.parallel_result.failure_count,
                "total_duration_ms": self.parallel_result.total_duration_ms,
            },
            "conflict": self.conflict_report.to_dict(),
            "debate": self.debate_result.to_dict() if self.debate_result else None,
            "risk": self.risk_assessment.to_dict(),
            "resolution": self.resolution.to_dict(),
            "total_duration_ms": self.total_duration_ms,
        }

    @property
    def direction(self) -> str:
        return self.synthesis.final_direction

    @property
    def confidence(self) -> float:
        return self.synthesis.final_confidence


class AgentPipelineOrchestrator:
    """Tüm agent fazlarını birleştiren ana pipeline.

    Bu sınıf, MasterOrchestrator.run_full_pipeline() tarafından çağrılır.
    Mevcut sisteme entegre çalışır.
    """

    def __init__(
        self,
        llm_client: Optional[BaseLLMClient] = None,
        max_concurrent: int = 6,
        agent_timeout: int = 120,
        enable_debate: bool = True,
        enable_memory: bool = True,
        enable_self_eval: bool = True,
        memory_path: Optional[str] = None,
    ):
        self.llm_client = llm_client
        self.max_concurrent = max_concurrent
        self.agent_timeout = agent_timeout
        self.enable_debate = enable_debate
        self.enable_memory = enable_memory
        self.enable_self_eval = enable_self_eval

        # Modüller
        self.runner = ParallelAgentRunner(
            max_concurrent=max_concurrent,
            timeout_seconds=agent_timeout,
        )
        self.conflict_detector = ConflictDetector()
        self.debate_engine = DebateEngine()
        self.risk_assessor = RiskAssessor()
        self.synthesis_engine = SynthesisEngine()
        self.conflict_resolver = ConflictResolver()
        self.comm_bus = AgentCommunicationBus()
        self.consolidator = MemoryConsolidator()
        self.multi_evaluator = MultiAgentEvaluator()

        # Agent hafızası
        self._memories: Dict[str, AgentMemory] = {}
        if enable_memory:
            for role in ["TECHNICAL", "FUNDAMENTAL", "NEWS", "MACRO", "RISK", "SYNTHESIS"]:
                path = f"{memory_path}/{role}_memory.json" if memory_path else None
                self._memories[role] = AgentMemory(
                    agent_role=role,
                    persistence_path=path,
                )
                self._memories[role].load()

    async def run(
        self,
        ticker: str,
        features: Dict[str, float],
        context: Optional[Dict[str, Any]] = None,
        sector: Optional[str] = None,
        regime: Optional[str] = None,
        price: Optional[float] = None,
        portfolio_info: Optional[Dict] = None,
    ) -> PipelineResult:
        """Tam agent pipeline çalıştır.

        Args:
            ticker: Hisse kodu
            features: Feature'lar
            context: Ek bağlam
            sektör: Sektör adı
            regime: Piyasa rejimi
            price: Güncel fiyat
            portfolio_info: Portföy bilgisi

        Returns:
            PipelineResult
        """
        start = time.monotonic()

        # Bağlam hazırla
        full_context = {
            "features": features,
            "sector": sector or "UNKNOWN",
            "regime": regime or "UNKNOWN",
            "price": price,
            **(context or {}),
        }

        # Memory bağlamı ekle
        if self.enable_memory:
            for role_name, memory in self._memories.items():
                mem_context = memory.get_context_for_task(ticker, regime)
                full_context[f"memory_{role_name.lower()}"] = mem_context

        logger.info("Agent pipeline started", ticker=ticker, regime=regime)

        # === PHASE 1: PARALLEL RESEARCH ===
        research_roles = [
            AgentRole.TECHNICAL, AgentRole.FUNDAMENTAL,
            AgentRole.NEWS, AgentRole.MACRO,
        ]
        agents = {
            role: BaseAgent(role, llm_client=self.llm_client)
            for role in research_roles
        }
        tasks = self._create_tasks(ticker, research_roles, full_context)

        parallel_result = await self.runner.run_agents(agents, tasks, self.llm_client)

        # === PHASE 2: CONFLICT DETECTION ===
        conflict_report = self.conflict_detector.detect(parallel_result.results)

        # === PHASE 3: BULL/BEAR DEBATE (eğer çelişki varsa) ===
        debate_result = None
        if self.enable_debate and conflict_report.requires_debate:
            debate_result = await self.debate_engine.run_debate(
                ticker=ticker,
                context=full_context,
                llm_client=self.llm_client,
            )

        # === PHASE 4: RISK ASSESSMENT ===
        risk_assessment = await self.risk_assessor.assess(
            ticker=ticker,
            agent_results=parallel_result.results,
            features=features,
            portfolio_info=portfolio_info,
            llm_client=self.llm_client,
        )

        # === PHASE 5: CONFLICT RESOLUTION ===
        resolution = self.conflict_resolver.resolve(
            results=parallel_result.results,
            debate_consensus=debate_result.consensus if debate_result else None,
            risk_approved=risk_assessment.approved,
        )

        # === PHASE 6: SYNTHESIS ===
        synthesis = await self.synthesis_engine.synthesize(
            ticker=ticker,
            agent_results=parallel_result.results,
            debate_result=debate_result,
            resolution=resolution,
            risk_approved=risk_assessment.approved,
            agent_memory=self._memories.get("SYNTHESIS"),
            llm_client=self.llm_client,
        )

        # === PHASE 7: MEMORY UPDATE ===
        if self.enable_memory:
            await self._update_memories(
                ticker, parallel_result.results, synthesis
            )

        total_duration = (time.monotonic() - start) * 1000

        result = PipelineResult(
            ticker=ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            synthesis=synthesis,
            parallel_result=parallel_result,
            conflict_report=conflict_report,
            debate_result=debate_result,
            risk_assessment=risk_assessment,
            resolution=resolution,
            total_duration_ms=round(total_duration, 2),
        )

        logger.info(
            "Agent pipeline completed",
            ticker=ticker,
            direction=result.direction,
            confidence=result.confidence,
            total_duration_ms=round(total_duration, 2),
        )

        return result

    def _create_tasks(
        self,
        ticker: str,
        roles: List[AgentRole],
        context: Dict[str, Any],
    ) -> Dict[AgentRole, Any]:
        """Task'ları oluştur."""
        from .agent_system import AgentTask

        template_map = {
            AgentRole.TECHNICAL: "technical",
            AgentRole.FUNDAMENTAL: "fundamental",
            AgentRole.NEWS: "news",
            AgentRole.MACRO: "macro",
        }

        tasks = {}
        for role in roles:
            tasks[role] = AgentTask(
                task_id=f"{ticker}-{role.value}-{int(time.time())}",
                agent_role=role,
                ticker=ticker,
                prompt=f"Analyze {ticker} from {role.value} perspective",
                context=context,
                template_name=template_map.get(role),
            )
        return tasks

    async def _update_memories(
        self,
        ticker: str,
        results: Dict[AgentRole, Any],
        synthesis: SynthesisResult,
    ):
        """Memory'leri güncelle."""
        for role, result in results.items():
            role_name = role.value
            if role_name in self._memories:
                self._memories[role_name].record_task(
                    task_id=result.task_id,
                    ticker=ticker,
                    direction=result.output.get("direction", "NEUTRAL"),
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                )

    async def evaluate_agents(self) -> Dict[str, Any]:
        """Tüm agent'ları değerlendir."""
        if not self.enable_self_eval:
            return {"enabled": False}

        return self.multi_evaluator.evaluate_all(self._memories)

    async def consolidate_memories(self) -> Dict[str, Any]:
        """Memory'leri birleştir."""
        if not self.enable_memory:
            return {"enabled": False}

        results = {}
        for role_name, memory in self._memories.items():
            results[role_name] = await self.consolidator.consolidate(memory)
        return results

    def get_memory_summary(self) -> Dict[str, Any]:
        """Memory özetini getir."""
        if not self.enable_memory:
            return {"enabled": False}

        return {
            role_name: memory.get_performance_summary()
            for role_name, memory in self._memories.items()
        }
