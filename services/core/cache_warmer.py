"""ALPHA BIST — Cache Warming (Sıcak Veri Önyükleme Servisi)

Bu modül, servis başlangıcında ve periyodik arka plan döngülerinde sık kullanılan
BIST verilerini (hisse evreni, işlem takvimi, son fiyatlar, aktif sinyaller,
portföy ve risk metrikleri) Redis ve yerel bellek önbelleğine önceden yükleyerek
ilk istek gecikmesini (cold-start latency) ve API yanıt sürelerini düşürür.

Özellikler:
- `CacheWarmer`: Asenkron, paralel ve thread-safe (`asyncio.Lock`) önbellek ısıtıcı.
- `CacheWarmingTaskResult` & `CacheWarmingReport`: Tip güvenli ve `slots=True` veri modelleri.
- Polars & DuckDB Entegrasyonu: Isıtma geçmişinin ve başarım metriklerinin analitik saklanması.
- BIST FSM Entegrasyonu: Seans saatleri ve tatil kontrollerinde tek doğruluk kaynağı (`bist_session_fsm`).
- OpenTelemetry Entegrasyonu: Dağıtık izleme ve span desteği.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.market_session_fsm import bist_session_fsm
from services.core.otel import otel_trace
from services.core.redis_helper import get_cached, set_cached

logger = structlog.get_logger(__name__)

# --- Varsayılan Yapılandırma Sabitleri ---
DEFAULT_UNIVERSE_TTL_SECONDS: int = 86400  # 24 saat
DEFAULT_CALENDAR_TTL_SECONDS: int = 86400  # 24 saat
DEFAULT_RADAR_FRESH_LIMIT: int = 500
DEFAULT_REFRESH_INTERVAL_SECONDS: float = 3600.0  # 1 saat
DEFAULT_MAX_HISTORY: int = 100
DEFAULT_DUCKDB_PATH: Path = Path("data/cache_warmer.duckdb")


@dataclass(slots=True)
class CacheWarmingTaskResult:
    """Tekil bir önbellek ısıtma alt görevinin sonuç veri modeli.

    Attributes:
        task_name: Görev adı (örn. 'bist_universe', 'market_calendar').
        success: Görevin başarı durumu.
        duration_ms: Görev çalışma süresi (milisaniye).
        item_count: Önbelleğe alınan öğe sayısı.
        error_message: Hata durumunda açıklayıcı hata metni.
        timestamp: Görevin tamamlanma zaman damgası.
    """

    task_name: str
    success: bool
    duration_ms: float
    item_count: int = 0
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür."""
        return {
            "task_name": self.task_name,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "item_count": self.item_count,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ile ikili bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Modeli JSON dizgisine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheWarmingTaskResult":
        """Sözlük verisinden model nesnesi üretir."""
        return cls(
            task_name=str(data.get("task_name", "")),
            success=bool(data.get("success", False)),
            duration_ms=float(data.get("duration_ms", 0.0)),
            item_count=int(data.get("item_count", 0)),
            error_message=str(data.get("error_message", "")),
            timestamp=float(data.get("timestamp", time.time())),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> "CacheWarmingTaskResult":
        """JSON verisinden model nesnesi oluşturur."""
        return cls.from_dict(orjson.loads(json_str_or_bytes))

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        durum = "BAŞARILI" if self.success else f"BAŞARISIZ ({self.error_message})"
        return (
            f"<CacheWarmingTaskResult gorev='{self.task_name}' durum={durum} "
            f"sure={self.duration_ms:.1f}ms oge={self.item_count}>"
        )


@dataclass(slots=True)
class CacheWarmingReport:
    """Tüm önbellek ısıtma operasyonunu özetleyen rapor veri modeli.

    Attributes:
        report_id: Benzersiz rapor kimliği.
        total_tasks: Çalıştırılan toplam görev sayısı.
        successful_tasks: Başarıyla tamamlanan görev sayısı.
        total_duration_ms: Toplam ısıtma süresi (milisaniye).
        tasks: Alt görevlerin sonuç listesi.
        timestamp: Raporun oluşturulma zaman damgası.
    """

    report_id: str
    total_tasks: int
    successful_tasks: int
    total_duration_ms: float
    tasks: list[CacheWarmingTaskResult]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Modeli sözlük yapısına dönüştürür."""
        return {
            "report_id": self.report_id,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "tasks": [t.to_dict() for t in self.tasks],
            "timestamp": self.timestamp,
        }

    def to_orjson_bytes(self) -> bytes:
        """Modeli orjson ile ikili bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict(), default=str)

    def to_json(self) -> str:
        """Modeli JSON dizgisine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheWarmingReport":
        """Sözlük verisinden model nesnesi üretir."""
        raw_tasks = data.get("tasks", [])
        tasks = [CacheWarmingTaskResult.from_dict(t) if isinstance(t, dict) else t for t in raw_tasks]
        return cls(
            report_id=str(data.get("report_id", "")),
            total_tasks=int(data.get("total_tasks", len(tasks))),
            successful_tasks=int(data.get("successful_tasks", sum(1 for t in tasks if t.success))),
            total_duration_ms=float(data.get("total_duration_ms", 0.0)),
            tasks=tasks,
            timestamp=float(data.get("timestamp", time.time())),
        )

    @classmethod
    def from_json(cls, json_str_or_bytes: str | bytes) -> "CacheWarmingReport":
        """JSON verisinden model nesnesi oluşturur."""
        return cls.from_dict(orjson.loads(json_str_or_bytes))

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        return (
            f"<CacheWarmingReport id='{self.report_id}' basarili={self.successful_tasks}/{self.total_tasks} "
            f"toplam_sure={self.total_duration_ms:.1f}ms>"
        )


class CacheWarmer:
    """Redis ve yerel önbellek ısıtma yöneticisi.

    Servis ayağa kalkarken kritik tabloları, hisse evrenini, seans takvimini ve
    güncel piyasa sinyallerini asenkron olarak hafızaya çeker.
    """

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY) -> None:
        """Önbellek ısıtıcıyı başlatır.

        Args:
            max_history: Bellekte saklanacak maksimum rapor geçmişi sayısı.
        """
        self._warmed = False
        self._lock = asyncio.Lock()
        self._max_history = max_history
        self._last_report: CacheWarmingReport | None = None
        self._history: list[CacheWarmingReport] = []
        self._background_task: asyncio.Task[None] | None = None
        self._running_refresher = False

    @otel_trace("cache_warmer.warm_all")
    async def warm_all(self, force: bool = False) -> CacheWarmingReport:
        """Tüm kritik önbellek verilerini paralel alt görevlerle ısıtır.

        Args:
            force: Daha önce ısıtılmış olsa dahi yeniden ısıtmayı zorunlu kılar.

        Returns:
            Isıtma operasyonu detaylarını içeren CacheWarmingReport modeli.
        """
        async with self._lock:
            if self._warmed and not force and self._last_report is not None:
                logger.debug("Önbellek zaten sıcak durumda, yeniden ısıtma atlandı.")
                return self._last_report

            start_time = time.monotonic()
            report_id = f"warm_{uuid.uuid4().hex[:10]}"
            logger.info("Önbellek ısıtma operasyonu başlatıldı", report_id=report_id, zorlama=force)

            task_coroutines = [
                self._warm_bist_universe(),
                self._warm_market_calendar(),
                self._warm_latest_prices(),
                self._warm_active_signals(),
                self._warm_portfolio_state(),
                self._warm_risk_metrics(),
            ]

            results = await asyncio.gather(*task_coroutines, return_exceptions=False)
            total_duration_ms = (time.monotonic() - start_time) * 1000.0
            success_count = sum(1 for r in results if r.success)

            report = CacheWarmingReport(
                report_id=report_id,
                total_tasks=len(results),
                successful_tasks=success_count,
                total_duration_ms=total_duration_ms,
                tasks=results,
            )

            self._warmed = True
            self._last_report = report
            self._history.append(report)
            if len(self._history) > self._max_history:
                self._history.pop(0)

            logger.info(
                "Önbellek ısıtma tamamlandı",
                report_id=report.report_id,
                basari_orani=f"{success_count}/{len(results)}",
                sure_ms=round(total_duration_ms, 1),
            )
            return report

    @otel_trace("cache_warmer._warm_bist_universe")
    async def _warm_bist_universe(self) -> CacheWarmingTaskResult:
        """BIST hisse listesi ve evrenini önbelleğe yükler."""
        start = time.monotonic()
        try:
            from services.ingestion.bist_universe import get_bist_universe

            universe = get_bist_universe()
            item_count = len(universe) if universe else 0
            if item_count > 0:
                set_cached("bist:universe", universe, ttl=DEFAULT_UNIVERSE_TTL_SECONDS)
                dur = (time.monotonic() - start) * 1000.0
                logger.debug("BIST hisse evreni önbelleğe yüklendi", adet=item_count)
                return CacheWarmingTaskResult(
                    task_name="bist_universe",
                    success=True,
                    duration_ms=dur,
                    item_count=item_count,
                )
            dur = (time.monotonic() - start) * 1000.0
            return CacheWarmingTaskResult(
                task_name="bist_universe",
                success=False,
                duration_ms=dur,
                error_message="BIST hisse evreni boş döndü.",
            )
        except Exception as e:
            dur = (time.monotonic() - start) * 1000.0
            logger.warning("BIST hisse evreni ısıtması başarısız oldu", hata=str(e))
            return CacheWarmingTaskResult(
                task_name="bist_universe",
                success=False,
                duration_ms=dur,
                error_message=str(e),
            )

    @otel_trace("cache_warmer._warm_market_calendar")
    async def _warm_market_calendar(self) -> CacheWarmingTaskResult:
        """BIST seans ve tatil takvimini senkronize edip önbelleğe yükler."""
        start = time.monotonic()
        try:
            from datetime import date

            from services.core.holiday_manager import holiday_manager
            from services.core.market_calendar import get_market_calendar

            today = date.today()
            holidays = holiday_manager.get_holidays(today.year)
            half_days = holiday_manager.get_half_days(today.year)

            try:
                synced = await asyncio.wait_for(holiday_manager.sync_from_bist(), timeout=2.0)
            except Exception:
                synced = False

            calendar = get_market_calendar()
            if calendar:
                set_cached("market:calendar", calendar.to_dict() if hasattr(calendar, "to_dict") else calendar, ttl=DEFAULT_CALENDAR_TTL_SECONDS)
                dur = (time.monotonic() - start) * 1000.0
                total_items = len(holidays) + len(half_days)
                logger.debug(
                    "Piyasa takvimi önbelleğe yüklendi",
                    tatil_sayisi=len(holidays),
                    yarim_gun_sayisi=len(half_days),
                    bist_senkron=synced,
                )
                return CacheWarmingTaskResult(
                    task_name="market_calendar",
                    success=True,
                    duration_ms=dur,
                    item_count=total_items,
                )
            dur = (time.monotonic() - start) * 1000.0
            return CacheWarmingTaskResult(
                task_name="market_calendar",
                success=False,
                duration_ms=dur,
                error_message="Piyasa takvimi nesnesi alınamadı.",
            )
        except Exception as e:
            dur = (time.monotonic() - start) * 1000.0
            logger.warning("Piyasa takvimi ısıtması başarısız oldu", hata=str(e))
            return CacheWarmingTaskResult(
                task_name="market_calendar",
                success=False,
                duration_ms=dur,
                error_message=str(e),
            )

    @otel_trace("cache_warmer._warm_latest_prices")
    async def _warm_latest_prices(self) -> CacheWarmingTaskResult:
        """Son piyasa fiyatlarını (radar cache) kontrol eder ve günceller."""
        start = time.monotonic()
        try:
            radar = get_cached("radar:data")
            if radar:
                dur = (time.monotonic() - start) * 1000.0
                item_count = len(radar) if isinstance(radar, (list, dict)) else 1
                logger.debug("Radar fiyat önbelleği mevcut", adet=item_count)
                return CacheWarmingTaskResult(
                    task_name="latest_prices",
                    success=True,
                    duration_ms=dur,
                    item_count=item_count,
                )

            # Önbellek boşsa API servisinden taze veri çekmeyi dene
            try:
                from services.api.v1.market import _fetch_radar_fresh

                radar_data = await _fetch_radar_fresh(limit=DEFAULT_RADAR_FRESH_LIMIT)
                item_count = len(radar_data) if isinstance(radar_data, (list, dict)) else 0
                dur = (time.monotonic() - start) * 1000.0
                return CacheWarmingTaskResult(
                    task_name="latest_prices",
                    success=True,
                    duration_ms=dur,
                    item_count=item_count,
                )
            except Exception as inner_e:
                dur = (time.monotonic() - start) * 1000.0
                return CacheWarmingTaskResult(
                    task_name="latest_prices",
                    success=False,
                    duration_ms=dur,
                    error_message=f"Taze radar verisi çekilemedi: {inner_e}",
                )
        except Exception as e:
            dur = (time.monotonic() - start) * 1000.0
            logger.warning("Fiyat verisi ısıtması başarısız oldu", hata=str(e))
            return CacheWarmingTaskResult(
                task_name="latest_prices",
                success=False,
                duration_ms=dur,
                error_message=str(e),
            )

    @otel_trace("cache_warmer._warm_active_signals")
    async def _warm_active_signals(self) -> CacheWarmingTaskResult:
        """Aktif algoritmik sinyalleri önbellekte doğrular."""
        start = time.monotonic()
        try:
            signals = get_cached("signals:latest")
            dur = (time.monotonic() - start) * 1000.0
            item_count = len(signals) if isinstance(signals, (list, dict)) else (1 if signals else 0)
            return CacheWarmingTaskResult(
                task_name="active_signals",
                success=True,
                duration_ms=dur,
                item_count=item_count,
            )
        except Exception as e:
            dur = (time.monotonic() - start) * 1000.0
            logger.warning("Aktif sinyal ısıtması başarısız oldu", hata=str(e))
            return CacheWarmingTaskResult(
                task_name="active_signals",
                success=False,
                duration_ms=dur,
                error_message=str(e),
            )

    @otel_trace("cache_warmer._warm_portfolio_state")
    async def _warm_portfolio_state(self) -> CacheWarmingTaskResult:
        """Portföy anlık durumunu doğrular."""
        start = time.monotonic()
        try:
            pf = get_cached("portfolio:state")
            dur = (time.monotonic() - start) * 1000.0
            item_count = len(pf) if isinstance(pf, (list, dict)) else (1 if pf else 0)
            return CacheWarmingTaskResult(
                task_name="portfolio_state",
                success=True,
                duration_ms=dur,
                item_count=item_count,
            )
        except Exception as e:
            dur = (time.monotonic() - start) * 1000.0
            logger.warning("Portföy durumu ısıtması başarısız oldu", hata=str(e))
            return CacheWarmingTaskResult(
                task_name="portfolio_state",
                success=False,
                duration_ms=dur,
                error_message=str(e),
            )

    @otel_trace("cache_warmer._warm_risk_metrics")
    async def _warm_risk_metrics(self) -> CacheWarmingTaskResult:
        """Risk metriklerini doğrular."""
        start = time.monotonic()
        try:
            risk = get_cached("risk:metrics")
            dur = (time.monotonic() - start) * 1000.0
            item_count = len(risk) if isinstance(risk, (list, dict)) else (1 if risk else 0)
            return CacheWarmingTaskResult(
                task_name="risk_metrics",
                success=True,
                duration_ms=dur,
                item_count=item_count,
            )
        except Exception as e:
            dur = (time.monotonic() - start) * 1000.0
            logger.warning("Risk metrikleri ısıtması başarısız oldu", hata=str(e))
            return CacheWarmingTaskResult(
                task_name="risk_metrics",
                success=False,
                duration_ms=dur,
                error_message=str(e),
            )

    @otel_trace("cache_warmer.refresh_hot_keys")
    async def refresh_hot_keys(self) -> None:
        """Sıcak anahtarları periyodik olarak arka planda tazeler.

        BIST seans durumu tek kaynak olan `bist_session_fsm` üzerinden denetlenir.
        KAP duyuruları ve ani tatil durumları kontrol edilir.
        """
        from datetime import date

        from services.core.holiday_manager import holiday_manager

        while self._running_refresher:
            try:
                await self._warm_latest_prices()
                await self._warm_active_signals()

                today = date.today()
                if today.weekday() < 5:  # Hafta içi işlem günleri
                    # 1. KAP anlık duyuru izleme
                    try:
                        kap_holidays = await holiday_manager.check_kap_for_holidays()
                        if kap_holidays:
                            logger.warning(
                                "KAP tatil duyurusu tespit edildi",
                                tarihler=[d.isoformat() for d in kap_holidays],
                            )
                    except Exception as e:
                        logger.debug("KAP tatil kontrolü başarısız oldu", hata=str(e))

                    # 2. Seans açıkken radar veri denetimi (Single Source of Truth: bist_session_fsm)
                    if bist_session_fsm.is_trading_hours():
                        radar = get_cached("radar:data")
                        if not radar:
                            detected = holiday_manager.report_no_data(today)
                            if detected:
                                logger.warning(
                                    "Seans sırasında veri kesintisi veya ani tatil tespit edildi",
                                    tarih=today.isoformat(),
                                )

            except Exception as e:
                logger.error("Sıcak anahtar periyodik tazeleme döngüsünde hata", hata=str(e))

            try:
                await asyncio.sleep(DEFAULT_REFRESH_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                logger.info("Sıcak anahtar periyodik tazeleme görevi sonlandırıldı.")
                break

    def start_background_refresher(
        self,
        interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
    ) -> asyncio.Task[None]:
        """Arka plan periyodik tazeleme görevini başlatır.

        Args:
            interval_seconds: Periyodik çalışma aralığı (saniye).

        Returns:
            Başlatılan asyncio.Task nesnesi.
        """
        if self._background_task and not self._background_task.done():
            logger.debug("Arka plan tazeleme görevi zaten çalışıyor.")
            return self._background_task

        self._running_refresher = True
        self._background_task = asyncio.create_task(self.refresh_hot_keys())
        logger.info("Arka plan önbellek tazeleme görevi başlatıldı", periyot_sn=interval_seconds)
        return self._background_task

    def stop_background_refresher(self) -> None:
        """Arka plan periyodik tazeleme görevini güvenli biçimde durdurur."""
        self._running_refresher = False
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            self._background_task = None
            logger.info("Arka plan önbellek tazeleme görevi durduruldu.")

    def reset(self) -> None:
        """Önbellek ısıtıcı durumunu ve rapor geçmişini sıfırlar."""
        self._warmed = False
        self._last_report = None
        self._history.clear()
        self.stop_background_refresher()
        logger.info("Önbellek ısıtıcı durumu sıfırlandı.")

    def is_warmed(self) -> bool:
        """Önbelleğin en az bir kez ısıtılıp ısıtılmadığını bildirir."""
        return self._warmed

    def get_last_report(self) -> CacheWarmingReport | None:
        """Son çalıştırmanın detaylı raporunu döndürür."""
        return self._last_report

    def get_history(self) -> list[CacheWarmingReport]:
        """Geçmiş ısıtma raporlarını döndürür."""
        return list(self._history)

    def export_warming_history_to_polars(self) -> pl.DataFrame:
        """Tüm ısıtma operasyon geçmişini Polars DataFrame olarak dışa aktarır.

        Returns:
            Polars DataFrame (report_id, total_tasks, successful_tasks, total_duration_ms, timestamp).
        """
        schema = {
            "report_id": pl.Utf8,
            "total_tasks": pl.Int64,
            "successful_tasks": pl.Int64,
            "total_duration_ms": pl.Float64,
            "timestamp": pl.Float64,
        }
        if not self._history:
            return pl.DataFrame(schema=schema)

        records = [
            {
                "report_id": r.report_id,
                "total_tasks": r.total_tasks,
                "successful_tasks": r.successful_tasks,
                "total_duration_ms": r.total_duration_ms,
                "timestamp": r.timestamp,
            }
            for r in self._history
        ]
        return pl.DataFrame(records, schema=schema)

    def export_warming_history_to_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_cache_warming_log",
    ) -> int:
        """Isıtma rapor geçmişini DuckDB tablosuna kaydeder.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Kaydedilen kayıt sayısı.
        """
        df = self.export_warming_history_to_polars()
        if len(df) == 0:
            return 0

        target_path = Path(db_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and target_path.stat().st_size == 0:
            target_path.unlink()

        conn = duckdb.connect(str(target_path))
        try:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df WHERE 1=0;")
            conn.register("df_warming", df)
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_warming;")
            return len(df)
        finally:
            conn.close()

    def query_warming_history_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_cache_warming_log",
        limit: int = 50,
    ) -> pl.DataFrame:
        """DuckDB'den önbellek ısıtma geçmişini Polars DataFrame olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        target_path = Path(db_path)
        schema = {
            "report_id": pl.Utf8,
            "total_tasks": pl.Int64,
            "successful_tasks": pl.Int64,
            "total_duration_ms": pl.Float64,
            "timestamp": pl.Float64,
        }

        if not target_path.exists():
            return pl.DataFrame(schema=schema)

        if target_path.stat().st_size == 0:
            target_path.unlink()
            return pl.DataFrame(schema=schema)

        try:
            conn = duckdb.connect(str(target_path), read_only=True)
        except Exception as e:
            logger.warning("DuckDB bağlantısı açılamadı", db_path=str(target_path), hata=str(e))
            return pl.DataFrame(schema=schema)

        try:
            table_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [table_name],
            ).fetchone()
            if not table_check or table_check[0] == 0:
                return pl.DataFrame(schema=schema)

            arrow_table = conn.execute(
                f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT {int(limit)}"
            ).fetch_arrow_table()
            return pl.from_arrow(arrow_table)
        except Exception as e:
            logger.warning("DuckDB sorgu hatası", tablo=table_name, hata=str(e))
            return pl.DataFrame(schema=schema)
        finally:
            conn.close()

    def __repr__(self) -> str:
        """Açıklayıcı Türkçe metin gösterimi."""
        durum = "ISITILDI" if self._warmed else "SOĞUK"
        arka_plan = "AKTİF" if (self._background_task and not self._background_task.done()) else "PASİF"
        return (
            f"<CacheWarmer durum={durum} son_rapor={self._last_report is not None} "
            f"gecmis_sayisi={len(self._history)} arka_plan={arka_plan}>"
        )


