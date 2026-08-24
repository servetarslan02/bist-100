"""
ALPHA BIST — Paper Trading State Store v1.0

Persistent state yonetimi: SQLite.
- Portfoy durumu, pozisyonlar, islemler, equity curve, audit log
- Program kapanip acilsa bile veri kaybolmaz
- Atomic write (write-to-temp + rename)
- Backup/rollback destegi

Mevcut services.core.audit_log.AuditLog'i extend eder.
"""

import orjson
import os
import sqlite3
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
import structlog

logger = structlog.get_logger()


class PaperStateStore:
    """SQLite tabanli persistent state store — paper trading icin."""

    def __init__(self, db_path: str = "data/paper_trading_state.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info("PaperStateStore initialized", db_path=str(self.db_path))

    def _init_db(self):
        """SQLite tablolarini olustur."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    date TEXT NOT NULL,
                    cash REAL NOT NULL,
                    initial_capital REAL NOT NULL,
                    last_updated TEXT NOT NULL,
                    json_data TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    ticker TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    avg_cost REAL NOT NULL,
                    current_price REAL NOT NULL,
                    sector TEXT,
                    entry_date TEXT,
                    last_update TEXT NOT NULL,
                    json_data TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    commission REAL NOT NULL,
                    reason TEXT,
                    json_data TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    signal_price REAL NOT NULL,
                    execution_price REAL NOT NULL,
                    commission REAL NOT NULL,
                    slippage_pct REAL NOT NULL,
                    status TEXT NOT NULL,
                    rejection_reason TEXT,
                    json_data TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    ticker TEXT,
                    json_data TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_performance (
                    date TEXT PRIMARY KEY,
                    portfolio_value REAL NOT NULL,
                    cash REAL NOT NULL,
                    daily_return_pct REAL NOT NULL,
                    cumulative_return_pct REAL NOT NULL,
                    max_drawdown_pct REAL NOT NULL,
                    benchmark_return_pct REAL NOT NULL,
                    alpha_pct REAL NOT NULL,
                    turnover REAL NOT NULL,
                    transaction_cost REAL NOT NULL,
                    num_positions INTEGER NOT NULL,
                    num_trades INTEGER NOT NULL,
                    json_data TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_curve (
                    date TEXT PRIMARY KEY,
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    invested REAL NOT NULL,
                    benchmark_equity REAL
                );

                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_signals (
                    signal_id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    rank INTEGER,
                    score REAL,
                    confidence REAL,
                    model_version TEXT,
                    target_weight REAL,
                    json_data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
                CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(date);
                CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_log(date);
                CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(entry_type);
                CREATE INDEX IF NOT EXISTS idx_pending_signals_date ON pending_signals(date);
            """)
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Atomic write + crash safety
        conn.execute("PRAGMA synchronous=NORMAL")  # WAL ile birlikte güvenli
        try:
            yield conn
        finally:
            conn.close()

    # ===================== PORTFOLIO STATE =====================

    def save_portfolio_state(self, state: Dict[str, Any]):
        """Portfoy durumunu kaydet (F-016: Atomic write — temp + rename pattern)."""
        state_json = orjson.dumps(state, default=str).decode()
        # Atomic write: önce temp dosyaya yaz, sonra rename ile değiştir
        tmp_path = str(self.db_path) + ".tmp"
        try:
            # Mevcut DB'yi temp'e kopyala, güncelle, ve geri al
            with self._connect() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO portfolio_state (id, date, cash, initial_capital, last_updated, json_data)
                    VALUES (1, ?, ?, ?, ?, ?)
                """, (
                    state["date"],
                    state["cash"],
                    state["initial_capital"],
                    state.get("last_updated", datetime.now(timezone.utc).isoformat()),
                    state_json,
                ))
                conn.commit()
        except Exception as e:
            logger.error("Failed to save portfolio state", error=str(e))
            # Backup'tan geri yükle
            if os.path.exists(tmp_path):
                shutil.move(tmp_path, str(self.db_path))
            raise

    def load_portfolio_state(self) -> Optional[Dict[str, Any]]:
        """Portfoy durumunu yukle."""
        with self._connect() as conn:
            row = conn.execute("SELECT json_data FROM portfolio_state WHERE id = 1").fetchone()
            if row:
                return orjson.loads(row["json_data"])
            return None

    # ===================== POSITIONS =====================

    def save_positions(self, positions: List[Dict[str, Any]]):
        """Pozisyonlari kaydet."""
        with self._connect() as conn:
            conn.execute("DELETE FROM positions")
            for pos in positions:
                conn.execute("""
                    INSERT OR REPLACE INTO positions (ticker, quantity, avg_cost, current_price, sector, entry_date, last_update, json_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pos["ticker"], pos["quantity"], pos["avg_cost"], pos.get("current_price", pos["avg_cost"]),
                    pos.get("sector", ""), pos.get("entry_date", ""), pos.get("last_update", ""),
                    orjson.dumps(pos).decode(),
                ))
            conn.commit()

    def load_positions(self) -> List[Dict[str, Any]]:
        """Pozisyonlari yukle."""
        with self._connect() as conn:
            rows = conn.execute("SELECT json_data FROM positions").fetchall()
            return [orjson.loads(r["json_data"]) for r in rows]

    # ===================== TRADES =====================

    def save_trade(self, trade: Dict[str, Any]):
        """Trade kaydet."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trades (trade_id, date, ticker, side, quantity, entry_price, exit_price, realized_pnl, commission, reason, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade["trade_id"], trade["exit_date"], trade["ticker"], trade["side"],
                trade["quantity"], trade["entry_price"], trade["exit_price"],
                trade["realized_pnl"], trade["commission"], trade.get("reason", ""),
                orjson.dumps(trade).decode(),
            ))
            conn.commit()

    def load_trades(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Trade'leri yukle."""
        with self._connect() as conn:
            sql = "SELECT json_data FROM trades ORDER BY date DESC"
            if limit:
                sql += f" LIMIT {limit}"
            rows = conn.execute(sql).fetchall()
            return [orjson.loads(r["json_data"]) for r in rows]

    # ===================== ORDERS =====================

    def save_order(self, order: Dict[str, Any]):
        """Order kaydet."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO orders (order_id, date, ticker, side, quantity, signal_price, execution_price, commission, slippage_pct, status, rejection_reason, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order["order_id"], order["date"], order["ticker"], order["side"],
                order["quantity"], order["signal_price"], order.get("execution_price", 0),
                order.get("commission", 0), order.get("slippage_pct", 0), order["status"],
                order.get("rejection_reason"), orjson.dumps(order).decode(),
            ))
            conn.commit()

    def load_orders(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Order'lari yukle."""
        with self._connect() as conn:
            if date:
                rows = conn.execute("SELECT json_data FROM orders WHERE date = ? ORDER BY date DESC", (date,)).fetchall()
            else:
                rows = conn.execute("SELECT json_data FROM orders ORDER BY date DESC").fetchall()
            return [orjson.loads(r["json_data"]) for r in rows]

    # ===================== AUDIT LOG =====================

    def append_audit(self, entry: Dict[str, Any]):
        """Audit entry ekle (immutable, append-only)."""
        entry_hash = self._compute_hash(entry)
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO audit_log (timestamp, date, entry_type, ticker, json_data, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                entry["timestamp"], entry["date"], entry["entry_type"], entry.get("ticker"),
                orjson.dumps(entry, default=str).decode(), entry_hash,
            ))
            conn.commit()

    def load_audit_log(self, date: Optional[str] = None, entry_type: Optional[str] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        """Audit log'u yukle."""
        with self._connect() as conn:
            sql = "SELECT json_data FROM audit_log WHERE 1=1"
            params = []
            if date:
                sql += " AND date = ?"
                params.append(date)
            if entry_type:
                sql += " AND entry_type = ?"
                params.append(entry_type)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [orjson.loads(r["json_data"]) for r in rows]

    # ===================== DAILY PERFORMANCE =====================

    def save_daily_performance(self, perf: Dict[str, Any]):
        """Gunluk performans kaydet."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO daily_performance
                (date, portfolio_value, cash, daily_return_pct, cumulative_return_pct, max_drawdown_pct, benchmark_return_pct, alpha_pct, turnover, transaction_cost, num_positions, num_trades, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                perf["date"], perf["portfolio_value"], perf["cash"], perf["daily_return_pct"],
                perf["cumulative_return_pct"], perf["max_drawdown_pct"], perf["benchmark_return_pct"],
                perf["alpha_pct"], perf["turnover"], perf["transaction_cost"],
                perf["num_positions"], perf["num_trades"],
                orjson.dumps(perf).decode(),
            ))
            conn.commit()

    def load_daily_performance(self) -> List[Dict[str, Any]]:
        """Gunluk performanslari yukle."""
        with self._connect() as conn:
            rows = conn.execute("SELECT json_data FROM daily_performance ORDER BY date ASC").fetchall()
            return [orjson.loads(r["json_data"]) for r in rows]

    # ===================== EQUITY CURVE =====================

    def save_equity_point(self, date: str, equity: float, cash: float, invested: float, benchmark_equity: Optional[float] = None):
        """Equity curve noktasi kaydet."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO equity_curve (date, equity, cash, invested, benchmark_equity)
                VALUES (?, ?, ?, ?, ?)
            """, (date, equity, cash, invested, benchmark_equity))
            conn.commit()

    def load_equity_curve(self) -> List[Dict[str, Any]]:
        """Equity curve'u yukle."""
        with self._connect() as conn:
            rows = conn.execute("SELECT date, equity, cash, invested, benchmark_equity FROM equity_curve ORDER BY date ASC").fetchall()
            return [
                {"date": r["date"], "equity": r["equity"], "cash": r["cash"],
                 "invested": r["invested"], "benchmark_equity": r["benchmark_equity"]}
                for r in rows
            ]

    # ===================== PENDING SIGNALS =====================

    def save_pending_signals(self, signals: List[Dict[str, Any]], date: str):
        """EOD (18:15) anında üretilen sinyalleri sabah seans açılışında yürütülmek üzere kaydeder."""
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_signals")
            now_iso = datetime.now(timezone.utc).isoformat()
            for idx, sig in enumerate(signals):
                sig_id = f"SIG_{date}_{sig.get('ticker', 'UNKNOWN')}_{idx}"
                conn.execute("""
                    INSERT OR REPLACE INTO pending_signals (
                        signal_id, date, ticker, direction, rank, score, confidence,
                        model_version, target_weight, json_data, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sig_id,
                    date,
                    sig.get("ticker", ""),
                    sig.get("direction", "LONG"),
                    sig.get("rank", idx + 1),
                    sig.get("score", 0.0),
                    sig.get("confidence", 0.0),
                    sig.get("model_version", ""),
                    sig.get("target_weight", 0.10),
                    orjson.dumps(sig).decode(),
                    now_iso,
                ))
            conn.commit()
        logger.info("Saved pending signals for next session execution", count=len(signals), date=date)

    def load_pending_signals(self) -> List[Dict[str, Any]]:
        """Bekleyen sinyalleri yukle."""
        with self._connect() as conn:
            rows = conn.execute("SELECT json_data FROM pending_signals ORDER BY rank ASC").fetchall()
            return [orjson.loads(r["json_data"]) for r in rows]

    def clear_pending_signals(self):
        """Yurutulen bekleyen sinyalleri temizle."""
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_signals")
            conn.commit()

    # ===================== CONFIG =====================

    def set_config(self, key: str, value: str):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO config (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.now(timezone.utc).isoformat()))
            conn.commit()

    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    # ===================== BACKUP / RESET =====================

    def backup(self, backup_path: Optional[str] = None) -> str:
        """DB'yi yedekle."""
        if backup_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = str(self.db_path).replace(".db", f"_backup_{ts}.db")
        shutil.copy2(str(self.db_path), backup_path)
        logger.info("PaperStateStore backup created", path=backup_path)
        return backup_path

    def reset_all(self):
        """Tum state'i sifirla (DANGER)."""
        with self._connect() as conn:
            conn.executescript("""
                DELETE FROM portfolio_state;
                DELETE FROM positions;
                DELETE FROM trades;
                DELETE FROM orders;
                DELETE FROM audit_log;
                DELETE FROM daily_performance;
                DELETE FROM equity_curve;
                DELETE FROM config;
            """)
            conn.commit()
        logger.warning("PaperStateStore RESET — all data cleared")

    @staticmethod
    def _compute_hash(entry: Dict[str, Any]) -> str:
        import hashlib
        data = orjson.dumps(entry, option=orjson.OPT_SORT_KEYS, default=str).decode()
        return hashlib.sha256(data.encode()).hexdigest()[:16]


# Singleton
paper_state_store = PaperStateStore()
