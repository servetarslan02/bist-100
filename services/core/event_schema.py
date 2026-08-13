"""ALPHA BIST - Canonical Event Schema v1.1

Tüm olaylar bu standart formatta üretilir ve tüketilir.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class EventType(str, Enum):
    # Market
    MARKET_TICK = "market.tick"
    MARKET_TRADE = "market.trade"
    MARKET_QUOTE = "market.quote"
    MARKET_ORDERBOOK = "market.orderbook"

    # Events
    NEWS_RAW = "news.raw"
    NEWS_EVENT = "news.event"
    KAP_EVENT = "kap.event"
    MACRO_EVENT = "macro.event"
    SOCIAL_EVENT = "social.event"

    # State
    FEATURE_UPDATED = "feature.updated"
    STATE_UPDATED = "state.updated"
    MARKET_STATE_CHANGED = "market_state.changed"
    WORLD_STATE_CHANGED = "world_state.changed"
    IMPACT_PROPAGATED = "impact.propagated"

    # Signals
    SIGNAL_GENERATED = "signal.generated"
    ANOMALY_DETECTED = "anomaly.detected"
    REGIME_CHANGED = "regime.changed"

    # Simulation
    SIMULATION_REQUESTED = "simulation.requested"
    SIMULATION_COMPLETED = "simulation.completed"

    # Risk
    RISK_CHANGED = "risk.changed"
    RISK_ALERT = "risk.alert"
    KILL_SWITCH_TRIGGERED = "kill_switch.triggered"

    # Portfolio
    DECISION_CREATED = "decision.created"
    ORDER_PLACED = "order.placed"
    ORDER_FILLED = "order.filled"

    # Learning
    PREDICTION_CREATED = "prediction.created"
    OUTCOME_CREATED = "outcome.created"


class EventMetadata(BaseModel):
    provider: str = ""
    instrument_ids: List[int] = Field(default_factory=list)
    tickers: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    schema_version: str = "v1"


class CanonicalEvent(BaseModel):
    """Base event structure — tüm olaylar bu formata uymalıdır."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    schema_version: str = "v1"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = ""
    source_timestamp: Optional[datetime] = None
    ingest_timestamp: datetime = Field(default_factory=datetime.utcnow)
    quality: float = 1.0
    latency_ms: int = 0
    confidence: float = 1.0
    data: Dict[str, Any] = Field(default_factory=dict)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "CanonicalEvent":
        return cls.model_validate_json(json_str)


# =====================================================
# Typed Event Data Schemas
# =====================================================

class MarketTickData(BaseModel):
    instrument_id: int
    ticker: str
    price: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    trade_count: int = 0
    vwap: Optional[float] = None
    source: str = "yfinance"


class NewsEventData(BaseModel):
    news_id: str
    title: str
    body: str = ""
    url: str = ""
    language: str = "tr"
    entities: List[str] = Field(default_factory=list)
    instrument_ids: List[int] = Field(default_factory=list)
    event_class: str = "OTHER"  # MACRO | COMPANY | SECTOR | GEOPOLITICAL
    sentiment: float = 0.0
    importance: float = 0.0
    novelty: float = 0.0
    credibility: float = 1.0


class KAPEventData(BaseModel):
    kap_id: str
    ticker: str
    company_id: int
    announcement_type: str = ""
    title: str
    summary: str = ""
    is_price_sensitive: bool = False
    sentiment: float = 0.0
    importance: float = 0.0
    event_class: str = "OTHER"  # INVESTMENT | FINANCIAL_RESULT | DIVIDEND | CAPITAL_CHANGE | CONTRACT


class MacroEventData(BaseModel):
    macro_id: str
    indicator: str
    country: str = "TR"
    actual: float
    expected: Optional[float] = None
    previous: Optional[float] = None
    surprise: Optional[float] = None
    surprise_zscore: Optional[float] = None
    importance: float = 0.5
    source: str = "TCMB"


class SignalData(BaseModel):
    instrument_id: int
    ticker: str
    signal_type: str  # SPEC | MOMENTUM | BREAKOUT | VALUE | EVENT_DRIVEN
    direction: str  # LONG | SHORT | NEUTRAL
    score: float
    confidence: float
    risk_level: str  # LOW | MEDIUM | HIGH | CRITICAL
    horizon: str  # 1-5D | 1-4W | 1-6M | 6-24M
    expected_return_pct: float = 0.0
    expected_volatility_pct: float = 0.0
    edge_decomposition: Dict[str, float] = Field(default_factory=dict)
    reasoning: str = ""
    model_version: str = ""
    strategy_id: int = 0


class AnomalyData(BaseModel):
    instrument_id: int
    ticker: str
    anomaly_type: str
    severity: str  # LOW | MEDIUM | HIGH | CRITICAL
    score: float
    sigma: float
    description: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class ImpactPropagationData(BaseModel):
    source_event_id: str
    source_event_type: str
    propagation_chain: List[Dict[str, Any]] = Field(default_factory=list)
    affected_instruments: List[Dict[str, Any]] = Field(default_factory=list)
    world_state_delta: Dict[str, float] = Field(default_factory=dict)
