"""ALPHA BIST — Çapraz Kaynak Uzlaştırma Motoru (Cross-Source Reconciliation).

Aynı veri birden fazla kaynaktan geldiğinde:
- Fiyat, hacim ve derinlik uyuşmazlığı tespiti
- Kaynak güvenilirliği ve dinamik güven puanı bazlı seçim
- İstatistiksel anomali ve sıçrama (price jump) tespiti (Z-score, volatilite bazlı)
- Otomatik aykırı değer temizleme (Self-healing Outlier Removal)
- DuckDB üzerinde uzlaştırma denetim günlüğü (Reconciliation Audit Trail)
- Polars ve orjson desteği
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Modül Sabitleri
DEFAULT_RECONCILIATION_DUCKDB_PATH: Final[str] = "data/reconciliation_audit.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL boyutunu optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(e))


@dataclass
class ReconciledData:
    """Uzlaştırılmış çapraz kaynak verisi."""

    value: float
    source: str
    confidence: float  # 0.0 - 1.0
    quality_score: float  # 0.0 - 100.0
    all_sources: dict[str, float]
    discrepancy_pct: float  # Kaynaklar arası maksimum fark %
    is_consistent: bool
    anomaly_detected: bool
    reconciled_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"ReconciledData(source='{self.source}', val={self.value:.4f}, conf={self.confidence:.2f}, "
            f"qual={self.quality_score:.1f}, disc={self.discrepancy_pct:.2f}%, "
            f"consistent={self.is_consistent}, anomaly={self.anomaly_detected})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return {
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
            "quality_score": self.quality_score,
            "all_sources": self.all_sources,
            "discrepancy_pct": self.discrepancy_pct,
            "is_consistent": self.is_consistent,
            "anomaly_detected": self.anomaly_detected,
            "reconciled_at": self.reconciled_at.isoformat(),
        }

    def to_orjson_bytes(self) -> bytes:
        """Veriyi orjson formatında bayt dizisine serileştirir."""
        return orjson.dumps(self.to_dict(), default=str)


class CrossSourceReconciliation:
    """Çapraz kaynak doğrulama ve uzlaştırma motoru.

    Thread-safe, DuckDB denetim kayıtlı ve self-healing (aykırı değer arındırma).
    """

    # Statik baz kaynak güvenilirlik katsayıları (1.0 = mutlak güven)
    BASE_SOURCE_RELIABILITY: dict[str, float] = {
        "borsaistanbul.com": 0.99,
        "kap.org.tr": 0.98,
        "bloomberg": 0.97,
        "reuters": 0.97,
        "matriks": 0.95,
        "is_yatirim": 0.95,
        "yfinance": 0.90,
        "bloomberght": 0.90,
        "dunya.com": 0.85,
        "aa": 0.85,
        "borsagundem": 0.80,
        "rss_feed": 0.75,
        "social_media": 0.40,
    }

    # Uyuşmazlık eşikleri (%)
    TOLERANCE_PCT = 0.5  # %0.5 — normal tolerans
    WARNING_PCT = 2.0  # %2.0 — uyarı eşiği
    ANOMALY_PCT = 5.0  # %5.0 — anomali eşiği

    def __init__(self, duckdb_conn: duckdb.DuckDBPyConnection | None = None) -> None:
        self._lock = threading.RLock()
        self._dynamic_reliability = dict(self.BASE_SOURCE_RELIABILITY)
        self._duckdb_conn = duckdb_conn
        if self._duckdb_conn is not None:
            self._init_duckdb_schema()

    def set_duckdb_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        """DuckDB bağlantısını ayarlar ve denetim tablosunu hazırlar."""
        with self._lock:
            self._duckdb_conn = conn
            self._init_duckdb_schema()

    def _init_duckdb_schema(self) -> None:
        """DuckDB denetim tablosunu ilklendirir."""
        if self._duckdb_conn is None:
            return
        with self._lock:
            try:
                self._duckdb_conn.execute("""
                    CREATE TABLE IF NOT EXISTS reconciliation_audit (
                        id BIGINT,
                        ticker VARCHAR,
                        field_name VARCHAR,
                        best_source VARCHAR,
                        best_value DOUBLE,
                        discrepancy_pct DOUBLE,
                        quality_score DOUBLE,
                        confidence DOUBLE,
                        is_consistent BOOLEAN,
                        anomaly_detected BOOLEAN,
                        raw_sources_json VARCHAR,
                        reconciled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE SEQUENCE IF NOT EXISTS seq_reconciliation_audit START 1;
                """)
            except Exception as exc:
                logger.error("Reconciliation DuckDB şema oluşturma hatası", hata=str(exc))

    def save_audit_to_duckdb(
        self,
        ticker: str,
        field_name: str,
        result: ReconciledData,
        db_path: str | None = None,
    ) -> None:
        """Uzlaştırma denetim kaydını dosya tabanlı DuckDB'ye kaydeder."""
        target_path = db_path or DEFAULT_RECONCILIATION_DUCKDB_PATH
        path_obj = Path(target_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(path_obj))
        try:
            configure_duckdb_wal(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_audit (
                    ticker VARCHAR,
                    field_name VARCHAR,
                    best_source VARCHAR,
                    best_value DOUBLE,
                    discrepancy_pct DOUBLE,
                    quality_score DOUBLE,
                    confidence DOUBLE,
                    is_consistent BOOLEAN,
                    anomaly_detected BOOLEAN,
                    raw_sources_json VARCHAR,
                    reconciled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            raw_json = orjson.dumps(result.all_sources, default=str).decode("utf-8")
            conn.execute(
                """
                INSERT INTO reconciliation_audit (
                    ticker, field_name, best_source, best_value,
                    discrepancy_pct, quality_score, confidence,
                    is_consistent, anomaly_detected, raw_sources_json, reconciled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ticker,
                    field_name,
                    result.source,
                    result.value,
                    result.discrepancy_pct,
                    result.quality_score,
                    result.confidence,
                    result.is_consistent,
                    result.anomaly_detected,
                    raw_json,
                    result.reconciled_at,
                ],
            )
        except Exception as exc:
            logger.error("Reconciliation DuckDB dosya kaydi hatasi", ticker=ticker, field=field_name, hata=str(exc))
        finally:
            conn.close()

    def read_audit_from_duckdb(
        self,
        db_path: str | None = None,
        ticker: str | None = None,
    ) -> pl.DataFrame:
        """DuckDB'de kayıtlı uzlaştırma denetim kayıtlarını Polars DataFrame olarak okur."""
        target_path = db_path or DEFAULT_RECONCILIATION_DUCKDB_PATH
        path_obj = Path(target_path)
        empty_schema = {
            "ticker": pl.String,
            "field_name": pl.String,
            "best_source": pl.String,
            "best_value": pl.Float64,
            "discrepancy_pct": pl.Float64,
            "quality_score": pl.Float64,
            "confidence": pl.Float64,
            "is_consistent": pl.Boolean,
            "anomaly_detected": pl.Boolean,
            "raw_sources_json": pl.String,
            "reconciled_at": pl.Datetime,
        }
        if not path_obj.exists():
            return pl.DataFrame(schema=empty_schema)

        conn = duckdb.connect(str(path_obj), read_only=True)
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "reconciliation_audit" not in tables:
                return pl.DataFrame(schema=empty_schema)

            query = (
                "SELECT ticker, field_name, best_source, best_value, discrepancy_pct, "
                "quality_score, confidence, is_consistent, anomaly_detected, raw_sources_json, reconciled_at "
                "FROM reconciliation_audit "
            )
            params: list[Any] = []
            if ticker:
                query += "WHERE ticker = ? "
                params.append(ticker.upper().strip())
            query += "ORDER BY reconciled_at DESC"

            return conn.execute(query, params).pl()
        except Exception as e:
            logger.error("reconciliation_duckdb_okuma_hatasi", hata=str(e))
            return pl.DataFrame(schema=empty_schema)
        finally:
            conn.close()

    def clear_audit_duckdb(self, db_path: str | None = None) -> bool:
        """DuckDB tablosundaki uzlaştırma denetim kayıtlarını temizler."""
        target_path = db_path or DEFAULT_RECONCILIATION_DUCKDB_PATH
        path_obj = Path(target_path)
        if not path_obj.exists():
            return True

        conn = duckdb.connect(str(path_obj))
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "reconciliation_audit" in tables:
                conn.execute("DELETE FROM reconciliation_audit")
            logger.info("reconciliation_audit_temizlendi", db_path=str(path_obj))
            return True
        except Exception as e:
            logger.error("reconciliation_audit_temizleme_hatasi", hata=str(e))
            return False
        finally:
            conn.close()

    def _record_audit(
        self,
        ticker: str,
        field_name: str,
        result: ReconciledData,
    ) -> None:
        """Uzlaştırma denetim kaydını DuckDB'ye yazar."""
        if self._duckdb_conn is not None:
            with self._lock:
                try:
                    raw_json = orjson.dumps(result.all_sources, default=str).decode("utf-8")
                    self._duckdb_conn.execute(
                        """
                        INSERT INTO reconciliation_audit (
                            id, ticker, field_name, best_source, best_value,
                            discrepancy_pct, quality_score, confidence,
                            is_consistent, anomaly_detected, raw_sources_json, reconciled_at
                        ) VALUES (
                            nextval('seq_reconciliation_audit'), ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        [
                            ticker,
                            field_name,
                            result.source,
                            result.value,
                            result.discrepancy_pct,
                            result.quality_score,
                            result.confidence,
                            result.is_consistent,
                            result.anomaly_detected,
                            raw_json,
                            result.reconciled_at,
                        ],
                    )
                except Exception as exc:
                    logger.error("Reconciliation DuckDB denetim kaydı hatası", ticker=ticker, field=field_name, hata=str(exc))
        else:
            self.save_audit_to_duckdb(ticker, field_name, result)

    @otel_trace("reconciliation.reconcile_price")
    def reconcile_price(
        self,
        sources: dict[str, float],
        ticker: str = "UNKNOWN",
        field_name: str = "price",
        timestamp: datetime | None = None,
    ) -> ReconciledData:
        """Fiyat ve sayısal metrik kaynaklarını uzlaştırır.

        Args:
            sources: {"yfinance": 305.25, "matriks": 305.30, "kap.org.tr": 305.20}
            ticker: Sembol kodu
            field_name: Uzlaştırılan alan (price, volume vb.)
            timestamp: İsteğe bağlı zaman damgası

        Returns:
            ReconciledData: Doğrulanmış ve uzlaştırılmış nihai veri.
        """
        with self._lock:
            # Geçersiz ve NaN / Inf içeren değerleri filtrele
            valid_sources = {
                k: float(v)
                for k, v in sources.items()
                if v is not None and not math.isnan(float(v)) and not math.isinf(float(v))
            }

            if not valid_sources:
                empty_res = ReconciledData(
                    value=0.0,
                    source="none",
                    confidence=0.0,
                    quality_score=0.0,
                    all_sources={},
                    discrepancy_pct=0.0,
                    is_consistent=False,
                    anomaly_detected=True,
                    reconciled_at=timestamp or datetime.now(UTC),
                )
                self._record_audit(ticker, field_name, empty_res)
                return empty_res

            values = list(valid_sources.values())

            # Temel istatistikler
            mean_val = float(np.mean(values))
            min_val = min(values)
            max_val = max(values)

            # Uyuşmazlık yüzdesi
            discrepancy_pct = ((max_val - min_val) / mean_val * 100.0) if mean_val > 0 else 0.0

            # Anomali tespiti:
            # 1. Kaynaklar arası uyuşmazlık ANOMALY_PCT (%5.0) üzerindeyse
            # 2. Küçük örneklemde Samuelson eşitsizliği nedeniyle Z-score yerine MAD (Median Absolute Deviation) kullanılır
            anomaly_detected = False
            if discrepancy_pct >= self.ANOMALY_PCT:
                anomaly_detected = True
            elif len(values) >= 3:
                median_val = float(np.median(values))
                mad = float(np.median([abs(v - median_val) for v in values]))
                if mad > 0:
                    for val in values:
                        mod_z = 0.6745 * abs(val - median_val) / mad
                        if mod_z > 3.0:
                            anomaly_detected = True
                            break

            # Tutarlılık kontrolü
            is_consistent = discrepancy_pct < self.WARNING_PCT

            # En güvenilir kaynağı seç
            best_source, best_val = self._select_best_source(valid_sources, mean_val)

            # Quality score & Confidence
            quality_score = self._compute_quality_score(discrepancy_pct, anomaly_detected, len(valid_sources))
            confidence = self._compute_confidence(discrepancy_pct, anomaly_detected, len(valid_sources))

            result = ReconciledData(
                value=round(best_val, 4),
                source=best_source,
                confidence=round(confidence, 4),
                quality_score=round(quality_score, 1),
                all_sources=valid_sources,
                discrepancy_pct=round(discrepancy_pct, 2),
                is_consistent=is_consistent,
                anomaly_detected=anomaly_detected,
                reconciled_at=timestamp or datetime.now(UTC),
            )

            self._record_audit(ticker, field_name, result)
            return result

    @otel_trace("reconciliation.heal_reconcile_with_outlier_removal")
    def heal_reconcile_with_outlier_removal(
        self,
        sources: dict[str, float],
        ticker: str = "UNKNOWN",
        field_name: str = "price",
        max_outlier_removals: int = 1,
    ) -> tuple[ReconciledData, list[str]]:
        """Aykırı değer saptandığında bozuk kaynakları otomatik eleyip yeniden hesaplar (Self-Healing).

        Returns:
            (ReconciledData, elenen_kaynak_listesi)
        """
        with self._lock:
            current_sources = dict(sources)
            removed_sources: list[str] = []

            for _ in range(max_outlier_removals):
                if len(current_sources) < 3:
                    break

                res = self.reconcile_price(current_sources, ticker=ticker, field_name=field_name)
                if not res.anomaly_detected and res.discrepancy_pct <= self.WARNING_PCT:
                    return res, removed_sources

                # Ortalamadan en çok sapan kaynağı bul ve ele
                values = list(current_sources.values())
                mean_val = float(np.mean(values))
                worst_source = max(current_sources.keys(), key=lambda k: abs(current_sources[k] - mean_val))

                logger.warn(
                    "Reconciliation anomali nedeniyle kaynak elendi (Self-Healing)",
                    ticker=ticker,
                    elenen_kaynak=worst_source,
                    deger=current_sources[worst_source],
                    ortalama=mean_val,
                )

                # Dinamik ceza puanı ver
                self.penalize_source(worst_source, penalty=0.05)

                removed_sources.append(worst_source)
                current_sources.pop(worst_source, None)

            final_res = self.reconcile_price(current_sources, ticker=ticker, field_name=field_name)
            return final_res, removed_sources

    @otel_trace("reconciliation.reconcile_multi_field")
    def reconcile_multi_field(
        self,
        ticker: str,
        data_per_source: dict[str, dict[str, float]],
    ) -> dict[str, ReconciledData]:
        """Çoklu alan uzlaştırması (price, volume, bid, ask)."""
        with self._lock:
            results: dict[str, ReconciledData] = {}

            all_fields: set[str] = set()
            for source_data in data_per_source.values():
                all_fields.update(source_data.keys())

            for f_name in all_fields:
                field_sources: dict[str, float] = {}
                for source_name, source_data in data_per_source.items():
                    val = source_data.get(f_name)
                    if val is not None:
                        field_sources[source_name] = val

                if field_sources:
                    results[f_name] = self.reconcile_price(
                        field_sources,
                        ticker=ticker,
                        field_name=f_name,
                    )

            return results

    def _select_best_source(
        self,
        sources: dict[str, float],
        mean_val: float,
    ) -> tuple[str, float]:
        """En güvenilir kaynağı seçer (Dinamik güvenilirlik skoru ve ortalamaya yakınlık ağırlıklı)."""
        best_source = ""
        best_score = -1.0
        best_val = 0.0

        for source_name, value in sources.items():
            reliability = self._dynamic_reliability.get(source_name, 0.5)

            # Ortalamaya yakınlık bonusu (0.0 - 1.0)
            closeness = 1.0 - (abs(value - mean_val) / mean_val) if mean_val > 0 else 1.0
            closeness = max(0.0, min(1.0, closeness))

            score = (reliability * 0.7) + (closeness * 0.3)

            if score > best_score:
                best_score = score
                best_source = source_name
                best_val = value

        if not best_source and sources:
            first_key = next(iter(sources))
            return first_key, sources[first_key]

        return best_source, best_val

    def _compute_quality_score(
        self,
        discrepancy_pct: float,
        anomaly_detected: bool,
        source_count: int,
    ) -> float:
        """Quality score hesapla (0-100)."""
        score = 100.0

        if discrepancy_pct > self.ANOMALY_PCT:
            score -= 40.0
        elif discrepancy_pct > self.WARNING_PCT:
            score -= 20.0
        elif discrepancy_pct > self.TOLERANCE_PCT:
            score -= 10.0

        if anomaly_detected:
            score -= 30.0

        if source_count >= 3:
            score += 5.0
        elif source_count == 1:
            score -= 15.0

        return max(0.0, min(100.0, score))

    def _compute_confidence(
        self,
        discrepancy_pct: float,
        anomaly_detected: bool,
        source_count: int,
    ) -> float:
        """Confidence hesapla (0-1)."""
        confidence = 0.85

        if discrepancy_pct > self.ANOMALY_PCT:
            confidence -= 0.4
        elif discrepancy_pct > self.WARNING_PCT:
            confidence -= 0.2
        elif discrepancy_pct > self.TOLERANCE_PCT:
            confidence -= 0.1

        if anomaly_detected:
            confidence -= 0.3

        if source_count >= 3:
            confidence += 0.1
        elif source_count == 1:
            confidence -= 0.25

        return max(0.0, min(1.0, confidence))

    def penalize_source(self, source_name: str, penalty: float = 0.05) -> None:
        """Hatalı / aykırı veri üreten kaynağın güvenilirlik skorunu düşürür."""
        with self._lock:
            cur = self._dynamic_reliability.get(source_name, 0.5)
            self._dynamic_reliability[source_name] = max(0.1, cur - penalty)
            logger.info(
                "Kaynak güvenilirlik skoru düşürüldü",
                kaynak=source_name,
                yeni_skor=self._dynamic_reliability[source_name],
            )

    def reset_reliability(self) -> None:
        """Dinamik güvenilirlik skorlarını fabrika ayarlarına döndürür."""
        with self._lock:
            self._dynamic_reliability = dict(self.BASE_SOURCE_RELIABILITY)

    @otel_trace("reconciliation.detect_price_jump")
    def detect_price_jump(
        self,
        ticker: str,
        current_price: float,
        previous_price: float,
        volatility: float,
        threshold_sigma: float = 4.0,
    ) -> tuple[bool, float]:
        """Volatilite bazlı normalleştirilmiş ani fiyat sıçraması tespiti.

        Returns:
            (is_jump: bool, change_pct: float)
        """
        if previous_price <= 0 or current_price <= 0:
            return False, 0.0

        change_pct = abs((current_price / previous_price) - 1.0) * 100.0

        if volatility > 0:
            expected_move = (volatility / np.sqrt(252)) * threshold_sigma * 100.0
            is_jump = bool(change_pct > expected_move)
        else:
            is_jump = bool(change_pct > 10.0)  # Varsayılan %10 eşik

        return is_jump, float(change_pct)

    @staticmethod
    def export_to_polars(records: list[ReconciledData]) -> pl.DataFrame:
        """Uzlaştırılmış veri listesini Polars DataFrame'e dönüştürür."""
        if not records:
            return pl.DataFrame(
                schema={
                    "value": pl.Float64,
                    "source": pl.Utf8,
                    "confidence": pl.Float64,
                    "quality_score": pl.Float64,
                    "discrepancy_pct": pl.Float64,
                    "is_consistent": pl.Boolean,
                    "anomaly_detected": pl.Boolean,
                    "reconciled_at": pl.Datetime("ms"),
                }
            )

        data = [
            {
                "value": r.value,
                "source": r.source,
                "confidence": r.confidence,
                "quality_score": r.quality_score,
                "discrepancy_pct": r.discrepancy_pct,
                "is_consistent": r.is_consistent,
                "anomaly_detected": r.anomaly_detected,
                "reconciled_at": r.reconciled_at,
            }
            for r in records
        ]
        return pl.DataFrame(data)


# Global Singleton
cross_source_reconciliation = CrossSourceReconciliation()


def reconcile_price(
    sources: dict[str, float],
    ticker: str = "UNKNOWN",
    field_name: str = "price",
    timestamp: datetime | None = None,
    engine: CrossSourceReconciliation = cross_source_reconciliation,
) -> ReconciledData:
    """Fiyat ve sayısal metrik kaynaklarını uzlaştırır."""
    return engine.reconcile_price(sources, ticker=ticker, field_name=field_name, timestamp=timestamp)


def heal_reconcile_with_outlier_removal(
    sources: dict[str, float],
    ticker: str = "UNKNOWN",
    field_name: str = "price",
    max_outlier_removals: int = 1,
    engine: CrossSourceReconciliation = cross_source_reconciliation,
) -> tuple[ReconciledData, list[str]]:
    """Aykırı değer saptandığında bozuk kaynakları otomatik eleyip yeniden uzlaştırır (Self-Healing)."""
    return engine.heal_reconcile_with_outlier_removal(
        sources,
        ticker=ticker,
        field_name=field_name,
        max_outlier_removals=max_outlier_removals,
    )


def read_reconciliation_audit_from_duckdb(
    db_path: str = DEFAULT_RECONCILIATION_DUCKDB_PATH,
    ticker: str | None = None,
    engine: CrossSourceReconciliation = cross_source_reconciliation,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı uzlaştırma denetim kayıtlarını Polars DataFrame olarak okur."""
    return engine.read_audit_from_duckdb(db_path=db_path, ticker=ticker)


def clear_reconciliation_audit_duckdb(
    db_path: str = DEFAULT_RECONCILIATION_DUCKDB_PATH,
    engine: CrossSourceReconciliation = cross_source_reconciliation,
) -> bool:
    """DuckDB tablosundaki uzlaştırma denetim kayıtlarını temizler."""
    return engine.clear_audit_duckdb(db_path=db_path)


def export_reconciliation_to_polars(records: list[ReconciledData]) -> pl.DataFrame:
    """Uzlaştırılmış veri listesini Polars DataFrame'e dönüştürür."""
    return CrossSourceReconciliation.export_to_polars(records)


def to_orjson_bytes(data: Any) -> bytes:
    """Verilen veriyi orjson bayt dizisine dönüştürür."""
    return orjson.dumps(data, default=str)


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_RECONCILIATION_DUCKDB_PATH",
    "DEFAULT_WAL_SIZE",
    "CrossSourceReconciliation",
    "ReconciledData",
    "clear_reconciliation_audit_duckdb",
    "configure_duckdb_wal",
    "cross_source_reconciliation",
    "export_reconciliation_to_polars",
    "heal_reconcile_with_outlier_removal",
    "read_reconciliation_audit_from_duckdb",
    "reconcile_price",
    "to_orjson_bytes",
]

