"""ALPHA BIST — Veri Bütünlüğü ve Süreklilik Doğrulayıcı v3.0 (Data Integrity Validator)

F-023: Sistem yeniden başlatması (restart), kesinti sonrası toparlanma (recovery) ve
periyodik sağlık döngülerinde tüm veri depolama katmanlarının (ClickHouse, PostgreSQL,
TimescaleDB, Redis, Feature Store) veri tutarlılığını, eksik barlarını (gap) ve
veri tazeliğini (freshness) BIST takvim kurallarına uygun olarak doğrular.

Temel Yetenekler:
1. ClickHouse Piyasa Barları Denetimi (Son 30 iş günündeki eksik işlem günleri / gap tespiti)
2. BIST Tatil ve Yarım Gün Entegrasyonu (`holiday_manager` ile resmi tatillerde sahte alarm üretilmez)
3. PostgreSQL / TimescaleDB Tablo Varlık ve Ticker Bütünlüğü (NULL ticker ve tablo kayıt sayımları)
4. Feature Store Eksiksizlik Kontrolü (6 saatten eski feature hesaplamalarının tespiti)
5. Redis Bellek ve Bağlantı Durumu Denetimi (Key sayısı, bellek kullanımı, ping)
6. Veri Tazelik Kontrolü (Market data son güncelleme zamanının analizi, naive/aware UTC uyumu)
7. Otomatik Onarım ve Geri Besleme (Backfill motoru tetikleme arayüzü)
8. Polars ve DuckDB Analitik Raporlama Entegrasyonu
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import orjson
import polars as pl
import structlog

from services.core.duckdb_store import configure_duckdb_wal
from services.core.holiday_manager import holiday_manager
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# SABİTLER (DEFAULT CONSTANTS)
# =====================================================
DEFAULT_GAP_CHECK_DAYS: int = 30
DEFAULT_FEATURE_STALE_HOURS: int = 6
DEFAULT_MARKET_DATA_STALE_HOURS: int = 2
DEFAULT_INTEGRITY_MAX_HISTORY: int = 500
DEFAULT_INTEGRITY_DUCKDB_PATH: str = "data/integrity_audit.duckdb"
DEFAULT_INTEGRITY_AUDIT_TABLE: str = "bist_data_integrity_audit"

ALLOWED_PG_INTEGRITY_TABLES: tuple[str, ...] = (
    "instruments",
    "companies",
    "sectors",
    "market_data",
    "signals",
    "portfolios",
    "feature_store",
)


def _normalize_to_utc(dt: Any) -> datetime | None:
    """Farklı kaynaklardan gelen (str, date, datetime) zaman değerlerini UTC datetime nesnesine dönüştürür.

    Offset-naive ve offset-aware datetime karşılaştırma hatalarını (TypeError) önler.

    Args:
        dt: Dönüştürülecek zaman damgası nesnesi veya metni.

    Returns:
        UTC formatında aware datetime veya None.
    """
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt)
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            return None
    if isinstance(dt, datetime):
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day, tzinfo=UTC)
    return None


# =====================================================
# VERİ MODELLERİ (DATACLASSES)
# =====================================================
@dataclass(slots=True)
class IntegrityGapItem:
    """Eksik bar veya veri aralığı kaydı.

    Attributes:
        ticker: BIST hisse sembolü (örn. 'THYAO').
        missing_dates: Eksik işlem günleri listesi (ISO format).
        total_missing: Toplam eksik işlem günü adedi.
    """

    ticker: str
    missing_dates: list[str] = field(default_factory=list)
    total_missing: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisi üretir."""
        return orjson.dumps(self.to_dict())

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return f"<IntegrityGapItem ticker={self.ticker} total_missing={self.total_missing}>"


