"""ALPHA BIST — Periyodik Sistem Sağlık ve Bütünlük Raporlayıcı (Health Reporter).

Bu modül, platformun tüm operasyonel bileşenlerinin (İnternet bağlantısı, Downtime takipçisi,
Veri bütünlüğü doğrulayıcı, DLQ kuyruğu, Offline kuyruk, Backfill motoru, PostgreSQL, ClickHouse
ve Redis) çalışma durumunu asenkron olarak sorgular, tek bir sağlık raporunda (SystemHealthReport)
birleştirir; DuckDB ve Polars analitik denetim entegrasyonu sunar.

Bileşen Sağlık Seviyeleri:
- "HEALTHY": Tüm sistem bileşenleri tam kapasite çalışıyor, kritik aksaklık veya kuyruk birikmesi yok.
- "DEGRADED": Kritik olmayan bir bileşende aksaklık var (örn. DLQ > 100 veya bağlantı kopukluğu).
- "UNHEALTHY": PostgreSQL veya ClickHouse gibi birincil veri tabanı katmanlarına erişilemiyor.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import psutil
import structlog

from services.core.otel import otel_trace

try:
    from services.core.connectivity import connectivity_monitor
except ImportError:
    connectivity_monitor = None  # type: ignore[assignment]

try:
    from services.core.downtime_tracker import downtime_tracker
except ImportError:
    downtime_tracker = None  # type: ignore[assignment]

try:
    from services.core.data_integrity import data_integrity_validator
except ImportError:
    data_integrity_validator = None  # type: ignore[assignment]

try:
    from services.core.persistent_dlq import persistent_dlq
except ImportError:
    persistent_dlq = None  # type: ignore[assignment]

try:
    from services.core.offline_queue import offline_queue
except ImportError:
    offline_queue = None  # type: ignore[assignment]

try:
    from services.ingestion.backfill import backfill_manager
except ImportError:
    backfill_manager = None  # type: ignore[assignment]

logger = structlog.get_logger(__name__)

# ==============================================================================
# Standart Sağlık ve Eşik Değer Sabitleri
# ==============================================================================

STATUS_HEALTHY: str = "HEALTHY"
STATUS_DEGRADED: str = "DEGRADED"
STATUS_UNHEALTHY: str = "UNHEALTHY"

DEFAULT_MAX_HISTORY: int = 100
DEFAULT_DOWNTIME_THRESHOLD_SEC: float = 3600.0
DEFAULT_DLQ_THRESHOLD: int = 100
DEFAULT_HEALTH_AUDIT_DB_PATH: str = "data/health_audit.duckdb"


# ==============================================================================
# Veri Modelleri
# ==============================================================================


@dataclass(slots=True)
class SystemHealthReport:
    """Sistem genel sağlık raporu veri modeli.

    Attributes:
        timestamp: Rapor oluşturulma zaman damgası (ISO 8601 UTC).
        overall_health: Genel sağlık durumu ('HEALTHY', 'DEGRADED', 'UNHEALTHY').
        uptime: Süreç çalışma süresi detayları.
        components: Alt bileşenlerin bireysel durum sözlüğü.
        issues: Tespit edilen aksaklık ve uyarı listesi.
        generation_duration_seconds: Rapor oluşturma süresi (saniye).
    """

    timestamp: str
    overall_health: str
    uptime: dict[str, Any]
    components: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    generation_duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştür."""
        return {
            "timestamp": self.timestamp,
            "overall_health": self.overall_health,
            "uptime": dict(self.uptime),
            "components": dict(self.components),
            "issues": list(self.issues),
            "generation_duration_seconds": self.generation_duration_seconds,
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı orjson bayt dizisi serileştirmesi."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        return (
            f"SystemHealthReport(durum='{self.overall_health}', "
            f"bilesen_sayisi={len(self.components)}, sorun_sayisi={len(self.issues)}, "
            f"sure={self.generation_duration_seconds:.3f}s)"
        )


# ==============================================================================
# Health Reporter Çekirdek Sınıfı
# ==============================================================================