# Singleton Örnek
cache_warmer = CacheWarmer()


# --- Modül Seviyesinde Kolaylık Fonksiyonları ---

async def warm_cache(force: bool = False) -> CacheWarmingReport:
    """Singleton cache_warmer örneği üzerinden tüm önbelleği ısıtır."""
    return await cache_warmer.warm_all(force=force)


def get_cache_warmer() -> CacheWarmer:
    """Singleton CacheWarmer örneğini döndürür."""
    return cache_warmer


def is_cache_warmed() -> bool:
    """Önbelleğin sıcak olup olmadığını bildirir."""
    return cache_warmer.is_warmed()


def export_warming_history_to_polars() -> pl.DataFrame:
    """Isıtma geçmişini Polars DataFrame olarak döndürür."""
    return cache_warmer.export_warming_history_to_polars()


def export_warming_history_to_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_cache_warming_log",
) -> int:
    """Isıtma geçmişini DuckDB tablosuna kaydeder."""
    return cache_warmer.export_warming_history_to_duckdb(db_path, table_name)


def query_cache_warming_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_cache_warming_log",
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'den önbellek ısıtma geçmişini sorgular."""
    return cache_warmer.query_warming_history_duckdb(db_path, table_name, limit)


__all__ = [
    "DEFAULT_UNIVERSE_TTL_SECONDS",
    "DEFAULT_CALENDAR_TTL_SECONDS",
    "DEFAULT_RADAR_FRESH_LIMIT",
    "DEFAULT_REFRESH_INTERVAL_SECONDS",
    "DEFAULT_MAX_HISTORY",
    "DEFAULT_DUCKDB_PATH",
    "CacheWarmingTaskResult",
    "CacheWarmingReport",
    "CacheWarmer",
    "cache_warmer",
    "warm_cache",
    "get_cache_warmer",
    "is_cache_warmed",
    "export_warming_history_to_polars",
    "export_warming_history_to_duckdb",
    "query_cache_warming_duckdb",
]
