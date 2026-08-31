"""
ALPHA BIST — Paper Trading State Store v2.0

Persistent state yönetimi: DuckDB.
- Portföy durumu, pozisyonlar, işlemler, equity curve, audit log
- Program kapanıp açılsa bile veri kaybolmaz
- Atomic write & DuckDB sütunsal OLAP persistence
- Backup/rollback desteği
"""

import os
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:
    duckdb = None
import orjson
import structlog

logger = structlog.get_logger()


class PaperStateStore:
    """DuckDB tabanlı persistent state store — paper trading için."""

    def __init__(self, db_path: str = "data/paper_trading_state.db"):
        """Otomatik eklendi."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_buffer: list[tuple[str, tuple]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_size = 20  # Batch size
        self._last_flush = time.time()
        self._flush_interval = 30.0  # saniye
        self._periodic_thread: threading.Thread | None = None
        self._stop_periodic = threading.Event()
        if duckdb is not None:
            self._init_db()
            logger.info("PaperStateStore initialized", db_path=str(self.db_path))
        else:
            logger.warning("PaperStateStore initialized without persistence (duckdb not installed)")
        self._start_periodic_flush()

    def _init_db(self) -> Any:
        """SQLite tablolarini olustur."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    date TEXT NOT NULL,
                    cash REAL NOT NULL,
                    initial_capital REAL NOT NULL,
                    last_updated TEXT NOT NULL,
                    json_data TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    ticker TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    avg_cost REAL NOT NULL,
                    current_price REAL NOT NULL,
                    sector TEXT,
                    entry_date TEXT,
                    last_update TEXT NOT NULL,
                    json_data TEXT NOT NULL
                )
            """)
            conn.execute("""
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
                )
            """)
            conn.execute("""
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
                )
            """)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS audit_log_seq START 1
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id INTEGER DEFAULT nextval('audit_log_seq') PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    date TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    ticker TEXT,
                    json_data TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                )
            """)
            conn.execute("""
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
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_curve (
                    date TEXT PRIMARY KEY,
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    invested REAL NOT NULL,
                    benchmark_equity REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
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
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_log(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log(entry_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_signals_date ON pending_signals(date)")
            conn.commit()

    @contextmanager
    def _connect(self) -> Any:
        """Otomatik eklendi."""
        if duckdb is None:
            raise RuntimeError("DuckDB module is not installed in the environment.")

        conn = None
        for attempt in range(5):
            try:
                conn = duckdb.connect(str(self.db_path))
                break
            except Exception as e:
                if "lock" in str(e).lower() and attempt < 4:
                    time.sleep(0.3 * (attempt + 1))
                else:
                    raise

        # SSD write reduction: DuckDB WAL ayarları
        if conn is not None and hasattr(conn, "execute"):
            try:
                from services.core.debounce import configure_duckdb_wal
                configure_duckdb_wal(conn)
            except Exception:
                pass

        try:
            yield conn
        finally:
            if conn is not None:
                conn.close()

    def _buffered_write(self, query: str, params: tuple) -> Any:
        """Buffered write — toplu yaz (SSD dostu)."""
        with self._buffer_lock:
            self._write_buffer.append((query, params))
            should_flush = len(self._write_buffer) >= self._buffer_size
        if should_flush:
            self._flush_buffer()

    def _flush_buffer(self) -> Any:
        """Write buffer'ı flush et (batched write — SSD dostu)."""
        with self._buffer_lock:
            if not self._write_buffer:
                return
            batch = self._write_buffer.copy()
            self._write_buffer.clear()
        try:
            with self._connect() as conn:
                for query, params in batch:
                    conn.execute(query, params)
                conn.commit()
            self._last_flush = time.time()
        except Exception as e:
            logger.error("Paper state buffer flush error", error=str(e))
            with self._buffer_lock:
                self._write_buffer = batch + self._write_buffer  # Re-queue on failure

    def _start_periodic_flush(self) -> None:
        """Arka planda periyodik flush başlat."""
        def _loop() -> None:
            while not self._stop_periodic.wait(self._flush_interval):
                try:
                    self.periodic_flush()
                except Exception as e:
                    logger.debug("Paper state periodic flush error", error=str(e))
        self._periodic_thread = threading.Thread(target=_loop, daemon=True, name="paper-periodic-flush")
        self._periodic_thread.start()

    def periodic_flush(self) -> Any:
        """Periyodik flush (scheduler tarafından çağrılır)."""
        if time.time() - self._last_flush > self._flush_interval:
            self._flush_buffer()

    def flush(self) -> Any:
        """Manuel flush."""
        self._flush_buffer()

    # ===================== PORTFOLIO STATE =====================

    def save_portfolio_state(self, state: dict[str, Any]) -> Any:
        """Portfoy durumunu kaydet (buffered — SSD dostu)."""
        state_json = orjson.dumps(state, default=str).decode()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO portfolio_state (id, date, cash, initial_capital, last_updated, json_data)
            VALUES (1, ?, ?, ?, ?, ?)
        """,
            (
                state["date"],
                state["cash"],
                state["initial_capital"],
                state.get("last_updated", datetime.now(UTC).isoformat()),
                state_json,
            ),
        )

    def load_portfolio_state(self) -> dict[str, Any] | None:
        """Portfoy durumunu yukle."""
        if duckdb is None:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT json_data FROM portfolio_state WHERE id = 1").fetchone()
            if row:
                raw = row[0] if isinstance(row, (tuple, list)) else row["json_data"]
                return orjson.loads(raw)
            return None

    # ===================== POSITIONS =====================

    def save_positions(self, positions: list[dict[str, Any]]) -> Any:
        """Pozisyonlari kaydet (buffered — SSD dostu)."""
        self._buffered_write("DELETE FROM positions", ())
        for pos in positions:
            self._buffered_write(
                """
                INSERT OR REPLACE INTO positions (ticker, quantity, avg_cost, current_price, sector, entry_date, last_update, json_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    pos["ticker"],
                    pos["quantity"],
                    pos["avg_cost"],
                    pos.get("current_price", pos["avg_cost"]),
                    pos.get("sector", ""),
                    pos.get("entry_date", ""),
                    pos.get("last_update", ""),
                    orjson.dumps(pos).decode(),
                ),
            )

    def load_positions(self) -> list[dict[str, Any]]:
        """Pozisyonlari yukle."""
        with self._connect() as conn:
            rows = conn.execute("SELECT json_data FROM positions").fetchall()
            return [orjson.loads(r[0] if isinstance(r, (tuple, list)) else r["json_data"]) for r in rows]

    # ===================== TRADES =====================

    def save_trade(self, trade: dict[str, Any]) -> Any:
        """Trade kaydet (buffered — SSD dostu)."""
        self._buffered_write(
            """
            INSERT OR REPLACE INTO trades (trade_id, date, ticker, side, quantity, entry_price, exit_price, realized_pnl, commission, reason, json_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                trade["trade_id"],
                trade["exit_date"],
                trade["ticker"],
                trade["side"],
                trade["quantity"],
                trade["entry_price"],
                trade["exit_price"],
                trade["realized_pnl"],
                trade["commission"],
                trade.get("reason", ""),
                orjson.dumps(trade).decode(),
            ),
        )

    def load_trades(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Trade'leri yukle."""
        with self._connect() as conn:
            sql = "SELECT json_data FROM trades ORDER BY date DESC"
            if limit:
                sql += f" LIMIT {limit}"
            rows = conn.execute(sql).fetchall()
            return [orjson.loads(r[0] if isinstance(r, (tuple, list)) else r["json_data"]) for r in rows]

    # ===================== ORDERS =====================

    def save_order(self, order: dict[str, Any]) -> Any:
        """Order kaydet (buffered — SSD dostu)."""
        self._buffered_write(
            """
            INSERT OR REPLACE INTO orders (order_id, date, ticker, side, quantity, signal_price, execution_price, commission, slippage_pct, status, rejection_reason, json_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                order["order_id"],
                order["date"],
                order["ticker"],
                order["side"],
                order["quantity"],
                order["signal_price"],
                order.get("execution_price", 0),
                order.get("commission", 0),
                order.get("slippage_pct", 0),
                order["status"],
                order.get("rejection_reason"),
                orjson.dumps(order).decode(),
            ),
        )

    def load_orders(self, date: str | None = None) -> list[dict[str, Any]]:
        """Order'lari yukle."""
        with self._connect() as conn:
            if date:
                rows = conn.execute(
                    "SELECT json_data FROM orders WHERE date = ? ORDER BY date DESC", (date,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT json_data FROM orders ORDER BY date DESC").fetchall()
            return [orjson.loads(r[0] if isinstance(r, (tuple, list)) else r["json_data"]) for r in rows]

    # ===================== AUDIT LOG =====================

    def append_audit(self, entry: dict[str, Any]) -> Any:
        """Audit entry ekle (immutable, append-only, buffered — SSD dostu)."""
        entry_hash = self._compute_hash(entry)
        self._buffered_write(
            """
            INSERT INTO audit_log (timestamp, date, entry_type, ticker, json_data, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                entry["timestamp"],
                entry["date"],
                entry["entry_type"],
                entry.get("ticker"),
                orjson.dumps(entry, default=str).decode(),
                entry_hash,
            ),
        )

    def load_audit_log(
        self, date: str | None = None, entry_type: str | None = None, limit: int = 1000
    ) -> list[dict[str, Any]]:
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
            return [orjson.loads(r[0] if isinstance(r, (tuple, list)) else r["json_data"]) for r in rows]

    # ===================== DAILY PERFORMANCE =====================

    def save_daily_performance(self, perf: dict[str, Any]) -> Any:
        """Gunluk performans kaydet (buffered — SSD dostu)."""
        self._buffered_write(
            """
            INSERT OR REPLACE INTO daily_performance
            (date, portfolio_value, cash, daily_return_pct, cumulative_return_pct, max_drawdown_pct, benchmark_return_pct, alpha_pct, turnover, transaction_cost, num_positions, num_trades, json_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                perf["date"],
                perf["portfolio_value"],
                perf["cash"],
                perf["daily_return_pct"],
                perf["cumulative_return_pct"],
                perf["max_drawdown_pct"],
                perf["benchmark_return_pct"],
                perf["alpha_pct"],
                perf["turnover"],
                perf["transaction_cost"],
                perf["num_positions"],
                perf["num_trades"],
                orjson.dumps(perf).decode(),
            ),
        )

    def load_daily_performance(self) -> list[dict[str, Any]]:
        """Gunluk performanslari yukle."""
        with self._connect() as conn:
            rows = conn.execute("SELECT json_data FROM daily_performance ORDER BY date ASC").fetchall()
            return [orjson.loads(r[0] if isinstance(r, (tuple, list)) else r["json_data"]) for r in rows]

    # ===================== EQUITY CURVE =====================

    def save_equity_point(
        self, date: str, equity: float, cash: float, invested: float, benchmark_equity: float | None = None
    ) -> Any:
        """Equity curve noktasi kaydet (buffered — SSD dostu)."""
        self._buffered_write(
            """
            INSERT OR REPLACE INTO equity_curve (date, equity, cash, invested, benchmark_equity)
            VALUES (?, ?, ?, ?, ?)
        """,
            (date, equity, cash, invested, benchmark_equity),
        )

    def load_equity_curve(self) -> list[dict[str, Any]]:
        """Equity curve'u yukle."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, equity, cash, invested, benchmark_equity FROM equity_curve ORDER BY date ASC"
            ).fetchall()
            return [
                {
                    "date": r[0] if isinstance(r, (tuple, list)) else r["date"],
                    "equity": r[1] if isinstance(r, (tuple, list)) else r["equity"],
                    "cash": r[2] if isinstance(r, (tuple, list)) else r["cash"],
                    "invested": r[3] if isinstance(r, (tuple, list)) else r["invested"],
                    "benchmark_equity": r[4] if isinstance(r, (tuple, list)) else r["benchmark_equity"],
                }
                for r in rows
            ]

    # ===================== PENDING SIGNALS =====================

    def save_pending_signals(self, signals: list[dict[str, Any]], date: str) -> Any:
        """EOD (18:15) anında üretilen sinyalleri sabah seans açılışında yürütülmek üzere kaydeder (buffered — SSD dostu)."""
        self._buffered_write("DELETE FROM pending_signals", ())
        now_iso = datetime.now(UTC).isoformat()
        expires_dt = datetime.now(UTC) + timedelta(days=1)
        expires_iso = expires_dt.isoformat()
        for idx, sig in enumerate(signals):
            sig_id = f"SIG_{date}_{sig.get('ticker', 'UNKNOWN')}_{idx}"
            self._buffered_write(
                """
                INSERT OR REPLACE INTO pending_signals (
                    signal_id, date, ticker, direction, rank, score, confidence,
                    model_version, target_weight, json_data, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
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
                    expires_iso,
                ),
            )
        logger.info(
            "Saved pending signals for next session execution", count=len(signals), date=date, expires=expires_iso
        )

    def load_pending_signals(self) -> list[dict[str, Any]]:
        """Bekleyen sinyalleri yukle (süresi dolmuş olanlar hariç)."""
        with self._connect() as conn:
            now_iso = datetime.now(UTC).isoformat()
            rows = conn.execute(
                "SELECT json_data FROM pending_signals WHERE expires_at > ? ORDER BY rank ASC", (now_iso,)
            ).fetchall()
            return [orjson.loads(r[0] if isinstance(r, (tuple, list)) else r["json_data"]) for r in rows]

    def clear_stale_pending_signals(self, max_age_days: int = 1) -> int:
        """Süresi dolmuş bekleyen sinyalleri temizler (buffered — SSD dostu)."""
        now_iso = datetime.now(UTC).isoformat()
        self._buffered_write("DELETE FROM pending_signals WHERE expires_at <= ?", (now_iso,))
        return 0  # Actual count unknown until flush

    def clear_pending_signals(self) -> Any:
        """Yurutulen bekleyen sinyalleri temizle (buffered — SSD dostu)."""
        self._buffered_write("DELETE FROM pending_signals", ())

    # ===================== CONFIG =====================

    def set_config(self, key: str, value: str) -> Any:
        """Otomatik eklendi (buffered — SSD dostu)."""
        self._buffered_write(
            """
            INSERT OR REPLACE INTO config (key, value, updated_at)
            VALUES (?, ?, ?)
        """,
            (key, value, datetime.now(UTC).isoformat()),
        )

    def get_config(self, key: str, default: str | None = None) -> str | None:
        """Otomatik eklendi."""
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            return row[0] if isinstance(row, (tuple, list)) else row["value"]

    # ===================== BACKUP / RESET =====================

    def backup(self, backup_path: str | None = None) -> str:
        """DB'yi yedekle."""
        if backup_path is None:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            backup_path = str(self.db_path).replace(".db", f"_backup_{ts}.db")
        shutil.copy2(str(self.db_path), backup_path)
        logger.info("PaperStateStore backup created", path=backup_path)
        return backup_path

    def reset_all(self) -> Any:
        """Tum state'i sifirla (DANGER — buffered)."""
        for table in ["portfolio_state", "positions", "trades", "orders", "audit_log", "daily_performance", "equity_curve", "config"]:
            self._buffered_write(f"DELETE FROM {table}", ())
        self._flush_buffer()  # Immediate flush for reset
        logger.warning("PaperStateStore RESET — all data cleared")

    @staticmethod
    def _compute_hash(entry: dict[str, Any]) -> str:
        """Otomatik eklendi."""
        import hashlib

        data = orjson.dumps(entry, option=orjson.OPT_SORT_KEYS, default=str).decode()
        return hashlib.sha256(data.encode()).hexdigest()[:16]


# Singleton
paper_state_store = PaperStateStore()

# Graceful shutdown: buffer'ı flush et
import atexit
import signal as _signal

def _flush_paper_on_exit() -> None:
    try:
        paper_state_store.flush()
    except Exception:
        logger.warning("Paper state flush on exit failed", exc_info=True)

def _flush_paper_on_signal(signum, frame) -> None:
    try:
        paper_state_store.flush()
    except Exception:
        logger.warning("Paper state flush on signal failed", exc_info=True)

atexit.register(_flush_paper_on_exit)
try:
    _signal.signal(_signal.SIGTERM, _flush_paper_on_signal)
    _signal.signal(_signal.SIGINT, _flush_paper_on_signal)
except (ValueError, OSError):
    pass
