"""
ALPHA BIST — Macro Historical Data Store v2.0 (DuckDB Native)

Tarihsel makro veri deposu — Point-In-Time (PIT):
- DuckDB tabanlı gömülü analitik motoru
- Sıfır veri sızıntılı (Point-In-Time) sorgulama
- Çoklu gösterge desteği (TÜFE, TCMB faiz, CDS, USDTRY vb.)
- Toplu backfill ve thread-safe işlem garantisi
- SSD korumalı debounced checkpoint ve atomik erişim

KURAL: Backtest'te sadece o tarihte bilinen veriyi kullan (Zero Lookahead Bias).
"""

import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import duckdb
import orjson
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class MacroDataPoint:
    """Tekil makro veri noktası."""

    date: str
    indicator: str
    value: float
    source: str
    timestamp: str

    def __repr__(self) -> str:
        """Makro veri noktasının okunabilir string temsili."""
        return (
            f"MacroDataPoint(indicator='{self.indicator}', date='{self.date}', "
            f"value={self.value}, source='{self.source}', ts='{self.timestamp}')"
        )


class MacroHistoricalStore:
    """DuckDB tabanlı tarihsel makro veri deposu."""

    def __init__(self, storage_path: str = "data/macro_historical.duckdb") -> None:
        """Tarihsel makro veri deposu başlatıcı.

        DuckDB bağlantısını kurar, gerekli şema ve indeksleri ilklendirir.

        Args:
            storage_path: Veri dosyası saklama yolu (varsayılan: 'data/macro_historical.duckdb').
        """
        self._lock = threading.RLock()
        self._last_flush: float = 0.0

        # JSON uzantısı gelirse geriye dönük uyumluluk için duckdb'ye uyarla
        if storage_path.endswith(".json"):
            self._storage_path = storage_path[:-5] + ".duckdb"
            self._legacy_json_path = storage_path
        else:
            self._storage_path = storage_path
            self._legacy_json_path = None

        if self._storage_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._storage_path)), exist_ok=True)

        self._conn = duckdb.connect(self._storage_path)
        self._init_db()
        self._migrate_legacy_json_if_needed()

    def __repr__(self) -> str:
        """Tarihsel makro veri deposu okunabilir string temsili."""
        with self._lock:
            try:
                row = self._conn.execute("SELECT COUNT(*), COUNT(DISTINCT indicator) FROM macro_historical").fetchone()
                total_pts = row[0] if row else 0
                n_ind = row[1] if row else 0
            except Exception:
                total_pts, n_ind = 0, 0

            return (
                f"MacroHistoricalStore(storage_path='{self._storage_path}', "
                f"indicators={n_ind}, total_points={total_pts})"
            )

    def _init_db(self) -> None:
        """Veritabanı tablosunu ve Point-In-Time indekslerini hazırlar."""
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS macro_historical (
                    date VARCHAR NOT NULL,
                    indicator VARCHAR NOT NULL,
                    value DOUBLE NOT NULL,
                    source VARCHAR NOT NULL,
                    timestamp VARCHAR NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_macro_hist ON macro_historical (indicator, date)
                """
            )

    def _migrate_legacy_json_if_needed(self) -> None:
        """Legacy JSON dosyası varsa verileri DuckDB tablosuna taşır."""
        paths_to_check = []
        if self._legacy_json_path and os.path.exists(self._legacy_json_path):
            paths_to_check.append(self._legacy_json_path)
        default_json = "data/macro_historical.json"
        if os.path.exists(default_json) and default_json not in paths_to_check:
            paths_to_check.append(default_json)

        for json_path in paths_to_check:
            try:
                with open(json_path, "rb") as f:
                    content = f.read()
                    if not content:
                        continue
                    data = orjson.loads(content)

                with self._lock:
                    count_row = self._conn.execute("SELECT COUNT(*) FROM macro_historical").fetchone()
                    if count_row and count_row[0] > 0:
                        continue

                    batch = []
                    for indicator, dates in data.items():
                        for date_str, entries in dates.items():
                            for entry in entries:
                                batch.append(
                                    (
                                        date_str,
                                        indicator,
                                        float(entry.get("value", 0.0)),
                                        str(entry.get("source", "legacy")),
                                        str(entry.get("timestamp", datetime.now(UTC).isoformat())),
                                    )
                                )

                    if batch:
                        self._conn.executemany("INSERT INTO macro_historical VALUES (?, ?, ?, ?, ?)", batch)
                        logger.info("Migrated legacy macro JSON to DuckDB", records=len(batch), path=json_path)
            except Exception as e:
                logger.warning("Failed legacy JSON migration to DuckDB", error=str(e), path=json_path)

    def save(
        self,
        date: str,
        indicator: str,
        value: float,
        source: str = "unknown",
    ) -> None:
        """Makro veri noktasını DuckDB deposuna kaydeder.

        Args:
            date: Veri tarihi (YYYY-MM-DD).
            indicator: Makro gösterge kodu (örn. CPI, USDTRY, POLICY_RATE).
            value: Sayısal gösterge değeri.
            source: Veri kaynağı adı (örn. tuik, tcmb, evds).
        """
        ts = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO macro_historical VALUES (?, ?, ?, ?, ?)",
                (date, indicator, float(value), source, ts),
            )
        self._debounced_flush()
        logger.debug("Macro data saved to DuckDB", indicator=indicator, date=date, value=value)

    def get(
        self,
        date: str,
        indicator: str,
    ) -> float | None:
        """Belirli tarihteki en son kaydedilen gösterge değerini getirir.

        Args:
            date: Veri tarihi (YYYY-MM-DD).
            indicator: Gösterge kodu.

        Returns:
            float | None: Kayıtlı değer veya veri yoksa None.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT value FROM macro_historical
                WHERE indicator = ? AND date = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (indicator, date),
            ).fetchone()
            return float(row[0]) if row else None

    def get_latest_before(
        self,
        date: str,
        indicator: str,
    ) -> dict[str, Any] | None:
        """Belirli bir tarihte ve öncesinde bilinen en güncel veriyi getirir (Point-In-Time).

        Args:
            date: Referans tarih (YYYY-MM-DD).
            indicator: Gösterge adı.

        Returns:
            dict[str, Any] | None: Tarih, gösterge, değer ve kaynak sözlüğü.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT date, indicator, value, source, timestamp
                FROM macro_historical
                WHERE indicator = ? AND date <= ?
                ORDER BY date DESC, timestamp DESC
                LIMIT 1
                """,
                (indicator, date),
            ).fetchone()

            if not row:
                return None

            return {
                "date": row[0],
                "indicator": row[1],
                "value": float(row[2]),
                "source": row[3],
                "timestamp": row[4],
            }

    def get_range(
        self,
        indicator: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Belirtilen tarih aralığındaki verileri sıralı olarak döndürür.

        Args:
            indicator: Gösterge adı.
            start_date: Başlangıç tarihi (YYYY-MM-DD).
            end_date: Bitiş tarihi (YYYY-MM-DD).

        Returns:
            list[dict[str, Any]]: Gün bazında tekilleştirilmiş veri kayıtları listesi.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT date, indicator, value, source
                FROM (
                    SELECT date, indicator, value, source, timestamp,
                           ROW_NUMBER() OVER(PARTITION BY date ORDER BY timestamp DESC) as rn
                    FROM macro_historical
                    WHERE indicator = ? AND date BETWEEN ? AND ?
                )
                WHERE rn = 1
                ORDER BY date ASC
                """,
                (indicator, start_date, end_date),
            ).fetchall()

            return [
                {
                    "date": r[0],
                    "indicator": r[1],
                    "value": float(r[2]),
                    "source": r[3],
                }
                for r in rows
            ]

    def get_latest(self, indicator: str) -> dict[str, Any] | None:
        """Göstergeye ait en son bilinen güncel veriyi döndürür.

        Args:
            indicator: Gösterge adı.

        Returns:
            dict[str, Any] | None: Son bilinen veri sözlüğü.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT date, indicator, value, source, timestamp
                FROM macro_historical
                WHERE indicator = ?
                ORDER BY date DESC, timestamp DESC
                LIMIT 1
                """,
                (indicator,),
            ).fetchone()

            if not row:
                return None

            return {
                "date": row[0],
                "indicator": row[1],
                "value": float(row[2]),
                "source": row[3],
                "timestamp": row[4],
            }

    def backfill(
        self,
        indicator: str,
        data: list[dict[str, Any]],
    ) -> int:
        """Toplu tarihsel veri yüklemesini DuckDB üzerinde atomik olarak gerçekleştirir.

        Args:
            indicator: Gösterge adı.
            data: [{'date': 'YYYY-MM-DD', 'value': float, 'source': str}] formatında liste.

        Returns:
            int: Başarıyla kaydedilen kayıt adedi.
        """
        if not data:
            return 0

        ts_now = datetime.now(UTC).isoformat()
        records = [
            (
                str(d["date"]),
                indicator,
                float(d["value"]),
                str(d.get("source", "backfill")),
                str(d.get("timestamp", ts_now)),
            )
            for d in data
        ]

        with self._lock:
            self._conn.executemany("INSERT INTO macro_historical VALUES (?, ?, ?, ?, ?)", records)

        self._debounced_flush()
        logger.info("DuckDB backfill completed", indicator=indicator, count=len(records))
        return len(records)

    def get_available_indicators(self) -> list[str]:
        """Kayıtlı mevcut tüm makro göstergeleri listeler.

        Returns:
            list[str]: Gösterge adları listesi.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT indicator FROM macro_historical ORDER BY indicator"
            ).fetchall()
            return [r[0] for r in rows]

    def get_date_range(self, indicator: str) -> dict[str, Any] | None:
        """Bir göstergenin kapsadığı tarih aralığını ve toplam nokta sayısını döndürür.

        Args:
            indicator: Gösterge adı.

        Returns:
            dict[str, Any] | None: Başlangıç/bitiş tarihleri ve nokta adedi.
        """
        with self._lock:
            row = self._conn.execute(
                """
                SELECT MIN(date), MAX(date), COUNT(DISTINCT date)
                FROM macro_historical
                WHERE indicator = ?
                """,
                (indicator,),
            ).fetchone()

            if not row or row[0] is None:
                return None

            return {
                "indicator": indicator,
                "start_date": row[0],
                "end_date": row[1],
                "total_points": int(row[2]),
            }

    def get_report(self) -> dict[str, Any]:
        """Tarihsel deponun genel durum özetini üretir.

        Returns:
            dict[str, Any]: Göstergeler, veri adedi ve depolama yolu raporu.
        """
        indicators = self.get_available_indicators()
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM macro_historical").fetchone()
            total_points = int(row[0]) if row else 0

        return {
            "indicators": len(indicators),
            "total_data_points": total_points,
            "indicator_list": indicators,
            "storage_path": self._storage_path,
        }

    # ===================== PERSISTENCE & RESOURCE LIFECYCLE =====================

    def _debounced_flush(self) -> None:
        """SSD aşınmasını önlemek üzere aralıklı checkpoint çağırır."""
        now = time.monotonic()
        if now - self._last_flush < 60.0:
            return
        self._last_flush = now
        self.flush()

    def flush(self) -> None:
        """DuckDB veritabanı önbelleğini diske checkpoint eder."""
        with self._lock:
            try:
                self._conn.execute("CHECKPOINT")
            except Exception as e:
                logger.debug("DuckDB checkpoint warning", error=str(e))

    def close(self) -> None:
        """DuckDB bağlantısını güvenli bir şekilde kapatır."""
        with self._lock:
            try:
                self._conn.execute("CHECKPOINT")
                self._conn.close()
            except Exception as e:
                logger.debug("Error closing DuckDB connection", error=str(e))

    def __enter__(self) -> "MacroHistoricalStore":
        """Bağlam yöneticisi girişi."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Bağlam yöneticisi çıkışında kaynakları kapatır."""
        self.close()


# Singleton
macro_historical_store = MacroHistoricalStore()

__all__ = [
    "MacroDataPoint",
    "MacroHistoricalStore",
    "macro_historical_store",
]