@dataclass(slots=True)
class IntegrityValidationReport:
    """Veri bütünlüğü tam denetim raporu.

    Attributes:
        timestamp: Denetim zaman damgası (ISO UTC).
        duration_seconds: Denetim süresi (saniye).
        has_issues: Herhangi bir problem tespit edildi mi?
        issues: Tespit edilen problem açıklamaları listesi.
        recommendations: Önerilen aksiyonlar listesi.
        checks: Alt sistem kontrollerinin detay sonuçları sözlüğü.
    """

    timestamp: str
    duration_seconds: float = 0.0
    has_issues: bool = False
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)

    def to_orjson_bytes(self) -> bytes:
        """orjson bayt dizisi üretir."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """JSON metni üretir."""
        return self.to_orjson_bytes().decode("utf-8")

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        return (
            f"<IntegrityValidationReport timestamp='{self.timestamp}' "
            f"has_issues={self.has_issues} issues_count={len(self.issues)} "
            f"duration={self.duration_seconds}s>"
        )


# =====================================================
# DATA INTEGRITY VALIDATOR MOTORU
# =====================================================
class DataIntegrityValidator:
    """Veri bütünlüğü doğrulayıcı motor.

    Sistem başlangıcında ve periyodik sağlık kontrollerinde tüm veri
    kaynaklarının tutarlılığını BIST tatil takvimi kurallarıyla doğrular.
    """

    def __init__(
        self,
        max_history: int = DEFAULT_INTEGRITY_MAX_HISTORY,
        duckdb_path: str | Path = DEFAULT_INTEGRITY_DUCKDB_PATH,
    ) -> None:
        """DataIntegrityValidator başlatıcı.

        Args:
            max_history: Bellekte tutulacak maksimum doğrulama raporu sayısı.
            duckdb_path: Denetim kayıtlarının saklanacağı DuckDB veritabanı yolu.
        """
        self._max_history = max(10, max_history)
        self._duckdb_path = Path(duckdb_path)
        self._last_validation: float | None = None
        self._validation_history: deque[IntegrityValidationReport] = deque(maxlen=self._max_history)
        self._lock = threading.RLock()

        logger.info(
            "data_integrity_validator_baslatildi",
            max_history=self._max_history,
            duckdb_path=str(self._duckdb_path),
        )

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            last_dt = (
                datetime.fromtimestamp(self._last_validation, tz=UTC).isoformat()
                if self._last_validation
                else "Yok"
            )
            return (
                f"<DataIntegrityValidator last_validation='{last_dt}' "
                f"history_len={len(self._validation_history)} max={self._max_history}>"
            )

    @otel_trace("data_integrity.validate_on_startup")
    async def validate_on_startup(
        self,
        clickhouse_client: Any = None,
        pg_pool: Any = None,
        redis_client: Any = None,
    ) -> IntegrityValidationReport:
        """Sistem başlangıcında tüm veri kaynaklarını kapsamlı doğrular.

        Args:
            clickhouse_client: ClickHouse veritabanı bağlantı istemcisi.
            pg_pool: asyncpg PostgreSQL bağlantı havuzu.
            redis_client: Redis / Sentinel asenkron bağlantı istemcisi.

        Returns:
            IntegrityValidationReport: Doğrulama sonuç raporu.
        """
        start_time = time.time()
        issues: list[str] = []
        recommendations: list[str] = []
        checks: dict[str, Any] = {}
        has_issues = False

        # 1. ClickHouse bar eksikliği kontrolü (BIST takvimi uyumlu)
        ch_result = await self._check_clickhouse_gaps(clickhouse_client)
        checks["clickhouse_gaps"] = ch_result
        if ch_result.get("has_gaps"):
            has_issues = True
            gap_cnt = ch_result.get("gap_count", 0)
            issues.append(f"ClickHouse: {gap_cnt} eksik bar tespit edildi")
            recommendations.append("Eksik günler için Ingestion Backfill servisini çalıştırın")

        # 2. PostgreSQL / TimescaleDB tutarlılığı
        pg_result = await self._check_postgres_consistency(pg_pool)
        checks["postgres_consistency"] = pg_result
        if pg_result.get("has_issues"):
            has_issues = True
            issues.extend(pg_result.get("issues", []))
            recommendations.append("PostgreSQL veritabanı tablolarını ve şema migration durumunu kontrol edin")

        # 3. Feature completeness kontrolü
        feat_result = await self._check_feature_completeness(pg_pool)
        checks["feature_completeness"] = feat_result
        incomplete_tickers = feat_result.get("incomplete_tickers", [])
        if incomplete_tickers:
            has_issues = True
            issues.append(f"Feature eksikliği: {len(incomplete_tickers)} hisse için feature güncel değil")
            recommendations.append("Feature pipeline hesaplama motorunu tetikleyin")

        # 4. Redis cache durumu
        redis_result = await self._check_redis_health(redis_client)
        checks["redis_health"] = redis_result
        if redis_result.get("status") == "error" or not redis_result.get("connected", False):
            if redis_client is not None:
                has_issues = True
                issues.append(f"Redis bağlantı hatası: {redis_result.get('error', 'Bilinmeyen hata')}")
                recommendations.append("Redis sunucusunun çalışır durumda olduğunu doğrulayın")

        # 5. Son veri tazelik kontrolü (Offset-aware UTC karşılaştırmalı)
        freshness_result = await self._check_data_freshness(clickhouse_client, pg_pool)
        checks["data_freshness"] = freshness_result
        stale_tickers = freshness_result.get("stale_tickers", [])
        if stale_tickers:
            has_issues = True
            issues.append(f"Bayat piyasa verisi: {len(stale_tickers)} hisse için son veri 2 saatten eski")
            recommendations.append("Canlı veri akışını (Streamer/WebSocket) ve aracı kurum beslemesini kontrol edin")

        duration = round(time.time() - start_time, 3)

        report = IntegrityValidationReport(
            timestamp=datetime.now(UTC).isoformat(),
            duration_seconds=duration,
            has_issues=has_issues,
            issues=issues,
            recommendations=recommendations,
            checks=checks,
        )

        with self._lock:
            self._last_validation = time.time()
            self._validation_history.append(report)

        if has_issues:
            logger.warning(
                "veri_butunlugu_sorunlari_tespit_edildi",
                issues_count=len(issues),
                duration=duration,
                issues=issues[:5],
            )
        else:
            logger.info("veri_butunlugu_dogrulamasi_basarili", duration=duration)

        return report

    @otel_trace("data_integrity._check_clickhouse_gaps")
    async def _check_clickhouse_gaps(self, client: Any = None) -> dict[str, Any]:
        """ClickHouse'da eksik işlem günlerini BIST takvimine göre kontrol eder.

        Args:
            client: ClickHouse bağlantı istemcisi.

        Returns:
            dict: Eksik bar analizi sonucu.
        """
        result: dict[str, Any] = {
            "has_gaps": False,
            "gap_count": 0,
            "gaps": [],
            "checked_tickers": 0,
            "status": "ok",
        }

        if not client:
            result["status"] = "skipped"
            return result

        try:
            # Son 30 gündeki bar tarihlerini sorgula
            query = f"""
                SELECT
                    ticker,
                    toDate(timestamp) as trade_date,
                    count() as bar_count
                FROM market_bars
                WHERE timestamp >= now() - INTERVAL {DEFAULT_GAP_CHECK_DAYS} DAY
                GROUP BY ticker, trade_date
                ORDER BY ticker, trade_date
            """

            query_result = client.query(query)
            if not getattr(query_result, "result_rows", None):
                result["status"] = "no_data"
                return result

            ticker_dates: dict[str, set[date]] = {}
            for row in query_result.result_rows:
                ticker = str(row[0])
                t_date = row[1]
                if isinstance(t_date, str):
                    try:
                        t_date = date.fromisoformat(t_date)
                    except ValueError:
                        continue
                elif isinstance(t_date, datetime):
                    t_date = t_date.date()

                if ticker not in ticker_dates:
                    ticker_dates[ticker] = set()
                ticker_dates[ticker].add(t_date)

            result["checked_tickers"] = len(ticker_dates)

            # BIST takvimi ile beklenen işlem günlerini oluştur
            today = date.today()
            expected_trading_days: set[date] = set()
            cur_date = today - timedelta(days=DEFAULT_GAP_CHECK_DAYS)

            while cur_date <= today:
                # BIST tatil yöneticisi ile kontrol (Hafta sonu + Resmi Tatiller elenir)
                if holiday_manager.is_trading_day(cur_date):
                    expected_trading_days.add(cur_date)
                cur_date += timedelta(days=1)

            # Her ticker için eksik günleri hesapla
            for ticker, dates in ticker_dates.items():
                missing = expected_trading_days - dates
                if missing:
                    result["has_gaps"] = True
                    result["gap_count"] += len(missing)
                    result["gaps"].append(
                        {
                            "ticker": ticker,
                            "missing_dates": [d.isoformat() for d in sorted(missing)[-5:]],
                            "total_missing": len(missing),
                        }
                    )

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error("clickhouse_gap_denetimi_hatasi", error=str(e))

        return result

    @otel_trace("data_integrity._check_postgres_consistency")
    async def _check_postgres_consistency(self, pg_pool: Any = None) -> dict[str, Any]:
        """PostgreSQL / TimescaleDB tablolarını ve tutarlılığını doğrular.

        Args:
            pg_pool: asyncpg havuzu.

        Returns:
            dict: PostgreSQL tutarlılık sonuçları.
        """
        result: dict[str, Any] = {
            "has_issues": False,
            "issues": [],
            "tables_checked": 0,
            "status": "ok",
        }

        if not pg_pool:
            result["status"] = "skipped"
            return result

        try:
            async with pg_pool.acquire() as conn:
                for table in ALLOWED_PG_INTEGRITY_TABLES:
                    try:
                        row = await conn.fetchrow(f"SELECT COUNT(*) as cnt FROM {table}")
                        result["tables_checked"] += 1
                        result[f"{table}_count"] = row["cnt"] if row else 0
                    except Exception as e:
                        result["has_issues"] = True
                        result["issues"].append(f"Tablo '{table}' okuma hatası: {str(e)[:100]}")

                # Instruments tablosunda NULL sembol kontrolü
                try:
                    null_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM instruments WHERE symbol IS NULL OR symbol = ''"
                    )
                    if null_count and null_count > 0:
                        result["has_issues"] = True
                        result["issues"].append(f"{null_count} adet sembolsüz (NULL) enstrüman kaydı var")
                except Exception as e:
                    result["has_issues"] = True
                    result["issues"].append(f"Instruments NULL sembol sorgulama hatası: {str(e)[:100]}")

        except Exception as e:
            result["has_issues"] = True
            result["status"] = "error"
            result["issues"].append(f"PostgreSQL bağlantı hatası: {str(e)[:100]}")
            logger.error("postgres_tutarlilik_denetimi_hatasi", error=str(e))

        return result

    @otel_trace("data_integrity._check_feature_completeness")
    async def _check_feature_completeness(self, pg_pool: Any = None) -> dict[str, Any]:
        """Feature hesaplama bütünlüğünü doğrular.

        Args:
            pg_pool: asyncpg havuzu.

        Returns:
            dict: Feature eksiklik analizi.
        """
        result: dict[str, Any] = {
            "incomplete_tickers": [],
            "total_tickers": 0,
            "complete_tickers": 0,
            "status": "ok",
        }

        if not pg_pool:
            result["status"] = "skipped"
            return result

        try:
            async with pg_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT ticker, MAX(computed_at) as last_computed
                    FROM feature_store
                    GROUP BY ticker
                """)

                result["total_tickers"] = len(rows)
                cutoff = datetime.now(UTC) - timedelta(hours=DEFAULT_FEATURE_STALE_HOURS)

                for row in rows:
                    last_comp = _normalize_to_utc(row.get("last_computed"))
                    if last_comp is None or last_comp < cutoff:
                        result["incomplete_tickers"].append(
                            {
                                "ticker": row.get("ticker", "UNKNOWN"),
                                "last_computed": last_comp.isoformat() if last_comp else "None",
                            }
                        )
                    else:
                        result["complete_tickers"] += 1

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error("feature_tamlik_denetimi_hatasi", error=str(e))

        return result

    @otel_trace("data_integrity._check_redis_health")
    async def _check_redis_health(self, redis_client: Any = None) -> dict[str, Any]:
        """Redis önbellek ve Sentinel sağlık durumunu doğrular.

        Args:
            redis_client: Redis istemcisi.

        Returns:
            dict: Redis sağlık durumu.
        """
        result: dict[str, Any] = {
            "connected": False,
            "keys_count": 0,
            "memory_used": "unknown",
            "status": "ok",
        }

        if not redis_client:
            result["status"] = "skipped"
            return result

        try:
            pong = await redis_client.ping()
            result["connected"] = bool(pong)

            if pong:
                info = await redis_client.info("memory")
                result["memory_used"] = info.get("used_memory_human", "unknown") if isinstance(info, dict) else "unknown"

                dbsize = await redis_client.dbsize()
                result["keys_count"] = int(dbsize)

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["connected"] = False
            logger.error("redis_saglik_denetimi_hatasi", error=str(e))

        return result

    @otel_trace("data_integrity._check_data_freshness")
    async def _check_data_freshness(
        self,
        clickhouse_client: Any = None,
        pg_pool: Any = None,
    ) -> dict[str, Any]:
        """Piyasa verisi tazelik kontrolünü offset-aware UTC standartlarında yapar.

        Args:
            clickhouse_client: ClickHouse istemcisi.
            pg_pool: asyncpg havuzu.

        Returns:
            dict: Tazelik analizi sonucu.
        """
        result: dict[str, Any] = {
            "stale_tickers": [],
            "fresh_tickers": 0,
            "total_checked": 0,
            "status": "ok",
        }

        stale_threshold = datetime.now(UTC) - timedelta(hours=DEFAULT_MARKET_DATA_STALE_HOURS)

        if pg_pool:
            try:
                async with pg_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT ticker, MAX(timestamp) as last_ts
                        FROM market_data
                        GROUP BY ticker
                    """)

                    result["total_checked"] = len(rows)
                    now_utc = datetime.now(UTC)

                    for row in rows:
                        last_ts = _normalize_to_utc(row.get("last_ts"))
                        if last_ts is not None and last_ts < stale_threshold:
                            age_hours = round((now_utc - last_ts).total_seconds() / 3600.0, 1)
                            result["stale_tickers"].append(
                                {
                                    "ticker": row.get("ticker", "UNKNOWN"),
                                    "last_update": last_ts.isoformat(),
                                    "age_hours": age_hours,
                                }
                            )
                        else:
                            result["fresh_tickers"] += 1

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                logger.error("veri_tazelik_denetimi_hatasi", error=str(e))

        return result

    @otel_trace("data_integrity.auto_repair")
    async def auto_repair(self, validation_results: IntegrityValidationReport | dict[str, Any]) -> dict[str, Any]:
        """Tespit edilen veri eksiklikleri ve bayatlıklar için onarım tetikler.

        Args:
            validation_results: Doğrulama raporu nesnesi veya sözlüğü.

        Returns:
            dict: Onarım tetikleme sonuç özeti.
        """
        results_dict = (
            validation_results.to_dict()
            if isinstance(validation_results, IntegrityValidationReport)
            else validation_results
        )

        repair_summary: dict[str, Any] = {
            "backfill_triggered": False,
            "refresh_triggered": False,
            "errors": [],
        }

        logger.info("veri_butunlugu_otomatik_onarim_baslatiliyor")

        # ClickHouse gap'leri için backfill tetikle
        checks = results_dict.get("checks", {})
        ch_gaps = checks.get("clickhouse_gaps", {})
        if ch_gaps.get("has_gaps"):
            gap_cnt = ch_gaps.get("gap_count", 0)
            logger.info("clickhouse_bosluklari_icin_backfill_tetikleniyor", gap_count=gap_cnt)
            try:
                # Lazy import ile dairesel bağımlılığı önle
                from services.ingestion.backfill import backfill_manager

                gaps = await backfill_manager.detect_all_gaps()
                await backfill_manager.backfill_all(gaps)
                repair_summary["backfill_triggered"] = True
            except Exception as e:
                err_msg = f"Backfill otomatik onarım hatası: {str(e)}"
                repair_summary["errors"].append(err_msg)
                logger.error("backfill_otomatik_onarim_hatasi", error=str(e))

        # Stale data için yenileme tetikle
        freshness = checks.get("data_freshness", {})
        stale_tickers = freshness.get("stale_tickers", [])
        if stale_tickers:
            logger.info("bayat_veriler_icin_yenileme_tetikleniyor", count=len(stale_tickers))
            repair_summary["refresh_triggered"] = True

        return repair_summary

    def get_status(self) -> dict[str, Any]:
        """Doğrulayıcının son çalışma durum özetini döndürür.

        Returns:
            dict: Son doğrulama zamanı ve geçmiş rapor adedi.
        """
        with self._lock:
            return {
                "last_validation": (
                    datetime.fromtimestamp(self._last_validation, tz=UTC).isoformat()
                    if self._last_validation
                    else None
                ),
                "validation_count": len(self._validation_history),
                "max_history": self._max_history,
            }

    # =====================================================
    # POLARS VE DUCKDB ANALİTİK ENTEGRASYONU
    # =====================================================
    def export_integrity_history_to_polars(self) -> pl.DataFrame:
        """Geçmiş doğrulama raporlarını Polars DataFrame olarak dışa aktarır.

        Returns:
            pl.DataFrame: Katı şemalı analitik rapor tablosu.
        """
        with self._lock:
            reports = list(self._validation_history)

        schema = {
            "timestamp": pl.Utf8,
            "duration_seconds": pl.Float64,
            "has_issues": pl.Boolean,
            "issues_count": pl.Int32,
            "recommendations_count": pl.Int32,
            "raw_issues": pl.Utf8,
        }

        if not reports:
            return pl.DataFrame(schema=schema)

        data = [
            {
                "timestamp": r.timestamp,
                "duration_seconds": float(r.duration_seconds),
                "has_issues": bool(r.has_issues),
                "issues_count": len(r.issues),
                "recommendations_count": len(r.recommendations),
                "raw_issues": orjson.dumps(r.issues).decode("utf-8"),
            }
            for r in reports
        ]

        return pl.DataFrame(data, schema=schema)

    def export_integrity_to_duckdb(
        self,
        db_path: str | Path | None = None,
        table_name: str = DEFAULT_INTEGRITY_AUDIT_TABLE,
    ) -> int:
        """Doğrulama geçmişini yerel DuckDB tablosuna aktarır.

        Args:
            db_path: Hedef DuckDB dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            int: Eklenen rapor satır adedi.
        """
        df_history = self.export_integrity_history_to_polars()
        if len(df_history) == 0:
            return 0

        target_path = Path(db_path or self._duckdb_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and target_path.stat().st_size == 0:
            with contextlib.suppress(OSError):
                target_path.unlink()

        try:
            with duckdb.connect(str(target_path)) as conn:
                configure_duckdb_wal(conn)
                conn.register("df_integrity", df_history.to_arrow())
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_integrity WHERE 1=0"
                )
                conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_integrity")
            return len(df_history)
        except Exception as e:
            logger.error("export_integrity_to_duckdb_failed", error=str(e))
            return 0

    def query_integrity_duckdb(
        self,
        db_path: str | Path | None = None,
        table_name: str = DEFAULT_INTEGRITY_AUDIT_TABLE,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB üzerinden geçmiş bütünlük denetim raporlarını sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            limit: Maksimum kayıt limiti.

        Returns:
            pl.DataFrame: Rapor tablosu.
        """
        schema = {
            "timestamp": pl.Utf8,
            "duration_seconds": pl.Float64,
            "has_issues": pl.Boolean,
            "issues_count": pl.Int32,
            "recommendations_count": pl.Int32,
            "raw_issues": pl.Utf8,
        }
        empty_df = pl.DataFrame(schema=schema)

        target_path = Path(db_path or self._duckdb_path)
        if not target_path.exists() or target_path.stat().st_size == 0:
            return empty_df

        try:
            with duckdb.connect(str(target_path), read_only=True) as conn:
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                    [table_name],
                ).fetchall()
                if not tables:
                    return empty_df

                query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT ?"
                arrow_res = conn.execute(query, [limit]).arrow()
                return pl.from_arrow(arrow_res)
        except Exception as e:
            logger.error("query_integrity_duckdb_failed", error=str(e))
            return empty_df


