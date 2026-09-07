"""ALPHA BIST — QuestDB Client v1.0 (Tick Data Store)

QuestDB tabanlı yüksek frekanslı tick ve zaman serisi veri deposu.
ILP (InfluxDB Line Protocol) ile mikro saniye seviyesinde hızlı yazma ve HTTP SQL sorgu desteği.
Thread-safe soket yönetimi (RLock), DuckDB çevrimdışı tamponu ve Polars analitik entegrasyonu.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import duckdb
import httpx
import orjson
import polars as pl
import structlog

from services.core.config import settings
from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# Modül Sabitleri
DEFAULT_SOCKET_TIMEOUT: Final[float] = 5.0
DEFAULT_HTTP_TIMEOUT: Final[float] = 30.0
DEFAULT_QUESTDB_DUCKDB_BUFFER_PATH: Final[str] = "data/questdb_buffer.duckdb"
DEFAULT_CHECKPOINT_SIZE: Final[str] = "4MB"
DEFAULT_WAL_SIZE: Final[str] = "2MB"


def configure_duckdb_wal(
    conn: duckdb.DuckDBPyConnection,
    checkpoint_threshold: str = DEFAULT_CHECKPOINT_SIZE,
    wal_autocheckpoint: str = DEFAULT_WAL_SIZE,
) -> None:
    """DuckDB WAL boyutunu optimize eder."""
    try:
        conn.execute(f"SET checkpoint_threshold = '{checkpoint_threshold}';")
        conn.execute(f"SET wal_autocheckpoint = '{wal_autocheckpoint}';")
    except Exception as e:
        logger.warning("duckdb_wal_yapilandirma_uyarisi", hata=str(e))


class QuestDBClient:
    """QuestDB istemcisi — ILP soket yazımı ve HTTP SQL sorguları.

    Tüm soket işlemleri reentrant kilit (RLock) ile iş parçacığı güvenli tutulur.
    Ağ kesintilerinde self-healing otomatik yeniden bağlanma ve DuckDB tamponlama desteği sunar.
    """

    def __init__(self, duckdb_buffer_path: str = DEFAULT_QUESTDB_DUCKDB_BUFFER_PATH) -> None:
        self._lock = threading.RLock()
        self._duckdb_buffer_path = duckdb_buffer_path
        self._host: str = getattr(settings, "questdb_host", "localhost")
        self._http_port: int = getattr(settings, "questdb_http_port", 9000)
        self._pg_port: int = getattr(settings, "questdb_pg_port", 8812)
        self._ilp_port: int = getattr(settings, "questdb_ilp_port", 9009)
        self._connected: bool = False
        self._ilp_socket: socket.socket | None = None

    @otel_trace("questdb_client.connect")
    async def connect(self) -> bool:
        """QuestDB ILP soketine asenkron bağlanır."""
        with self._lock:
            return self._sync_connect()

    @otel_trace("questdb_client.close")
    def close(self) -> None:
        """Aktif QuestDB soket bağlantısını güvenle kapatır."""
        with self._lock:
            if self._ilp_socket:
                with contextlib.suppress(Exception):
                    self._ilp_socket.close()
                self._ilp_socket = None
            self._connected = False
            logger.info("questdb_baglantisi_kapatildi")

    def _sync_connect(self) -> bool:
        """Senkron ILP TCP soket bağlantısı kurar."""
        try:
            if self._ilp_socket:
                with contextlib.suppress(Exception):
                    self._ilp_socket.close()
            self._ilp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ilp_socket.settimeout(DEFAULT_SOCKET_TIMEOUT)
            self._ilp_socket.connect((self._host, self._ilp_port))
            self._connected = True
            logger.info("questdb_ilp_baglandi", host=self._host, port=self._ilp_port)
            return True
        except Exception as e:
            logger.warning("questdb_baglanti_hatasi", host=self._host, port=self._ilp_port, hata=str(e))
            self._connected = False
            self._ilp_socket = None
            return False

    @otel_trace("questdb_client.heal_connection")
    def heal_connection(self) -> bool:
        """Kopan veya zaman aşımına uğrayan bağlantıyı otomatik onarır (Self-Healing)."""
        with self._lock:
            logger.info("questdb_baglanti_onarimi_baslatildi")
            return self._sync_connect()

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
        """Tekil tick verisini ILP protokolü ile QuestDB'ye yazar.

        Args:
            ticker: Hisse/enstrüman kodu.
            price: İşlem fiyatı.
            volume: İşlem hacmi (lot).
            bid: En iyi alış fiyatı.
            ask: En iyi satış fiyatı.
            timestamp: İsteğe bağlı zaman damgası (UTC).

        Returns:
            Yazma başarılı ise True, aksi halde False.
        """
        ts = timestamp or datetime.now(UTC)
        ts_ns = int(ts.timestamp() * 1_000_000_000)
        line = f"market_ticks,ticker={ticker} price={float(price)},volume={int(volume)}i,bid={float(bid)},ask={float(ask)} {ts_ns}\n"

        with self._lock:
            if not self._connected and not self._sync_connect():
                self._buffer_tick_offline(ticker, price, volume, bid, ask, ts)
                return False

            try:
                assert self._ilp_socket is not None
                self._ilp_socket.sendall(line.encode("utf-8"))
                return True
            except Exception as e:
                logger.warning("questdb_ilp_yazma_hatasi", hisse=ticker, hata=str(e))
                self._connected = False
                self._buffer_tick_offline(ticker, price, volume, bid, ask, ts)
                return False

    @otel_trace("questdb_client.insert_ticks_batch")
    def insert_ticks_batch(self, ticks: list[dict[str, Any]]) -> bool:
        """Toplu tick verilerini tek TCP paketinde yüksek hızda yazar.

        Args:
            ticks: Tick sözlükleri listesi.

        Returns:
            Toplu yazım başarılı ise True, aksi halde False.
        """
        if not ticks:
            return True

        lines = []
        for tick in ticks:
            ts = tick.get("timestamp") or datetime.now(UTC)
            ts_ns = int(ts.timestamp() * 1_000_000_000)
            vol = int(tick.get("volume", 0) or 0)
            line = (
                f"market_ticks,ticker={tick['ticker']} "
                f"price={float(tick['price'])},volume={vol}i,"
                f"bid={float(tick.get('bid', 0.0) or 0.0)},ask={float(tick.get('ask', 0.0) or 0.0)} "
                f"{ts_ns}\n"
            )
            lines.append(line)

        payload = "".join(lines).encode("utf-8")

        with self._lock:
            if not self._connected and not self._sync_connect():
                for t in ticks:
                    self._buffer_tick_offline(
                        t["ticker"],
                        float(t["price"]),
                        int(t.get("volume", 0) or 0),
                        float(t.get("bid", 0.0) or 0.0),
                        float(t.get("ask", 0.0) or 0.0),
                        t.get("timestamp") or datetime.now(UTC),
                    )
                return False

            try:
                assert self._ilp_socket is not None
                self._ilp_socket.sendall(payload)
                return True
            except Exception as e:
                logger.warning("questdb_toplu_yazma_hatasi", kayit_sayisi=len(ticks), hata=str(e))
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
        """OHLCV çubuk verisini ILP protokolüyle yazar."""
        ts = timestamp or datetime.now(UTC)
        ts_ns = int(ts.timestamp() * 1_000_000_000)
        vol = int(volume or 0)

        line = (
            f"ohlcv,ticker={ticker},timeframe={timeframe} "
            f"open={float(open_p)},high={float(high)},low={float(low)},close={float(close)},volume={vol}i "
            f"{ts_ns}\n"
        )

        with self._lock:
            if not self._connected and not self._sync_connect():
                return False

            try:
                assert self._ilp_socket is not None
                self._ilp_socket.sendall(line.encode("utf-8"))
                return True
            except Exception as e:
                logger.warning("questdb_ohlcv_yazma_hatasi", hisse=ticker, periyot=timeframe, hata=str(e))
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
        """Olay ve duyuru verisini (KAP, haber) ILP formatında yazar."""
        ts = timestamp or datetime.now(UTC)
        ts_ns = int(ts.timestamp() * 1_000_000_000)

        title_escaped = title.replace(",", "\\,").replace(" ", "\\ ")
        body_escaped = body.replace(",", "\\,").replace("=", "\\=")[:500]

        line = (
            f"events,event_type={event_type},ticker={ticker} "
            f'title="{title_escaped}",sentiment={sentiment},'
            f'importance={importance},body="{body_escaped}" '
            f"{ts_ns}\n"
        )

        with self._lock:
            if not self._connected and not self._sync_connect():
                return False

            try:
                assert self._ilp_socket is not None
                self._ilp_socket.sendall(line.encode("utf-8"))
                return True
            except Exception as e:
                logger.warning("questdb_olay_yazma_hatasi", hisse=ticker, olay=event_type, hata=str(e))
                self._connected = False
                return False

    @otel_trace("questdb_client.query")
    async def query(self, sql: str) -> list[dict[str, Any]]:
        """QuestDB HTTP REST API üzerinden SQL sorgusu çalıştırır."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://{self._host}:{self._http_port}/exec",
                    params={"query": sql},
                    timeout=DEFAULT_HTTP_TIMEOUT,
                )
                if resp.status_code == 200:
                    data = orjson.loads(resp.content)
                    columns = [col["name"] for col in data.get("columns", [])]
                    rows = data.get("dataset", [])
                    return [dict(zip(columns, row, strict=False)) for row in rows]
                else:
                    logger.warning("questdb_sorgu_basarisiz", durum_kodu=resp.status_code, govde=resp.text[:200])
                    return []
        except Exception as e:
            logger.warning("questdb_sorgu_hatasi", hata=str(e))
            return []

    @otel_trace("questdb_client.query_df")
    async def query_df(self, sql: str) -> pl.DataFrame:
        """SQL sorgusu çalıştırır ve katı tip güvenliğiyle Polars DataFrame döndürür."""
        rows = await self.query(sql)
        if not rows:
            return pl.DataFrame()
        return pl.from_dicts(rows)

    def _buffer_tick_offline(
        self,
        ticker: str,
        price: float,
        volume: int,
        bid: float,
        ask: float,
        ts: datetime,
    ) -> None:
        """QuestDB erişilemezken veri kaybını önlemek için tick verisini DuckDB tamponuna yazar."""
        try:
            path_obj = Path(self._duckdb_buffer_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            conn = duckdb.connect(str(path_obj))
            try:
                configure_duckdb_wal(conn)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS questdb_offline_ticks (
                        ticker VARCHAR,
                        price DOUBLE,
                        volume BIGINT,
                        bid DOUBLE,
                        ask DOUBLE,
                        recorded_at TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO questdb_offline_ticks VALUES (?, ?, ?, ?, ?, ?)",
                    [ticker, price, volume, bid, ask, ts],
                )
            finally:
                conn.close()
        except Exception as e:
            logger.error("questdb_duckdb_tampon_hatasi", hisse=ticker, hata=str(e))

    def flush_offline_buffer(self) -> int:
        """DuckDB tamponundaki birikmiş tick verilerini QuestDB'ye geri aktarır (Self-Healing)."""
        path_obj = Path(self._duckdb_buffer_path)
        if not path_obj.exists():
            return 0

        conn = duckdb.connect(str(path_obj))
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "questdb_offline_ticks" not in tables:
                return 0

            rows = conn.execute("SELECT ticker, price, volume, bid, ask, recorded_at FROM questdb_offline_ticks").fetchall()
            if not rows:
                return 0

            ticks = [
                {
                    "ticker": r[0],
                    "price": float(r[1]),
                    "volume": int(r[2]),
                    "bid": float(r[3]),
                    "ask": float(r[4]),
                    "timestamp": r[5],
                }
                for r in rows
            ]
            if self.insert_ticks_batch(ticks):
                conn.execute("DELETE FROM questdb_offline_ticks")
                logger.info("questdb_tampon_basariyla_bosaltildi", kayit_sayisi=len(ticks))
                return len(ticks)
            return 0
        finally:
            conn.close()

    def read_buffer_from_duckdb(
        self,
        db_path: str | None = None,
        ticker: str | None = None,
    ) -> pl.DataFrame:
        """DuckDB çevrimdışı tamponundaki tick kayıtlarını Polars DataFrame olarak okur."""
        target_path = db_path or self._duckdb_buffer_path
        path_obj = Path(target_path)
        empty_schema = {
            "ticker": pl.String,
            "price": pl.Float64,
            "volume": pl.Int64,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "recorded_at": pl.Datetime,
        }
        if not path_obj.exists():
            return pl.DataFrame(schema=empty_schema)

        conn = duckdb.connect(str(path_obj), read_only=True)
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "questdb_offline_ticks" not in tables:
                return pl.DataFrame(schema=empty_schema)

            query = "SELECT ticker, price, volume, bid, ask, recorded_at FROM questdb_offline_ticks "
            params: list[Any] = []
            if ticker:
                query += "WHERE ticker = ? "
                params.append(ticker.upper().strip())
            query += "ORDER BY recorded_at ASC"

            return conn.execute(query, params).pl()
        except Exception as e:
            logger.error("questdb_tampon_okuma_hatasi", hata=str(e))
            return pl.DataFrame(schema=empty_schema)
        finally:
            conn.close()

    def clear_buffer_duckdb(self, db_path: str | None = None) -> bool:
        """DuckDB çevrimdışı tamponundaki tüm tick kayıtlarını temizler."""
        target_path = db_path or self._duckdb_buffer_path
        path_obj = Path(target_path)
        if not path_obj.exists():
            return True

        conn = duckdb.connect(str(path_obj))
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
            if "questdb_offline_ticks" in tables:
                conn.execute("DELETE FROM questdb_offline_ticks")
            logger.info("questdb_tampon_temizlendi", db_path=str(path_obj))
            return True
        except Exception as e:
            logger.error("questdb_tampon_temizleme_hatasi", hata=str(e))
            return False
        finally:
            conn.close()

    def to_orjson_bytes(self) -> bytes:
        """İstemci durumunu ve tampon büyüklüğünü orjson bayt dizisine dönüştürür."""
        with self._lock:
            buffer_df = self.read_buffer_from_duckdb()
            state = {
                "host": self._host,
                "ilp_port": self._ilp_port,
                "http_port": self._http_port,
                "connected": self._connected,
                "buffered_ticks_count": len(buffer_df),
                "duckdb_path": self._duckdb_buffer_path,
            }
            return orjson.dumps(state, default=str)

    def __repr__(self) -> str:
        """Açıklayıcı metin temsili."""
        with self._lock:
            return (
                f"QuestDBClient(host={self._host!r}, ilp_port={self._ilp_port}, "
                f"http_port={self._http_port}, connected={self._connected})"
            )


# Singleton
questdb_client = QuestDBClient()


def read_questdb_buffer_from_duckdb(
    db_path: str = DEFAULT_QUESTDB_DUCKDB_BUFFER_PATH,
    ticker: str | None = None,
    client: QuestDBClient = questdb_client,
) -> pl.DataFrame:
    """DuckDB çevrimdışı tamponundaki tick kayıtlarını Polars DataFrame olarak okur."""
    return client.read_buffer_from_duckdb(db_path=db_path, ticker=ticker)


def clear_questdb_buffer_duckdb(
    db_path: str = DEFAULT_QUESTDB_DUCKDB_BUFFER_PATH,
    client: QuestDBClient = questdb_client,
) -> bool:
    """DuckDB çevrimdışı tamponundaki kayıtları temizler."""
    return client.clear_buffer_duckdb(db_path=db_path)


def export_offline_ticks_to_polars(
    db_path: str = DEFAULT_QUESTDB_DUCKDB_BUFFER_PATH,
    client: QuestDBClient = questdb_client,
) -> pl.DataFrame:
    """Çevrimdışı tamponundaki tick kayıtlarını Polars DataFrame olarak döndürür."""
    return client.read_buffer_from_duckdb(db_path=db_path)


def to_orjson_bytes(data: Any) -> bytes:
    """Verilen veriyi orjson bayt dizisine dönüştürür."""
    return orjson.dumps(data, default=str)


__all__: Final[list[str]] = [
    "DEFAULT_CHECKPOINT_SIZE",
    "DEFAULT_HTTP_TIMEOUT",
    "DEFAULT_QUESTDB_DUCKDB_BUFFER_PATH",
    "DEFAULT_SOCKET_TIMEOUT",
    "DEFAULT_WAL_SIZE",
    "QuestDBClient",
    "clear_questdb_buffer_duckdb",
    "configure_duckdb_wal",
    "export_offline_ticks_to_polars",
    "questdb_client",
    "read_questdb_buffer_from_duckdb",
    "to_orjson_bytes",
]


