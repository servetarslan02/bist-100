"""
ALPHA BIST — QuestDB Client v1.0 (Tick Data Store)

QuestDB tabanlı tick veri deposu.
ClickHouse'dan daha hızlı yazma, SQL destekli, finans odaklı.

Özellikler:
- ILP (InfluxDB Line Protocol) ile ultra hızlı yazma
- SQL sorgu desteği (PostgreSQL wire protocol)
- Otomatik zaman serisi partitioning
- Parquet export desteği

Kullanım:
    from services.core.questdb_client import questdb_client

    # Tick verisi yaz
    await questdb_client.insert_tick("THYAO", 100.50, 1000, 100.40, 100.60)

    # Sorgu
    rows = await questdb_client.query("SELECT * FROM market_ticks WHERE ticker = 'THYAO'")
"""

import socket
from datetime import UTC, datetime
from typing import Any

import structlog

try:
    import orjson
except ImportError:
    orjson = None

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

import contextlib
import functools

from opentelemetry import trace

from .config import settings

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.questdb_client")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Otomatik eklendi."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Otomatik eklendi."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


class QuestDBClient:
    """QuestDB istemcisi — ILP yazma + SQL sorgu."""

    def __init__(self):
        """Otomatik eklendi."""
        self._host = settings.questdb_host
        self._http_port = settings.questdb_http_port
        self._pg_port = settings.questdb_pg_port
        self._ilp_port = settings.questdb_ilp_port
        self._connected = False
        self._ilp_socket: socket.socket | None = None

    @otel_trace("questdb_client.connect")
    async def connect(self) -> bool:
        """QuestDB'ye bağlan."""
        try:
            # ILP socket bağlantısı
            self._ilp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ilp_socket.settimeout(5)
            self._ilp_socket.connect((self._host, self._ilp_port))
            self._connected = True
            logger.info("QuestDB ILP connected", host=self._host, port=self._ilp_port)
            return True
        except Exception as e:
            logger.warning("QuestDB connection failed", error=str(e))
            self._connected = False
            return False

    @otel_trace("questdb_client.close")
    def close(self) -> Any:
        """Bağlantıyı kapat."""
        if self._ilp_socket:
            with contextlib.suppress(Exception):
                self._ilp_socket.close()
            self._ilp_socket = None
        self._connected = False

    @otel_trace("questdb_client.insert_tick")
    def insert_tick(
        self,
        ticker: str,
        price: float,
        volume: int,
        bid: float = 0.0,
        ask: float = 0.0,
        timestamp: datetime | None = None,
    ) -> bool:
        """Tick verisi yaz (ILP protocol)."""
        if not self._connected and not self._sync_connect():
            return False

        ts = timestamp or datetime.now(UTC)
        ts_ns = int(ts.timestamp() * 1_000_000_000)

        # ILP format: measurement,tag=value field=value timestamp
        line = f"market_ticks,ticker={ticker} price={price},volume={volume},bid={bid},ask={ask} {ts_ns}\n"

        try:
            self._ilp_socket.sendall(line.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning("QuestDB ILP write failed", error=str(e))
            self._connected = False
            return False

    @otel_trace("questdb_client.insert_ticks_batch")
    def insert_ticks_batch(self, ticks: list[dict[str, Any]]) -> bool:
        """Toplu tick verisi yaz."""
        if not self._connected and not self._sync_connect():
            return False

        lines = []
        for tick in ticks:
            ts = tick.get("timestamp", datetime.now(UTC))
            ts_ns = int(ts.timestamp() * 1_000_000_000)
            line = (
                f"market_ticks,ticker={tick['ticker']} "
                f"price={tick['price']},volume={tick.get('volume', 0)},"
                f"bid={tick.get('bid', 0.0)},ask={tick.get('ask', 0.0)} "
                f"{ts_ns}\n"
            )
            lines.append(line)

        try:
            self._ilp_socket.sendall("".join(lines).encode("utf-8"))
            return True
        except Exception as e:
            logger.warning("QuestDB batch write failed", error=str(e))
            self._connected = False
            return False

    @otel_trace("questdb_client.insert_ohlcv")
    def insert_ohlcv(
        self,
        ticker: str,
        timeframe: str,
        open_p: float,
        high: float,
        low: float,
        close: float,
        volume: int,
        timestamp: datetime | None = None,
    ) -> bool:
        """OHLCV verisi yaz."""
        if not self._connected and not self._sync_connect():
            return False

        ts = timestamp or datetime.now(UTC)
        ts_ns = int(ts.timestamp() * 1_000_000_000)

        line = (
            f"ohlcv,ticker={ticker},timeframe={timeframe} "
            f"open={open_p},high={high},low={low},close={close},volume={volume} "
            f"{ts_ns}\n"
        )

        try:
            self._ilp_socket.sendall(line.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning("QuestDB OHLCV write failed", error=str(e))
            self._connected = False
            return False

    @otel_trace("questdb_client.insert_event")
    def insert_event(
        self,
        event_type: str,
        ticker: str,
        title: str,
        sentiment: float = 0.0,
        importance: float = 0.0,
        body: str = "",
        timestamp: datetime | None = None,
    ) -> bool:
        """Olay verisi yaz (KAP, haber, makro)."""
        if not self._connected and not self._sync_connect():
            return False

        ts = timestamp or datetime.now(UTC)
        ts_ns = int(ts.timestamp() * 1_000_000_000)

        # Escape special characters for ILP
        title_escaped = title.replace(",", "\\,").replace(" ", "\\ ")
        body_escaped = body.replace(",", "\\,").replace("=", "\\=")[:500]

        line = (
            f"events,event_type={event_type},ticker={ticker} "
            f'title="{title_escaped}",sentiment={sentiment},'
            f'importance={importance},body="{body_escaped}" '
            f"{ts_ns}\n"
        )

        try:
            self._ilp_socket.sendall(line.encode("utf-8"))
            return True
        except Exception as e:
            logger.warning("QuestDB event write failed", error=str(e))
            self._connected = False
            return False

    @otel_trace("questdb_client.query")
    async def query(self, sql: str) -> list[dict[str, Any]]:
        """SQL sorgusu çalıştır (HTTP API)."""
        if not HAS_HTTPX:
            logger.warning("httpx not installed, cannot query QuestDB")
            return []

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://{self._host}:{self._http_port}/exec",
                    params={"query": sql},
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    columns = [col["name"] for col in data.get("columns", [])]
                    rows = data.get("dataset", [])
                    return [dict(zip(columns, row, strict=False)) for row in rows]
                else:
                    logger.warning("QuestDB query failed", status=resp.status_code, body=resp.text[:200])
                    return []
        except Exception as e:
            logger.warning("QuestDB query error", error=str(e))
            return []

    @otel_trace("questdb_client.query_df")
    async def query_df(self, sql: str) -> Any:
        """SQL sorgusu çalıştır ve Polars DataFrame döndür."""
        import polars as pl

        rows = await self.query(sql)
        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows)

    def _sync_connect(self) -> bool:
        """Senkron ILP bağlantısı."""
        try:
            self._ilp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ilp_socket.settimeout(5)
            self._ilp_socket.connect((self._host, self._ilp_port))
            self._connected = True
            return True
        except Exception as e:
            logger.debug("QuestDB sync connect failed", error=str(e))
            self._connected = False
            return False

    @otel_trace("questdb_client.ensure_tables")
    async def ensure_tables(self) -> bool:
        """Gerekli tabloları oluştur."""
        tables_sql = [
            """
            CREATE TABLE IF NOT EXISTS market_ticks (
                ticker SYMBOL,
                timestamp TIMESTAMP,
                price DOUBLE,
                volume LONG,
                bid DOUBLE,
                ask DOUBLE
            ) TIMESTAMP(timestamp) PARTITION BY DAY WAL
            DEDUP UPSERT KEYS(timestamp, ticker)
            """,
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                ticker SYMBOL,
                timeframe SYMBOL,
                timestamp TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume LONG
            ) TIMESTAMP(timestamp) PARTITION BY DAY WAL
            DEDUP UPSERT KEYS(timestamp, ticker, timeframe)
            """,
            """
            CREATE TABLE IF NOT EXISTS events (
                event_type SYMBOL,
                ticker SYMBOL,
                timestamp TIMESTAMP,
                title STRING,
                sentiment DOUBLE,
                importance DOUBLE,
                body STRING
            ) TIMESTAMP(timestamp) PARTITION BY MONTH WAL
            """,
        ]

        for sql in tables_sql:
            try:
                await self.query(sql.strip())
            except Exception as e:
                logger.warning("QuestDB table creation failed", error=str(e))

        logger.info("QuestDB tables ensured")
        return True


# Singleton
questdb_client = QuestDBClient()
