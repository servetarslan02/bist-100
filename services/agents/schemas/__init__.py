"""ALPHA BIST — Agent JSON Şemaları Modülü.

Bu modül, Alpha BIST multi-agent mimarisindeki tüm uzman agent'lar (Teknik, Temel,
Haber/KAP, Makro, Portföy, Senaryo, Backtest, Risk, Münazara ve Sentez) için Pydantic v2
tabanlı tip-güvenli yapılandırılmış çıktı şemalarını (Structured Output) tanımlar.
LLM halüsinasyonlarını minimize eder, sınır değerlerini ve güven aralıklarını otomatik
normalize eder, fail-closed doğrulama mekanizmaları sağlar.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "Direction",
    "RiskLevel",
    "MarketRegime",
    "ValuationStatus",
    "TrendDirection",
    "RebalanceUrgency",
    "AgentOutputSchema",
    "TechnicalOutputSchema",
    "FundamentalOutputSchema",
    "ValuationOutputSchema",
    "NewsOutputSchema",
    "MacroOutputSchema",
    "PortfolioOutputSchema",
    "ScenarioOutputSchema",
    "BacktestOutputSchema",
    "DebateArgumentSchema",
    "RiskAssessmentSchema",
    "SynthesisResultSchema",
    "AgentMessageSchema",
    "get_schema_for_role",
    "validate_agent_output",
]


class Direction(StrEnum):
    """Piyasa yön kararları — LONG, SHORT, NEUTRAL, NO_TRADE."""

    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    NO_TRADE = "NO_TRADE"


class RiskLevel(StrEnum):
    """Risk seviyesi sınıflandırması — LOW, MEDIUM, HIGH, CRITICAL."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MarketRegime(StrEnum):
    """Makro piyasa rejim sınıflandırması."""

    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"
    TRANSITION = "TRANSITION"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class ValuationStatus(StrEnum):
    """Temel analiz değerleme durumu."""

    UNDERVALUED = "UNDERVALUED"
    FAIR = "FAIR"
    OVERVALUED = "OVERVALUED"
    DISTRESSED = "DISTRESSED"


class TrendDirection(StrEnum):
    """Teknik analiz trend yönü."""

    STRONG_UP = "STRONG_UP"
    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"
    STRONG_DOWN = "STRONG_DOWN"


class RebalanceUrgency(StrEnum):
    """Portföy yeniden dengeleme aciliyeti."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    IMMEDIATE = "IMMEDIATE"


def _normalize_confidence(v: Any) -> float:
    """Güven (confidence) skorunu [0.0, 1.0] aralığına güvenle normalize eder.

    Args:
        v: Sayısal veya dönüştürülebilir güven değeri (0-100 veya 0-1).

    Returns:
        float: 0.0 ile 1.0 aralığında sınırlandırılmış güven skoru.
    """
    if v is None:
        return 0.5
    try:
        val = float(v)
    except (ValueError, TypeError):
        return 0.5

    if math.isnan(val) or math.isinf(val):
        return 0.5

    if val > 1.0:
        val = val / 100.0

    return max(0.0, min(1.0, val))


def _normalize_score(v: Any, default: float = 50.0) -> float:
    """Puan değerini [0.0, 100.0] aralığına güvenle sınırlar.

    Args:
        v: Giriş puan değeri.
        default: Hatalı veya eksik veri durumundaki varsayılan puan.

    Returns:
        float: 0.0 ile 100.0 aralığında sınırlandırılmış puan.
    """
    if v is None:
        return default
    try:
        val = float(v)
    except (ValueError, TypeError):
        return default

    if math.isnan(val) or math.isinf(val):
        return default

    return max(0.0, min(100.0, val))


class AgentOutputSchema(BaseModel):
    """Standart agent karar ve analiz çıktısı temel şeması."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    direction: Direction = Direction.NEUTRAL
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    score: float = Field(default=50.0, ge=0.0, le=100.0)
    reasoning: str = ""
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    source: str = "llm"

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v: Any) -> float:
        """Güven skorunu 0-1 aralığına normalize eder."""
        return _normalize_confidence(v)

    @field_validator("score", mode="before")
    @classmethod
    def validate_score(cls, v: Any) -> float:
        """Skoru 0-100 aralığına normalize eder."""
        return _normalize_score(v, default=50.0)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(direction={self.direction.value!r}, "
            f"confidence={self.confidence:.2f}, score={self.score:.1f})"
        )


class TechnicalOutputSchema(AgentOutputSchema):
    """Teknik analiz agent'ı yapılandırılmış çıktısı."""

    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    trend: str = TrendDirection.NEUTRAL.value
    momentum: str = "NEUTRAL"
    rsi: float | None = None
    macd_signal: str = "NEUTRAL"

    @field_validator("support_levels", "resistance_levels", mode="before")
    @classmethod
    def clean_levels(cls, v: Any) -> list[float]:
        """Geçersiz veya NaN sayıları temizler."""
        if not isinstance(v, list):
            return []
        cleaned: list[float] = []
        for x in v:
            try:
                num = float(x)
                if not math.isnan(num) and not math.isinf(num) and num > 0:
                    cleaned.append(round(num, 4))
            except (ValueError, TypeError):
                continue
        return sorted(cleaned)


