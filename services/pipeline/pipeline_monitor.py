"""
ALPHA BIST — Pipeline İzleme & SLA Metrik Motoru

Tüm veri çekme, feature hesaplama, model tahmini ve emir yürütüm aşamalarının
çalışma sürelerini (latency), kaynak kullanımını (bellek/işlemci) ve SLA (Hizmet Seviyesi
Anlaşması) hedeflerini denetleyen merkezi izleme motoru.

Özellikler:
  - Adım bazlı SLA eşikleri (örn: Veri çekme max 120s, Tahmin max 45s)
  - SLA ihlali tespit ve uyarı mekanizması (Warning/Critical)
  - Aşama süre ve başarı/başarısızlık oranı istatistikleri
  - DuckDB tabanlı metrik arşivi
  - Prometheus uyumlu metrik formatlama çıktısı
"""
from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

import duckdb
import structlog

logger = structlog.get_logger(__name__)

DB_TABLE_PIPELINE_METRICS = "pipeline_execution_metrics"


class PipelineStatus(Enum):
    """Aşama yürütüm durumu."""

    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    SLA_VIOLATED = auto()


@dataclass
class StageMetric:
    """Tek bir pipeline aşamasının metrik kaydı.

    Attributes:
        pipeline_name: Ana pipeline adı (örn: daily_unified, eod_inference).
        stage_name: Aşama adı (örn: data_fetch, feature_calc, model_predict).
        execution_id: Yürütüm oturum kimliği.
        start_time: Başlangıç zamanı.
        end_time: Bitiş zamanı.
        duration_seconds: Yürütüm süresi (saniye).
        sla_threshold_seconds: Belirlenen azami hedef süre.
        status: Başarı / Hata / SLA ihlali durumu.
        records_processed: İşlenen satır / ticker sayısı.
        error_message: Hata metni (varsa).
        metadata: İlave bağlam verileri.
    """

    pipeline_name: str
    stage_name: str
    execution_id: str
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    sla_threshold_seconds: float = 60.0
    status: PipelineStatus = PipelineStatus.RUNNING
    records_processed: int = 0
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_sla_breached(self) -> bool:
        """SLA eşiği aşıldı mı kontrolü."""
        return self.duration_seconds > self.sla_threshold_seconds

    def __repr__(self) -> str:
        """Kısa temsil."""
        return (
            f"StageMetric({self.stage_name}: {self.duration_seconds:.2f}s / "
            f"SLA: {self.sla_threshold_seconds}s, status={self.status.name})"
        )


