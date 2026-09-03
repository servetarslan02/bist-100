"""
ALPHA BIST — Agent JSON Schemas v1.0

Structured output şemaları — hallucination azaltır.
Her agent rolü için beklenen JSON formatı tanımlı.
"""

from enum import Enum, StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class Direction(StrEnum):
    """Standart agent çıktı şeması."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    NO_TRADE = "NO_TRADE"


class RiskLevel(StrEnum):
    """metod metodu."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def _normalize_confidence(v) -> float | int:
    """Confidence değerini 0-1 aralığına normalize et."""
    if isinstance(v, (int, float)) and v > 1:
        return v / 100
    return v


class AgentOutputSchema(BaseModel):
    """Standart agent çıktı şeması."""

    direction: Direction = Direction.NEUTRAL
    confidence: float = Field(default=0.5)
    score: float = Field(default=50.0, ge=0.0, le=100.0)
    reasoning: str = ""
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source: str = "llm"

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v) -> float | int:
        """validate_confidence metodu."""
        return _normalize_confidence(v)


class TechnicalOutputSchema(AgentOutputSchema):
    """Teknik analiz agent çıktısı."""

    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    trend: str = "NEUTRAL"  # UP, DOWN, NEUTRAL
    momentum: str = "NEUTRAL"  # STRONG, WEAK, NEUTRAL


class FundamentalOutputSchema(AgentOutputSchema):
    """Fundamental analiz agent çıktısı."""

    valuation: str = "FAIR"  # UNDERVALUED, OVERVALUED, FAIR
    quality_score: float = Field(default=50.0, ge=0.0, le=100.0)
    growth_score: float = Field(default=50.0, ge=0.0, le=100.0)
    key_metrics: dict[str, float] = Field(default_factory=dict)


class NewsOutputSchema(AgentOutputSchema):
    """Haber/KAP analiz agent çıktısı."""

    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    event_count: int = 0
    key_events: list[str] = Field(default_factory=list)
    sentiment_trend: str = "STABLE"  # IMPROVING, DETERIORATING, STABLE


class MacroOutputSchema(AgentOutputSchema):
    """Makro analiz agent çıktısı."""

    regime: str = "UNKNOWN"  # RISK_ON, RISK_OFF, NEUTRAL, TRANSITION
    macro_score: float = Field(default=50.0, ge=0.0, le=100.0)
    key_factors: list[str] = Field(default_factory=list)
    fx_impact: str = "NEUTRAL"  # POSITIVE, NEGATIVE, NEUTRAL


class DebateArgumentSchema(BaseModel):
    """Tartışma argüman şeması."""

    position: Direction
    confidence: float = Field(default=0.5)
    main_argument: str = ""
    evidence: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    conclusion: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v) -> float | int:
        """validate_confidence metodu."""
        return _normalize_confidence(v)


class RiskAssessmentSchema(BaseModel):
    """Risk değerlendirme şeması."""

    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_score: float = Field(default=50.0, ge=0.0, le=100.0)
    approved: bool = False  # Fail-closed: LLM onaylamazsa reddet
    veto_reason: str | None = None
    risk_factors: list[str] = Field(default_factory=list)
    max_position_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    stop_loss_pct: float = Field(default=5.0, ge=0.0, le=100.0)


class SynthesisResultSchema(BaseModel):
    """Sentez sonuç şeması."""

    ticker: str
    final_direction: Direction = Direction.NEUTRAL
    final_confidence: float = Field(default=0.0)
    weighted_score: float = Field(default=50.0, ge=0.0, le=100.0)
    consensus_reached: bool = True
    debate_occurred: bool = False
    risk_approved: bool = True
    agent_summary: dict[str, Any] = Field(default_factory=dict)
    conflict_analysis: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @field_validator("final_confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v) -> float | int:
        """validate_confidence metodu."""
        return _normalize_confidence(v)


class AgentMessageSchema(BaseModel):
    """Agent iletişim mesaj şeması."""

    sender: str
    receiver: str
    task_id: str
    message_type: str  # REQUEST, RESPONSE, DEBATE, ALERT, CONTEXT
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
    priority: str = "NORMAL"  # LOW, NORMAL, HIGH, CRITICAL


def validate_agent_output(data: dict[str, Any], schema_class=None) -> tuple:
    """Agent çıktısını doğrula.

    Returns: (is_valid, parsed_data, errors)
    """
    if schema_class is None:
        schema_class = AgentOutputSchema

    try:
        parsed = schema_class(**data)
        return True, parsed.model_dump(), []
    except Exception as e:
        errors = [str(e)]
        # Fallback: temel alanları kontrol et ama validation başarısız
        # direction geçerli olsa bile diğer alanlar doğrulanmadı → False
        return False, data, errors
