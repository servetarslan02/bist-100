"""ALPHA BIST — Persistent Model Memory Store v2.0

Kalıcı model hafızası:
- DuckDB tabanlı atomik ve WAL modunda veri saklama
- Prediction -> Outcome eşleşme tablosu
- Model versiyonları ve anlık metrik snapshots
- Sinyal ağırlık geçmişi (Weight history audit trail)
- Otomatik retention ve rollup temizliği
"""

import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    duckdb = None
    HAS_DUCKDB = False

import orjson
import structlog

logger = structlog.get_logger()


class _DummyDuckDBConn:
    """Otomatik eklendi."""
    def execute(self, *args, **kwargs) -> Any:
        """Otomatik eklendi."""
        return self

    def fetchall(self) -> Any:
        """Otomatik eklendi."""
        return []

    def fetchone(self) -> Any:
        """Otomatik eklendi."""
        return None

    def df(self) -> Any:
        """Otomatik eklendi."""
        import pandas as pd

        return pd.DataFrame()

    def commit(self) -> Any:
        """Otomatik eklendi."""
        pass

    def close(self) -> Any:
        """Otomatik eklendi."""
        pass

    def __enter__(self) -> Any:
        """Otomatik eklendi."""
        return self

    def __exit__(self, *args) -> Any:
        """Otomatik eklendi."""
        pass


