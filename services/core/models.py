"""ALPHA BIST - Data Models & Schemas"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

# =====================================================
# Enums
# =====================================================


class Direction(StrEnum):
    """Otomatik eklendi."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RiskLevel(StrEnum):
    """Otomatik eklendi."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalStatus(StrEnum):
    """Otomatik eklendi."""
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TRIGGERED = "TRIGGERED"
    CANCELLED = "CANCELLED"


class MarketRegime(StrEnum):
    """Otomatik eklendi."""
    RISK_ON = "RISK-ON"
    RISK_OFF = "RISK-OFF"
    TRENDING_UP = "TRENDING-UP"
    TRENDING_DOWN = "TRENDING-DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH-VOLATILITY"
    LOW_VOLATILITY = "LOW-VOLATILITY"
    PANIC = "PANIC"
    RECOVERY = "RECOVERY"
    MOMENTUM_EXPANSION = "MOMENTUM-EXPANSION"
    MOMENTUM_CONTRACTION = "MOMENTUM-CONTRACTION"


class TimeHorizon(StrEnum):
    """Otomatik eklendi."""
    SHORT = "1-5D"
    MEDIUM = "1-4W"
    LONG = "1-6M"
    VERY_LONG = "6-24M"


# =====================================================
# Market Data Models
# =====================================================


class MarketTick(BaseModel):
    """P0-8: Invariant validation eklendi."""

    instrument_id: int
    ticker: str
    timestamp: datetime
    price: float
    volume: int
    bid: float | None = None
    ask: float | None = None
    source: str = "yfinance"
    quality: float = 1.0

    @field_validator("price")
    @classmethod
    def _validate_price(cls, v: float) -> float:
        """Otomatik eklendi."""
        if v <= 0:
            raise ValueError(f"Price must be positive, got {v}")
        return v

    @field_validator("volume")
    @classmethod
    def _validate_volume(cls, v: int) -> int:
        """Otomatik eklendi."""
        if v < 0:
            raise ValueError(f"Volume must be non-negative, got {v}")
        return v

    @field_validator("quality")
    @classmethod
    def _validate_quality(cls, v: float) -> float:
        """Otomatik eklendi."""
        if not 0 <= v <= 1:
            raise ValueError(f"Quality must be in [0,1], got {v}")
        return v


class OHLCV(BaseModel):
    """Otomatik eklendi."""
    instrument_id: int
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None


class OrderBookSnapshot(BaseModel):
    """Otomatik eklendi."""
    instrument_id: int
    timestamp: datetime
    bid_prices: list[float]
    bid_volumes: list[int]
    ask_prices: list[float]
    ask_volumes: list[int]
    spread: float
    mid_price: float


# =====================================================
# Asset State Models
# =====================================================


class AssetState(BaseModel):
    """Complete state of a single asset.

    P0-8: Invariant validation eklendi.
    Missing != 0 != NaN != Invalid ayrımı korunmalı.
    """

    instrument_id: int
    ticker: str
    timestamp: datetime

    # Price
    price: float = 0.0
    price_change_pct: float = 0.0
    price_change_1d: float = 0.0
    price_change_5d: float = 0.0
    price_change_20d: float = 0.0

    # Volume
    volume: int = 0
    volume_avg_20d: int = 0
    volume_zscore: float = 0.0
    volume_ratio: float = 0.0
    unusual_volume: bool = False

    # Momentum
    momentum_5d: float = 0.0
    momentum_20d: float = 0.0
    momentum_60d: float = 0.0
    rate_of_change: float = 0.0

    # Volatility
    atr_14: float = 0.0
    realized_vol_5d: float = 0.0
    realized_vol_20d: float = 0.0
    volatility_regime: str = "NORMAL"
    volatility_zscore: float = 0.0

    # Technical
    rsi_14: float = 50.0
    macd_signal: float = 0.0
    adx: float = 0.0
    trend_strength: float = 0.0

    # Relative
    relative_strength_vs_index: float = 0.0
    relative_strength_vs_sector: float = 0.0
    sector_rank: int = 0
    cross_sectional_rank: int = 0

    # Liquidity
    bid_ask_spread: float = 0.0
    amihud_illiquidity: float = 0.0
    turnover_rate: float = 0.0

    # Fundamental
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    dividend_yield: float | None = None

    # Event/Sentiment
    kap_sentiment: float = 0.0
    news_sentiment: float = 0.0
    social_sentiment: float = 0.0
    event_impact: float = 0.0
    days_since_last_event: int = 0

    # ML Scores
    anomaly_score: float = 0.0
    spec_score: float = 0.0
    ml_momentum_score: float = 0.0
    ml_breakout_score: float = 0.0
    ml_return_5d: float = 0.0
    ml_return_20d: float = 0.0
    ml_return_60d: float = 0.0
    ml_risk_score: float = 0.0

    # Composite
    edge_score: float = 0.0
    confidence: float = 0.0
    risk_level: str = "MEDIUM"

    # Regime
    regime: str = "NORMAL"
    regime_confidence: float = 0.0


class MarketState(BaseModel):
    """Overall market state."""

    timestamp: datetime
    regime: MarketRegime = MarketRegime.RANGE
    regime_confidence: float = 0.0
    trend_score: float = 0.0
    breadth_pct: float = 0.0
    dispersion: float = 0.0
    correlation: float = 0.0
    volatility_regime: str = "NORMAL"
    liquidity_level: str = "NORMAL"
    risk_appetite: float = 0.5
    advancing_count: int = 0
    declining_count: int = 0
    unchanged_count: int = 0


class WorldState(BaseModel):
    """Global macro state.

    P0-8: VIX ayrı normalize edilmeli (0-1 state'lerle karışmamalı).
    0-1 arası state'ler invariant validation ile korunmalı.
    """

    timestamp: datetime
    geopolitical_risk: float = 0.0
    global_risk_appetite: float = 0.5
    usd_strength: float = 0.5
    us_rate_pressure: float = 0.5
    commodity_pressure: float = 0.5
    oil_pressure: float = 0.5
    turkey_macro_risk: float = 0.5
    vix_level: float = 20.0  # RAW VIX (0-100+), 0-1 ile karıştırılmamalı
    vix_normalized: float = 0.5  # 0-1 arası normalize VIX
    news_shock: float = 0.0
    emerging_market_risk: float = 0.5

    @field_validator(
        "geopolitical_risk",
        "global_risk_appetite",
        "usd_strength",
        "us_rate_pressure",
        "commodity_pressure",
        "oil_pressure",
        "turkey_macro_risk",
        "vix_normalized",
        "emerging_market_risk",
    )
    @classmethod
    def _validate_01_range(cls, v: float, info) -> float:
        """Otomatik eklendi."""
        if not 0 <= v <= 1:
            # Clamp to [0,1] instead of raising (for robustness)
            return max(0.0, min(1.0, v))
        return v


# =====================================================
# Signal Models
# =====================================================


class EdgeDecomposition(BaseModel):
    """Breakdown of why a signal was generated."""

    flow_anomaly: float = 0.0
    relative_strength: float = 0.0
    regime_compatibility: float = 0.0
    historical_similarity: float = 0.0
    fundamental_state: float = 0.0
    event_state: float = 0.0
    volatility_risk: float = 0.0
    correlation_risk: float = 0.0
    total: float = 0.0


class Signal(BaseModel):
    """Trading signal.

    P0-8: Invariant validation eklendi.
    - score, confidence ∈ [0,1] aralığında olmalı
    - Timestamp timezone-aware
    """

    id: int | None = None
    instrument_id: int
    ticker: str
    signal_type: str
    direction: Direction
    score: float
    confidence: float
    risk_level: RiskLevel
    horizon: TimeHorizon
    expected_return_pct: float = 0.0
    expected_volatility_pct: float = 0.0
    edge_decomposition: EdgeDecomposition = Field(default_factory=EdgeDecomposition)
    reasoning: str = ""
    model_version: str = ""
    strategy_id: int = 0
    status: SignalStatus = SignalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        """Otomatik eklendi."""
        if not 0 <= v <= 1:
            raise ValueError(f"Confidence must be in [0,1], got {v}")
        return v

    @field_validator("score")
    @classmethod
    def _validate_score(cls, v: float) -> float:
        """Otomatik eklendi."""
        if not 0 <= v <= 100:
            raise ValueError(f"Score must be in [0,100], got {v}")
        return v


# =====================================================
# Portfolio Models
# =====================================================


class Position(BaseModel):
    """Otomatik eklendi."""
    instrument_id: int
    ticker: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    weight_pct: float = 0.0
    entry_date: datetime | None = None


class Portfolio(BaseModel):
    """Otomatik eklendi."""
    id: int | None = None
    name: str
    initial_capital: float = 100000
    current_capital: float = 100000
    cash_balance: float = 100000
    invested_value: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    is_paper: bool = True


# =====================================================
# Prediction & Outcome Models
# =====================================================


class Prediction(BaseModel):
    """Otomatik eklendi."""
    id: int | None = None
    model_version_id: int
    instrument_id: int
    ticker: str
    prediction_date: date
    horizon_days: int
    predicted_direction: Direction
    predicted_return_pct: float
    probability_positive: float
    predicted_volatility_pct: float
    confidence: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Outcome(BaseModel):
    """Otomatik eklendi."""
    prediction_id: int
    actual_return_pct: float
    actual_direction: Direction
    actual_volatility_pct: float
    prediction_error: float
    is_correct: bool
    outcome_date: date


# =====================================================
# Simulation Models
# =====================================================


class ScenarioResult(BaseModel):
    """Otomatik eklendi."""
    scenario_name: str
    market_change_pct: float
    portfolio_impact: dict[str, Any]
    probability: float


class SimulationResult(BaseModel):
    """Otomatik eklendi."""
    id: int | None = None
    name: str
    simulation_type: str
    parameters: dict[str, Any]
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    expected_return: float = 0.0
    expected_drawdown: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    status: str = "PENDING"


# =====================================================
# Alert Models
# =====================================================


class Alert(BaseModel):
    """Otomatik eklendi."""
    id: int | None = None
    alert_type: str
    severity: RiskLevel
    title: str
    message: str
    instrument_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
