"""
ALPHA BIST — Parallel Agent Runner v2.1

Agent'ları asyncio.gather() ile paralel çalıştırır.
Semaphore ile LLM rate limit koruması.
Partial failure handling.

v2.1 değişiklikleri:
- Placeholder docstring'ler temizlendi
- Gereksiz exception handling kaldırıldı
- AgentPipelineBuilder task_id UUID ile değiştirildi
- __repr__ metodları eklendi

FAZ 1: Paralel Çalışma
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .agent_system import (
    AgentResult,
    AgentRole,
    AgentTask,
    AIFallback,
    BaseAgent,
)
from .llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


@dataclass
class ParallelRunResult:
    """Paralel çalıştırma sonucu — tüm agent sonuçlarını ve istatistikleri içerir."""

    results: dict[AgentRole, AgentResult]
    total_duration_ms: float
    success_count: int
    failure_count: int
    timeout_count: int
    agent_durations: dict[str, float] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Başarı oranı (0-1 arası)."""
        total = self.success_count + self.failure_count + self.timeout_count
        return self.success_count / total if total > 0 else 0

    @property
    def all_failed(self) -> bool:
        """Tüm agent'lar başarısız oldu mu?"""
        return self.success_count == 0

    @property
    def partial_success(self) -> bool:
        """Kısmi başarı — bazı agent'lar başarılı, bazıları başarısız mı?"""
        total = self.success_count + self.failure_count + self.timeout_count
        return 0 < self.success_count < total

    def __repr__(self) -> str:
        return (
            f"ParallelRunResult(success={self.success_count}, "
            f"failed={self.failure_count}, timeout={self.timeout_count}, "
            f"rate={self.success_rate:.1%}, duration={self.total_duration_ms:.0f}ms)"
        )


class ParallelAgentRunner:
    """Agent'ları paralel çalıştırır.

    Özellikler:
    - asyncio.gather(return_exceptions=True) — bir agent çökse diğerleri devam eder
    - asyncio.Semaphore(max_concurrent) — LLM rate limit koruması
    - asyncio.wait_for(timeout) — takılan agent'ı kes
    - Partial failure handling — 3/4 başarılı = devam
    - Fallback — başarısız agent için rule-based sonuç
    """

    def __init__(
        self,
        max_concurrent: int = 6,
        timeout_seconds: int = 120,
        enable_fallback: bool = True,
    ):
        """Paralel agent runner oluştur.

        Args:
            max_concurrent: Aynı anda çalışacak maksimum agent sayısı
            timeout_seconds: Tek agent için timeout süresi (saniye)
            enable_fallback: Başarısız agent için rule-based fallback kullan
        """
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self.enable_fallback = enable_fallback
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def run_agents(
        self,
        agents: dict[AgentRole, BaseAgent],
        tasks: dict[AgentRole, AgentTask],
        llm_client: BaseLLMClient | None = None,
    ) -> ParallelRunResult:
        """Tüm agent'ları paralel çalıştır.

        Args:
            agents: {role: agent_instance}
            tasks: {role: task}
            llm_client: LLM client (opsiyonel)

        Returns:
            ParallelRunResult — tüm sonuçlar + istatistikler
        """
        start = time.monotonic()

        # Agent'ları eşleştir
        agent_tasks = []
        for role in agents:
            if role in tasks:
                agent_tasks.append((role, agents[role], tasks[role]))

        if not agent_tasks:
            return ParallelRunResult(
                results={},
                total_duration_ms=0,
                success_count=0,
                failure_count=0,
                timeout_count=0,
            )

        logger.info(
            "Starting parallel agent run",
            agent_count=len(agent_tasks),
            max_concurrent=self.max_concurrent,
        )

        # Paralel çalıştır
        coroutines = [self._run_one_with_semaphore(role, agent, task, llm_client) for role, agent, task in agent_tasks]

        gathered_results = await asyncio.gather(
            *coroutines,
            return_exceptions=True,
        )

        # Sonuçları işle
        results = {}
        success_count = 0
        failure_count = 0
        timeout_count = 0
        agent_durations = {}

        for (role, _agent, task), result in zip(agent_tasks, gathered_results, strict=False):
            if isinstance(result, asyncio.TimeoutError):
                timeout_count += 1
                results[role] = self._create_timeout_result(task, role)
                logger.warning("Agent timeout", role=role.value, timeout=self.timeout_seconds)
            elif isinstance(result, Exception):
                failure_count += 1
                results[role] = self._create_error_result(task, role, str(result))
                logger.error("Agent exception", role=role.value, error=str(result))
            elif isinstance(result, AgentResult):
                results[role] = result
                if result.success:
                    success_count += 1
                else:
                    failure_count += 1
                agent_durations[role.value] = result.duration_ms
            else:
                failure_count += 1
                results[role] = self._create_error_result(task, role, "Unknown result type")

        total_duration = (time.monotonic() - start) * 1000

        parallel_result = ParallelRunResult(
            results=results,
            total_duration_ms=round(total_duration, 2),
            success_count=success_count,
            failure_count=failure_count,
            timeout_count=timeout_count,
            agent_durations=agent_durations,
        )

        logger.info(
            "Parallel agent run completed",
            success=success_count,
            failed=failure_count,
            timeout=timeout_count,
            total_duration_ms=round(total_duration, 2),
            success_rate=f"{parallel_result.success_rate:.1%}",
        )

        return parallel_result

    async def _run_one_with_semaphore(
        self,
        role: AgentRole,
        agent: BaseAgent,
        task: AgentTask,
        llm_client: BaseLLMClient | None,
    ) -> AgentResult:
        """Tek agent'ı semaphore ile çalıştır.

        Timeout durumunda asyncio.TimeoutError fırlatır.
        asyncio.gather(return_exceptions=True) tarafından yakalanır.
        """
        async with self._semaphore:
            return await asyncio.wait_for(
                agent.execute(task, llm_client),
                timeout=self.timeout_seconds,
            )

    def _create_timeout_result(self, task: AgentTask, role: AgentRole) -> AgentResult:
        """Timeout sonucu oluştur — fallback varsa rule-based analiz kullanır."""
        fallback_output = {}
        if self.enable_fallback:
            fallback_output = AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)
            fallback_output["source"] = "fallback_timeout"

        return AgentResult(
            task_id=task.task_id,
            agent_role=role,
            ticker=task.ticker,
            success=False,
            output=fallback_output,
            confidence=fallback_output.get("confidence", 0.0),
            evidence=[],
            reasoning=f"Agent timed out after {self.timeout_seconds}s, fallback used",
            model_version="timeout_fallback" if self.enable_fallback else "timeout",
            prompt_version=task.template_name or "",
            input_hash="",
            duration_ms=self.timeout_seconds * 1000,
            error=f"Timeout after {self.timeout_seconds}s",
        )

    def _create_error_result(self, task: AgentTask, role: AgentRole, error: str) -> AgentResult:
        """Hata sonucu oluştur — fallback varsa rule-based analiz kullanır."""
        fallback_output = {}
        if self.enable_fallback:
            fallback_output = AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)
            fallback_output["source"] = "fallback_error"

        return AgentResult(
            task_id=task.task_id,
            agent_role=role,
            ticker=task.ticker,
            success=False,
            output=fallback_output,
            confidence=fallback_output.get("confidence", 0.0),
            evidence=[],
            reasoning=f"Agent error: {error}, fallback used" if self.enable_fallback else "",
            model_version="error_fallback" if self.enable_fallback else "error",
            prompt_version=task.template_name or "",
            input_hash="",
            duration_ms=0,
            error=error,
        )

    def __repr__(self) -> str:
        return (
            f"ParallelAgentRunner(max_concurrent={self.max_concurrent}, "
            f"timeout={self.timeout_seconds}s, fallback={self.enable_fallback})"
        )


