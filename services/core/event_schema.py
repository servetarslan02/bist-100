"""ALPHA BIST — Event Schema v2.0 (Protobuf-Ready)

Protobuf uyumlu kurumsal olay şeması.
JSON, Binary (Protobuf uyumlu) ve Polars/DuckDB arasında yüksek başarımlı dönüşüm.

Kullanım:
    from services.core.event_schema import CanonicalEvent, EventType

    event = CanonicalEvent(
        event_type=EventType.TICK,
        ticker="THYAO",
        data={"price": 245.50, "volume": 1000000}
    )

    # JSON olarak serileştirme
    json_data = event.to_json()

    # Binary olarak (Protobuf uyumlu) serileştirme
    binary_data = event.to_binary()
"""

from __future__ import annotations

import contextlib
import functools
import re
import struct
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

import duckdb
import orjson
import polars as pl
import structlog
from opentelemetry import trace

from services.core.debounce import configure_duckdb_wal

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.event_schema")

# Binary serileştirme sabitleri:
# ! = Network byte order (big-endian)
# B = uint8 (event_type, 1 bayt)
# 10s = 10 bayt ticker (boşluklar \x00 ile doldurulur)
# q = int64 (timestamp ms, 8 bayt)
# f = float32 (confidence, 4 bayt)
# B = uint8 (source_len, 1 bayt)
# H = uint16 (data_len, 2 bayt, 65535 bayta kadar JSON desteği)
BINARY_HEADER_FORMAT: str = "!B10sqfBH"
BINARY_HEADER_SIZE: int = struct.calcsize(BINARY_HEADER_FORMAT)  # 26 bayt

DEFAULT_EVENT_SCHEMA_DB_PATH: str = "data/event_schema_audit.duckdb"