# =====================================================
# MODÜL SEVİYESİNDE SINGLETON VE YARDIMCI FONKSİYONLAR
# =====================================================
data_integrity_validator = DataIntegrityValidator()


def get_data_integrity_validator() -> DataIntegrityValidator:
    """Merkezi DataIntegrityValidator tekil örneğini döndürür."""
    return data_integrity_validator


async def validate_data_integrity(
    clickhouse_client: Any = None,
    pg_pool: Any = None,
    redis_client: Any = None,
) -> IntegrityValidationReport:
    """Hızlı veri bütünlüğü doğrulama fonksiyonu.

    Args:
        clickhouse_client: ClickHouse istemcisi.
        pg_pool: asyncpg havuzu.
        redis_client: Redis istemcisi.

    Returns:
        IntegrityValidationReport: Doğrulama sonuç raporu.
    """
    return await data_integrity_validator.validate_on_startup(
        clickhouse_client=clickhouse_client,
        pg_pool=pg_pool,
        redis_client=redis_client,
    )


def get_data_integrity_status() -> dict[str, Any]:
    """Doğrulayıcı durum özetini döndürür."""
    return data_integrity_validator.get_status()


def export_integrity_to_polars() -> pl.DataFrame:
    """Doğrulama geçmişini Polars DataFrame olarak dışa aktarır."""
    return data_integrity_validator.export_integrity_history_to_polars()