class AgentPipelineBuilder:
    """Agent pipeline builder — fluent API ile kolay kullanım.

    Kullanım:
        result = await (AgentPipelineBuilder(llm_client)
            .with_default_agents()
            .run(ticker="THYAO", context={...}))
    """

    def __init__(self, llm_client: BaseLLMClient | None = None):
        """Pipeline builder oluştur.

        Args:
            llm_client: LLM client (opsiyonel)
        """
        self.llm_client = llm_client
        self._runner = ParallelAgentRunner()
        self._agents: dict[AgentRole, BaseAgent] = {}

    def with_runner(self, runner: ParallelAgentRunner) -> "AgentPipelineBuilder":
        """Custom runner ata.

        Args:
            runner: Paralel agent runner instance'ı

        Returns:
            Builder (fluent API)
        """
        self._runner = runner
        return self

    def with_agent(self, role: AgentRole, agent: BaseAgent) -> "AgentPipelineBuilder":
        """Tek agent ekle.

        Args:
            role: Agent rolü
            agent: Agent instance'ı

        Returns:
            Builder (fluent API)
        """
        self._agents[role] = agent
        return self

    def with_default_agents(self) -> "AgentPipelineBuilder":
        """Varsayılan agent'ları ekle (TECHNICAL, FUNDAMENTAL, NEWS, MACRO)."""
        for role in [
            AgentRole.TECHNICAL,
            AgentRole.FUNDAMENTAL,
            AgentRole.NEWS,
            AgentRole.MACRO,
        ]:
            self._agents[role] = BaseAgent(role, llm_client=self.llm_client)
        return self

    async def run(
        self,
        ticker: str,
        context: dict[str, Any],
    ) -> ParallelRunResult:
        """Pipeline'ı çalıştır.

        Args:
            ticker: Hisse kodu
            context: Bağlam (features, price, news, vb.)

        Returns:
            ParallelRunResult
        """
        template_map = {
            AgentRole.TECHNICAL: "technical",
            AgentRole.FUNDAMENTAL: "fundamental",
            AgentRole.NEWS: "news",
            AgentRole.MACRO: "macro",
        }

        tasks = {}
        for role in self._agents:
            tasks[role] = AgentTask(
                task_id=f"{ticker}-{role.value}-{uuid.uuid4().hex[:8]}",
                agent_role=role,
                ticker=ticker,
                prompt=f"Analyze {ticker} from {role.value} perspective",
                context=context,
                template_name=template_map.get(role),
            )

        return await self._runner.run_agents(self._agents, tasks, self.llm_client)

    def __repr__(self) -> str:
        return (
            f"AgentPipelineBuilder(agents={len(self._agents)}, "
            f"runner={self._runner!r})"
        )
