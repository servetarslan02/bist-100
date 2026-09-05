"""ALPHA BIST — Backtest Kalıcılık Katmanı (DuckDB Persistence Layer) v2.0.

Backtest sonuçlarını DuckDB üzerinde güvenli, thread-safe ve yüksek performanslı şekilde
saklar ve sorgular:
- Çalıştırma üstverileri (Run metadata)
- Gerçekleşen işlemler (Trades)
- Özkaynak eğrisi (Equity curve)
- Performans metrikleri ve yapılandırma JSON'ları

Özellikler:
- Bağlantı yeniden kullanımı (Connection reuse)
- Thread-safe bağlantı ve işlem yönetimi (threading.Lock)
- Otomatik artan ID desteği (DuckDB Sequence)
- Toplu ekleme optimizasyonu (Batch insert)
- Sağlık kontrolü (Health check)
- Polars DataFrame doğrudan dışa aktarım desteği
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

import structlog

try:
    import duckdb
except ImportError:
    duckdb = None

try:
    import polars as pl
except ImportError:
    pl = None

import orjson

logger = structlog.get_logger(__name__)

DEFAULT_DB_PATH: str = "data/backtest_results.db"
DEFAULT_LIST_LIMIT: int = 50

__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_LIST_LIMIT",
    "BacktestPersistence",
    "backtest_persistence",
]


class BacktestPersistence:
    """Backtest sonuçlarını DuckDB veritabanında saklayan ve yöneten sınıf.

    DuckDB bağlantısını yeniden kullanarak I/O maliyetini düşürür,
    iş parçacığı kilidi (Lock) ile eşzamanlı erişim güvenliği sağlar.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """BacktestPersistence sınıfını başlatır.

        Args:
            db_path: DuckDB veritabanı dosya yolu.
        """
        self._db_path: str = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock: threading.Lock = threading.Lock()
        if duckdb is not None:
            self._ensure_db()

    def __repr__(self) -> str:
        """Sınıfın okunabilir dize temsilini döndürür."""
        is_connected = self._conn is not None
        return f"BacktestPersistence(db_path='{self._db_path}', connected={is_connected})"

    def __enter__(self) -> BacktestPersistence:
        """Context manager giriş noktası."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager çıkış noktası, bağlantıyı kapatır."""
        self.close()

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısını getirir veya henüz yoksa oluşturur.

        Returns:
            duckdb.DuckDBPyConnection: Aktif veritabanı bağlantısı.

        Raises:
            RuntimeError: DuckDB kütüphanesi çalışma ortamında yüklü değilse.
        """
        if duckdb is None:
            raise RuntimeError("DuckDB kütüphanesi ortamda yüklü değil.")
        if self._conn is None:
            db_file = Path(self._db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Açık olan veritabanı bağlantısını güvenle kapatır."""
        with self._lock:
            if self._conn is not None:
                with contextlib.suppress(Exception):
                    self._conn.close()
                self._conn = None
                logger.info("DuckDB bağlantısı kapatıldı: %s", self._db_path)

    def _ensure_db(self) -> None:
        """Gerekli sequence, tablo ve indekslerin varlığını doğrular ve oluşturur.

        Raises:
            RuntimeError: Tablolar veya indeksler oluşturulamazsa.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                # DuckDB yerel sequence desteği
                with contextlib.suppress(Exception):
                    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_backtest_trades_id START 1;")
                with contextlib.suppress(Exception):
                    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_backtest_equity_id START 1;")

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS backtest_runs (
                        run_id TEXT PRIMARY KEY,
                        start_date TEXT NOT NULL,
                        end_date TEXT NOT NULL,
                        initial_capital REAL,
                        final_equity REAL,
                        total_return_pct REAL,
                        sharpe_ratio REAL,
                        max_drawdown_pct REAL,
                        total_trades INTEGER,
                        config_json TEXT,
                        metrics_json TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS backtest_trades (
                        id INTEGER PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        trade_id INTEGER,
                        ticker TEXT,
                        side TEXT,
                        date TEXT,
                        quantity INTEGER,
                        price REAL,
                        commission REAL,
                        slippage REAL,
                        pnl REAL,
                        pnl_pct REAL,
                        holding_days INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS backtest_equity (
                        id INTEGER PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        date TEXT NOT NULL,
                        equity REAL,
                        cash REAL,
                        market_value REAL,
                        positions INTEGER,
                        drawdown REAL,
                        daily_return REAL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_run ON backtest_trades(run_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_equity_run ON backtest_equity(run_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_equity_date ON backtest_equity(run_id, date)")
                conn.commit()
            except Exception as e:
                logger.error("Veritabanı tabloları doğrulanırken hata oluştu: %s", e)
                raise RuntimeError(f"Veritabanı başlatılamadı: {e}") from e

    def save_run(
        self,
        run_id: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        metrics: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Backtest çalıştırma üstverilerini veritabanına kaydeder veya günceller.

        Args:
            run_id: Benzersiz çalıştırma kimliği.
            start_date: Backtest başlangıç tarihi (YYYY-MM-DD).
            end_date: Backtest bitiş tarihi (YYYY-MM-DD).
            initial_capital: Başlangıç sermayesi.
            metrics: Özet performans metrikleri sözlüğü.
            config: Backtest konfigürasyon parametreleri sözlüğü.

        Raises:
            ValueError: run_id veya tarihler boş ise.
            RuntimeError: Veritabanı kaydı başarısız olursa (Fail-Closed).
        """
        if not run_id or not start_date or not end_date:
            raise ValueError("run_id, start_date ve end_date boş olamaz.")

        safe_metrics = metrics or {}
        safe_config = config or {}

        with self._lock:
            try:
                conn = self._get_conn()
                conn.execute(
                    """INSERT OR REPLACE INTO backtest_runs
                       (run_id, start_date, end_date, initial_capital, final_equity,
                        total_return_pct, sharpe_ratio, max_drawdown_pct, total_trades,
                        config_json, metrics_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(run_id),
                        str(start_date),
                        str(end_date),
                        float(initial_capital),
                        float(safe_metrics.get("final_equity", 0.0) or 0.0),
                        float(safe_metrics.get("total_return_pct", 0.0) or 0.0),
                        float(safe_metrics.get("sharpe_ratio", 0.0) or 0.0),
                        float(safe_metrics.get("max_drawdown_pct", 0.0) or 0.0),
                        int(safe_metrics.get("total_trades", 0) or 0),
                        orjson.dumps(safe_config).decode(),
                        orjson.dumps(safe_metrics, default=str).decode(),
                    ),
                )
                conn.commit()
                logger.info("Backtest çalıştırması kaydedildi: run_id=%s", run_id)
            except Exception as e:
                logger.error("Backtest çalıştırması kaydedilemedi: run_id=%s, hata=%s", run_id, e)
                raise RuntimeError(f"Backtest çalıştırması kaydedilemedi (run_id={run_id}): {e}") from e


    def save_trades(self, run_id: str, trades: list[dict[str, Any]]) -> None:
        """Backtest sırasında gerçekleşen işlemleri toplu olarak kaydeder.

        Args:
            run_id: Benzersiz çalıştırma kimliği.
            trades: İşlem sözlükleri listesi.
        """
        if not trades:
            return
        with self._lock:
            try:
                conn = self._get_conn()
                max_id_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM backtest_trades").fetchone()
                start_id = (max_id_row[0] if max_id_row else 0) + 1

                conn.executemany(
                    """INSERT INTO backtest_trades
                       (id, run_id, trade_id, ticker, side, date, quantity, price,
                        commission, slippage, pnl, pnl_pct, holding_days)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            start_id + idx,
                            run_id,
                            t.get("trade_id", 0),
                            t.get("ticker", ""),
                            t.get("side", ""),
                            str(t.get("date", "")),
                            int(t.get("quantity", 0)),
                            float(t.get("price", 0.0)),
                            float(t.get("commission", 0.0)),
                            float(t.get("slippage", 0.0)),
                            float(t.get("pnl", 0.0)),
                            float(t.get("pnl_pct", 0.0)),
                            int(t.get("holding_days", 0)),
                        )
                        for idx, t in enumerate(trades)
                    ],
                )
                conn.commit()
                logger.info("İşlemler başarıyla kaydedildi: run_id=%s, adet=%d", run_id, len(trades))
            except Exception as e:
                logger.error("İşlemler kaydedilemedi: run_id=%s, hata=%s", run_id, e)
                raise RuntimeError(f"İşlemler kaydedilemedi (run_id={run_id}): {e}") from e

    def save_equity_curve(self, run_id: str, curve: list[dict[str, Any]]) -> None:
        """Backtest özkaynak eğrisi noktalarını toplu olarak kaydeder.

        Args:
            run_id: Benzersiz çalıştırma kimliği.
            curve: Günlük özkaynak durum sözlükleri listesi.

        Raises:
            RuntimeError: Veritabanına kayıt başarısız olursa.
        """
        if not curve:
            return
        with self._lock:
            try:
                conn = self._get_conn()
                max_id_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM backtest_equity").fetchone()
                start_id = (max_id_row[0] if max_id_row else 0) + 1

                conn.executemany(
                    """INSERT INTO backtest_equity
                       (id, run_id, date, equity, cash, market_value, positions, drawdown, daily_return)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            start_id + idx,
                            run_id,
                            str(s.get("date", "")),
                            float(s.get("equity", 0.0)),
                            float(s.get("cash", 0.0)),
                            float(s.get("market_value", 0.0)),
                            int(s.get("positions", 0)),
                            float(s.get("drawdown", 0.0)),
                            float(s.get("daily_return", 0.0)),
                        )
                        for idx, s in enumerate(curve)
                    ],
                )
                conn.commit()
                logger.info("Özkaynak eğrisi kaydedildi: run_id=%s, nokta_sayisi=%d", run_id, len(curve))
            except Exception as e:
                logger.error("Özkaynak eğrisi kaydedilemedi: run_id=%s, hata=%s", run_id, e)
                raise RuntimeError(f"Özkaynak eğrisi kaydedilemedi (run_id={run_id}): {e}") from e



    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Belirtilen çalıştırma kimliğine ait üstverileri ve metrikleri getirir.

        Args:
            run_id: Benzersiz çalıştırma kimliği.

        Returns:
            dict[str, Any] | None: Bulunursa çalıştırma detayları, aksi halde None.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                cursor = conn.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,))
                row = cursor.fetchone()
                if row is None or cursor.description is None:
                    return None

                col_names = [desc[0] for desc in cursor.description]
                result = dict(zip(col_names, row, strict=False))

                if result.get("metrics_json"):
                    with contextlib.suppress(Exception):
                        result["metrics"] = orjson.loads(result["metrics_json"])
                if result.get("config_json"):
                    with contextlib.suppress(Exception):
                        result["config"] = orjson.loads(result["config_json"])
                return result
            except Exception as e:
                logger.error("Çalıştırma bilgisi getirilemedi: run_id=%s, hata=%s", run_id, e)
                return None

    def get_trades(self, run_id: str) -> list[dict[str, Any]]:
        """Belirtilen çalıştırmaya ait tüm işlemleri liste olarak getirir.

        Args:
            run_id: Benzersiz çalıştırma kimliği.

        Returns:
            list[dict[str, Any]]: İşlem sözlükleri listesi.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY id",
                    (run_id,),
                )
                rows = cursor.fetchall()
                if not rows or cursor.description is None:
                    return []

                col_names = [desc[0] for desc in cursor.description]
                return [dict(zip(col_names, r, strict=False)) for r in rows]
            except Exception as e:
                logger.error("İşlemler getirilemedi: run_id=%s, hata=%s", run_id, e)
                return []

    def get_trades_df(self, run_id: str) -> pl.DataFrame:
        """Belirtilen çalıştırmaya ait işlemleri doğrudan Polars DataFrame olarak döndürür.

        Args:
            run_id: Benzersiz çalıştırma kimliği.

        Returns:
            pl.DataFrame: İşlem verilerini içeren Polars DataFrame.
        """
        trades = self.get_trades(run_id)
        if pl is not None:
            return pl.DataFrame(trades) if trades else pl.DataFrame()
        logger.warning("Polars kütüphanesi bulunamadı, boş DataFrame yerine sözlük listesi kullanılmalı.")
        raise RuntimeError("Polars kütüphanesi ortamda yüklü değil.")

    def get_equity_curve(self, run_id: str) -> list[dict[str, Any]]:
        """Belirtilen çalıştırmaya ait özkaynak eğrisi noktalarını liste olarak getirir.

        Args:
            run_id: Benzersiz çalıştırma kimliği.

        Returns:
            list[dict[str, Any]]: Özkaynak eğrisi sözlükleri listesi.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM backtest_equity WHERE run_id = ? ORDER BY id",
                    (run_id,),
                )
                rows = cursor.fetchall()
                if not rows or cursor.description is None:
                    return []

                col_names = [desc[0] for desc in cursor.description]
                return [dict(zip(col_names, r, strict=False)) for r in rows]
            except Exception as e:
                logger.error("Özkaynak eğrisi getirilemedi: run_id=%s, hata=%s", run_id, e)
                return []

    def get_equity_curve_df(self, run_id: str) -> pl.DataFrame:
        """Belirtilen çalıştırmaya ait özkaynak eğrisini doğrudan Polars DataFrame olarak döndürür.

        Args:
            run_id: Benzersiz çalıştırma kimliği.

        Returns:
            pl.DataFrame: Özkaynak eğrisi verilerini içeren Polars DataFrame.
        """
        curve = self.get_equity_curve(run_id)
        if pl is not None:
            return pl.DataFrame(curve) if curve else pl.DataFrame()
        logger.warning("Polars kütüphanesi bulunamadı, boş DataFrame yerine sözlük listesi kullanılmalı.")
        raise RuntimeError("Polars kütüphanesi ortamda yüklü değil.")

    def list_runs(self, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
        """Kayıtlı en güncel çalıştırmaları tarihe göre azalan sırada listeler.

        Args:
            limit: Döndürülecek maksimum kayıt sayısı.

        Returns:
            list[dict[str, Any]]: Çalıştırma özetleri listesi.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                cursor = conn.execute(
                    "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                rows = cursor.fetchall()
                if not rows or cursor.description is None:
                    return []

                col_names = [desc[0] for desc in cursor.description]
                return [dict(zip(col_names, r, strict=False)) for r in rows]
            except Exception as e:
                logger.error("Çalıştırmalar listelenemedi: hata=%s", e)
                return []

    def delete_run(self, run_id: str) -> None:
        """Belirtilen çalıştırmaya ait tüm üstveri, işlem ve özkaynak kayıtlarını siler.

        Args:
            run_id: Benzersiz çalıştırma kimliği.

        Raises:
            RuntimeError: Silme işlemi başarısız olursa.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                conn.execute("DELETE FROM backtest_equity WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM backtest_runs WHERE run_id = ?", (run_id,))
                conn.commit()
                logger.info("Çalıştırma verileri başarıyla silindi: run_id=%s", run_id)
            except Exception as e:
                logger.error("Çalıştırma silinemedi: run_id=%s, hata=%s", run_id, e)
                raise RuntimeError(f"Çalıştırma silinemedi (run_id={run_id}): {e}") from e


    def health_check(self) -> dict[str, Any]:
        """DuckDB bağlantı ve tablo sağlığını kontrol eder.

        Returns:
            dict[str, Any]: Durum ve toplam kayıt istatistikleri.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                run_row = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()
                trade_row = conn.execute("SELECT COUNT(*) FROM backtest_trades").fetchone()
                equity_row = conn.execute("SELECT COUNT(*) FROM backtest_equity").fetchone()

                run_count = run_row[0] if run_row else 0
                trade_count = trade_row[0] if trade_row else 0
                equity_count = equity_row[0] if equity_row else 0

                return {
                    "status": "healthy",
                    "db_path": self._db_path,
                    "total_runs": run_count,
                    "total_trades": trade_count,
                    "total_equity_points": equity_count,
                }
            except Exception as e:
                logger.error("Sağlık kontrolü başarısız: hata=%s", e)
                return {"status": "error", "error": str(e), "db_path": self._db_path}


# Global Singleton Örneği
backtest_persistence = BacktestPersistence()