def otel_trace(span_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Metotları OpenTelemetry span'i ile sarmalayan kurumsal izleme dekoratörü.

    Args:
        span_name: Üretilecek span için benzersiz izleme adı.

    Returns:
        Dekoratör fonksiyonu.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class EventType(IntEnum):
    """Olay tipleri — Protobuf enum ve merkezi olay veri yolu ile tam uyumlu."""

    TICK = 0
    OHLCV = 1
    SIGNAL = 2
    PORTFOLIO = 3
    RISK = 4
    REGIME = 5
    EVENT = 6
    ALERT = 7
    HEARTBEAT = 8
    LEARNING = 9
    MACRO = 10
    DATA_REFRESH = 11
    ANOMALY_DETECTED = 12
    ANOMALY_CLUSTER = 13
    AGENT_ANALYSIS_COMPLETED = 14
    BREADTH_ALERT = 15
    DECISION_CREATED = 16
    FEATURE_UPDATED = 17
    KAP_EVENT = 18
    KILL_SWITCH_TRIGGERED = 19
    LIQUIDITY_ALERT = 20
    MACRO_EVENT = 21
    MARKET_STATE_CHANGED = 22
    MARKET_TICK = 23
    MULTI_TF_DIVERGENCE = 24
    NEWS_EVENT = 25
    NEWS_RAW = 26
    ORDER_FILLED = 27
    OUTCOME_CREATED = 28
    PREDICTION_CREATED = 29
    REGIME_TRANSITION = 30
    RISK_ALERT = 31
    SENTIMENT_SHIFT = 32
    SIGNAL_GENERATED = 33
    SIMULATION_COMPLETED = 34
    SIMULATION_REQUESTED = 35
    SOCIAL_EVENT = 36
    WORLD_STATE_CHANGED = 37


@dataclass
class CanonicalEvent:
    """Standart olay formatı — tüm servisler ve mikro mimari bu sözleşmeyi kullanır."""

    event_type: EventType
    ticker: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0
    source: str = ""
    confidence: float = 0.0
    sequence: int = 0
    version: int = 1  # Event Schema Versiyonu (v1/v2)
    correlation_id: str = ""
    event_id: str = ""

    def __post_init__(self) -> None:
        """Varsayılan zaman damgası ve benzersiz olay kimliğini hazırlar."""
        if self.timestamp == 0:
            self.timestamp = int(time.time() * 1000)
        if not self.event_id:
            self.event_id = str(uuid.uuid4())

    def __repr__(self) -> str:
        type_name = self.event_type.name if hasattr(self.event_type, "name") else str(self.event_type)
        short_id = f"{self.event_id[:8]}..." if len(self.event_id) > 8 else self.event_id
        return (
            f"CanonicalEvent(type={type_name}, ticker='{self.ticker}', "
            f"seq={self.sequence}, v={self.version}, id='{short_id}', ts={self.timestamp})"
        )

    @otel_trace("event_schema.validate")
    def validate(self) -> tuple[bool, str]:
        """Event şeması ve zorunlu alan doğrulaması gerçekleştirir.

        Returns:
            (gecerli_mi, hata_mesaji) ikilisi.
        """
        if not isinstance(self.event_type, (EventType, int)):
            return False, f"Geçersiz event type: {self.event_type}"
        if self.timestamp <= 0:
            return False, "Geçersiz timestamp: <= 0"
        if self.version < 1:
            return False, f"Desteklenmeyen şema versiyonu: {self.version}"
        return True, "OK"

    @otel_trace("event_schema.to_json")
    def to_json(self) -> str:
        """Olayı yüksek başarımlı UTF-8 JSON metnine serileştirir.

        Returns:
            JSON metni.
        """
        return orjson.dumps(
            {
                "type": self.event_type.value if hasattr(self.event_type, "value") else int(self.event_type),
                "ticker": self.ticker,
                "data": self.data,
                "timestamp": self.timestamp,
                "source": self.source,
                "confidence": self.confidence,
                "sequence": self.sequence,
                "version": self.version,
                "correlation_id": self.correlation_id,
                "event_id": self.event_id,
            },
            default=str,
        ).decode("utf-8")

    @otel_trace("event_schema.to_dict")
    def to_dict(self) -> dict[str, Any]:
        """Olayı standart Python sözlüğü formatına dönüştürür.

        Returns:
            Olay alanlarını içeren sözlük.
        """
        return {
            "type": self.event_type.value if hasattr(self.event_type, "value") else int(self.event_type),
            "ticker": self.ticker,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "sequence": self.sequence,
            "version": self.version,
            "correlation_id": self.correlation_id,
            "event_id": self.event_id,
        }

    @otel_trace("event_schema.to_binary")
    def to_binary(self) -> bytes:
        """Olayı Protobuf uyumlu kompakt ikili (binary) formata çevirir.

        Returns:
            Serileştirilmiş bayt dizisi.
        """
        ticker_bytes = self.ticker.encode("utf-8")[:10].ljust(10, b"\x00")
        source_bytes = self.source.encode("utf-8")[:255]
        source_len = len(source_bytes)

        data_json = orjson.dumps(self.data, default=str)[:65535]
        data_len = len(data_json)

        type_val = self.event_type.value if hasattr(self.event_type, "value") else int(self.event_type)

        header = struct.pack(
            BINARY_HEADER_FORMAT,
            type_val,
            ticker_bytes,
            int(self.timestamp),
            float(self.confidence),
            source_len,
            data_len,
        )

        return header + source_bytes + data_json

    @classmethod
    @otel_trace("event_schema.from_json")
    def from_json(cls, json_str: str | bytes) -> CanonicalEvent:
        """JSON metni veya baytlarından CanonicalEvent nesnesi inşa eder.

        Args:
            json_str: Çözümlenecek JSON metni ya da baytları.

        Returns:
            Oluşturulan CanonicalEvent nesnesi.
        """
        data = orjson.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    @otel_trace("event_schema.from_dict")
    def from_dict(cls, data: dict[str, Any]) -> CanonicalEvent:
        """Sözlük yapısından güvenli CanonicalEvent nesnesi inşa eder.

        Args:
            data: Ham olay verilerini içeren sözlük.

        Returns:
            Oluşturulan CanonicalEvent nesnesi.
        """
        raw_type = data.get("type", data.get("event_type", 0))
        if isinstance(raw_type, str):
            try:
                event_type = EventType[raw_type.upper()]
            except KeyError:
                event_type = EventType.EVENT
        else:
            try:
                event_type = EventType(int(raw_type))
            except (ValueError, TypeError):
                event_type = EventType.EVENT

        return cls(
            event_type=event_type,
            ticker=str(data.get("ticker", "")),
            data=dict(data.get("data", {})) if isinstance(data.get("data"), dict) else {},
            timestamp=int(data.get("timestamp", 0)),
            source=str(data.get("source", "")),
            confidence=float(data.get("confidence", 0.0)),
            sequence=int(data.get("sequence", 0)),
            version=int(data.get("version", 1)),
            correlation_id=str(data.get("correlation_id", "")),
            event_id=str(data.get("event_id", "")),
        )

    @classmethod
    @otel_trace("event_schema.from_binary")
    def from_binary(cls, binary: bytes) -> CanonicalEvent:
        """Kompakt ikili (binary) veriden CanonicalEvent nesnesi oluşturur.

        Args:
            binary: Çözümlenecek bayt dizisi.

        Returns:
            Oluşturulan CanonicalEvent nesnesi.
        """
        if len(binary) < BINARY_HEADER_SIZE:
            logger.warning("binary_payload_too_short", size=len(binary), required=BINARY_HEADER_SIZE)
            return cls(event_type=EventType.HEARTBEAT)

        try:
            type_val, ticker_bytes, timestamp, confidence, source_len, data_len = struct.unpack(
                BINARY_HEADER_FORMAT, binary[:BINARY_HEADER_SIZE]
            )
            ticker = ticker_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")

            offset = BINARY_HEADER_SIZE
            source = binary[offset : offset + source_len].decode("utf-8", errors="replace") if source_len > 0 else ""
            offset += source_len

            data_raw = binary[offset : offset + data_len]
            data = orjson.loads(data_raw) if data_raw else {}

            try:
                event_type = EventType(type_val)
            except ValueError:
                event_type = EventType.EVENT

            return cls(
                event_type=event_type,
                ticker=ticker,
                data=data,
                timestamp=timestamp,
                source=source,
                confidence=confidence,
            )
        except Exception as e:
            logger.error("binary_decode_failed", error=str(e))
            return cls(event_type=EventType.HEARTBEAT)


# =====================================================
# Hızlı Olay Oluşturucular (Event Factories)
# =====================================================


def create_tick_event(
    ticker: str, price: float, change: float, volume: int, source: str = "ingestion"
) -> CanonicalEvent:
    """Fiyat ve işlem hacmi olayını (TICK) oluşturur.

    Args:
        ticker: BIST hisse sembolü (ör: 'THYAO').
        price: Güncel işlem fiyatı.
        change: Günlük yüzde değişim oranı.
        volume: Toplam işlem hacmi (lot/adet).
        source: Veri kaynağı etiketi.

    Returns:
        Oluşturulan CanonicalEvent nesnesi.
    """
    return CanonicalEvent(
        event_type=EventType.TICK,
        ticker=ticker,
        data={"price": float(price), "change": float(change), "volume": int(volume)},
        source=source,
    )


def create_signal_event(
    ticker: str, direction: str, confidence: float, target: float, stop_loss: float, reason: str = ""
) -> CanonicalEvent:
    """Al/Sat işlem sinyali olayını (SIGNAL) oluşturur.

    Args:
        ticker: BIST hisse sembolü.
        direction: Sinyal yönü ('BUY', 'SELL', 'HOLD').
        confidence: Model güven skoru (0.0 - 1.0).
        target: Hedef kâr fiyatı.
        stop_loss: Zarar kes fiyatı.
        reason: Sinyalin üretilme gerekçesi.

    Returns:
        Oluşturulan CanonicalEvent nesnesi.
    """
    return CanonicalEvent(
        event_type=EventType.SIGNAL,
        ticker=ticker,
        data={
            "direction": str(direction),
            "target": float(target),
            "stop_loss": float(stop_loss),
            "reason": str(reason),
        },
        confidence=float(confidence),
        source="intelligence",
    )


def create_alert_event(
    ticker: str,
    alert_type: str,
    message: str,
    severity: str = "INFO",
    value: float = 0.0,
    threshold: float = 0.0,
) -> CanonicalEvent:
    """Sistem, risk veya piyasa alarmı olayını (ALERT) oluşturur.

    Args:
        ticker: İlgili hisse sembolü.
        alert_type: Alarm kategorisi veya türü.
        message: Alarm detay bildirimi.
        severity: Önem derecesi ('INFO', 'WARNING', 'CRITICAL').
        value: Ölçülen anlık değer.
        threshold: İhlal edilen eşik değer.

    Returns:
        Oluşturulan CanonicalEvent nesnesi.
    """
    return CanonicalEvent(
        event_type=EventType.ALERT,
        ticker=ticker,
        data={
            "alert_type": str(alert_type),
            "message": str(message),
            "severity": str(severity),
            "value": float(value),
            "threshold": float(threshold),
        },
        source="alerting",
    )


def create_regime_event(regime: str, confidence: float, vix: float = 0.0, breadth: float = 0.0) -> CanonicalEvent:
    """Piyasa rejimi ve oynaklık durum olayını (REGIME) oluşturur.

    Args:
        regime: Tespit edilen piyasa rejimi (ör: 'TRENDING_BULL', 'HIGH_VOLATILITY').
        confidence: Rejim tespit güven skoru.
        vix: Volatilite endeks değeri.
        breadth: Piyasa derinlik/yayılım göstergesi.

    Returns:
        Oluşturulan CanonicalEvent nesnesi.
    """
    return CanonicalEvent(
        event_type=EventType.REGIME,
        data={"regime": str(regime), "vix": float(vix), "breadth": float(breadth)},
        confidence=float(confidence),
        source="market_state",
    )


def create_heartbeat_event(source: str = "system") -> CanonicalEvent:
    """Sistem canlılık sinyali olayını (HEARTBEAT) oluşturur.

    Args:
        source: Canlılık sinyali gönderen servis adı.

    Returns:
        Oluşturulan CanonicalEvent nesnesi.
    """
    return CanonicalEvent(
        event_type=EventType.HEARTBEAT,
        source=source,
    )


def create_order_filled_event(
    ticker: str,
    order_id: str,
    side: str,
    price: float,
    quantity: float,
    source: str = "execution",
) -> CanonicalEvent:
    """Emir gerçekleşme olayını (ORDER_FILLED) oluşturur.

    Args:
        ticker: Hisse sembolü.
        order_id: Emir numarası.
        side: İşlem tarafı ('BUY', 'SELL').
        price: Gerçekleşme fiyatı.
        quantity: Gerçekleşen lot miktarı.
        source: İcra motoru etiketi.

    Returns:
        Oluşturulan CanonicalEvent nesnesi.
    """
    return CanonicalEvent(
        event_type=EventType.ORDER_FILLED,
        ticker=ticker,
        data={
            "order_id": str(order_id),
            "side": str(side),
            "price": float(price),
            "quantity": float(quantity),
        },
        source=source,
    )


# =====================================================
# Polars ve DuckDB Entegrasyonu (GEMINI.md Kuralları)
# =====================================================


def events_to_polars(events: list[CanonicalEvent]) -> pl.DataFrame:
    """CanonicalEvent nesneleri listesini vektörize Polars DataFrame yapısına dönüştürür.

    Args:
        events: CanonicalEvent nesneleri listesi.

    Returns:
        Olayları yapısal olarak içeren polars.DataFrame nesnesi.
    """
    if not events:
        return pl.DataFrame({
            "event_id": pl.Series(dtype=pl.String),
            "type": pl.Series(dtype=pl.Int32),
            "type_name": pl.Series(dtype=pl.String),
            "ticker": pl.Series(dtype=pl.String),
            "timestamp": pl.Series(dtype=pl.Int64),
            "source": pl.Series(dtype=pl.String),
            "confidence": pl.Series(dtype=pl.Float64),
            "sequence": pl.Series(dtype=pl.Int64),
            "version": pl.Series(dtype=pl.Int32),
            "correlation_id": pl.Series(dtype=pl.String),
            "data_json": pl.Series(dtype=pl.String),
        })

    records: list[dict[str, Any]] = []
    for ev in events:
        type_val = ev.event_type.value if hasattr(ev.event_type, "value") else int(ev.event_type)
        type_name = ev.event_type.name if hasattr(ev.event_type, "name") else str(ev.event_type)
        records.append({
            "event_id": ev.event_id,
            "type": type_val,
            "type_name": type_name,
            "ticker": ev.ticker,
            "timestamp": ev.timestamp,
            "source": ev.source,
            "confidence": ev.confidence,
            "sequence": ev.sequence,
            "version": ev.version,
            "correlation_id": ev.correlation_id,
            "data_json": orjson.dumps(ev.data, default=str).decode("utf-8"),
        })

    schema = {
        "event_id": pl.String,
        "type": pl.Int32,
        "type_name": pl.String,
        "ticker": pl.String,
        "timestamp": pl.Int64,
        "source": pl.String,
        "confidence": pl.Float64,
        "sequence": pl.Int64,
        "version": pl.Int32,
        "correlation_id": pl.String,
        "data_json": pl.String,
    }
    return pl.DataFrame(records, schema=schema)


def events_from_polars(df: pl.DataFrame) -> list[CanonicalEvent]:
    """Polars DataFrame tablosundaki satırları CanonicalEvent nesneleri listesine dönüştürür.

    Args:
        df: Polars DataFrame tablosu.

    Returns:
        Oluşturulan CanonicalEvent nesneleri listesi.
    """
    if df.is_empty():
        return []

    events: list[CanonicalEvent] = []
    for row in df.iter_rows(named=True):
        raw_type = row.get("type", 0)
        try:
            event_type = EventType(int(raw_type))
        except (ValueError, TypeError):
            event_type = EventType.EVENT

        data_json = row.get("data_json", "{}")
        try:
            data = orjson.loads(data_json) if data_json else {}
        except Exception:
            data = {}

        ev = CanonicalEvent(
            event_type=event_type,
            ticker=str(row.get("ticker", "")),
            data=data,
            timestamp=int(row.get("timestamp", 0)),
            source=str(row.get("source", "")),
            confidence=float(row.get("confidence", 0.0)),
            sequence=int(row.get("sequence", 0)),
            version=int(row.get("version", 1)),
            correlation_id=str(row.get("correlation_id", "")),
            event_id=str(row.get("event_id", "")),
        )
        events.append(ev)

    return events


def export_events_to_duckdb(
    events: list[CanonicalEvent],
    db_path: str = DEFAULT_EVENT_SCHEMA_DB_PATH,
    table_name: str = "canonical_events",
) -> int:
    """Olay listesini doğrudan DuckDB veritabanına yazar.

    Args:
        events: Kaydedilecek CanonicalEvent listesi.
        db_path: DuckDB veritabanı dosya yolu.
        table_name: Hedef tablo adı.

    Returns:
        Veritabanına eklenen toplam kayıt sayısı.
    """
    if not events:
        return 0

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
        raise ValueError(f"Geçersiz tablo adı: {table_name}")

    df = events_to_polars(events)
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == 0:
        with contextlib.suppress(OSError):
            target.unlink()

    with duckdb.connect(db_path) as conn:
        configure_duckdb_wal(conn)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                event_id VARCHAR PRIMARY KEY,
                type INTEGER,
                type_name VARCHAR,
                ticker VARCHAR,
                timestamp BIGINT,
                source VARCHAR,
                confidence DOUBLE,
                sequence BIGINT,
                version INTEGER,
                correlation_id VARCHAR,
                data_json VARCHAR
            )
        """)
        conn.register("df_events_view", df.to_arrow())
        conn.execute(f"INSERT OR REPLACE INTO {table_name} SELECT * FROM df_events_view")

    return df.height


def query_events_duckdb(
    query: str,
    params: list[Any] | None = None,
    db_path: str = DEFAULT_EVENT_SCHEMA_DB_PATH,
) -> list[dict[str, Any]]:
    """Yerel DuckDB olay şeması defteri üzerinde parametrik SQL sorgusu çalıştırır.

    Args:
        query: Çalıştırılacak SQL sorgusu.
        params: Parametre listesi.
        db_path: DuckDB veritabanı dosya yolu.

    Returns:
        Sorgu sonuçlarını sözlükler listesi olarak döndürür.
    """
    target = Path(db_path)
    if not target.exists() or target.stat().st_size == 0:
        return []

    try:
        with duckdb.connect(db_path, read_only=True) as conn:
            cursor = conn.execute(query, params or [])
            cols = [desc[0] for desc in cursor.description]
            return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]
    except Exception as exc:
        logger.error("query_events_duckdb_hatasi", query=query, hata=str(exc))
        return []


__all__ = [
    "BINARY_HEADER_FORMAT",
    "BINARY_HEADER_SIZE",
    "CanonicalEvent",
    "DEFAULT_EVENT_SCHEMA_DB_PATH",
    "EventType",
    "create_alert_event",
    "create_heartbeat_event",
    "create_order_filled_event",
    "create_regime_event",
    "create_signal_event",
    "create_tick_event",
    "events_from_polars",
    "events_to_polars",
    "export_events_to_duckdb",
    "otel_trace",
    "query_events_duckdb",
]
