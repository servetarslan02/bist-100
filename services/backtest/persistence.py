"""
ALPHA BIST — Backtest Persistence Layer v1.0

SQLite-based persistence for backtest results:
- Run metadata
- Trades
- Equity curve
- Performance metrics

Recovery: restart sonrası eksiksiz veri yükler.
"""

import orjson
import sqlite3
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path
import structlog

logger = structlog.get_logger()

DB_PATH = "data/backtest_results.db"


class BacktestPersistence:
    """Backtest sonuçlarını SQLite'a persist eder."""

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        """DB ve tabloları oluştur."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript("""
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
                );

                CREATE TABLE IF NOT EXISTS backtest_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    holding_days INTEGER,
                    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS backtest_equity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    equity REAL,
                    cash REAL,
                    market_value REAL,
                    positions INTEGER,
                    drawdown REAL,
                    daily_return REAL,
                    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_trades_run ON backtest_trades(run_id);
                CREATE INDEX IF NOT EXISTS idx_equity_run ON backtest_equity(run_id);
                CREATE INDEX IF NOT EXISTS idx_equity_date ON backtest_equity(run_id, date);
            """)
            conn.commit()
        finally:
            conn.close()

    def save_run(
        self,
        run_id: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        metrics: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Run metadata kaydet."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO backtest_runs
                   (run_id, start_date, end_date, initial_capital, final_equity,
                    total_return_pct, sharpe_ratio, max_drawdown_pct, total_trades,
                    config_json, metrics_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, start_date, end_date, initial_capital,
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
        finally:
            conn.close()

    def save_trades(self, run_id: str, trades: List[Dict[str, Any]]) -> None:
        """Trade'leri kaydet."""
        if not trades:
            return
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executemany(
                """INSERT INTO backtest_trades
                   (run_id, trade_id, ticker, side, date, quantity, price,
                    commission, slippage, pnl, pnl_pct, holding_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id, t.get("trade_id", 0), t.get("ticker", ""),
                        t.get("side", ""), t.get("date", ""),
                        t.get("quantity", 0), t.get("price", 0),
                        t.get("commission", 0), t.get("slippage", 0),
                        t.get("pnl", 0), t.get("pnl_pct", 0),
                        t.get("holding_days", 0),
                    )
                    for t in trades
                ],
            )
            conn.commit()
            logger.info("Trades saved", run_id=run_id, count=len(trades))
        finally:
            conn.close()

    def save_equity_curve(self, run_id: str, curve: List[Dict[str, Any]]) -> None:
        """Equity curve kaydet."""
        if not curve:
            return
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executemany(
                """INSERT INTO backtest_equity
                   (run_id, date, equity, cash, market_value, positions, drawdown, daily_return)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id, s.get("date", ""), s.get("equity", 0),
                        s.get("cash", 0), s.get("market_value", 0),
                        s.get("positions", 0), s.get("drawdown", 0),
                        s.get("daily_return", 0),
                    )
                    for s in curve
                ],
            )
            conn.commit()
            logger.info("Equity curve saved", run_id=run_id, points=len(curve))
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Run metadata getir."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row:
                result = dict(row)
                if result.get("metrics_json"):
                    result["metrics"] = orjson.loads(result["metrics_json"])
                if result.get("config_json"):
                    result["config"] = orjson.loads(result["config_json"])
                return result
            return None
        finally:
            conn.close()

    def get_trades(self, run_id: str) -> List[Dict[str, Any]]:
        """Trade'leri getir."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_equity_curve(self, run_id: str) -> List[Dict[str, Any]]:
        """Equity curve getir."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM backtest_equity WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Son run'ları listele."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_run(self, run_id: str) -> None:
        """Run ve ilgili verileri sil."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM backtest_equity WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM backtest_runs WHERE run_id = ?", (run_id,))
            conn.commit()
            logger.info("Run deleted", run_id=run_id)
        finally:
            conn.close()


# Singleton
backtest_persistence = BacktestPersistence()
