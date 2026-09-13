"""
ALPHA BIST — Pipeline DAG (Yönlü Döngüsüz Çizge) Yürütücüsü

BIST günlük işlem ve EOD pipeline aşamalarını (Veri → Feature → Rejim → Model → Portföy → Risk → Emir)
bağımlılıklarına göre sıralayan, hata kurtarma (RecoveryEngine) ve performans/SLA takibi
(PipelineMonitor) ile entegre uçtan uca yürütüm motoru.

Özellikler:
  - Topolojik sıra ile adım sıralama (Kahn algoritması)
  - Kritik adım koruması: Risk veya veri aşamasında hata olursa Fail-Closed duruş
  - Aşama bazlı RecoveryEngine (CircuitBreaker ve Retry) koruması
  - PipelineMonitor ile otomatik SLA ve süre metrik kaydı
  - Paralel veya sıralı yürütüm desteği
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import structlog

from services.pipeline.pipeline_monitor import PipelineMonitor, pipeline_monitor
from services.pipeline.recovery_engine import RecoveryEngine, recovery_engine

logger = structlog.get_logger(__name__)


class TaskState(Enum):
    """DAG görev yürütüm durumu."""

    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class DAGTask:
    """DAG içindeki tek bir pipeline görevi.

    Attributes:
        name: Görev adı (benzersiz).
        fn: Çalıştırılacak fonksiyon (Callable[[], Any]).
        dependencies: Bu görevden önce tamamlanması gereken görev isimleri.
        is_critical: True ise hata durumunda tüm pipeline durur (Fail-Closed).
        sla_seconds: Görev için hedeflenen azami süre.
        state: Mevcut yürütüm durumu.
        result: Görev çıktısı.
        error: Görev hatası (varsa).
        duration_seconds: Fiili çalışma süresi.
    """

    name: str
    fn: Callable[..., Any]
    dependencies: list[str] = field(default_factory=list)
    is_critical: bool = True
    sla_seconds: float = 60.0
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: str = ""
    duration_seconds: float = 0.0

    def __repr__(self) -> str:
        """DAGTask kısa temsili."""
        return f"DAGTask({self.name}, state={self.state.name}, critical={self.is_critical})"


@dataclass
class DAGExecutionResult:
    """Tüm DAG yürütümünün nihai özeti.

    Attributes:
        execution_id: Oturum kimliği.
        pipeline_name: Pipeline adı.
        start_time: Başlama zamanı.
        end_time: Bitiş zamanı.
        total_duration_seconds: Toplam yürütüm süresi.
        is_success: Tüm kritik adımlar başarılı mı?
        tasks: Görev sonuçları haritası.
    """

    execution_id: str
    pipeline_name: str
    start_time: datetime
    end_time: datetime | None = None
    total_duration_seconds: float = 0.0
    is_success: bool = False
    tasks: dict[str, DAGTask] = field(default_factory=dict)

    def __repr__(self) -> str:
        """DAGExecutionResult temsili."""
        status = "SUCCESS" if self.is_success else "FAILED"
        return (
            f"DAGExecutionResult({self.pipeline_name} [{status}], "
            f"duration={self.total_duration_seconds:.2f}s, "
            f"tasks={len(self.tasks)})"
        )


class PipelineDAGExecutor:
    """BIST Pipeline DAG Yürütücü Motoru."""

    def __init__(
        self,
        pipeline_name: str = "bist_daily_pipeline",
        monitor: PipelineMonitor | None = None,
        recovery: RecoveryEngine | None = None,
    ) -> None:
        """PipelineDAGExecutor başlatıcı.

        Args:
            pipeline_name: Pipeline ismi.
            monitor: İzleme motoru.
            recovery: Hata kurtarma motoru.
        """
        self.pipeline_name = pipeline_name
        self.monitor = monitor or pipeline_monitor
        self.recovery = recovery or recovery_engine
        self._tasks: dict[str, DAGTask] = {}

    def __repr__(self) -> str:
        """Executor temsili."""
        return f"PipelineDAGExecutor({self.pipeline_name}, registered_tasks={len(self._tasks)})"

    def add_task(
        self,
        name: str,
        fn: Callable[..., Any],
        dependencies: list[str] | None = None,
        is_critical: bool = True,
        sla_seconds: float = 60.0,
    ) -> DAGTask:
        """Yeni bir DAG görevi ekler.

        Args:
            name: Benzersiz görev adı.
            fn: Yürütülecek fonksiyon.
            dependencies: Öncelikli görev isimleri.
            is_critical: Kritik adım mı?
            sla_seconds: SLA hedef süresi.

        Returns:
            Oluşturulan DAGTask.
        """
        task = DAGTask(
            name=name,
            fn=fn,
            dependencies=dependencies or [],
            is_critical=is_critical,
            sla_seconds=sla_seconds,
        )
        self._tasks[name] = task
        self.monitor.set_sla_threshold(name, sla_seconds)
        return task

    def _resolve_execution_order(self) -> list[DAGTask]:
        """Kahn algoritması ile topolojik sıra hesaplar.

        Returns:
            Sıralı DAGTask listesi.

        Raises:
            ValueError: Çizgede döngü (cycle) tespit edilirse.
        """
        in_degree = {name: 0 for name in self._tasks}
        adj: dict[str, list[str]] = {name: [] for name in self._tasks}

        for name, task in self._tasks.items():
            for dep in task.dependencies:
                if dep not in self._tasks:
                    msg = f"Tanımsız bağımlılık: '{dep}' ('{name}' için)"
                    raise ValueError(msg)
                adj[dep].append(name)
                in_degree[name] += 1

        queue = [name for name, deg in in_degree.items() if deg == 0]
        order: list[str] = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) < len(self._tasks):
            msg = "Pipeline DAG döngü (cycle) içeriyor, yürütülemez!"
            raise ValueError(msg)

        return [self._tasks[name] for name in order]

    def execute(self, execution_id: str | None = None) -> DAGExecutionResult:
        """Tanımlı DAG görevlerini sırayla yürütür.

        Args:
            execution_id: Oturum kimliği (verilmezse otomatik üretilir).

        Returns:
            DAGExecutionResult yürütüm özeti.
        """
        exec_id = execution_id or uuid.uuid4().hex[:12]
        ordered_tasks = self._resolve_execution_order()
        start_time = datetime.now(tz=UTC)
        t_global_start = time.perf_counter()

        logger.info(
            "Pipeline DAG yürütümü başladı.",
            pipeline=self.pipeline_name,
            execution_id=exec_id,
            task_count=len(ordered_tasks),
        )

        all_critical_passed = True
        failed_tasks: set[str] = set()

        for task in ordered_tasks:
            # Bağımlılıklardan biri çöktü mü?
            has_failed_dep = any(dep in failed_tasks for dep in task.dependencies)
            if has_failed_dep:
                task.state = TaskState.SKIPPED
                task.error = "Öncül görev başarısız olduğu için atlandı."
                logger.warning("Görev atlandı.", task=task.name, sebep=task.error)
                continue

            task.state = TaskState.RUNNING
            t_task_start = time.perf_counter()

            try:
                with self.monitor.track_stage(
                    pipeline_name=self.pipeline_name,
                    stage_name=task.name,
                    execution_id=exec_id,
                ):
                    # RecoveryEngine ile güvenli yürütüm
                    rec_result = self.recovery.execute_with_recovery(
                        stage_name=task.name,
                        fn=task.fn,
                    )
                    if rec_result.success:
                        task.result = rec_result.final_result
                        task.state = TaskState.SUCCESS
                    else:
                        task.state = TaskState.FAILED
                        last_err = rec_result.attempts[-1].error_message if rec_result.attempts else "Bilinmeyen hata"
                        task.error = last_err

            except Exception as exc:
                task.state = TaskState.FAILED
                task.error = str(exc)

            task.duration_seconds = time.perf_counter() - t_task_start

            if task.state == TaskState.FAILED:
                failed_tasks.add(task.name)
                logger.error(
                    "DAG görevi başarısız!",
                    task=task.name,
                    critical=task.is_critical,
                    error=task.error,
                )
                if task.is_critical:
                    all_critical_passed = False
                    logger.critical(
                        "Kritik adım çöktü! Fail-Closed prensibi ile pipeline durduruluyor.",
                        task=task.name,
                    )
                    break

        total_duration = time.perf_counter() - t_global_start
        end_time = datetime.now(tz=UTC)

        result = DAGExecutionResult(
            execution_id=exec_id,
            pipeline_name=self.pipeline_name,
            start_time=start_time,
            end_time=end_time,
            total_duration_seconds=total_duration,
            is_success=all_critical_passed,
            tasks=dict(self._tasks),
        )

        logger.info(
            "Pipeline DAG tamamlandı.",
            pipeline=self.pipeline_name,
            duration=round(total_duration, 2),
            is_success=result.is_success,
        )
        return result


__all__ = [
    "DAGExecutionResult",
    "DAGTask",
    "PipelineDAGExecutor",
    "TaskState",
]
