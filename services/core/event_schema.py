"""
ALPHA BIST — Event Schema v2.0 (Protobuf-Ready)

Protobuf uyumlu olay şeması.
JSON ve Protobuf arasında otomatik dönüşüm.

Kullanım:
    from services.core.event_schema import CanonicalEvent, EventType
    
    event = CanonicalEvent(
        type=EventType.TICK,
        ticker="THYAO",
        data={"price": 245.50, "volume": 1000000}
    )
    
    # JSON olarak
    json_data = event.to_json()
    
    # Binary olarak (Protobuf uyumlu)
    binary_data = event.to_binary()
"""

import orjson
import time
import struct
from enum import IntEnum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


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


@dataclass
class CanonicalEvent:
    """Standart olay formatı — tüm servisler bunu kullanır."""
    type: EventType
    ticker: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0
    source: str = ""
    confidence: float = 0.0
    sequence: int = 0

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time() * 1000)

    def to_json(self) -> str:
        """JSON formatına çevir."""
        return orjson.dumps({
            "type": self.type.value,
            "ticker": self.ticker,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "sequence": self.sequence,
        }, default=str)

    def to_dict(self) -> Dict[str, Any]:
        """Dict formatına çevir."""
        return {
            "type": self.type.value,
            "ticker": self.ticker,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "sequence": self.sequence,
        }

    def to_binary(self) -> bytes:
        """Binary formatına çevir — Protobuf uyumlu."""
        ticker_bytes = self.ticker.encode('utf-8')[:10].ljust(10, b'\x00')
        data_json = orjson.dumps(self.data, default=str)[:256]
        data_len = len(data_json)

        # Format: type(1) + ticker(10) + timestamp(8) + confidence(4) + source_len(1) + source + data_len(2) + data
        source_bytes = self.source.encode('utf-8')[:20]
        source_len = len(source_bytes)

        header = struct.pack('!B10sdfBB',
            self.type.value,
            ticker_bytes,
            self.timestamp,
            self.confidence,
            source_len,
            data_len
        )

        return header + source_bytes + data_json

    @classmethod
    def from_json(cls, json_str: str) -> 'CanonicalEvent':
        """JSON'dan oluştur."""
        data = orjson.loads(json_str)
        return cls(
            type=EventType(data.get("type", 0)),
            ticker=data.get("ticker", ""),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", 0),
            source=data.get("source", ""),
            confidence=data.get("confidence", 0.0),
            sequence=data.get("sequence", 0),
        )

    @classmethod
    def from_binary(cls, binary: bytes) -> 'CanonicalEvent':
        """Binary'den oluştur."""
        if len(binary) < 26:
            return cls(type=EventType.HEARTBEAT)

        try:
            type_val, ticker_bytes, timestamp, confidence, source_len, data_len = struct.unpack('!B10sdfBB', binary[:26])
            ticker = ticker_bytes.rstrip(b'\x00').decode('utf-8')

            source = binary[26:26+source_len].decode('utf-8') if source_len > 0 else ""
            data_json = binary[26+source_len:26+source_len+data_len].decode('utf-8')
            data = orjson.loads(data_json) if data_json else {}

            return cls(
                type=EventType(type_val),
                ticker=ticker,
                data=data,
                timestamp=timestamp,
                source=source,
                confidence=confidence,
            )
        except Exception as e:
            logger.error("Binary decode failed", error=str(e))
            return cls(type=EventType.HEARTBEAT)


# =====================================================
# Hızlı Olay Oluşturucular
# =====================================================

def create_tick_event(ticker: str, price: float, change: float, volume: int, source: str = "ingestion") -> CanonicalEvent:
    """Fiyat olayı oluştur."""
    return CanonicalEvent(
        type=EventType.TICK,
        ticker=ticker,
        data={"price": price, "change": change, "volume": volume},
        source=source,
    )

def create_signal_event(ticker: str, direction: str, confidence: float, target: float, stop_loss: float, reason: str = "") -> CanonicalEvent:
    """Sinyal olayı oluştur."""
    return CanonicalEvent(
        type=EventType.SIGNAL,
        ticker=ticker,
        data={"direction": direction, "target": target, "stop_loss": stop_loss, "reason": reason},
        confidence=confidence,
        source="intelligence",
    )

def create_alert_event(ticker: str, alert_type: str, message: str, severity: str = "INFO", value: float = 0, threshold: float = 0) -> CanonicalEvent:
    """Alarm olayı oluştur."""
    return CanonicalEvent(
        type=EventType.ALERT,
        ticker=ticker,
        data={"alert_type": alert_type, "message": message, "severity": severity, "value": value, "threshold": threshold},
        source="alerting",
    )

def create_regime_event(regime: str, confidence: float, vix: float = 0, breadth: float = 0) -> CanonicalEvent:
    """Piyasa rejimi olayı oluştur."""
    return CanonicalEvent(
        type=EventType.REGIME,
        data={"regime": regime, "vix": vix, "breadth": breadth},
        confidence=confidence,
        source="market_state",
    )