class FundamentalOutputSchema(AgentOutputSchema):
    """Temel analiz agent'ı yapılandırılmış çıktısı."""

    valuation: str = ValuationStatus.FAIR.value
    quality_score: float = Field(default=50.0, ge=0.0, le=100.0)
    growth_score: float = Field(default=50.0, ge=0.0, le=100.0)
    financial_health: str = "GOOD"
    key_metrics: dict[str, float] = Field(default_factory=dict)

    @field_validator("quality_score", "growth_score", mode="before")
    @classmethod
    def clean_sub_scores(cls, v: Any) -> float:
        """Alt puanları normalize eder."""
        return _normalize_score(v, default=50.0)


class ValuationOutputSchema(AgentOutputSchema):
    """İskonto ve çarpan değerleme agent'ı yapılandırılmış çıktısı."""

    fair_value: float = Field(default=0.0, ge=0.0)
    upside_potential: float = Field(default=0.0)
    valuation_status: str = ValuationStatus.FAIR.value
    method: str = "dcf_multiple_blend"
    wacc: float | None = None
    terminal_growth: float | None = None
    target_multiple: float | None = None

    @field_validator("fair_value", mode="before")
    @classmethod
    def clean_fair_value(cls, v: Any) -> float:
        """Adil değer fiyatını doğrular ve negatif olmasını engeller."""
        if v is None:
            return 0.0
        try:
            val = float(v)
            return 0.0 if math.isnan(val) or math.isinf(val) or val < 0 else round(val, 2)
        except (ValueError, TypeError):
            return 0.0


class NewsOutputSchema(AgentOutputSchema):
    """Haber, KAP ve sosyal medya analiz agent'ı yapılandırılmış çıktısı."""

    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    event_count: int = Field(default=0, ge=0)
    key_events: list[str] = Field(default_factory=list)
    sentiment_trend: str = "STABLE"
    kap_material_events: list[str] = Field(default_factory=list)

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def clean_sentiment(cls, v: Any) -> float:
        """Duygu skorunu [-1.0, 1.0] aralığında sınırlar."""
        if v is None:
            return 0.0
        try:
            val = float(v)
            if math.isnan(val) or math.isinf(val):
                return 0.0
            return max(-1.0, min(1.0, val))
        except (ValueError, TypeError):
            return 0.0


class MacroOutputSchema(AgentOutputSchema):
    """Makroekonomi ve piyasa rejimi agent'ı yapılandırılmış çıktısı."""

    regime: str = MarketRegime.UNKNOWN.value
    macro_score: float = Field(default=50.0, ge=0.0, le=100.0)
    key_factors: list[str] = Field(default_factory=list)
    fx_impact: str = "NEUTRAL"
    interest_rate_bias: str = "NEUTRAL"

    @field_validator("macro_score", mode="before")
    @classmethod
    def clean_macro_score(cls, v: Any) -> float:
        """Makro puanını normalize eder."""
        return _normalize_score(v, default=50.0)


class PortfolioOutputSchema(AgentOutputSchema):
    """Portföy optimizasyonu ve pozisyon tahsisi agent'ı çıktısı."""

    target_weight_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    recommended_action: str = "HOLD"
    max_position_size_tl: float = Field(default=0.0, ge=0.0)
    urgency: str = RebalanceUrgency.MEDIUM.value
    cash_reserve_pct: float = Field(default=10.0, ge=0.0, le=100.0)


class ScenarioOutputSchema(AgentOutputSchema):
    """Senaryo ve stres analizi agent'ı çıktısı."""

    bull_case_probability: float = Field(default=0.33, ge=0.0, le=1.0)
    base_case_probability: float = Field(default=0.34, ge=0.0, le=1.0)
    bear_case_probability: float = Field(default=0.33, ge=0.0, le=1.0)
    target_price_bull: float | None = None
    target_price_base: float | None = None
    target_price_bear: float | None = None
    max_drawdown_estimate_pct: float = Field(default=10.0, ge=0.0, le=100.0)


class BacktestOutputSchema(AgentOutputSchema):
    """Strateji geriye dönük test (Backtest) doğrulama çıktısı."""

    win_rate_pct: float = Field(default=50.0, ge=0.0, le=100.0)
    profit_factor: float = Field(default=1.0, ge=0.0)
    max_drawdown_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    sample_trades_count: int = Field(default=0, ge=0)
    sharpe_ratio: float = Field(default=0.0)


class DebateArgumentSchema(BaseModel):
    """Boğa/Ayı münazara argüman şeması."""

    model_config = ConfigDict(extra="ignore")

    position: Direction
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    main_argument: str = ""
    evidence: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    conclusion: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v: Any) -> float:
        """Güven skorunu normalize eder."""
        return _normalize_confidence(v)

    def __repr__(self) -> str:
        return f"DebateArgumentSchema(position={self.position.value!r}, confidence={self.confidence:.2f})"


