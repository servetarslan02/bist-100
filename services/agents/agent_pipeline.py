"""
ALPHA BIST — Agent Pipeline Orchestrator v2.0

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

import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import logging

from .agent_memory import AgentMemory, MemoryConsolidator
from .agent_system import AgentRole, AgentResult, AgentTask, BaseAgent
from .circuit_breaker import CircuitBreaker, CircuitBreakerLLMClient
from .trace_context import TraceContext
from .communication_bus import ConflictResolver, Resolution
from .conflict_detector import ConflictDetector, ConflictReport, ConflictSeverity
from .debate_engine import DebateEngine, DebateResult
from .llm_client import BaseLLMClient
from .parallel_runner import ParallelAgentRunner, ParallelRunResult
from .prompts import PromptFactory
from .risk_assessor import RiskAssessment, RiskAssessor
from .self_evaluator import MultiAgentEvaluator
from .synthesis_engine import SynthesisEngine, SynthesisResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineMetrics:
    """Pipeline çalıştırma istatistikleri."""

    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_duration_ms: float = 0.0
    last_run_ticker: str = ""
    last_run_timestamp: str = ""

    @property
    def success_rate(self) -> float:
        """Başarı oranı (0-1)."""
        return self.successful_runs / self.total_runs if self.total_runs > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        """Ortalama çalıştırma süresi."""
        return self.total_duration_ms / self.total_runs if self.total_runs > 0 else 0.0

    def record_run(self, success: bool, duration_ms: float, ticker: str) -> None:
        """Çalıştırma kaydı."""
        self.total_runs += 1
        if success:
            self.successful_runs += 1
        else:
            self.failed_runs += 1
        self.total_duration_ms += duration_ms
        self.last_run_ticker = ticker
        self.last_run_timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
        return {
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "success_rate": round(self.success_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "last_run_ticker": self.last_run_ticker,
            "last_run_timestamp": self.last_run_timestamp,
        }

    def __repr__(self) -> str:
        return (
            f"PipelineMetrics(runs={self.total_runs}, "
            f"success={self.successful_runs}, failed={self.failed_runs}, "
            f"rate={self.success_rate:.1%})"
        )


@dataclass
class PipelineResult:
    """Agent pipeline sonucu — tüm fazların çıktılarını içerir."""

    ticker: str
    timestamp: str
    synthesis: SynthesisResult
    parallel_result: ParallelRunResult
    conflict_report: ConflictReport
    debate_result: DebateResult | None
    risk_assessment: RiskAssessment
    resolution: Resolution
    total_duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        """Serialization için dict'e çevir."""
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
        """Nihai yön kararı (LONG/SHORT/NEUTRAL/NO_TRADE)."""
        return self.synthesis.final_direction

    @property
    def confidence(self) -> float:
        """Nihai güven skoru (0-1)."""
        return self.synthesis.final_confidence

    def __repr__(self) -> str:
        return (
            f"PipelineResult(ticker={self.ticker!r}, direction={self.direction!r}, "
            f"confidence={self.confidence:.2f}, duration={self.total_duration_ms:.0f}ms)"
        )