class HealthReporter:
    """Sistem sağlık raporlayıcı motor.

    Platformun tüm alt bileşenlerinin operasyonel durumlarını sorgular,
    sorunları tespit eder, geçmiş metrikleri RAM'de tutar ve DuckDB/Polars denetimi sunar.
    """

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY) -> None:
        """HealthReporter başlatıcı.

        Args:
            max_history: Bellekte saklanacak maksimum rapor geçmişi sayısı.
        """
        self._lock = threading.RLock()
        self._max_history = max_history
        self._last_report: SystemHealthReport | None = None
        self._report_history: deque[SystemHealthReport] = deque(maxlen=max_history)

    def _get_uptime(self) -> dict[str, Any]:
        """Süreç çalışma süresi (uptime) bilgilerini hesaplar.

        Returns:
            dict[str, Any]: Saniye, saat ve gün bazında çalışma süreleri.
        """
        try:
            proc = psutil.Process()
            uptime_seconds = time.time() - proc.create_time()
            return {
                "seconds": round(uptime_seconds, 1),
                "hours": round(uptime_seconds / 3600, 2),
                "days": round(uptime_seconds / 86400, 2),
            }
        except Exception as e:
            logger.warning("uptime_hesaplama_hatasi", hata=str(e))
            return {"seconds": 0.0, "hours": 0.0, "days": 0.0, "error": str(e)}

    @otel_trace("health_reporter.generate_report")
    async def generate_report(
        self,
        clickhouse_client: Any = None,
        pg_pool: Any = None,
        redis_client: Any = None,
    ) -> dict[str, Any]:
        """Tüm bileşenlerin durumunu toplayıp tam sağlık raporu üretir.

        Args:
            clickhouse_client: Opsiyonel ClickHouse istemci nesnesi.
            pg_pool: Opsiyonel asyncpg PostgreSQL bağlantı havuzu.
            redis_client: Opsiyonel async Redis istemcisi.

        Returns:
            dict[str, Any]: Standartlaştırılmış sistem sağlık raporu sözlüğü.
        """
        start_time = time.time()
        components: dict[str, Any] = {}
        issues: list[str] = []
        overall_health = STATUS_HEALTHY

        # 1. İnternet ve Borsa Bağlantı Durumu
        if connectivity_monitor is not None:
            try:
                conn_status = connectivity_monitor.get_status()
                components["connectivity"] = conn_status
                conn_state = str(conn_status.get("state", "")).lower()
                is_offline = bool(getattr(connectivity_monitor, "is_offline", False) or conn_state == "offline")
                is_degraded = bool(conn_state == "degraded")

                if is_offline:
                    overall_health = STATUS_DEGRADED
                    issues.append("İnternet bağlantısı yok veya erişilemiyor (OFFLINE)")
                elif is_degraded:
                    overall_health = STATUS_DEGRADED
                    issues.append("İnternet bağlantı performansı düşük veya kısmi erişim (DEGRADED)")
            except Exception as e:
                logger.warning("saglik_bilesen_sorgu_hatasi", bilesen="connectivity", hata=str(e))
                components["connectivity"] = {"status": "unknown", "error": str(e)}
        else:
            components["connectivity"] = {"status": "not_loaded"}

        # 2. Downtime (Kesinti) Durumu
        if downtime_tracker is not None:
            try:
                dt_status = downtime_tracker.get_status()
                components["downtime"] = dt_status
                dt_sec = max(0.0, float(downtime_tracker.get_downtime_seconds()))
                if dt_sec > DEFAULT_DOWNTIME_THRESHOLD_SEC:
                    overall_health = STATUS_DEGRADED
                    issues.append(f"Son kesinti süresi eşiği aşıldı: {dt_sec / 3600:.1f} saat")
            except Exception as e:
                logger.warning("saglik_bilesen_sorgu_hatasi", bilesen="downtime", hata=str(e))
                components["downtime"] = {"status": "unknown", "error": str(e)}
        else:
            components["downtime"] = {"status": "not_loaded"}

        # 3. Veri Bütünlüğü Doğrulayıcı
        if data_integrity_validator is not None:
            try:
                components["data_integrity"] = data_integrity_validator.get_status()
            except Exception as e:
                logger.warning("saglik_bilesen_sorgu_hatasi", bilesen="data_integrity", hata=str(e))
                components["data_integrity"] = {"status": "unknown", "error": str(e)}
        else:
            components["data_integrity"] = {"status": "not_loaded"}

        # 4. DLQ (Dead Letter Queue) Durumu
        if persistent_dlq is not None:
            try:
                dlq_stats = await persistent_dlq.get_stats()
                components["dlq"] = dlq_stats
                by_status = dlq_stats.get("by_status", {}) if isinstance(dlq_stats, dict) else {}
                pending = by_status.get("PENDING", 0) + by_status.get("RETRYING", 0)
                exhausted = by_status.get("EXHAUSTED", 0)

                if pending > DEFAULT_DLQ_THRESHOLD:
                    overall_health = STATUS_DEGRADED
                    issues.append(f"DLQ bekleyen iş birikmesi: {pending} adet (eşik: {DEFAULT_DLQ_THRESHOLD})")
                if exhausted > 0:
                    overall_health = STATUS_DEGRADED
                    issues.append(f"DLQ tükenmiş (başarısız) kayıtlar mevcut: {exhausted} adet")
            except Exception as e:
                logger.warning("saglik_bilesen_sorgu_hatasi", bilesen="dlq", hata=str(e))
                components["dlq"] = {"status": "unknown", "error": str(e)}
        else:
            components["dlq"] = {"status": "not_loaded"}

        # 5. Çevrimdışı Kuyruk (Offline Queue) Durumu
        if offline_queue is not None:
            try:
                oq_stats = await offline_queue.get_stats()
                components["offline_queue"] = oq_stats
                pending_oq = (
                    oq_stats.get("pending_entries", 0) if isinstance(oq_stats, dict) else 0
                )
                if pending_oq > 0:
                    issues.append(f"Offline queue: {pending_oq} bekleyen event")
                    if pending_oq > DEFAULT_DLQ_THRESHOLD:
                        overall_health = STATUS_DEGRADED
            except Exception as e:
                logger.warning("saglik_bilesen_sorgu_hatasi", bilesen="offline_queue", hata=str(e))
                components["offline_queue"] = {"status": "unknown", "error": str(e)}
        else:
            components["offline_queue"] = {"status": "not_loaded"}

        # 6. Tarihsel Veri Tamamlama (Backfill) Durumu
        if backfill_manager is not None:
            try:
                components["backfill"] = backfill_manager.get_stats()
            except Exception as e:
                logger.warning("saglik_bilesen_sorgu_hatasi", bilesen="backfill", hata=str(e))
                components["backfill"] = {"status": "unknown", "error": str(e)}
        else:
            components["backfill"] = {"status": "not_loaded"}

        # 7. PostgreSQL Bağlantı Havuzu
        if pg_pool is not None:
            try:
                async with pg_pool.acquire() as conn:
                    version = await conn.fetchval("SELECT version()")
                    components["postgresql"] = {
                        "connected": True,
                        "version": str(version)[:50] if version else "unknown",
                    }
            except Exception as e:
                logger.error("postgresql_saglik_sorgu_hatasi", hata=str(e))
                components["postgresql"] = {
                    "connected": False,
                    "error": str(e)[:100],
                }
                overall_health = STATUS_UNHEALTHY
                issues.append("PostgreSQL veritabanı bağlantı hatası")

        # 8. ClickHouse Analitik Veritabanı
        if clickhouse_client is not None:
            try:
                result = clickhouse_client.query("SELECT version()")
                components["clickhouse"] = {
                    "connected": True,
                    "version": result.result_rows[0][0] if result.result_rows else "unknown",
                }
            except Exception as e:
                logger.error("clickhouse_saglik_sorgu_hatasi", hata=str(e))
                components["clickhouse"] = {
                    "connected": False,
                    "error": str(e)[:100],
                }
                overall_health = STATUS_UNHEALTHY
                issues.append("ClickHouse analitik veritabanı bağlantı hatası")

        # 9. Redis Önbellek ve Akış Sunucusu
        if redis_client is not None:
            try:
                pong = await redis_client.ping()
                info = await redis_client.info("memory")
                components["redis"] = {
                    "connected": bool(pong),
                    "memory_used": info.get("used_memory_human", "unknown"),
                    "keys": await redis_client.dbsize(),
                }
            except Exception as e:
                logger.warning("redis_saglik_sorgu_hatasi", hata=str(e))
                components["redis"] = {
                    "connected": False,
                    "error": str(e)[:100],
                }
                issues.append("Redis önbellek bağlantı hatası")

        # Genel durum değerlendirmesi
        if overall_health == STATUS_HEALTHY and issues:
            overall_health = STATUS_DEGRADED

        duration = round(time.time() - start_time, 3)
        now_iso = datetime.now(UTC).isoformat()
        uptime_info = self._get_uptime()

        report_model = SystemHealthReport(
            timestamp=now_iso,
            overall_health=overall_health,
            uptime=uptime_info,
            components=components,
            issues=issues,
            generation_duration_seconds=duration,
        )

        with self._lock:
            self._last_report = report_model
            self._report_history.append(report_model)

        logger.info(
            "sistem_saglik_raporu_uretildi",
            durum=overall_health,
            sorunlar=len(issues),
            sure_sn=duration,
        )
        return report_model.to_dict()

    def get_last_report(self) -> dict[str, Any] | None:
        """En son üretilen sağlık raporunu sözlük formatında döndürür.

        Returns:
            dict[str, Any] | None: Son rapor sözlüğü veya henüz üretilmediyse None.
        """
        with self._lock:
            return self._last_report.to_dict() if self._last_report else None

    def get_last_report_model(self) -> SystemHealthReport | None:
        """En son üretilen sağlık raporunu veri modeli olarak döndürür.

        Returns:
            SystemHealthReport | None: Son rapor modeli veya None.
        """
        with self._lock:
            return self._last_report

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Geçmiş sağlık raporlarının listesini döndürür.

        Args:
            limit: Döndürülecek maksimum geçmiş rapor sayısı.

        Returns:
            list[dict[str, Any]]: Rapor sözlükleri listesi.
        """
        with self._lock:
            items = list(self._report_history)
            selected = items[-limit:] if limit > 0 else items
            return [r.to_dict() for r in selected]

    def get_summary(self) -> dict[str, Any]:
        """En güncel sağlık durumu özetini döndürür.

        Returns:
            dict[str, Any]: Durum, sorun sayısı ve zaman damgası özeti.
        """
        with self._lock:
            if not self._last_report:
                return {"status": "no_report_yet", "overall_health": "UNKNOWN", "issues_count": 0}

            return {
                "overall_health": self._last_report.overall_health,
                "issues_count": len(self._last_report.issues),
                "issues": list(self._last_report.issues),
                "timestamp": self._last_report.timestamp,
                "uptime_seconds": self._last_report.uptime.get("seconds", 0.0),
            }

    # ==========================================================================
    # POLARS VE DUCKDB ENTEGRASYONU
    # ==========================================================================

    def export_history_to_polars(self) -> pl.DataFrame:
        """Rapor geçmişini analitik inceleme için Polars DataFrame'e dönüştürür.

        Returns:
            pl.DataFrame: Zaman serisi sağlık geçmişi tablosu.
        """
        with self._lock:
            items = list(self._report_history)

        if not items:
            return pl.DataFrame(
                schema={
                    "timestamp": pl.Utf8,
                    "overall_health": pl.Utf8,
                    "issues_count": pl.Int64,
                    "generation_duration_seconds": pl.Float64,
                    "uptime_seconds": pl.Float64,
                }
            )

        rows = []
        for r in items:
            rows.append(
                {
                    "timestamp": r.timestamp,
                    "overall_health": r.overall_health,
                    "issues_count": len(r.issues),
                    "generation_duration_seconds": r.generation_duration_seconds,
                    "uptime_seconds": float(r.uptime.get("seconds", 0.0)),
                }
            )

        return pl.DataFrame(rows)

    def export_to_duckdb(
        self,
        db_path: str = DEFAULT_HEALTH_AUDIT_DB_PATH,
    ) -> int:
        """Son sağlık raporunu kalıcı denetim için DuckDB tablosuna aktarır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.

        Returns:
            int: Kaydedilen satır sayısı (1 veya kayıt yoksa 0).

        Raises:
            Exception: DuckDB bağlantı veya yazma hatası durumunda.
        """
        with self._lock:
            if not self._last_report:
                return 0
            rep = self._last_report

        target_file = Path(db_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        row = (
            uuid.uuid4().hex,
            rep.timestamp,
            rep.overall_health,
            len(rep.issues),
            rep.generation_duration_seconds,
            float(rep.uptime.get("seconds", 0.0)),
            orjson.dumps(rep.to_dict()).decode("utf-8"),
        )

        with self._lock:
            conn = duckdb.connect(str(target_file))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS system_health_audit (
                        id VARCHAR PRIMARY KEY,
                        timestamp VARCHAR,
                        overall_health VARCHAR,
                        issues_count INTEGER,
                        generation_duration_seconds DOUBLE,
                        uptime_seconds DOUBLE,
                        report_json VARCHAR
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO system_health_audit (
                        id, timestamp, overall_health, issues_count,
                        generation_duration_seconds, uptime_seconds, report_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
                conn.commit()
            finally:
                conn.close()

        logger.info("saglik_raporu_duckdb_aktarildi", durum=rep.overall_health, yol=db_path)
        return 1

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            durum = self._last_report.overall_health if self._last_report else "RAPOR_YOK"
            return f"HealthReporter(son_durum='{durum}', gecmis_rapor_sayisi={len(self._report_history)})"


# ==============================================================================
# Global Singleton ve Modül Düzeyi Kolaylık Fonksiyonları
# ==============================================================================

health_reporter: HealthReporter = HealthReporter()


def get_health_reporter() -> HealthReporter:
    """Global HealthReporter tekil örneğini döner.

    Returns:
        HealthReporter: Paylaşılan raporlayıcı örneği.
    """
    return health_reporter


async def generate_health_report(
    clickhouse_client: Any = None,
    pg_pool: Any = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    """Sistem genel sağlık raporunu üretir ve sözlük olarak döner.

    Args:
        clickhouse_client: Opsiyonel ClickHouse istemci nesnesi.
        pg_pool: Opsiyonel asyncpg PostgreSQL bağlantı havuzu.
        redis_client: Opsiyonel async Redis istemcisi.

    Returns:
        dict[str, Any]: Sistem sağlık raporu sözlüğü.
    """
    return await health_reporter.generate_report(
        clickhouse_client=clickhouse_client,
        pg_pool=pg_pool,
        redis_client=redis_client,
    )


def get_last_health_report() -> dict[str, Any] | None:
    """En son üretilen sistem sağlık raporunu döner.

    Returns:
        dict[str, Any] | None: Son rapor veya None.
    """
    return health_reporter.get_last_report()


def get_health_summary() -> dict[str, Any]:
    """En güncel sistem sağlık durumu özetini döner.

    Returns:
        dict[str, Any]: Sağlık durumu ve sorun sayısı özeti.
    """
    return health_reporter.get_summary()


def export_health_to_polars() -> pl.DataFrame:
    """Tüm rapor geçmişini analitik Polars DataFrame tablosuna aktarır.

    Returns:
        pl.DataFrame: Geçmiş sağlık kayıtları.
    """
    return health_reporter.export_history_to_polars()


def export_health_to_duckdb(db_path: str = DEFAULT_HEALTH_AUDIT_DB_PATH) -> int:
    """Son sağlık raporunu DuckDB denetim tablosuna kaydeder.

    Args:
        db_path: Hedef DuckDB veritabanı dosyası.

    Returns:
        int: Kayıt durumu (1 başarılı, 0 rapor yok).
    """
    return health_reporter.export_to_duckdb(db_path=db_path)


__all__: list[str] = [
    "DEFAULT_DLQ_THRESHOLD",
    "DEFAULT_DOWNTIME_THRESHOLD_SEC",
    "DEFAULT_HEALTH_AUDIT_DB_PATH",
    "DEFAULT_MAX_HISTORY",
    "STATUS_DEGRADED",
    "STATUS_HEALTHY",
    "STATUS_UNHEALTHY",
    "HealthReporter",
    "SystemHealthReport",
    "export_health_to_duckdb",
    "export_health_to_polars",
    "generate_health_report",
    "get_health_reporter",
    "get_health_summary",
    "get_last_health_report",
    "health_reporter",
]
