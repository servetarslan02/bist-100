"""ALPHA BIST — Tarihsel Veri Adaptörü ve Öznitelik Köprüsü (Historical Data Adapter).

Bu modül, Point-In-Time (PIT) uyumlu tarihsel veri deposu (HistoricalDataRepository) ile
kanonik skorlama boru hattı (canonical scoring pipeline) arasındaki öznitelik köprüsünü oluşturur.

Temel Yetenekler:
1. Temel Analiz Snapshot Uyarlaması: Bilanço kalitesi, değer skoru, serbest nakit akışı verimi vb.
2. KAP ve Haber Olayları Uyarlaması: Duygu (sentiment) ağırlıklandırması ve tekilleştirme (deduplication).
3. Katalist Olayları Uyarlaması: Zaman aşımı (time-decay) ağırlıklı katalist etki skoru.
4. Sıfır Veri Sızıntısı (Zero Data Leakage): Yalnızca `current_date` öncesinde bilinen veriler kullanılır.
5. DuckDB WAL ve Checkpoint optimizasyonları ile entegre denetim izi.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from services.data.historical_contracts import HistoricalDataRepository

logger = structlog.get_logger(__name__)

# ==============================================================================
# Yapılandırma ve WAL Sabitleri
# ==============================================================================

DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"
DEFAULT_HISTORICAL_AUDIT_DB_PATH: Final[str] = "data/historical_audit.duckdb"
DEFAULT_HALF_LIFE_DAYS: Final[float] = 30.0


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
# Adaptör Sınıfı
# ==============================================================================


class HistoricalDataAdapter:
    """Tarihsel veri deposu ile model skorlama motorları arasındaki uyarlayıcı sınıf."""

    def __init__(self, repository: HistoricalDataRepository | None = None) -> None:
        """HistoricalDataAdapter başlatıcı.

        Args:
            repository: Veri deposu deposu (None ise varsayılan PersistentHistoricalRepository başlatılır).
        """
        self._lock = threading.RLock()
        if repository is None:
            from services.data.persistent_repository import PersistentHistoricalRepository

            self._repo: HistoricalDataRepository = PersistentHistoricalRepository()
        else:
            self._repo = repository

        logger.info("tarihsel_veri_adaptoru_baslatildi", repo=type(self._repo).__name__)

    def __repr__(self) -> str:
        """Okunabilir nesne temsili."""
        with self._lock:
            return f"HistoricalDataAdapter(repo='{type(self._repo).__name__}')"

    def to_dict(self) -> dict[str, Any]:
        """Adaptör yapılandırmasını sözlük formatında döner."""
        with self._lock:
            return {
                "repository": type(self._repo).__name__,
            }

    def to_orjson_bytes(self) -> bytes:
        """Adaptör yapılandırmasını ikili orjson baytlarına dönüştürür."""
        return to_orjson_bytes(self.to_dict())

    def get_fundamental_features(
        self,
        ticker: str,
        current_date: str,
    ) -> dict[str, Any]:
        """Tarihsel temel analiz snapshot'larından kanonik öznitelik sözlüğü üretir.

        Point-In-Time Kuralı: available_at <= current_date

        Args:
            ticker: Hisse senedi sembolü.
            current_date: Simülasyon anındaki geçerli tarih (YYYY-MM-DD).

        Returns:
            dict[str, Any]: Model öznitelikleri ve ham değerler.
        """
        with self._lock:
            snapshots = self._repo.get_fundamental_snapshots(ticker, current_date)
            if not snapshots:
                return {}

            latest = snapshots[0]
            v = latest.values
            features: dict[str, Any] = {}

            # Ham değerler
            for key, val in v.items():
                if val is not None:
                    try:
                        float_val = float(val)
                        features[key] = float_val
                        features[f"raw_{key}"] = float_val
                    except (TypeError, ValueError):
                        logger.debug("temel_analiz_deger_donusturme_atladi", anahtar=key, deger=val)

            # 1. Serbest Nakit Akışı Verimi (FCF Yield)
            fcf = float(v.get("free_cash_flow", 0.0) or 0.0)
            market_cap = float(v.get("market_cap", 0.0) or 0.0)
            if fcf and market_cap and market_cap > 0:
                features["fcf_yield_pct"] = round(float(fcf / market_cap * 100.0), 4)

            # 2. Bilanço Kalite Skoru (Balance Sheet Quality)
            quality_score = 50.0
            debt_eq = float(v.get("debt_to_equity", 0.0) or 0.0)
            current_ratio = float(v.get("current_ratio", 0.0) or 0.0)
            if debt_eq:
                if debt_eq < 0.3:
                    quality_score += 25.0
                elif debt_eq < 0.5:
                    quality_score += 15.0
                elif debt_eq > 2.0:
                    quality_score -= 25.0
                elif debt_eq > 1.0:
                    quality_score -= 10.0
            if current_ratio:
                if current_ratio > 2.0:
                    quality_score += 15.0
                elif current_ratio > 1.5:
                    quality_score += 10.0
                elif current_ratio < 1.0:
                    quality_score -= 15.0
            features["balance_sheet_quality"] = round(float(min(100.0, max(0.0, quality_score))), 0)

            # 3. Değerleme Skoru (Value Score - Sektör Medyanı Ayarlı)
            pe = float(v.get("pe_ratio", 0.0) or 0.0)
            pb = float(v.get("pb_ratio", 0.0) or 0.0)
            fcf_yield = float(v.get("fcf_yield", 0.0) or 0.0)
            sector_pe_median = float(v.get("sector_pe_median", 0.0) or 0.0)
            value_score = 0.0

            pe_threshold_low = 15.0
            pe_threshold_high = 25.0
            if sector_pe_median and sector_pe_median > 0:
                pe_threshold_low = sector_pe_median * 0.7
                pe_threshold_high = sector_pe_median * 1.1

            if pe and 0 < pe < pe_threshold_low:
                value_score += 30.0
            elif pe and pe < pe_threshold_high:
                value_score += 15.0

            if pb and 0 < pb < 1.5:
                value_score += 30.0
            elif pb and pb < 3.0:
                value_score += 15.0

            if fcf_yield and fcf_yield > 0.05:
                value_score += 40.0
            elif fcf_yield and fcf_yield > 0.02:
                value_score += 20.0
            features["value_score"] = round(float(min(100.0, value_score)), 0)

            # 4. Genel Şirket Kalite Skoru (Overall Quality Score)
            roe = float(v.get("roe", 0.0) or 0.0)
            profit_margin = float(v.get("profit_margin", 0.0) or 0.0)
            q_score = 0.0
            if roe and roe > 0.15:
                q_score += 40.0
            elif roe and roe > 0.10:
                q_score += 20.0
            if profit_margin and profit_margin > 0.20:
                q_score += 30.0
            elif profit_margin and profit_margin > 0.10:
                q_score += 15.0

            q_score += features.get("balance_sheet_quality", 50.0) * 0.3
            features["quality_score"] = round(float(min(100.0, q_score)), 0)

            return features

    def get_kap_events(
        self,
        ticker: str,
        current_date: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Tarihsel KAP duyuru olaylarından tekilleştirilmiş liste üretir."""
        with self._lock:
            events = self._repo.get_event_snapshots(ticker, current_date, event_types=None)
            seen_ids: set[str] = set()
            result: list[dict[str, Any]] = []

            for event in events:
                if event.event_id in seen_ids:
                    continue
                seen_ids.add(event.event_id)
                result.append(
                    {
                        "id": event.event_id,
                        "ticker": event.ticker,
                        "title": event.title,
                        "category": event.event_type,
                        "publish_date": event.published_at[:10],
                        "sentiment": event.sentiment,
                        "importance": event.importance,
                        "source": event.source,
                    }
                )
                if len(result) >= limit:
                    break

            return result

    def get_news_events(
        self,
        ticker: str,
        current_date: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Tarihsel haber olaylarından tekilleştirilmiş haber listesi üretir."""
        with self._lock:
            events = self._repo.get_event_snapshots(ticker, current_date, event_types=None)
            news_events = [e for e in events if e.source in ("news", "rss")]
            seen_ids: set[str] = set()
            result: list[dict[str, Any]] = []

            for event in news_events:
                if event.event_id in seen_ids:
                    continue
                seen_ids.add(event.event_id)
                result.append(
                    {
                        "title": event.title,
                        "published": event.published_at[:10],
                        "date": event.published_at[:10],
                        "sentiment": event.sentiment,
                        "importance": event.importance,
                        "source": event.source,
                        "ticker": event.ticker,
                    }
                )
                if len(result) >= limit:
                    break

            return result

    def get_catalyst_events(
        self,
        ticker: str,
        current_date: str,
    ) -> list[dict[str, Any]]:
        """Tarihsel şirket katalist olaylarını güncel tarihe göre gün farkıyla hesaplar."""
        with self._lock:
            catalysts = self._repo.get_catalyst_snapshots(ticker, current_date)
            result: list[dict[str, Any]] = []

            for cat in catalysts:
                try:
                    d_event = datetime.strptime(cat.event_date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
                    d_current = datetime.strptime(current_date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
                    days_until = max(0, (d_event - d_current).days)
                except ValueError:
                    days_until = 0

                result.append(
                    {
                        "type": cat.catalyst_type,
                        "importance": cat.importance,
                        "days_until": days_until,
                        "source": cat.source,
                        "announcement_date": cat.announcement_date,
                        "event_date": cat.event_date,
                    }
                )

            return result

    def compute_sentiment(
        self,
        kap_events: list[dict[str, Any]],
        news_events: list[dict[str, Any]],
    ) -> dict[str, float]:
        """KAP ve haber olaylarından duygu (sentiment) özniteliklerini türetir."""
        features: dict[str, float] = {}

        # KAP duygu analizi
        if kap_events:
            sentiments = [float(e.get("sentiment", 0.0)) for e in kap_events]
            importances = [float(e.get("importance", 0.5)) for e in kap_events]
            total_imp = sum(importances)

            if total_imp > 0:
                weighted = sum(s * i for s, i in zip(sentiments, importances, strict=False)) / total_imp
            else:
                weighted = float(np.mean(sentiments)) if sentiments else 0.0

            features["kap_sentiment_avg"] = round(float(np.mean(sentiments)), 4)
            features["kap_sentiment_weighted"] = round(float(weighted), 4)
            features["kap_sentiment_latest"] = round(float(sentiments[0]), 4) if sentiments else 0.0
            features["kap_avg_importance"] = round(float(np.mean(importances)), 4)

        # Haber duygu analizi
        if news_events:
            sentiments = [float(e.get("sentiment", 0.0)) for e in news_events]
            importances = [float(e.get("importance", 0.5)) for e in news_events]
            total_imp = sum(importances)

            if total_imp > 0:
                weighted = sum(s * i for s, i in zip(sentiments, importances, strict=False)) / total_imp
            else:
                weighted = float(np.mean(sentiments)) if sentiments else 0.0

            features["news_sentiment_weighted"] = round(float(weighted), 4)

        # Birleşik duygu skoru (%60 KAP, %40 Haber)
        kap_sent = features.get("kap_sentiment_weighted", 0.0)
        news_sent = features.get("news_sentiment_weighted", 0.0)
        if kap_sent != 0.0 or news_sent != 0.0:
            features["combined_sentiment"] = round(0.6 * kap_sent + 0.4 * news_sent, 4)

        return features

    def compute_catalyst_features(
        self,
        catalyst_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Katalist olaylarından zaman aşımı ağırlıklı öznitelikler üretir."""
        features: dict[str, Any] = {}

        if not catalyst_events:
            features["catalyst_count"] = 0
            features["catalyst_importance"] = 0.0
            features["catalyst_days_nearest"] = 999
            features["catalyst_time_decay_score"] = 0.0
            return features

        features["catalyst_count"] = len(catalyst_events)
        importances = [float(e.get("importance", 0.5)) for e in catalyst_events]
        days_list = [int(e.get("days_until", 999)) for e in catalyst_events]

        features["catalyst_importance"] = round(float(max(importances)), 4)
        features["catalyst_avg_importance"] = round(float(np.mean(importances)), 4)
        features["catalyst_days_nearest"] = min(days_list) if days_list else 999

        # Yarılanma ömrü modeli (30 gün)
        time_decay_scores: list[float] = []
        for event in catalyst_events:
            imp = float(event.get("importance", 0.5))
            days = float(event.get("days_until", 999))
            time_weight = float(np.exp(-days / DEFAULT_HALF_LIFE_DAYS))
            time_decay_scores.append(imp * time_weight)

        features["catalyst_time_decay_score"] = round(float(sum(time_decay_scores)), 4)
        return features


# Geriye dönük uyumluluk takma adı
HistoricalAdapter = HistoricalDataAdapter

# Global Singleton Örneği
historical_adapter: HistoricalDataAdapter = HistoricalDataAdapter()


# ==============================================================================
# DuckDB ve Polars Yardımcı Fonksiyonları
# ==============================================================================


def export_features_to_polars(features: dict[str, Any]) -> pl.DataFrame:
    """Üretilen öznitelik sözlüğünü Polars DataFrame formatına dönüştürür."""
    if not features:
        return pl.DataFrame()
    return pl.DataFrame({k: [v] for k, v in features.items()})


def export_features_to_duckdb(
    ticker: str,
    current_date: str,
    features: dict[str, Any],
    db_path: str = DEFAULT_HISTORICAL_AUDIT_DB_PATH,
) -> int:
    """Hesaplanan öznitelikleri DuckDB denetim tablosuna kaydeder.

    Args:
        ticker: Hisse senedi kodu.
        current_date: Geçerli tarih.
        features: Kaydedilecek öznitelik sözlüğü.
        db_path: DuckDB veritabanı dosya yolu.

    Returns:
        int: Eklenen kayıt sayısı (1).
    """
    target_file = Path(db_path)
    target_file.parent.mkdir(parents=True, exist_ok=True)

    row_id = uuid.uuid4().hex
    row = (
        row_id,
        datetime.now(UTC),
        ticker,
        current_date,
        orjson.dumps(features, default=str).decode("utf-8"),
    )

    try:
        with duckdb.connect(str(target_file)) as conn:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_feature_audit (
                    id VARCHAR PRIMARY KEY,
                    created_at TIMESTAMP,
                    ticker VARCHAR,
                    current_date VARCHAR,
                    features_json VARCHAR
                )
                """
            )
            conn.execute(
                """
                INSERT INTO historical_feature_audit (
                    id, created_at, ticker, current_date, features_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                row,
            )
        logger.info("tarihsel_oznitelik_duckdb_kaydedildi", id=row_id, hisse=ticker)
        return 1
    except Exception as exc:
        logger.error("tarihsel_oznitelik_kayit_hatasi", hisse=ticker, hata=str(exc))
        return 0


def read_historical_audit_from_duckdb(
    db_path: str = DEFAULT_HISTORICAL_AUDIT_DB_PATH,
    limit: int = 100,
) -> pl.DataFrame:
    """DuckDB denetim tablosunu doğrudan Polars DataFrame olarak sorgular.

    Args:
        db_path: DuckDB dosya yolu.
        limit: Maksimum kayıt sayısı.

    Returns:
        pl.DataFrame: Tarihsel öznitelik denetim geçmişi.
    """
    path_obj = Path(db_path)
    schema: dict[str, pl.DataType] = {
        "id": pl.Utf8,
        "created_at": pl.Datetime,
        "ticker": pl.Utf8,
        "current_date": pl.Utf8,
        "features_json": pl.Utf8,
    }
    if not path_obj.exists():
        return pl.DataFrame(schema=schema)

    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            tbl_check = conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'historical_feature_audit'"
            ).fetchone()
            if not tbl_check or tbl_check[0] == 0:
                return pl.DataFrame(schema=schema)

            query = (
                "SELECT id, created_at, ticker, current_date, features_json "
                "FROM historical_feature_audit ORDER BY created_at DESC LIMIT ?"
            )
            return conn.execute(query, [max(1, int(limit))]).pl()
    except Exception as exc:
        logger.warning("duckdb_historical_audit_okuma_hatasi", db_path=db_path, hata=str(exc))
        return pl.DataFrame(schema=schema)


def clear_historical_audit_duckdb(db_path: str = DEFAULT_HISTORICAL_AUDIT_DB_PATH) -> None:
    """DuckDB denetim tablosunu temizler.

    Args:
        db_path: DuckDB dosya yolu.
    """
    path_obj = Path(db_path)
    if not path_obj.exists():
        return
    try:
        with duckdb.connect(str(path_obj)) as conn:
            configure_duckdb_wal(conn)
            conn.execute("DROP TABLE IF EXISTS historical_feature_audit;")
    except Exception as exc:
        logger.error("duckdb_historical_audit_temizleme_hatasi", db_path=db_path, hata=str(exc))


__all__: Final[list[str]] = [
    # Sabitler
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_HALF_LIFE_DAYS",
    "DEFAULT_HISTORICAL_AUDIT_DB_PATH",
    "DEFAULT_WAL_SIZE",
    # Adaptör ve Singleton
    "HistoricalAdapter",
    "HistoricalDataAdapter",
    "historical_adapter",
    # Yardımcı Fonksiyonlar
    "clear_historical_audit_duckdb",
    "configure_duckdb_wal",
    "export_features_to_duckdb",
    "export_features_to_polars",
    "read_historical_audit_from_duckdb",
    "to_orjson_bytes",
]
