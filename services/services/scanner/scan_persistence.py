"""
ALPHA BIST — Scan Result Persistence v1.0

Tarama sonuçlarını kalıcı olarak saklar.
Geçmiş tarama analizi ve performans takibi için.

Kaynaklar: TradingAgents (TauricResearch 2025), Endüstri standardı
"""

import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import structlog

logger = structlog.get_logger()


@dataclass
class ScanResultRecord:
    """Tarama sonucu kaydı."""
    scan_id: str
    scan_type: str          # batch, live, event, manual
    ticker: str
    score: float
    signal: str             # MOMENTUM, BREAKOUT, VOLUME_ANOMALY, vb.
    direction: str          # LONG, SHORT, NEUTRAL
    confidence: float
    tier: int
    regime: str
    price: float
    volume: int
    features: Dict[str, float]  # Key feature'lar
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
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
        self._db_path = db_path
        self._initialized = False

    def _ensure_table(self):
        """Tabloyu oluştur (yoksa)."""
        if self._initialized:
            return

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    def save_scan_result(self, record: ScanResultRecord):
        """Tek tarama sonucu kaydet.

        Args:
            record: Tarama sonucu kaydı
        """
        self._ensure_table()

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO scan_results
                (scan_id, scan_type, ticker, score, signal, direction,
                 confidence, tier, regime, price, volume, features_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
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
                json.dumps(record.features or {}),
                record.timestamp,
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error("Failed to save scan result",
                        ticker=record.ticker, error=str(e))

    def save_batch_results(
        self,
        scan_type: str,
        results: List[Dict[str, Any]],
        regime: str = "RANGE",
    ):
        """Toplu tarama sonuçları kaydet.

        Args:
            scan_type: Tarama türü
            results: Tarama sonuçları listesi
            regime: Piyasa rejimi
        """
        scan_id = f"{scan_type}_{int(time.time())}"
        now = datetime.now(timezone.utc).isoformat()

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

        logger.info("Batch scan results saved",
                    scan_type=scan_type,
                    count=len(results),
                    scan_id=scan_id)

    def get_scan_history(
        self,
        ticker: str,
        days: int = 30,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Hisse tarama geçmişini al.

        Args:
            ticker: Hisse kodu
            days: Son kaç gün
            limit: Maksimum kayıt

        Returns:
            Tarama geçmişi
        """
        self._ensure_table()

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            cursor.execute("""
                SELECT * FROM scan_results
                WHERE ticker = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (ticker, cutoff, limit))

            rows = cursor.fetchall()
            conn.close()

            return [dict(row) for row in rows]

        except Exception as e:
            logger.error("Failed to get scan history",
                        ticker=ticker, error=str(e))
            return []

    def get_scan_stats(
        self,
        scan_type: str = None,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Tarama istatistikleri.

        Args:
            scan_type: Tarama türü filtresi
            days: Son kaç gün

        Returns:
            İstatistikler
        """
        self._ensure_table()

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            if scan_type:
                cursor.execute("""
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT ticker) as unique_tickers,
                           AVG(score) as avg_score,
                           AVG(confidence) as avg_confidence,
                           COUNT(CASE WHEN signal != '' THEN 1 END) as signals
                    FROM scan_results
                    WHERE scan_type = ? AND timestamp > ?
                """, (scan_type, cutoff))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT ticker) as unique_tickers,
                           AVG(score) as avg_score,
                           AVG(confidence) as avg_confidence,
                           COUNT(CASE WHEN signal != '' THEN 1 END) as signals
                    FROM scan_results
                    WHERE timestamp > ?
                """, (cutoff,))

            row = cursor.fetchone()
            conn.close()

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

    def get_hit_rate(
        self,
        scan_type: str = None,
        days: int = 30,
        min_score: float = 70.0,
    ) -> Dict[str, Any]:
        """İsabet oranı — skoru yüksek sinyallerin takibi.

        Args:
            scan_type: Tarama türü
            days: Son kaç gün
            min_score: Minimum skor filtresi

        Returns:
            İsabet oranı
        """
        self._ensure_table()

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            # Yüksek skorlu sinyaller
            if scan_type:
                cursor.execute("""
                    SELECT ticker, score, signal, direction, timestamp
                    FROM scan_results
                    WHERE scan_type = ? AND timestamp > ? AND score >= ?
                    ORDER BY timestamp DESC
                """, (scan_type, cutoff, min_score))
            else:
                cursor.execute("""
                    SELECT ticker, score, signal, direction, timestamp
                    FROM scan_results
                    WHERE timestamp > ? AND score >= ?
                    ORDER BY timestamp DESC
                """, (cutoff, min_score))

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

            conn.close()

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

    def get_top_scanned_tickers(
        self,
        days: int = 7,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """En çok taranan hisseler.

        Args:
            days: Son kaç gün
            limit: Maksimum sonuç

        Returns:
            En çok taranan hisseler
        """
        self._ensure_table()

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            cursor.execute("""
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
            """, (cutoff, limit))

            rows = cursor.fetchall()
            conn.close()

            return [{
                "ticker": row[0],
                "scan_count": row[1],
                "avg_score": round(row[2], 2),
                "max_score": round(row[3], 2),
                "signal_count": row[4],
            } for row in rows]

        except Exception as e:
            logger.error("Failed to get top scanned tickers", error=str(e))
            return []

    def cleanup_old_records(self, days: int = 90):
        """Eski kayıtları temizle.

        Args:
            days: Bu günden eski kayıtları sil
        """
        self._ensure_table()

        try:
            import sqlite3
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            cursor.execute("DELETE FROM scan_results WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount

            conn.commit()
            conn.close()

            logger.info("Old scan records cleaned up",
                       deleted=deleted, older_than_days=days)

        except Exception as e:
            logger.error("Failed to cleanup old records", error=str(e))


# Singleton
scan_persistence = ScanPersistence()
