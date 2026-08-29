"""
ALPHA BIST — Event Schema v2.0 (Protobuf-Ready)

Protobuf uyumlu olay şeması.
JSON ve Protobuf arasında otomatik dönüşüm.

Kullanım:
    from services.core.event_schema import CanonicalEvent, EventType

    event = CanonicalEvent(
        event_type=EventType.TICK,
        ticker="THYAO",
        data={"price": 245.50, "volume": 1000000}
    )

    # JSON olarak
    json_data = event.to_json()

    # Binary olarak (Protobuf uyumlu)
    binary_data = event.to_binary()
"""

import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import functools
import orjson
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.event_schema")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


class EventType(IntEnum):
    """Olay tipleri — Protobuf enum ile uyumlu."""

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
    """Standart olay formatı — tüm servisler bunu kullanır."""

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

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time() * 1000)
        if not self.event_id:
            import uuid

            self.event_id = str(uuid.uuid4())

    @otel_trace("event_schema.validate")
    def validate(self) -> tuple[bool, str]:
        """Event şeması ve zorunlu alan doğrulaması."""
        if not isinstance(self.event_type, (EventType, int)):
            return False, f"Geçersiz event type: {self.event_type}"
        if self.timestamp <= 0:
            return False, "Geçersiz timestamp: <= 0"
        if self.version < 1:
            return False, f"Desteklenmeyen şema versiyonu: {self.version}"
        return True, "OK"

    @otel_trace("event_schema.to_json")
    def to_json(self) -> str:
        """JSON formatına çevir."""
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
            },
            default=str,
        ).decode()

    @otel_trace("event_schema.to_dict")
    def to_dict(self) -> dict[str, Any]:
        """Dict formatına çevir."""
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
        }

    @otel_trace("event_schema.to_binary")
    def to_binary(self) -> bytes:
        """Binary formatına çevir — Protobuf uyumlu."""
        ticker_bytes = self.ticker.encode("utf-8")[:10].ljust(10, b"\x00")
        data_json = orjson.dumps(self.data, default=str)[:256]
        data_len = len(data_json)

        # Format: type(1) + ticker(10) + timestamp(8) + confidence(4) + source_len(1) + source + data_len(2) + data
        source_bytes = self.source.encode("utf-8")[:20]
        source_len = len(source_bytes)

        header = struct.pack(
            "!B10sdfBB", self.event_type.value, ticker_bytes, self.timestamp, self.confidence, source_len, data_len
        )

        return header + source_bytes + data_json

    @classmethod
    @otel_trace("event_schema.from_json")
    def from_json(cls, json_str: str | bytes) -> "CanonicalEvent":
        """JSON'dan oluştur."""
        data = orjson.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    @otel_trace("event_schema.from_dict")
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalEvent":
        """Dict'ten oluştur."""
        return cls(
            event_type=EventType(data.get("type", 0)),
            ticker=data.get("ticker", ""),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", 0),
            source=data.get("source", ""),
            confidence=float(data.get("confidence", 0.0)),
            sequence=int(data.get("sequence", 0)),
            version=int(data.get("version", 1)),
            correlation_id=str(data.get("correlation_id", "")),
        )

    @classmethod
    @otel_trace("event_schema.from_binary")
    def from_binary(cls, binary: bytes) -> "CanonicalEvent":
        """Binary'den oluştur."""
        if len(binary) < 26:
            return cls(event_type=EventType.HEARTBEAT)

        try:
            type_val, ticker_bytes, timestamp, confidence, source_len, data_len = struct.unpack(
                "!B10sdfBB", binary[:26]
            )
            ticker = ticker_bytes.rstrip(b"\x00").decode("utf-8")

            source = binary[26 : 26 + source_len].decode("utf-8") if source_len > 0 else ""
            data_json = binary[26 + source_len : 26 + source_len + data_len].decode("utf-8")
            data = orjson.loads(data_json) if data_json else {}

            return cls(
                event_type=EventType(type_val),
                ticker=ticker,
                data=data,
                timestamp=timestamp,
                source=source,
                confidence=confidence,
            )
        except Exception as e:
            logger.error("Binary decode failed", error=str(e))
            return cls(event_type=EventType.HEARTBEAT)


# =====================================================
# Hızlı Olay Oluşturucular
# =====================================================


def create_tick_event(
    ticker: str, price: float, change: float, volume: int, source: str = "ingestion"
) -> CanonicalEvent:
    """Fiyat olayı oluştur."""
    return CanonicalEvent(
        event_type=EventType.TICK,
        ticker=ticker,
        data={"price": price, "change": change, "volume": volume},
        source=source,
    )


def create_signal_event(
    ticker: str, direction: str, confidence: float, target: float, stop_loss: float, reason: str = ""
) -> CanonicalEvent:
    """Sinyal olayı oluştur."""
    return CanonicalEvent(
        event_type=EventType.SIGNAL,
        ticker=ticker,
        data={"direction": direction, "target": target, "stop_loss": stop_loss, "reason": reason},
        confidence=confidence,
        source="intelligence",
    )


def create_alert_event(
    ticker: str, alert_type: str, message: str, severity: str = "INFO", value: float = 0, threshold: float = 0
) -> CanonicalEvent:
    """Alarm olayı oluştur."""
    return CanonicalEvent(
        event_type=EventType.ALERT,
        ticker=ticker,
        data={
            "alert_type": alert_type,
            "message": message,
            "severity": severity,
            "value": value,
            "threshold": threshold,
        },
        source="alerting",
    )


def create_regime_event(regime: str, confidence: float, vix: float = 0, breadth: float = 0) -> CanonicalEvent:
    """Piyasa rejimi olayı oluştur."""
    return CanonicalEvent(
        event_type=EventType.REGIME,
        data={"regime": regime, "vix": vix, "breadth": breadth},
        confidence=confidence,
        source="market_state",
    )
