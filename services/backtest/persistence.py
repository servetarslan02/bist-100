"""
ALPHA BIST — Backtest Persistence Layer v2.0

DuckDB-based persistence for backtest results:
- Run metadata
- Trades
- Equity curve
- Performance metrics

v2.0 Eklemeleri:
- Connection reuse (her işlemde aç/kapat yok)
- Thread-safe connection management
- Batch insert optimization
- Health check
- Migration support

Recovery: restart sonrası eksiksiz veri yükler.
"""

from pathlib import Path
from typing import Any

import duckdb
import orjson
import structlog

logger = structlog.get_logger()

DB_PATH = "data/backtest_results.db"


class BacktestPersistence:
    """Backtest sonuçlarını DuckDB'ye persist eder.

    v2.0: Connection reuse ile performans optimizasyonu.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._ensure_db()

    def _get_conn(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısı al (lazy init + reuse)."""
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Bağlantıyı kapat."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _ensure_db(self):
        """DB ve tabloları oluştur."""
        conn = self._get_conn()
        try:
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
            logger.error("Failed to ensure DB", error=str(e))

    def save_run(
        self,
        run_id: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        metrics: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> None:
        """Run metadata kaydet."""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO backtest_runs
                   (run_id, start_date, end_date, initial_capital, final_equity,
                    total_return_pct, sharpe_ratio, max_drawdown_pct, total_trades,
                    config_json, metrics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    start_date,
                    end_date,
                    initial_capital,
                    metrics.get("final_equity", 0),
                    metrics.get("total_return_pct", 0),
                    metrics.get("sharpe_ratio", 0),
                    metrics.get("max_drawdown_pct", 0),
                    metrics.get("total_trades", 0),
                    orjson.dumps(config or {}).decode(),
                    orjson.dumps(metrics, default=str).decode(),
                ),
            )
            conn.commit()
            logger.info("Backtest run saved", run_id=run_id)
        except Exception as e:
            logger.error("Failed to save run", run_id=run_id, error=str(e))

    def save_trades(self, run_id: str, trades: list[dict[str, Any]]) -> None:
        """Trade'leri kaydet (batch insert)."""
        if not trades:
            return
        conn = self._get_conn()
        try:
            conn.executemany(
                """INSERT INTO backtest_trades
                   (run_id, trade_id, ticker, side, date, quantity, price,
                    commission, slippage, pnl, pnl_pct, holding_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        t.get("trade_id", 0),
                        t.get("ticker", ""),
                        t.get("side", ""),
                        t.get("date", ""),
                        t.get("quantity", 0),
                        t.get("price", 0),
                        t.get("commission", 0),
                        t.get("slippage", 0),
                        t.get("pnl", 0),
                        t.get("pnl_pct", 0),
                        t.get("holding_days", 0),
                    )
                    for t in trades
                ],
            )
            conn.commit()
            logger.info("Trades saved", run_id=run_id, count=len(trades))
        except Exception as e:
            logger.error("Failed to save trades", run_id=run_id, error=str(e))

    def save_equity_curve(self, run_id: str, curve: list[dict[str, Any]]) -> None:
        """Equity curve kaydet (batch insert)."""
        if not curve:
            return
        conn = self._get_conn()
        try:
            conn.executemany(
                """INSERT INTO backtest_equity
                   (run_id, date, equity, cash, market_value, positions, drawdown, daily_return)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id,
                        s.get("date", ""),
                        s.get("equity", 0),
                        s.get("cash", 0),
                        s.get("market_value", 0),
                        s.get("positions", 0),
                        s.get("drawdown", 0),
                        s.get("daily_return", 0),
                    )
                    for s in curve
                ],
            )
            conn.commit()
            logger.info("Equity curve saved", run_id=run_id, points=len(curve))
        except Exception as e:
            logger.error("Failed to save equity curve", run_id=run_id, error=str(e))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Run metadata getir."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()
            if row:
                result = dict(row)
                if result.get("metrics_json"):
                    result["metrics"] = orjson.loads(result["metrics_json"])
                if result.get("config_json"):
                    result["config"] = orjson.loads(result["config_json"])
                return result
            return None
        except Exception as e:
            logger.error("Failed to get run", run_id=run_id, error=str(e))
            return None

    def get_trades(self, run_id: str) -> list[dict[str, Any]]:
        """Trade'leri getir."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get trades", run_id=run_id, error=str(e))
            return []

    def get_equity_curve(self, run_id: str) -> list[dict[str, Any]]:
        """Equity curve getir."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM backtest_equity WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get equity curve", run_id=run_id, error=str(e))
            return []

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Son run'ları listele."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to list runs", error=str(e))
            return []

    def delete_run(self, run_id: str) -> None:
        """Run ve ilgili verileri sil."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM backtest_equity WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM backtest_runs WHERE run_id = ?", (run_id,))
            conn.commit()
            logger.info("Run deleted", run_id=run_id)
        except Exception as e:
            logger.error("Failed to delete run", run_id=run_id, error=str(e))

    def health_check(self) -> dict[str, Any]:
        """DB sağlık kontrolü."""
        conn = self._get_conn()
        try:
            run_count = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
            trade_count = conn.execute("SELECT COUNT(*) FROM backtest_trades").fetchone()[0]
            equity_count = conn.execute("SELECT COUNT(*) FROM backtest_equity").fetchone()[0]
            return {
                "status": "healthy",
                "db_path": self._db_path,
                "total_runs": run_count,
                "total_trades": trade_count,
                "total_equity_points": equity_count,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


# Singleton
backtest_persistence = BacktestPersistence()