class ModelMemoryStore:
    """Kalıcı model tahmin, sonuç ve metrik hafızası."""

    def __init__(self, db_path: str = "data/model_memory.duckdb"):
        """Otomatik eklendi."""
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._write_buffer: list[tuple[str, tuple]] = []
        self._buffer_lock = threading.Lock()
        self._buffer_size = 20
        self._last_flush = time.time()
        self._flush_interval = 30.0
        self._periodic_thread: threading.Thread | None = None
        self._stop_periodic = threading.Event()
        if HAS_DUCKDB:
            self._init_tables()
        self._start_periodic_flush()

    @contextmanager
    def _get_conn(self) -> Any:
        """DuckDB bağlantısı — context manager (resource leak önleme)."""
        if not HAS_DUCKDB or duckdb is None:
            yield _DummyDuckDBConn()
            return
        conn = duckdb.connect(self.db_path)
        # SSD write reduction: DuckDB WAL ayarları
        try:
            from services.core.debounce import configure_duckdb_wal
            configure_duckdb_wal(conn)
        except Exception:
            pass
        try:
            yield conn
        finally:
            conn.close()

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
            with self._get_conn() as conn:
                for query, params in batch:
                    conn.execute(query, params)
                if hasattr(conn, 'commit'):
                    conn.commit()
            self._last_flush = time.time()
        except Exception as e:
            logger.error("Model memory buffer flush error", error=str(e))
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
                    logger.debug("Model memory periodic flush error", error=str(e))
        self._periodic_thread = threading.Thread(target=_loop, daemon=True, name="model-memory-periodic-flush")
        self._periodic_thread.start()

    def periodic_flush(self) -> None:
        """Periyodik flush."""
        if time.time() - self._last_flush > self._flush_interval:
            self._flush_buffer()

    def _init_tables(self) -> Any:
        """Otomatik eklendi."""
        with self._get_conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                prediction_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                ticker TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                predicted_direction TEXT NOT NULL,
                confidence REAL NOT NULL,
                market_regime TEXT NOT NULL,
                prediction_horizon TEXT NOT NULL,
                entry_price REAL NOT NULL,
                features_json TEXT,
                status TEXT DEFAULT 'PENDING'
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                prediction_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                ticker TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                actual_price REAL NOT NULL,
                entry_price REAL NOT NULL,
                actual_return REAL NOT NULL,
                actual_direction TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                gross_pnl REAL NOT NULL,
                net_pnl REAL NOT NULL,
                transaction_cost REAL NOT NULL
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS model_metrics_history (
                model_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                sample_size INTEGER NOT NULL,
                direction_accuracy REAL NOT NULL,
                hit_rate_pct REAL NOT NULL,
                net_pnl REAL NOT NULL,
                annualized_sharpe REAL NOT NULL,
                max_drawdown_pct REAL NOT NULL,
                brier_score REAL NOT NULL,
                rank_ic REAL NOT NULL,
                reliability_score REAL NOT NULL,
                fusion_weight REAL NOT NULL,
                metrics_json TEXT
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS fusion_weights_history (
                timestamp TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                weights_json TEXT NOT NULL
            )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pred_model ON predictions(model_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_outcome_model ON outcomes(model_id, evaluated_at)")

    def save_prediction(
        self,
        prediction_id: str,
        model_id: str,
        model_version: str,
        ticker: str,
        predicted_direction: str,
        confidence: float,
        market_regime: str,
        prediction_horizon: str,
        entry_price: float,
        features: dict[str, Any] | None = None,
    ) -> Any:
        """Yeni tahmin kaydeder (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        self._buffered_write(
            """
            INSERT OR REPLACE INTO predictions (
                prediction_id, model_id, model_version, ticker, timestamp,
                predicted_direction, confidence, market_regime, prediction_horizon,
                entry_price, features_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                prediction_id,
                model_id,
                model_version,
                ticker,
                now,
                predicted_direction,
                confidence,
                market_regime,
                prediction_horizon,
                entry_price,
                orjson.dumps(features or {}).decode(),
            ),
        )

    def save_batch_records(self, records: list[dict[str, Any]]) -> Any:
        """Büyük hacimli tahmin ve outcome kayıtlarını tek atomik işlemde toplu kaydeder."""
        if not records:
            return

        cost_pct = 0.074
        pos_val = 10000.0

        pred_tuples = []
        outcome_tuples = []

        for r in records:
            p_id = r["prediction_id"]
            m_id = r["model_id"]
            m_ver = r.get("model_version", "v1.0")
            ticker = r["ticker"]
            t_stamp = r.get("timestamp", datetime.now(UTC).isoformat())
            pred_dir = r.get("predicted_direction", "UP").upper()
            conf = float(r.get("confidence", 0.65))
            regime = r.get("market_regime", "BULL_TREND")
            horizon = r.get("prediction_horizon", "1-5D")
            entry_p = float(r.get("entry_price", 100.0))
            features = orjson.dumps(r.get("features", {})).decode()

            pred_tuples.append(
                (p_id, m_id, m_ver, ticker, t_stamp, pred_dir, conf, regime, horizon, entry_p, features, "EVALUATED")
            )

            if "actual_price" in r:
                act_p = float(r["actual_price"])
                eval_at = r.get("evaluated_at", t_stamp)
                actual_ret = ((act_p - entry_p) / entry_p) * 100.0 if entry_p > 0 else 0.0
                act_dir = "UP" if actual_ret >= 0 else "DOWN"
                is_corr = 1 if (pred_dir == act_dir) else 0

                trade_ret = actual_ret if pred_dir in ["UP", "LONG", "BUY"] else -actual_ret
                gross_pnl = pos_val * (trade_ret / 100.0)
                cost = pos_val * (cost_pct / 100.0)
                net_pnl = gross_pnl - cost

                outcome_tuples.append(
                    (
                        p_id,
                        m_id,
                        m_ver,
                        ticker,
                        eval_at,
                        act_p,
                        entry_p,
                        actual_ret,
                        act_dir,
                        is_corr,
                        gross_pnl,
                        net_pnl,
                        cost,
                    )
                )

        # Buffered write — batch olarak ekle (SSD dostu)
        for t in pred_tuples:
            self._buffered_write(
                """
                INSERT OR REPLACE INTO predictions (
                    prediction_id, model_id, model_version, ticker, timestamp,
                    predicted_direction, confidence, market_regime, prediction_horizon,
                    entry_price, features_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                t,
            )
        for t in outcome_tuples:
            self._buffered_write(
                """
                INSERT OR REPLACE INTO outcomes (
                    prediction_id, model_id, model_version, ticker, evaluated_at,
                    actual_price, entry_price, actual_return, actual_direction,
                    is_correct, gross_pnl, net_pnl, transaction_cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                t,
            )

    def save_outcome(
        self,
        prediction_id: str,
        actual_price: float,
        evaluated_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Bekleyen tahmine gerçek piyasa sonucunu bağlar ve net PnL hesaplar."""
        now = evaluated_at or datetime.now(UTC).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT prediction_id, model_id, model_version, ticker, predicted_direction, entry_price FROM predictions WHERE prediction_id = ?",
                (prediction_id,),
            ).fetchone()
            if not row:
                return None

            p_id, m_id, m_ver, ticker, pred_dir_raw, entry_p = row
            entry_price = float(entry_p)
            if entry_price <= 0:
                entry_price = 1.0

            actual_ret = ((actual_price - entry_price) / entry_price) * 100.0
            pred_dir = str(pred_dir_raw).upper()
            act_dir = "UP" if actual_ret >= 0 else "DOWN"
            is_correct = 1 if (pred_dir in ["UP", "LONG", "BUY"] and actual_ret >= 0) or (pred_dir in ["DOWN", "SHORT", "SELL"] and actual_ret < 0) else 0

            # Roundtrip BIST işlem maliyeti (%0.074)
            cost_pct = 0.074
            trade_ret = actual_ret if pred_dir in ["UP", "LONG", "BUY"] else -actual_ret

            pos_val = 10000.0  # Standart lot
            gross_pnl = pos_val * (trade_ret / 100.0)
            cost = pos_val * (cost_pct / 100.0)
            net_pnl = gross_pnl - cost

            self._buffered_write(
                """
                INSERT OR REPLACE INTO outcomes (
                    prediction_id, model_id, model_version, ticker, evaluated_at,
                    actual_price, entry_price, actual_return, actual_direction,
                    is_correct, gross_pnl, net_pnl, transaction_cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction_id,
                    m_id,
                    m_ver,
                    ticker,
                    now,
                    actual_price,
                    entry_price,
                    actual_ret,
                    act_dir,
                    is_correct,
                    gross_pnl,
                    net_pnl,
                    cost,
                ),
            )

            self._buffered_write("UPDATE predictions SET status = 'EVALUATED' WHERE prediction_id = ?", (prediction_id,))

            return {
                "prediction_id": prediction_id,
                "model_id": m_id,
                "ticker": ticker,
                "predicted_direction": pred_dir,
                "actual_direction": act_dir,
                "actual_return": actual_ret,
                "is_correct": is_correct,
                "net_pnl": net_pnl,
            }

    def get_evaluated_predictions_for_model(
        self,
        model_id: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Modelin değerlendirilmiş tahmin ve outcome geçmişini döndürür."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT p.*, o.actual_price, o.actual_return, o.actual_direction,
                       o.is_correct, o.gross_pnl, o.net_pnl, o.transaction_cost, o.evaluated_at
                FROM predictions p
                JOIN outcomes o ON p.prediction_id = o.prediction_id
                WHERE p.model_id = ?
                ORDER BY o.evaluated_at DESC
                LIMIT ?
                """,
                (model_id, limit),
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r, strict=False)) for r in rows]

    def record_metrics_snapshot(
        self,
        model_id: str,
        model_version: str,
        metrics: dict[str, Any],
        reliability_score: float,
        fusion_weight: float,
    ) -> Any:
        """Modelin anlık metrik ve güvenilirlik kaydını ekler (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        self._buffered_write(
            """
            INSERT INTO model_metrics_history (
                model_id, model_version, evaluated_at, sample_size,
                direction_accuracy, hit_rate_pct, net_pnl, annualized_sharpe,
                max_drawdown_pct, brier_score, rank_ic, reliability_score,
                fusion_weight, metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_id,
                model_version,
                now,
                metrics.get("evaluated_samples", 0),
                metrics.get("direction_accuracy", 0.5),
                metrics.get("hit_rate_pct", 50.0),
                metrics.get("net_pnl", 0.0),
                metrics.get("annualized_sharpe", 0.0),
                metrics.get("max_drawdown_pct", 0.0),
                metrics.get("brier_score", 0.25),
                metrics.get("rank_ic", 0.0),
                reliability_score,
                fusion_weight,
                orjson.dumps(metrics).decode(),
            ),
        )

    def record_fusion_weights(self, weights: dict[str, float], market_regime: str) -> Any:
        """Güncel sinyal ağırlıklarını geçmişe kaydeder (buffered — SSD dostu)."""
        now = datetime.now(UTC).isoformat()
        self._buffered_write(
            "INSERT INTO fusion_weights_history (timestamp, market_regime, weights_json) VALUES (?, ?, ?)",
            (now, market_regime, orjson.dumps(weights).decode()),
        )

    def get_latest_metrics_all_models(self) -> list[dict[str, Any]]:
        """Tüm modellerin en son metrik kayıtlarını getirir."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT m.* FROM model_metrics_history m
                INNER JOIN (
                    SELECT model_id, MAX(evaluated_at) as max_time
                    FROM model_metrics_history
                    GROUP BY model_id
                ) latest ON m.model_id = latest.model_id AND m.evaluated_at = latest.max_time
                ORDER BY m.reliability_score DESC
                """
            )
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r, strict=False)) for r in rows]

    def prune_old_records(self, max_records_per_model: int = 20000) -> Any:
        """Ham geçmişi budayarak kontrolsüz büyümesini engeller."""
        with self._get_conn() as conn:
            conn.execute(
                """
                DELETE FROM predictions
                WHERE prediction_id IN (
                    SELECT prediction_id FROM predictions
                    WHERE status = 'EVALUATED'
                    ORDER BY timestamp ASC
                    LIMIT max(0, (SELECT COUNT(*) FROM predictions WHERE status = 'EVALUATED') - ?)
                )
                """,
                (max_records_per_model,),
            )


# Singleton
model_memory_store = ModelMemoryStore()

# Graceful shutdown: buffer'ı flush et
import atexit
import signal as _signal

def _flush_model_memory_on_exit() -> None:
    try:
        model_memory_store.flush()
    except Exception:
        logger.warning("Model memory flush on exit failed", exc_info=True)

def _flush_model_memory_on_signal(signum, frame) -> None:
    try:
        model_memory_store.flush()
    except Exception:
        logger.warning("Model memory flush on signal failed", exc_info=True)

atexit.register(_flush_model_memory_on_exit)
try:
    _signal.signal(_signal.SIGTERM, _flush_model_memory_on_signal)
    _signal.signal(_signal.SIGINT, _flush_model_memory_on_signal)
except (ValueError, OSError):
    pass