class RiskAssessmentSchema(BaseModel):
    """Risk denetleyicisi değerlendirme şeması (Fail-Closed)."""

    model_config = ConfigDict(extra="ignore")

    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_score: float = Field(default=50.0, ge=0.0, le=100.0)
    approved: bool = False  # Fail-closed: LLM açıkça onaylamazsa daima reddet
    veto_reason: str | None = None
    risk_factors: list[str] = Field(default_factory=list)
    max_position_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    stop_loss_pct: float = Field(default=5.0, ge=0.0, le=100.0)

    @field_validator("risk_score", mode="before")
    @classmethod
    def clean_risk_score(cls, v: Any) -> float:
        """Risk puanını normalize eder."""
        return _normalize_score(v, default=50.0)

    def __repr__(self) -> str:
        return (
            f"RiskAssessmentSchema(risk_level={self.risk_level.value!r}, "
            f"approved={self.approved}, max_position_pct={self.max_position_pct}%)"
        )


class SynthesisResultSchema(BaseModel):
    """Nihai pipeline karar sentezi şeması."""

    model_config = ConfigDict(extra="ignore")

    ticker: str
    final_direction: Direction = Direction.NEUTRAL
    final_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
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
    def validate_confidence(cls, v: Any) -> float:
        """Nihai güven skorunu normalize eder."""
        return _normalize_confidence(v)

    @field_validator("weighted_score", mode="before")
    @classmethod
    def clean_score(cls, v: Any) -> float:
        """Ağırlıklı skoru normalize eder."""
        return _normalize_score(v, default=50.0)

    def __repr__(self) -> str:
        return (
            f"SynthesisResultSchema(ticker={self.ticker!r}, direction={self.final_direction.value!r}, "
            f"confidence={self.final_confidence:.2f}, risk_approved={self.risk_approved})"
        )


class AgentMessageSchema(BaseModel):
    """Ajanlar arası iletişim veriyolu mesaj şeması."""

    model_config = ConfigDict(extra="ignore")

    sender: str
    receiver: str
    task_id: str
    message_type: str  # REQUEST, RESPONSE, DEBATE, ALERT, CONTEXT
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None
    priority: str = "NORMAL"  # LOW, NORMAL, HIGH, CRITICAL

    def __repr__(self) -> str:
        return (
            f"AgentMessageSchema(from={self.sender!r} to={self.receiver!r}, "
            f"type={self.message_type!r}, priority={self.priority!r})"
        )


_ROLE_SCHEMA_MAP: dict[str, type[AgentOutputSchema]] = {
    "TECHNICAL": TechnicalOutputSchema,
    "FUNDAMENTAL": FundamentalOutputSchema,
    "VALUATION": ValuationOutputSchema,
    "NEWS": NewsOutputSchema,
    "MACRO": MacroOutputSchema,
    "PORTFOLIO": PortfolioOutputSchema,
    "SCENARIO": ScenarioOutputSchema,
    "BACKTEST": BacktestOutputSchema,
    "RESEARCH": AgentOutputSchema,
    "SYNTHESIS": AgentOutputSchema,
}


def get_schema_for_role(role: str) -> type[AgentOutputSchema]:
    """Verilen agent rolüne uygun Pydantic çıktı şemasını döner.

    Args:
        role: Ajan rol adı (örn: 'TECHNICAL', 'FUNDAMENTAL').

    Returns:
        type[AgentOutputSchema]: Eşleşen Pydantic model sınıfı.
    """
    normalized_role = str(role).strip().upper()
    return _ROLE_SCHEMA_MAP.get(normalized_role, AgentOutputSchema)


def validate_agent_output(
    data: dict[str, Any],
    schema_class: type[BaseModel] | None = None,
) -> tuple[bool, dict[str, Any], list[str]]:
    """Agent çıktısını belirtilen veya varsayılan şemaya göre doğrular.

    Fail-closed prensibiyle çalışır: Doğrulama başarısız olursa is_valid False döner,
    hatalar ayrıntılı bir liste halinde raporlanır.

    Args:
        data: Doğrulanacak ham sözlük çıktısı.
        schema_class: Kullanılacak Pydantic şema sınıfı (varsayılan: AgentOutputSchema).

    Returns:
        tuple[bool, dict[str, Any], list[str]]:
            - bool: Doğrulama başarılı mı (is_valid).
            - dict[str, Any]: Doğrulanmış veya ham veri.
            - list[str]: Varsa doğrulama hata mesajları listesi.
    """
    target_schema = schema_class or AgentOutputSchema

    if not isinstance(data, dict):
        return False, {}, [f"Beklenen veri tipi dict, alınan: {type(data).__name__}"]

    try:
        parsed = target_schema.model_validate(data)
        return True, parsed.model_dump(), []
    except Exception as exc:
        errors = [str(exc)]
        return False, data, errors