class PipelineMonitor:
    """Merkezi Pipeline Gözlem ve SLA Motoru."""

    def __init__(
        self,
        db_path: str = "data/pipeline_metrics.duckdb",
        default_sla_seconds: float = 60.0,
    ) -> None:
        """PipelineMonitor başlatıcı.

        Args:
            db_path: DuckDB dosya yolu.
            default_sla_seconds: Varsayılan aşama SLA eşiği.
        """
        self.db_path = db_path
        self.default_sla_seconds = default_sla_seconds
        self._lock = threading.RLock()
        self._memory_con = duckdb.connect(":memory:") if self.db_path == ":memory:" else None
        self._stage_sla_config: dict[str, float] = {
            "market_data_ingest": 180.0,
            "feature_engineering": 120.0,
            "regime_detection": 30.0,
            "model_inference": 45.0,
            "portfolio_optimization": 60.0,
            "risk_checks": 15.0,
            "order_execution": 20.0,
        }
        self._metrics_history: list[StageMetric] = []
        self._init_db()

    def __repr__(self) -> str:
        """PipelineMonitor temsili."""
        return f"PipelineMonitor(history_len={len(self._metrics_history)}, db={self.db_path})"

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısını döndürür."""
        if self._memory_con is not None:
            return self._memory_con
        return duckdb.connect(self.db_path)

    def _init_db(self) -> None:
        """DuckDB tablosunu oluşturur."""
        try:
            con = self._get_connection()
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_PIPELINE_METRICS} (
                    execution_id            VARCHAR NOT NULL,
                    pipeline_name           VARCHAR NOT NULL,
                    stage_name              VARCHAR NOT NULL,
                    start_time              TIMESTAMP NOT NULL,
                    end_time                TIMESTAMP,
                    duration_seconds        DOUBLE,
                    sla_threshold_seconds   DOUBLE,
                    status                  VARCHAR NOT NULL,
                    records_processed       BIGINT,
                    error_message           VARCHAR
                )
            """)
            if self._memory_con is None:
                con.close()
            logger.info("Pipeline monitor DuckDB hazır.", db=self.db_path)
        except Exception as exc:
            logger.warning("Pipeline monitor DB başlatılamadı.", hata=str(exc))

    def set_sla_threshold(self, stage_name: str, seconds: float) -> None:
        """Belirli bir aşama için SLA süresi tanımlar.

        Args:
            stage_name: Aşama adı.
            seconds: Azami süre (saniye).
        """
        with self._lock:
            self._stage_sla_config[stage_name] = max(0.1, seconds)

    @contextlib.contextmanager
    def track_stage(
        self,
        pipeline_name: str,
        stage_name: str,
        execution_id: str,
        records_processed: int = 0,
    ) -> Generator[StageMetric, None, None]:
        """Bir aşamanın çalışma süresini ve durumunu bağlam yöneticisi ile izler.

        Args:
            pipeline_name: Pipeline ismi.
            stage_name: Aşama ismi.
            execution_id: Oturum kimliği.
            records_processed: İşlenecek tahmini/fiili kayıt adedi.

        Yields:
            Aşama süreci StageMetric nesnesi.
        """
        sla_target = self._stage_sla_config.get(stage_name, self.default_sla_seconds)
        metric = StageMetric(
            pipeline_name=pipeline_name,
            stage_name=stage_name,
            execution_id=execution_id,
            start_time=datetime.now(tz=UTC),
            sla_threshold_seconds=sla_target,
            records_processed=records_processed,
            status=PipelineStatus.RUNNING,
        )
        t0 = time.perf_counter()

        try:
            yield metric
            metric.duration_seconds = time.perf_counter() - t0
            metric.end_time = datetime.now(tz=UTC)

            if metric.is_sla_breached:
                metric.status = PipelineStatus.SLA_VIOLATED
                logger.warning(
                    "Aşama SLA eşiğini aştı!",
                    pipeline=pipeline_name,
                    stage=stage_name,
                    duration_s=round(metric.duration_seconds, 2),
                    sla_target_s=sla_target,
                )
            else:
                metric.status = PipelineStatus.SUCCESS

        except Exception as exc:
            metric.duration_seconds = time.perf_counter() - t0
            metric.end_time = datetime.now(tz=UTC)
            metric.status = PipelineStatus.FAILED
            metric.error_message = str(exc)
            logger.error(
                "Aşama yürütümünde hata!",
                pipeline=pipeline_name,
                stage=stage_name,
                duration_s=round(metric.duration_seconds, 2),
                hata=str(exc),
            )
            raise
        finally:
            self._record_metric(metric)

    def _record_metric(self, metric: StageMetric) -> None:
        """Metriği listeye ve DuckDB'ye yazar."""
        with self._lock:
            self._metrics_history.append(metric)

        try:
            con = self._get_connection()
            con.execute(
                f"""
                INSERT INTO {DB_TABLE_PIPELINE_METRICS}
                    (execution_id, pipeline_name, stage_name, start_time,
                     end_time, duration_seconds, sla_threshold_seconds,
                     status, records_processed, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    metric.execution_id,
                    metric.pipeline_name,
                    metric.stage_name,
                    metric.start_time,
                    metric.end_time,
                    metric.duration_seconds,
                    metric.sla_threshold_seconds,
                    metric.status.name,
                    metric.records_processed,
                    metric.error_message,
                ],
            )
            if self._memory_con is None:
                con.close()
        except Exception as exc:
            logger.warning("Pipeline metrik kaydedilemedi.", stage=metric.stage_name, hata=str(exc))

    def get_stage_stats(self, stage_name: str) -> dict[str, Any]:
        """Aşama için tarihsel istatistikleri döndürür.

        Args:
            stage_name: Aşama adı.

        Returns:
            {count, avg_duration_s, max_duration_s, sla_breach_rate, success_rate} sözlüğü.
        """
        with self._lock:
            relevant = [m for m in self._metrics_history if m.stage_name == stage_name]

        if not relevant:
            return {
                "stage_name": stage_name,
                "count": 0,
                "avg_duration_s": 0.0,
                "max_duration_s": 0.0,
                "sla_breach_rate": 0.0,
                "success_rate": 0.0,
            }

        total_cnt = len(relevant)
        durations = [m.duration_seconds for m in relevant]
        success_cnt = sum(1 for m in relevant if m.status in (PipelineStatus.SUCCESS, PipelineStatus.SLA_VIOLATED))
        breach_cnt = sum(1 for m in relevant if m.is_sla_breached)

        return {
            "stage_name": stage_name,
            "count": total_cnt,
            "avg_duration_s": round(sum(durations) / total_cnt, 3),
            "max_duration_s": round(max(durations), 3),
            "sla_breach_rate": round(breach_cnt / total_cnt, 3),
            "success_rate": round(success_cnt / total_cnt, 3),
        }

    def export_prometheus_metrics(self) -> str:
        """Prometheus formatında metrik dökümü üretir.

        Returns:
            Prometheus text formatında metrikler.
        """
        lines = [
            "# HELP bist_pipeline_stage_duration_seconds Pipeline aşama yürütüm süresi",
            "# TYPE bist_pipeline_stage_duration_seconds gauge",
        ]

        with self._lock:
            for m in self._metrics_history[-50:]:  # Son 50 aşama
                status_label = m.status.name.lower()
                lines.append(
                    f'bist_pipeline_stage_duration_seconds{{pipeline="{m.pipeline_name}",'
                    f'stage="{m.stage_name}",status="{status_label}"}} {m.duration_seconds:.4f}'
                )

        return "\n".join(lines)


# Singleton
pipeline_monitor = PipelineMonitor()

__all__ = [
    "PipelineMonitor",
    "PipelineStatus",
    "StageMetric",
    "pipeline_monitor",
]
