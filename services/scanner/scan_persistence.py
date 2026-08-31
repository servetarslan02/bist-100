"""
ALPHA BIST — Scan Result Persistence v1.0

Tarama sonuçlarını kalıcı olarak saklar.
Geçmiş tarama analizi ve performans takibi için.

Kaynaklar: TradingAgents (TauricResearch 2025), Endüstri standardı
"""

import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
import structlog

logger = structlog.get_logger()


@dataclass
class ScanResultRecord:
    """Tarama sonucu kaydı."""

    scan_id: str
    scan_type: str  # batch, live, event, manual
    ticker: str
    score: float
    signal: str  # MOMENTUM, BREAKOUT, VOLUME_ANOMALY, vb.
    direction: str  # LONG, SHORT, NEUTRAL
    confidence: float
    tier: int
    regime: str
    price: float
    volume: int
    features: dict[str, float]  # Key feature'lar
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        """Otomatik eklendi."""
        return asdict(self)


class ScanPersistence:
    """Tarama sonuçlarını SQLite'a kaydeder.

    Tablo: scan_results
    - scan_id: Benzersiz tarama kimliği
    - scan_type: Tarama türü (batch, live, event, manual)
    - ticker: Hisse kodu
    - score: Fırsat skoru
    - signal: Sinyal türü
    - direction: Yön (LONG, SHORT, NEUTRAL)
    - confidence: Güven skoru
    - tier: Tier seviyesi
    - regime: Piyasa rejimi
    - price: Fiyat
    - volume: Hacim
    - features_json: Feature'lar (JSON)
    - timestamp: Zaman damgası
    """

    def __init__(self, db_path: str = "data/scan_results.db"):
        """Otomatik eklendi."""
        self._db_path = db_path
        self._initialized = False
        self._write_buffer: list[tuple[str, tuple]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_size = 20
        self._last_flush = time.time()
        self._flush_interval = 30.0
        self._periodic_thread: threading.Thread | None = None
        self._stop_periodic = threading.Event()
        self._start_periodic_flush()

    def _ensure_table(self) -> Any:
        """Tabloyu oluştur (yoksa). Thread-safe double-checked locking."""
        if self._initialized:
            return
        with self._buffer_lock:
            if self._initialized:
                return

        try:
            import duckdb

            conn = duckdb.connect(self._db_path)
            # SSD write reduction: DuckDB WAL ayarları
            try:
                from services.core.debounce import configure_duckdb_wal
                configure_duckdb_wal(conn)
            except Exception:
                pass
            cursor = conn.cursor()

            cursor.execute("CREATE SEQUENCE IF NOT EXISTS scan_results_seq START 1")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_results (
                    id BIGINT PRIMARY KEY DEFAULT nextval('scan_results_seq'),
                    scan_id TEXT NOT NULL,
                    scan_type TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    score REAL,
                    signal TEXT,
                    direction TEXT,
                    confidence REAL,
                    tier INTEGER,
                    regime TEXT,
                    price REAL,
                    volume INTEGER,
                    features_json TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # İndeksler
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_ticker
                ON scan_results(ticker)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_timestamp
                ON scan_results(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_type
                ON scan_results(scan_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_signal
                ON scan_results(signal)
            """)

            conn.commit()
            conn.close()
            self._initialized = True
            logger.info("Scan persistence initialized", db=self._db_path)

        except Exception as e:
            logger.error("Failed to initialize scan persistence", error=str(e))

    def _buffered_write(self, query: str, params: tuple) -> None:
        """Buffered write — toplu yaz (SSD dostu)."""
        with self._buffer_lock:
            self._write_buffer.append((query, params))
            should_flush = len(self._write_buffer) >= self._buffer_size
        if should_flush:
            self._flush_buffer()

    def _flush_buffer(self) -> None:
        """Write buffer'ı flush et (batched write — SSD dostu)."""
        with self._buffer_lock:
            if not self._write_buffer:
                return
            batch = self._write_buffer.copy()
            self._write_buffer.clear()
        try:
            import duckdb
            conn = duckdb.connect(self._db_path)
            try:
                from services.core.debounce import configure_duckdb_wal
                configure_duckdb_wal(conn)
            except Exception:
                pass
            for query, params in batch:
                conn.execute(query, params)
            conn.commit()
            conn.close()
            self._last_flush = time.time()
        except Exception as e:
            logger.error("Scan persistence buffer flush error", error=str(e))
            with self._buffer_lock:
                self._write_buffer = batch + self._write_buffer  # Re-queue on failure

    def flush(self) -> None:
        """Manuel flush."""
        self._flush_buffer()

    def _start_periodic_flush(self) -> None:
        """Arka planda periyodik flush başlat."""
        def _loop() -> None:
            while not self._stop_periodic.wait(self._flush_interval):
                try:
                    self.periodic_flush()
                except Exception as e:
                    logger.debug("Scan persistence periodic flush error", error=str(e))
        self._periodic_thread = threading.Thread(target=_loop, daemon=True, name="scan-periodic-flush")
        self._periodic_thread.start()

    def periodic_flush(self) -> None:
        """Periyodik flush."""
        if time.time() - self._last_flush > self._flush_interval:
            self._flush_buffer()

    def save_scan_result(self, record: ScanResultRecord) -> Any:
        """Tek tarama sonucu kaydet (buffered — SSD dostu)."""
        self._ensure_table()
        self._buffered_write(
            """
            INSERT INTO scan_results
            (scan_id, scan_type, ticker, score, signal, direction,
             confidence, tier, regime, price, volume, features_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                record.scan_id,
                record.scan_type,
                record.ticker,
                record.score,
                record.signal,
                record.direction,
                record.confidence,
                record.tier,
                record.regime,
                record.price,
                record.volume,
                orjson.dumps(record.features or {}).decode(),
                record.timestamp,
            ),
        )

    def save_batch_results(
        self,
        scan_type: str,
        results: list[dict[str, Any]],
        regime: str = "RANGE",
    ) -> Any:
        """Toplu tarama sonuçları kaydet.

        Args:
            scan_type: Tarama türü
            results: Tarama sonuçları listesi
            regime: Piyasa rejimi
        """
        scan_id = f"{scan_type}_{int(time.time())}"
        now = datetime.now(UTC).isoformat()

        for result in results:
            record = ScanResultRecord(
                scan_id=scan_id,
                scan_type=scan_type,
                ticker=result.get("ticker", ""),
                score=result.get("score", 0),
                signal=result.get("signal", ""),
                direction=result.get("direction", "NEUTRAL"),
                confidence=result.get("confidence", 0),
                tier=result.get("tier", 0),
                regime=regime,
                price=result.get("price", 0),
                volume=result.get("volume", 0),
                features=result.get("features", {}),
                timestamp=now,
            )
            self.save_scan_result(record)

        logger.info("Batch scan results saved", scan_type=scan_type, count=len(results), scan_id=scan_id)

    def get_scan_history(
        self,
        ticker: str,
        days: int = 30,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Hisse tarama geçmişini al.

        Args:
            ticker: Hisse kodu
            days: Son kaç gün
            limit: Maksimum kayıt

        Returns:
            Tarama geçmişi
        """
        self._ensure_table()

        conn = None
        try:
            import duckdb

            conn = duckdb.connect(self._db_path, read_only=True)
            cursor = conn.cursor()

            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

            cursor.execute(
                """
                SELECT * FROM scan_results
                WHERE ticker = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (ticker, cutoff, limit),
            )

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            return [dict(zip(columns, row, strict=False)) for row in rows]

        except Exception as e:
            logger.error("Failed to get scan history", ticker=ticker, error=str(e))
            return []
        finally:
            if conn is not None:
                conn.close()

    def get_scan_stats(
        self,
        scan_type: str = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Tarama istatistikleri.

        Args:
            scan_type: Tarama türü filtresi
            days: Son kaç gün

        Returns:
            İstatistikler
        """
        self._ensure_table()

        conn = None
        try:
            import duckdb

            conn = duckdb.connect(self._db_path, read_only=True)
            cursor = conn.cursor()

            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

            if scan_type:
                cursor.execute(
                    """
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT ticker) as unique_tickers,
                           AVG(score) as avg_score,
                           AVG(confidence) as avg_confidence,
                           COUNT(CASE WHEN signal != '' THEN 1 END) as signals
                    FROM scan_results
                    WHERE scan_type = ? AND timestamp > ?
                """,
                    (scan_type, cutoff),
                )
            else:
                cursor.execute(
                    """
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT ticker) as unique_tickers,
                           AVG(score) as avg_score,
                           AVG(confidence) as avg_confidence,
                           COUNT(CASE WHEN signal != '' THEN 1 END) as signals
                    FROM scan_results
                    WHERE timestamp > ?
                """,
                    (cutoff,),
                )

            row = cursor.fetchone()

            return {
                "total_records": row[0] if row else 0,
                "unique_tickers": row[1] if row else 0,
                "avg_score": round(row[2], 2) if row and row[2] else 0,
                "avg_confidence": round(row[3], 4) if row and row[3] else 0,
                "signals_generated": row[4] if row else 0,
                "scan_type": scan_type or "all",
                "days": days,
            }

        except Exception as e:
            logger.error("Failed to get scan stats", error=str(e))
            return {}
        finally:
            if conn is not None:
                conn.close()

    def get_hit_rate(
        self,
        scan_type: str = None,
        days: int = 30,
        min_score: float = 70.0,
    ) -> dict[str, Any]:
        """İsabet oranı — skoru yüksek sinyallerin takibi.

        Args:
            scan_type: Tarama türü
            days: Son kaç gün
            min_score: Minimum skor filtresi

        Returns:
            İsabet oranı
        """
        self._ensure_table()

        conn = None
        try:
            import duckdb

            conn = duckdb.connect(self._db_path, read_only=True)
            cursor = conn.cursor()

            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

            # Yüksek skorlu sinyaller
            if scan_type:
                cursor.execute(
                    """
                    SELECT ticker, score, signal, direction, timestamp
                    FROM scan_results
                    WHERE scan_type = ? AND timestamp > ? AND score >= ?
                    ORDER BY timestamp DESC
                """,
                    (scan_type, cutoff, min_score),
                )
            else:
                cursor.execute(
                    """
                    SELECT ticker, score, signal, direction, timestamp
                    FROM scan_results
                    WHERE timestamp > ? AND score >= ?
                    ORDER BY timestamp DESC
                """,
                    (cutoff, min_score),
                )

            high_score_signals = cursor.fetchall()

            # Sinyal türü dağılımı
            signal_dist = {}
            for row in high_score_signals:
                sig = row[2] or "NONE"
                signal_dist[sig] = signal_dist.get(sig, 0) + 1

            # Yön dağılımı
            direction_dist = {}
            for row in high_score_signals:
                d = row[3] or "NEUTRAL"
                direction_dist[d] = direction_dist.get(d, 0) + 1

            return {
                "total_high_score_signals": len(high_score_signals),
                "signal_distribution": signal_dist,
                "direction_distribution": direction_dist,
                "min_score": min_score,
                "days": days,
            }

        except Exception as e:
            logger.error("Failed to get hit rate", error=str(e))
            return {}
        finally:
            if conn is not None:
                conn.close()

    def get_top_scanned_tickers(
        self,
        days: int = 7,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """En çok taranan hisseler.

        Args:
            days: Son kaç gün
            limit: Maksimum sonuç

        Returns:
            En çok taranan hisseler
        """
        self._ensure_table()

        conn = None
        try:
            import duckdb

            conn = duckdb.connect(self._db_path, read_only=True)
            cursor = conn.cursor()

            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

            cursor.execute(
                """
                SELECT ticker,
                       COUNT(*) as scan_count,
                       AVG(score) as avg_score,
                       MAX(score) as max_score,
                       COUNT(CASE WHEN signal != '' THEN 1 END) as signal_count
                FROM scan_results
                WHERE timestamp > ?
                GROUP BY ticker
                ORDER BY scan_count DESC
                LIMIT ?
            """,
                (cutoff, limit),
            )

            rows = cursor.fetchall()

            return [
                {
                    "ticker": row[0],
                    "scan_count": row[1],
                    "avg_score": round(row[2], 2),
                    "max_score": round(row[3], 2),
                    "signal_count": row[4],
                }
                for row in rows
            ]

        except Exception as e:
            logger.error("Failed to get top scanned tickers", error=str(e))
            return []
        finally:
            if conn is not None:
                conn.close()

    def cleanup_old_records(self, days: int = 90) -> Any:
        """Eski kayıtları temizle.

        Args:
            days: Bu günden eski kayıtları sil
        """
        self._ensure_table()

        conn = None
        try:
            import duckdb

            conn = duckdb.connect(self._db_path)
            # SSD write reduction: DuckDB WAL ayarları
            try:
                from services.core.debounce import configure_duckdb_wal
                configure_duckdb_wal(conn)
            except Exception:
                pass
            cursor = conn.cursor()

            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

            cursor.execute("DELETE FROM scan_results WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount

            conn.commit()

            logger.info("Old scan records cleaned up", deleted=deleted, older_than_days=days)

        except Exception as e:
            logger.error("Failed to cleanup old records", error=str(e))
        finally:
            if conn is not None:
                conn.close()


# Singleton
scan_persistence = ScanPersistence()

# Graceful shutdown: buffer'ı flush et
import atexit
import signal as _signal

def _flush_scan_on_exit() -> None:
    try:
        scan_persistence.flush()
    except Exception:
        logger.warning("Scan persistence flush on exit failed", exc_info=True)

def _flush_scan_on_signal(signum, frame) -> None:
    try:
        scan_persistence.flush()
    except Exception:
        logger.warning("Scan persistence flush on signal failed", exc_info=True)

atexit.register(_flush_scan_on_exit)
try:
    _signal.signal(_signal.SIGTERM, _flush_scan_on_signal)
    _signal.signal(_signal.SIGINT, _flush_scan_on_signal)
except (ValueError, OSError):
    pass