class AgentPipelineOrchestrator:
    """Tüm agent fazlarını birleştiren ana pipeline.

    Bu sınıf, MasterOrchestrator.run_full_pipeline() tarafından çağrılır.
    Mevcut sisteme entegre çalışır.

    Fazlar:
    1. Parallel Research — 4 agent paralel çalışır (TECHNICAL, FUNDAMENTAL, NEWS, MACRO)
    2. Conflict Detection — LONG/SHORT çelişkisi var mı?
    3. Bull/Bear Debate — çelişki varsa 3 turluk tartışma
    4. Risk Assessment — risk agent veto yetkisi ile değerlendirir
    5. Conflict Resolution — çelişki çözümü (majority vote / confidence tiebreak)
    6. Synthesis — tüm sonuçları birleştirip nihai karar
    7. Memory Update — hafızayı güncelle

    Kullanım:
        pipeline = AgentPipelineOrchestrator(llm_client=client)
        result = await pipeline.run(ticker="THYAO", features={...})
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        max_concurrent: int = 6,
        agent_timeout: int = 120,
        enable_debate: bool = True,
        enable_memory: bool = True,
        enable_self_eval: bool = True,
        memory_path: str | None = None,
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
        self.consolidator = MemoryConsolidator()
        self.multi_evaluator = MultiAgentEvaluator()

        # Agent hafızası — her rol için ayrı instance
        self._memories: dict[str, AgentMemory] = {}
        if enable_memory:
            _default_path = memory_path or "data/agent_memory"
            os.makedirs(_default_path, exist_ok=True)
            for role in ["TECHNICAL", "FUNDAMENTAL", "NEWS", "MACRO", "RISK", "SYNTHESIS"]:
                path = f"{_default_path}/{role}_memory.json"
                self._memories[role] = AgentMemory(
                    agent_role=role,
                    persistence_path=path,
                )
                self._memories[role].load()

        # Agent instance cache — her run'da yeniden oluşturmamak için
        self._agent_cache: dict[AgentRole, BaseAgent] = {}

        # Circuit Breaker — LLM provider koruması
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        )
        # LLM client'ı circuit breaker ile sar
        self._wrapped_llm: CircuitBreakerLLMClient | None = None
        if llm_client:
            self._wrapped_llm = CircuitBreakerLLMClient(llm_client, self.circuit_breaker)

        # Metrics
        self.metrics = PipelineMetrics()

    def set_llm_client(self, client: BaseLLMClient) -> None:
        """LLM client'ı güncelle (cache'lenmiş agent'lar dahil).

        Runtime'da LLM provider değiştirmek için kullanılır.
        Circuit breaker sıfırlanır.
        """
        self.llm_client = client
        self._wrapped_llm = CircuitBreakerLLMClient(client, self.circuit_breaker)
        # Cache'lenmiş agent'ların client'ını da güncelle (wrapped)
        for agent in self._agent_cache.values():
            agent.llm_client = self._wrapped_llm

    async def run(
        self,
        ticker: str,
        features: dict[str, float],
        context: dict[str, Any] | None = None,
        sector: str | None = None,
        regime: str | None = None,
        price: float | None = None,
        portfolio_info: dict | None = None,
    ) -> PipelineResult:
        """Tam agent pipeline çalıştır.

        Args:
            ticker: Hisse kodu (ör: "THYAO") — boş olamaz
            features: Feature'lar (teknik göstergeler) — boş dict bile kabul edilir
            context: Ek bağlam (prompt değişkenleri vb.)
            sector: Sektör adı
            regime: Piyasa rejimi (RISK_ON/RISK_OFF/NEUTRAL)
            price: Güncel fiyat
            portfolio_info: Portföy bilgisi (pozisyon sayısı, ağırlık vb.)

        Returns:
            PipelineResult — tüm fazların çıktılarını içerir

        Raises:
            ValueError: ticker boş ise
        """
        # Input validation
        if not ticker or not ticker.strip():
            raise ValueError("Ticker boş olamaz")

        ticker = ticker.strip().upper()
        start = time.monotonic()
        success = False

        try:
            result = await self._run_pipeline(
                ticker, features, context, sector, regime, price, portfolio_info
            )
            success = True
            return result
        except ValueError:
            raise  # ValueError'ı yukarı fırlat
        except Exception as e:
            logger.error("Pipeline failed unexpectedly", ticker=ticker, error=str(e), exc_info=True)
            # Konservatif fallback — NO_TRADE
            return self._create_fallback_result(ticker, str(e), start)
        finally:
            duration = (time.monotonic() - start) * 1000
            self.metrics.record_run(success, duration, ticker)

    async def _run_pipeline(
        self,
        ticker: str,
        features: dict[str, float],
        context: dict[str, Any] | None,
        sector: str | None,
        regime: str | None,
        price: float | None,
        portfolio_info: dict | None,
    ) -> PipelineResult:
        """Pipeline'ın asıl çalışma mantığı (ayrılmış hata yönetimi için)."""
        start = time.monotonic()

        # Bağlam hazırla — context'ten gelen anahtarlar features/sector/regime üzerine yazmaz
        safe_context = {
            k: v for k, v in (context or {}).items()
            if k not in ("features", "sector", "regime", "price")
        }
        full_context: dict[str, Any] = {
            "features": features,
            "sector": sector or "UNKNOWN",
            "regime": regime or "UNKNOWN",
            "price": price,
            **safe_context,
        }

        # Memory bağlamı ekle
        if self.enable_memory:
            for role_name, memory in self._memories.items():
                try:
                    mem_context = memory.get_context_for_task(ticker, regime)
                    full_context[f"memory_{role_name.lower()}"] = mem_context
                except Exception as e:
                    logger.warning("Failed to get memory context", role=role_name, error=str(e))

        logger.info("Agent pipeline started", ticker=ticker, regime=regime)

        # Trace context — tüm pipeline boyunca takip
        with TraceContext(ticker=ticker) as trace:
            return await self._run_phases(ticker, features, full_context, portfolio_info, trace, start)

    async def _run_phases(
        self,
        ticker: str,
        features: dict[str, float],
        full_context: dict[str, Any],
        portfolio_info: dict | None,
        trace: TraceContext,
        start: float,
    ) -> PipelineResult:
        """Pipeline fazlarını çalıştır (trace context ile)."""

        # === PHASE 1: PARALLEL RESEARCH ===
        trace.set_phase("PHASE_1_PARALLEL_RESEARCH")
        research_roles = [
            AgentRole.TECHNICAL,
            AgentRole.FUNDAMENTAL,
            AgentRole.NEWS,
            AgentRole.MACRO,
        ]
        agents = self._get_or_create_agents(research_roles)
        tasks = self._create_tasks(ticker, research_roles, full_context)

        # Circuit breaker kontrollü LLM client kullan
        effective_llm = self._wrapped_llm or self.llm_client
        parallel_result = await self.runner.run_agents(agents, tasks, effective_llm)

        # === PHASE 2: CONFLICT DETECTION ===
        trace.set_phase("PHASE_2_CONFLICT_DETECTION")
        conflict_report = self.conflict_detector.detect(parallel_result.results)

        # === PHASE 3: BULL/BEAR DEBATE (eğer çelişki varsa) ===
        trace.set_phase("PHASE_3_DEBATE")
        debate_result = None
        if self.enable_debate and conflict_report.requires_debate:
            try:
                debate_result = await self.debate_engine.run_debate(
                    ticker=ticker,
                    context=full_context,
                    llm_client=effective_llm,
                )
            except Exception as e:
                logger.warning("Debate failed, continuing without", error=str(e))

        # === PHASE 4: RISK ASSESSMENT ===
        trace.set_phase("PHASE_4_RISK_ASSESSMENT")
        try:
            risk_assessment = await self.risk_assessor.assess(
                ticker=ticker,
                agent_results=parallel_result.results,
                features=features,
                portfolio_info=portfolio_info,
                llm_client=effective_llm,
                context=full_context,
            )
        except Exception as e:
            logger.error("Risk assessment failed, using conservative default", error=str(e))
            risk_assessment = RiskAssessment(
                approved=False,
                risk_level="HIGH",
                risk_score=80.0,
                max_position_pct=0.0,
                stop_loss_pct=10.0,
                risk_factors=[f"Risk assessment error: {e}"],
                veto_reason="Risk assessment failed",
            )

        # === PHASE 5: CONFLICT RESOLUTION ===
        trace.set_phase("PHASE_5_CONFLICT_RESOLUTION")
        resolution = self.conflict_resolver.resolve(
            results=parallel_result.results,
            debate_consensus=debate_result.consensus if debate_result else None,
            risk_approved=risk_assessment.approved,
        )

        # === PHASE 6: SYNTHESIS ===
        trace.set_phase("PHASE_6_SYNTHESIS")
        try:
            synthesis = await self.synthesis_engine.synthesize(
                ticker=ticker,
                agent_results=parallel_result.results,
                debate_result=debate_result,
                resolution=resolution,
                risk_approved=risk_assessment.approved,
                agent_memory=self._memories.get("SYNTHESIS"),
                llm_client=effective_llm,
                context=full_context,
            )
        except Exception as e:
            logger.error("Synthesis failed, using fallback", error=str(e))
            synthesis = SynthesisResult(
                ticker=ticker,
                final_direction="NO_TRADE",
                final_confidence=0.0,
                weighted_score=50.0,
                consensus_reached=False,
                debate_occurred=debate_result is not None,
                risk_approved=risk_assessment.approved,
                reasoning=f"Synthesis failed: {e}",
            )

        # === PHASE 7: MEMORY UPDATE ===
        trace.set_phase("PHASE_7_MEMORY_UPDATE")
        if self.enable_memory:
            try:
                self._update_memories(ticker, parallel_result.results, synthesis)
            except Exception as e:
                logger.warning("Memory update failed", error=str(e))

        total_duration = (time.monotonic() - start) * 1000

        result = PipelineResult(
            ticker=ticker,
            timestamp=datetime.now(UTC).isoformat(),
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

    def _create_fallback_result(self, ticker: str, error: str, start: float) -> PipelineResult:
        """Pipeline çöktüğünde konservatif fallback sonuç oluştur."""
        duration = (time.monotonic() - start) * 1000

        empty_parallel = ParallelRunResult(
            results={}, total_duration_ms=0, success_count=0, failure_count=0, timeout_count=0
        )
        empty_conflict = ConflictReport(has_conflict=False, is_unanimous=False, severity=ConflictSeverity.NONE)
        empty_resolution = Resolution(direction="NO_TRADE", confidence=0.0, method="pipeline_error")
        empty_risk = RiskAssessment(
            approved=False, risk_level="HIGH", risk_score=100.0,
            max_position_pct=0.0, stop_loss_pct=10.0,
            risk_factors=[f"Pipeline error: {error}"], veto_reason="Pipeline crashed",
        )
        empty_synthesis = SynthesisResult(
            ticker=ticker, final_direction="NO_TRADE", final_confidence=0.0,
            weighted_score=50.0, consensus_reached=False, debate_occurred=False,
            risk_approved=False, reasoning=f"Pipeline error: {error}",
        )

        return PipelineResult(
            ticker=ticker,
            timestamp=datetime.now(UTC).isoformat(),
            synthesis=empty_synthesis,
            parallel_result=empty_parallel,
            conflict_report=empty_conflict,
            debate_result=None,
            risk_assessment=empty_risk,
            resolution=empty_resolution,
            total_duration_ms=round(duration, 2),
        )

    def _get_or_create_agents(self, roles: list[AgentRole]) -> dict[AgentRole, BaseAgent]:
        """Agent instance'larını getir veya oluştur (cache'li).

        LLM client değişirse cache'lenmiş agent'lar da güncellenir.
        Circuit breaker wrapped client kullanılır.
        """
        effective_llm = self._wrapped_llm or self.llm_client
        agents = {}
        for role in roles:
            if role not in self._agent_cache:
                self._agent_cache[role] = BaseAgent(role, llm_client=effective_llm)
            else:
                # LLM client güncellemesi varsa yansıt (wrapped)
                self._agent_cache[role].llm_client = effective_llm
            agents[role] = self._agent_cache[role]
        return agents

    def _create_tasks(
        self,
        ticker: str,
        roles: list[AgentRole],
        context: dict[str, Any],
    ) -> dict[AgentRole, AgentTask]:
        """Her rol için AgentTask oluştur.

        Prompt template varsa onu kullanır, yoksa genel prompt oluşturur.
        """
        template_map = {
            AgentRole.TECHNICAL: "technical",
            AgentRole.FUNDAMENTAL: "fundamental",
            AgentRole.NEWS: "news",
            AgentRole.MACRO: "macro",
        }

        tasks = {}
        for role in roles:
            template = template_map.get(role)
            if template:
                try:
                    _, user_prompt = PromptFactory.get_prompts(
                        template_name=template,
                        ticker=ticker,
                        context=context,
                    )
                except Exception as e:
                    logger.warning(
                        "Prompt template failed, using generic",
                        template=template,
                        error=str(e),
                    )
                    user_prompt = f"Analyze {ticker} from {role.value} perspective"
            else:
                user_prompt = f"Analyze {ticker} from {role.value} perspective"

            # Benzersiz task_id — uuid ile çarpışma riski sıfır
            tasks[role] = AgentTask(
                task_id=f"{ticker}-{role.value}-{uuid.uuid4().hex[:8]}",
                agent_role=role,
                ticker=ticker,
                prompt=user_prompt,
                context=context,
                template_name=template,
            )
        return tasks

    def _update_memories(
        self,
        ticker: str,
        results: dict[AgentRole, AgentResult],
        synthesis: SynthesisResult,
    ) -> None:
        """Memory'leri güncelle — task + outcome.

        Her başarılı agent sonucu için working memory'ye kaydeder.
        Gerçek getiri varsa outcome olarak da kaydeder.
        Hatalı memory işlemleri loglanır ama pipeline'ı durdurmaz.
        """
        for role, result in results.items():
            role_name = role.value
            if role_name not in self._memories:
                continue

            try:
                self._memories[role_name].record_task(
                    task_id=result.task_id,
                    ticker=ticker,
                    direction=result.output.get("direction", "NEUTRAL"),
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                )
                # Outcome kaydet (eğer gerçek getiri varsa)
                actual_return = result.output.get("actual_return")
                if actual_return is not None:
                    self._memories[role_name].record_outcome(
                        task_id=result.task_id,
                        actual_return=float(actual_return),
                        regime=result.output.get("regime", "UNKNOWN"),
                    )
            except Exception as e:
                logger.warning(
                    "Failed to update memory",
                    role=role_name,
                    task_id=result.task_id,
                    error=str(e),
                )

    def evaluate_agents(self) -> dict[str, Any]:
        """Tüm agent'ları değerlendir (self-evaluation).

        Returns:
            Her agent için accuracy, drift, calibration raporu
        """
        if not self.enable_self_eval:
            return {"enabled": False}

        try:
            return self.multi_evaluator.evaluate_all(self._memories)
        except Exception as e:
            logger.error("Agent evaluation failed", error=str(e))
            return {"enabled": True, "error": str(e)}

    def consolidate_memories(self) -> dict[str, Any]:
        """Memory'leri birleştir (periyodik bakım).

        Düşük güvenli kayıtları temizler, pattern'ları budar.
        """
        if not self.enable_memory:
            return {"enabled": False}

        results = {}
        for role_name, memory in self._memories.items():
            try:
                results[role_name] = self.consolidator.consolidate(memory)
            except Exception as e:
                logger.warning("Memory consolidation failed", role=role_name, error=str(e))
                results[role_name] = {"consolidated": False, "error": str(e)}
        return results

    def get_memory_summary(self) -> dict[str, Any]:
        """Memory özetini getir.

        Returns:
            Her agent rolü için performans istatistikleri
        """
        if not self.enable_memory:
            return {"enabled": False}

        return {role_name: memory.get_performance_summary() for role_name, memory in self._memories.items()}

    def get_metrics(self) -> dict[str, Any]:
        """Pipeline istatistiklerini getir.

        Returns:
            Çalıştırma sayısı, başarı oranı, ortalama süre, circuit breaker durumu
        """
        return {
            "pipeline": self.metrics.to_dict(),
            "circuit_breaker": self.circuit_breaker.get_stats(),
        }

    def __repr__(self) -> str:
        return (
            f"AgentPipelineOrchestrator("
            f"llm={'set' if self.llm_client else 'none'}, "
            f"debate={self.enable_debate}, "
            f"memory={self.enable_memory}, "
            f"runs={self.metrics.total_runs})"
        )
