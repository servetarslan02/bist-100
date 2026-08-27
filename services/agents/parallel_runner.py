"""
ALPHA BIST — Parallel Agent Runner v1.0

Agent'ları asyncio.gather() ile paralel çalıştırır.
Semaphore ile LLM rate limit koruması.
Partial failure handling.

FAZ 1: Paralel Çalışma
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from .agent_system import (
    AgentResult,
    AgentRole,
    AgentTask,
    AIFallback,
    BaseAgent,
)
from .llm_client import BaseLLMClient

logger = structlog.get_logger()


@dataclass
class ParallelRunResult:
    """Paralel çalıştırma sonucu."""

    results: dict[AgentRole, AgentResult]
    total_duration_ms: float
    success_count: int
    failure_count: int
    timeout_count: int
    agent_durations: dict[str, float] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count + self.timeout_count
        return self.success_count / total if total > 0 else 0

    @property
    def all_failed(self) -> bool:
        return self.success_count == 0

    @property
    def partial_success(self) -> bool:
        return 0 < self.success_count < (self.success_count + self.failure_count + self.timeout_count)


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
        """Tek agent'ı semaphore ile çalıştır."""
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    agent.execute(task, llm_client),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                raise
            except Exception as e:
                logger.error("Agent execution error", role=role.value, error=str(e))
                raise

    def _create_timeout_result(self, task: AgentTask, role: AgentRole) -> AgentResult:
        """Timeout sonucu oluştur."""
        fallback_output = {}
        if self.enable_fallback:
            fallback_output = AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)
            fallback_output["source"] = "fallback_timeout"

        return AgentResult(
            task_id=task.task_id,
            agent_role=role,
            ticker=task.ticker,
            success=self.enable_fallback,
            output=fallback_output,
            confidence=fallback_output.get("confidence", 0.0),
            evidence=[],
            reasoning=f"Agent timed out after {self.timeout_seconds}s",
            model_version="timeout",
            prompt_version="",
            input_hash="",
            duration_ms=self.timeout_seconds * 1000,
            error=f"Timeout after {self.timeout_seconds}s",
        )

    def _create_error_result(self, task: AgentTask, role: AgentRole, error: str) -> AgentResult:
        """Hata sonucu oluştur."""
        fallback_output = {}
        if self.enable_fallback:
            fallback_output = AIFallback.rule_based_analysis(task.context.get("features", {}), task.ticker)
            fallback_output["source"] = "fallback_error"

        return AgentResult(
            task_id=task.task_id,
            agent_role=role,
            ticker=task.ticker,
            success=self.enable_fallback,
            output=fallback_output,
            confidence=fallback_output.get("confidence", 0.0),
            evidence=[],
            reasoning="",
            model_version="error",
            prompt_version="",
            input_hash="",
            duration_ms=0,
            error=error,
        )


class AgentPipelineBuilder:
    """Agent pipeline builder — kolay kullanım için."""

    def __init__(self, llm_client: BaseLLMClient | None = None):
        self.llm_client = llm_client
        self._runner = ParallelAgentRunner()
        self._agents: dict[AgentRole, BaseAgent] = {}

    def with_runner(self, runner: ParallelAgentRunner) -> "AgentPipelineBuilder":
        self._runner = runner
        return self

    def with_agent(self, role: AgentRole, agent: BaseAgent) -> "AgentPipelineBuilder":
        self._agents[role] = agent
        return self

    def with_default_agents(self) -> "AgentPipelineBuilder":
        """Varsayılan agent'ları ekle."""
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
        """Pipeline'ı çalıştır."""
        # Task'ları oluştur
        template_map = {
            AgentRole.TECHNICAL: "technical",
            AgentRole.FUNDAMENTAL: "fundamental",
            AgentRole.NEWS: "news",
            AgentRole.MACRO: "macro",
        }

        tasks = {}
        for role in self._agents:
            tasks[role] = AgentTask(
                task_id=f"{ticker}-{role.value}-{int(time.time())}",
                agent_role=role,
                ticker=ticker,
                prompt=f"Analyze {ticker} from {role.value} perspective",
                context=context,
                template_name=template_map.get(role),
            )

        return await self._runner.run_agents(self._agents, tasks, self.llm_client)
