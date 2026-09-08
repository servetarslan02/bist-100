"""ALPHA BIST — Tarihsel Veri Alım Hattı (Historical Data Ingestion Pipeline).

Bu modül; finansal tablolar (KAP/yfinance), şirket bildirimleri (KAP) ve finansal haberler (RSS/News)
için artımlı (incremental), Point-In-Time (PIT) uyumlu ve tekrarsız (deterministic deduplication)
veri aktarım akışlarını yönetir.

Özellikler:
- Son başarılı alım (ingestion) zaman damgasını yönetir.
- Yalnızca yeni veya güncellenmiş verileri aktarır.
- Sağlayıcı hatalarında mevcut veri setini korur (fail-safe).
- Olaylardan (events) türetilmiş katalist (catalysts) veri modelleri oluşturur.
- DuckDB üzerinde alım denetim izini (ingestion audit log) tutar.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import duckdb
import orjson
import polars as pl
import structlog

from services.data.historical_contracts import (
    CatalystSnapshot,
    EventSnapshot,
    HistoricalDataRepository,
)
from services.data.historical_fundamental_provider import (
    HistoricalFundamentalProvider,
    historical_fundamental_provider,
)

logger = structlog.get_logger(__name__)

# Harici sağlayıcıların güvenli içe aktarımı
try:
    from services.ingestion.providers.kap_provider import KAPProvider
except ImportError:
    KAPProvider = None  # type: ignore[assignment, misc]

try:
    from services.ingestion.providers.news_provider import NewsProvider
except ImportError:
    NewsProvider = None  # type: ignore[assignment, misc]


# ==============================================================================
# Yapılandırma ve WAL Sabitleri
# ==============================================================================

DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"
DEFAULT_INGESTION_AUDIT_DB_PATH: Final[str] = "data/ingestion_audit.duckdb"
DEFAULT_MAX_PERIODS: Final[int] = 8
DEFAULT_DAYS_BACK: Final[int] = 365
DEFAULT_MIN_HOURS_INTERVAL: Final[float] = 1.0


# ==============================================================================
# DuckDB WAL ve orjson Yardımcıları
# ==============================================================================


def configure_duckdb_wal(conn: duckdb.DuckDBPyConnection) -> None:
    """DuckDB bağlantısı için WAL ve checkpoint parametrelerini optimize eder.

    Args:
        conn: Yapılandırılacak DuckDB bağlantısı.
    """
    try:
        conn.execute(f"PRAGMA checkpoint_threshold = '{DEFAULT_CHECKPOINT_SIZE}';")
        conn.execute(f"PRAGMA wal_autocheckpoint = '{DEFAULT_WAL_SIZE}';")
    except Exception as exc:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(exc))


def to_orjson_bytes(val: Any) -> bytes:
    """Herhangi bir nesneyi orjson ile ikili bayt dizisine dönüştürür.

    Args:
        val: Serileştirilecek veri veya nesne.

    Returns:
        bytes: orjson kodlanmış baytlar.
    """
    if hasattr(val, "to_dict"):
        val = val.to_dict()
    return orjson.dumps(val, default=str)


# ==============================================================================
# DuckDB Denetim ve Polars Yardımcı Fonksiyonları
# ==============================================================================


def export_ingestion_run_to_duckdb(
    stage: str,
    tickers: list[str],
    results: dict[str, Any],
    db_path: str = DEFAULT_INGESTION_AUDIT_DB_PATH,
) -> int:
    """Veri alım sürecinin sonucunu DuckDB denetim tablosuna kaydeder.

    Args:
        stage: Alım aşaması ('fundamental', 'kap', 'news', 'catalysts').
        tickers: İşlenen hisse kodları listesi.
        results: İşlem sonucu ve hisse bazlı kayıt sayıları.
        db_path: DuckDB dosya yolu.

    Returns:
        int: Başarıyla kaydedilen kayıt sayısı (1 veya 0).
    """
    path_obj = Path(db_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    now_dt = datetime.now(UTC)

    success_count = sum(1 for v in results.values() if isinstance(v, int) and v > 0)
    failed_count = sum(1 for v in results.values() if isinstance(v, str))

    row = (
        run_id,
        now_dt,
        stage,
        len(tickers),
        success_count,
        failed_count,
        orjson.dumps(results, default=str).decode("utf-8"),
    )

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_run_audit (
                    run_id VARCHAR PRIMARY KEY,
                    created_at TIMESTAMP WITH TIME ZONE,
                    stage VARCHAR,
                    total_tickers INTEGER,
                    success_count INTEGER,
                    failed_count INTEGER,
                    results_json VARCHAR
                )
                """
            )
            conn.execute(
                """
                INSERT INTO ingestion_run_audit (
                    run_id, created_at, stage, total_tickers,
                    success_count, failed_count, results_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        logger.info("alim_denetim_kaydi_olusturuldu", run_id=run_id, stage=stage)
        return 1
    except Exception as exc:
        logger.error("alim_denetim_kaydi_hatasi", stage=stage, hata=str(exc))
        return 0


def read_ingestion_audit_from_duckdb(
    db_path: str = DEFAULT_INGESTION_AUDIT_DB_PATH,
    stage: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosundan alım geçmişini Polars DataFrame olarak okur.

    Args:
        db_path: DuckDB dosya yolu.
        stage: İsteğe bağlı aşama filtresi.
        limit: Maksimum kayıt sayısı.

    Returns:
        pl.DataFrame: Alım denetim tablosu.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "run_id": pl.Utf8,
        "created_at": pl.Datetime,
        "stage": pl.Utf8,
        "total_tickers": pl.Int64,
        "success_count": pl.Int64,
        "failed_count": pl.Int64,
        "results_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'ingestion_run_audit'"
            ).fetchone()
            if not tbl or tbl[0] == 0:
                return pl.DataFrame(schema=schema)

            query = "SELECT run_id, created_at, stage, total_tickers, success_count, failed_count, results_json FROM ingestion_run_audit WHERE 1=1"
            params: list[Any] = []
            if stage:
                query += " AND stage = ?"
                params.append(stage.lower().strip())

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(max(1, int(limit)))

            return conn.execute(query, params).pl()
    except Exception as exc:
        logger.warning("duckdb_ingestion_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_ingestion_audit_duckdb(db_path: str = DEFAULT_INGESTION_AUDIT_DB_PATH) -> None:
    """DuckDB alım denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS ingestion_run_audit;")
            logger.info("ingestion_audit_tablosu_temizlendi", db_path=db_path)
    except Exception as exc:
        logger.error("ingestion_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


def export_ingestion_summary_to_polars(results: dict[str, Any], stage: str) -> pl.DataFrame:
    """Alım sonuç sözlüğünü Polars DataFrame formatına dönüştürür.

    Args:
        results: Hisse bazlı sonuç sözlüğü.
        stage: Alım aşaması.

    Returns:
        pl.DataFrame: Özet Polars tablosu.
    """
    if not results:
        return pl.DataFrame(schema={"ticker": pl.Utf8, "stage": pl.Utf8, "status": pl.Utf8, "count": pl.Int64})

    rows: list[dict[str, Any]] = []
    for ticker, res in results.items():
        if isinstance(res, int):
            rows.append({"ticker": ticker, "stage": stage, "status": "SUCCESS", "count": res})
        else:
            rows.append({"ticker": ticker, "stage": stage, "status": str(res), "count": 0})

    return pl.DataFrame(rows)


# ==============================================================================
# Alım Hattı Sınıfı (Ingestion Pipeline)
# ==============================================================================


class HistoricalIngestionPipeline:
    """Çok kaynaklı tarihsel veri alımını koordine eden ana hat (pipeline)."""

    def __init__(
        self,
        repository: HistoricalDataRepository,
        fundamental_provider: HistoricalFundamentalProvider | None = None,
    ) -> None:
        """HistoricalIngestionPipeline başlatıcı.

        Args:
            repository: Verilerin aktarılacağı tarihsel veri deposu.
            fundamental_provider: Temel analiz veri sağlayıcısı (opsiyonel).
        """
        self._lock = threading.RLock()
        self._repo = repository
        self._fund_provider = fundamental_provider or historical_fundamental_provider
        logger.info(
            "historical_ingestion_pipeline_baslatildi",
            repo=self._repo.__class__.__name__,
            fund_provider=self._fund_provider.__class__.__name__,
        )

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return (
                f"HistoricalIngestionPipeline(repo={self._repo.__class__.__name__}, "
                f"fund_provider={self._fund_provider.__class__.__name__})"
            )

    def to_dict(self) -> dict[str, Any]:
        """Bileşen durumunu sözlük formatında döner."""
        with self._lock:
            return {
                "repository": self._repo.__class__.__name__,
                "fundamental_provider": self._fund_provider.__class__.__name__,
                "kap_available": KAPProvider is not None,
                "news_available": NewsProvider is not None,
            }

    def to_orjson_bytes(self) -> bytes:
        """Bileşen durumunu ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def ingest_fundamentals(
        self,
        tickers: list[str],
        force: bool = False,
    ) -> dict[str, Any]:
        """Hisseler için tarihsel çeyreklik bilanço ve rasyoları çeker ve depoya kaydeder.

        Args:
            tickers: Hisse kodları listesi.
            force: True ise zaman damgası kontrolünü atlar ve tekrar çeker.

        Returns:
            dict[str, Any]: Hisse bazlı kaydedilen snapshot adedi veya hata mesajı.
        """
        with self._lock:
            results: dict[str, Any] = {}
            last_ingestion = getattr(self._repo, "get_last_ingestion_time", lambda _s: None)("fundamental")

            if not force and last_ingestion:
                try:
                    last_dt = datetime.fromisoformat(last_ingestion)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=UTC)
                    hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600.0
                    if hours_since < DEFAULT_MIN_HOURS_INTERVAL:
                        logger.info("temel_alim_atlandi_zaman_yakin", gecen_saat=round(hours_since, 2))
                        return {"status": "skipped", "reason": "too_recent"}
                except ValueError as exc:
                    logger.warning("temel_zaman_damgasi_ayristirma_uyarisi", hata=str(exc))

            success_count = 0
            for ticker in tickers:
                try:
                    snapshots = self._fund_provider.fetch_historical_fundamentals(
                        ticker, max_periods=DEFAULT_MAX_PERIODS
                    )

                    if not snapshots:
                        results[ticker] = "no_data"
                        continue

                    saved = 0
                    for snapshot in snapshots:
                        if not snapshot.available_at:
                            snapshot.status = "UNKNOWN"

                        add_fn = getattr(self._repo, "add_fundamental_snapshot", None)
                        if add_fn:
                            res = add_fn(snapshot)
                            if res is not False:
                                saved += 1

                    results[ticker] = saved
                    success_count += 1
                except Exception as exc:
                    logger.error("temel_veri_alimi_hatasi", hisse=ticker, hata=str(exc))
                    results[ticker] = str(exc)

            if success_count > 0:
                set_fn = getattr(self._repo, "set_last_ingestion_time", None)
                if set_fn:
                    set_fn("fundamental", datetime.now(UTC).isoformat())

            logger.info("temel_veri_alimi_tamamlandi", hisse_adedi=len(tickers), basarili=success_count)
            export_ingestion_run_to_duckdb(stage="fundamental", tickers=tickers, results=results)
            return results

    def ingest_kap_events(
        self,
        tickers: list[str],
        days_back: int = DEFAULT_DAYS_BACK,
        force: bool = False,
    ) -> dict[str, Any]:
        """Hisseler için KAP bildirimlerini çeker ve depoya kaydeder.

        Args:
            tickers: Hisse kodları listesi.
            days_back: Kaç gün geriye gidileceği.
            force: True ise zaman kontrolünü atlar.

        Returns:
            dict[str, Any]: Hisse bazlı sonuç sözlüğü.
        """
        with self._lock:
            results: dict[str, Any] = {}
            last_ingestion = getattr(self._repo, "get_last_ingestion_time", lambda _s: None)("kap")

            if not force and last_ingestion:
                try:
                    last_dt = datetime.fromisoformat(last_ingestion)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=UTC)
                    hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600.0
                    if hours_since < DEFAULT_MIN_HOURS_INTERVAL:
                        logger.info("kap_alimi_atlandi_zaman_yakin", gecen_saat=round(hours_since, 2))
                        return {"status": "skipped", "reason": "too_recent"}
                except ValueError as exc:
                    logger.warning("kap_zaman_damgasi_ayristirma_uyarisi", hata=str(exc))

            if KAPProvider is None:
                logger.error("kap_saglayicisi_mevcut_degil")
                return {"status": "error", "reason": "provider_unavailable"}

            try:
                kap = KAPProvider()
            except Exception as exc:
                logger.error("kap_saglayici_baslatma_hatasi", hata=str(exc))
                return {"status": "error", "reason": str(exc)}

            from_date = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
            to_date = datetime.now(UTC).strftime("%Y-%m-%d")

            success_count = 0
            for ticker in tickers:
                try:
                    events = asyncio.run(
                        kap.fetch_disclosures(
                            from_date=from_date,
                            to_date=to_date,
                            ticker=ticker,
                            limit=100,
                        )
                    )

                    if not events:
                        results[ticker] = 0
                        continue

                    saved = 0
                    for event in events:
                        event_id = event.get("id", "")
                        if not event_id:
                            continue

                        snapshot = EventSnapshot(
                            event_id=event_id,
                            ticker=ticker,
                            published_at=event.get("publish_date", ""),
                            event_type=event.get("category", "OTHER"),
                            title=event.get("title", ""),
                            sentiment=event.get("sentiment", 0.0),
                            importance=event.get("importance", 0.5),
                            source="kap",
                            content=event.get("summary", ""),
                        )

                        add_fn = getattr(self._repo, "add_event_snapshot", None)
                        if add_fn:
                            res = add_fn(snapshot)
                            if res is not False:
                                saved += 1

                    results[ticker] = saved
                    success_count += 1
                except Exception as exc:
                    logger.error("kap_bildirim_alimi_hatasi", hisse=ticker, hata=str(exc))
                    results[ticker] = str(exc)

            if success_count > 0:
                set_fn = getattr(self._repo, "set_last_ingestion_time", None)
                if set_fn:
                    set_fn("kap", datetime.now(UTC).isoformat())

            logger.info("kap_alimi_tamamlandi", hisse_adedi=len(tickers), basarili=success_count)
            export_ingestion_run_to_duckdb(stage="kap", tickers=tickers, results=results)
            return results

    def ingest_news_events(
        self,
        tickers: list[str],
        force: bool = False,
    ) -> dict[str, Any]:
        """Haber akışlarından güncel finansal haberleri çeker ve depoya aktarır.

        Args:
            tickers: Eşleştirilecek hisse kodları listesi.
            force: True ise zaman kontrolünü atlar.

        Returns:
            dict[str, Any]: İşlem sonucu ve aktarılan haber adedi.
        """
        with self._lock:
            last_ingestion = getattr(self._repo, "get_last_ingestion_time", lambda _s: None)("news")

            if not force and last_ingestion:
                try:
                    last_dt = datetime.fromisoformat(last_ingestion)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=UTC)
                    hours_since = (datetime.now(UTC) - last_dt).total_seconds() / 3600.0
                    if hours_since < DEFAULT_MIN_HOURS_INTERVAL:
                        logger.info("haber_alimi_atlandi_zaman_yakin", gecen_saat=round(hours_since, 2))
                        return {"status": "skipped", "reason": "too_recent"}
                except ValueError as exc:
                    logger.warning("haber_zaman_damgasi_ayristirma_uyarisi", hata=str(exc))

            if NewsProvider is None:
                logger.error("haber_saglayicisi_mevcut_degil")
                return {"status": "error", "reason": "provider_unavailable"}

            try:
                news = NewsProvider()
                raw_news = asyncio.run(news.fetch_financial_news_rss())
            except Exception as exc:
                logger.error("haber_cekme_hatasi", hata=str(exc))
                return {"status": "error", "reason": str(exc)}

            if not raw_news:
                return {"status": "no_data"}

            saved_total = 0
            results: dict[str, Any] = {}
            for item in raw_news:
                title = item.get("title", "").strip()
                if not title:
                    continue

                for ticker in tickers:
                    if not news.match_news_to_ticker(item, ticker):
                        continue

                    pub_date = item.get("published", "")
                    if not pub_date:
                        continue

                    event_id = hashlib.md5(f"{pub_date}:{title}:{ticker}".encode()).hexdigest()[:16]

                    snapshot = EventSnapshot(
                        event_id=event_id,
                        ticker=ticker,
                        published_at=pub_date,
                        event_type="NEWS",
                        title=title,
                        sentiment=float(item.get("sentiment", 0.0)),
                        importance=float(item.get("importance", 0.5)),
                        source="news",
                        content=item.get("summary", ""),
                    )

                    add_fn = getattr(self._repo, "add_event_snapshot", None)
                    if add_fn:
                        res = add_fn(snapshot)
                        if res is not False:
                            saved_total += 1
                            results[ticker] = results.get(ticker, 0) + 1

            set_fn = getattr(self._repo, "set_last_ingestion_time", None)
            if set_fn:
                set_fn("news", datetime.now(UTC).isoformat())

            logger.info("haber_alimi_tamamlandi", hisse_adedi=len(tickers), aktarilan_haber=saved_total)
            export_ingestion_run_to_duckdb(stage="news", tickers=tickers, results=results)
            return {"status": "ok", "events": saved_total, "tickers": results}

    def derive_catalysts_from_events(
        self,
        tickers: list[str],
    ) -> dict[str, Any]:
        """Kayıtlı KAP bildirimlerinden geleceğe dönük katalistleri türetir.

        Args:
            tickers: İncelenecek hisse kodları listesi.

        Returns:
            dict[str, Any]: Hisse bazlı türetilen katalist sayıları.
        """
        with self._lock:
            results: dict[str, Any] = {}

            for ticker in tickers:
                saved = 0
                events: list[EventSnapshot] = []

                # Öncelik 1: Soyut repo arayüzünden EventSnapshot nesnelerini çek
                try:
                    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
                    events = self._repo.get_event_snapshots(ticker=ticker, as_of_date=today_str)
                except Exception as exc:
                    logger.debug("repo_get_event_snapshots_denendi", hisse=ticker, hata=str(exc))

                # Öncelik 2: DuckDB bağlantısı üzerinden doğrudan filtrele
                if not events and hasattr(self._repo, "_get_conn"):
                    try:
                        conn = self._repo._get_conn()
                        res = conn.execute(
                            """SELECT event_id, ticker, published_at, event_type, title,
                                      sentiment, importance, source, content
                               FROM event_snapshots
                               WHERE ticker = ? AND source = 'kap'
                               ORDER BY published_at DESC""",
                            (ticker,),
                        ).fetchall()
                        for r in res:
                            events.append(
                                EventSnapshot(
                                    event_id=r[0],
                                    ticker=r[1],
                                    published_at=r[2],
                                    event_type=r[3],
                                    title=r[4],
                                    sentiment=float(r[5] or 0.0),
                                    importance=float(r[6] or 0.5),
                                    source=r[7],
                                    content=r[8] or "",
                                )
                            )
                    except Exception as exc:
                        logger.warning("duckdb_event_snapshots_sorgu_hatasi", hisse=ticker, hata=str(exc))

                for ev in events:
                    if ev.source != "kap":
                        continue

                    catalyst_type = self._category_to_catalyst_type(ev.event_type)
                    if not catalyst_type:
                        continue

                    try:
                        pub_clean = ev.published_at.replace("Z", "+00:00")
                        pub_dt = datetime.fromisoformat(pub_clean)
                        event_dt = pub_dt + timedelta(days=30)
                        event_date = event_dt.strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        event_date = ev.published_at[:10]

                    snapshot = CatalystSnapshot(
                        event_id=f"CAT-{ev.event_id}",
                        ticker=ticker,
                        announcement_date=ev.published_at[:10],
                        event_date=event_date,
                        catalyst_type=catalyst_type,
                        importance=ev.importance,
                        source="kap",
                    )

                    add_cat_fn = getattr(self._repo, "add_catalyst_snapshot", None)
                    if add_cat_fn:
                        res = add_cat_fn(snapshot)
                        if res is not False:
                            saved += 1

                results[ticker] = saved

            logger.info("katalistler_turetildi", hisse_adedi=len(tickers), sonuclar=results)
            export_ingestion_run_to_duckdb(stage="catalysts", tickers=tickers, results=results)
            return results

    @staticmethod
    def _category_to_catalyst_type(category: str) -> str | None:
        """KAP kategorisini katalist türüne dönüştürür.

        Args:
            category: KAP kategori adı.

        Returns:
            str | None: Katalist türü veya eşleşmiyorsa None.
        """
        mapping: Final[dict[str, str]] = {
            "FINANCIAL_REPORT": "EARNINGS",
            "DIVIDEND": "DIVIDEND_DATE",
            "CAPITAL_INCREASE": "OTHER",
            "MERGER_ACQUISITION": "OTHER",
            "SHARE_BUYBACK": "OTHER",
            "CONTRACT": "CONTRACT_EXPIRY",
            "BOARD_CHANGE": "OTHER",
        }
        return mapping.get(category.upper().strip())


# Geriye dönük uyumluluk takma adı
IngestionPipeline: Final[type[HistoricalIngestionPipeline]] = HistoricalIngestionPipeline

__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_DAYS_BACK",
    "DEFAULT_INGESTION_AUDIT_DB_PATH",
    "DEFAULT_MAX_PERIODS",
    "DEFAULT_MIN_HOURS_INTERVAL",
    "DEFAULT_WAL_SIZE",
    "HistoricalIngestionPipeline",
    "IngestionPipeline",
    "clear_ingestion_audit_duckdb",
    "configure_duckdb_wal",
    "export_ingestion_run_to_duckdb",
    "export_ingestion_summary_to_polars",
    "read_ingestion_audit_from_duckdb",
    "to_orjson_bytes",
]