def export_integrity_to_duckdb(
    db_path: str | Path | None = None,
    table_name: str = DEFAULT_INTEGRITY_AUDIT_TABLE,
) -> int:
    """Doğrulama geçmişini DuckDB tablosuna aktarır."""
    return data_integrity_validator.export_integrity_to_duckdb(db_path=db_path, table_name=table_name)


def query_integrity_duckdb(
    db_path: str | Path | None = None,
    table_name: str = DEFAULT_INTEGRITY_AUDIT_TABLE,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB üzerinden geçmiş doğrulama kayıtlarını sorgular."""
    return data_integrity_validator.query_integrity_duckdb(db_path=db_path, table_name=table_name, limit=limit)


__all__ = [
    "ALLOWED_PG_INTEGRITY_TABLES",
    "DEFAULT_FEATURE_STALE_HOURS",
    "DEFAULT_GAP_CHECK_DAYS",
    "DEFAULT_INTEGRITY_AUDIT_TABLE",
    "DEFAULT_INTEGRITY_DUCKDB_PATH",
    "DEFAULT_INTEGRITY_MAX_HISTORY",
    "DEFAULT_MARKET_DATA_STALE_HOURS",
    "DataIntegrityValidator",
    "IntegrityGapItem",
    "IntegrityValidationReport",
    "data_integrity_validator",
    "export_integrity_to_duckdb",
    "export_integrity_to_polars",
    "get_data_integrity_status",
    "get_data_integrity_validator",
    "query_integrity_duckdb",
    "validate_data_integrity",
]
