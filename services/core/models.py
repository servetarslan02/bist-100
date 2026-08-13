"""ALPHA BIST - Data Models & Schemas"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum


# =====================================================
# Enums
# =====================================================

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TRIGGERED = "TRIGGERED"
    CANCELLED = "CANCELLED"


class MarketRegime(str, Enum):
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


class TimeHorizon(str, Enum):
    SHORT = "1-5D"
    MEDIUM = "1-4W"
    LONG = "1-6M"
    VERY_LONG = "6-24M"


# =====================================================
# Market Data Models
# =====================================================

class MarketTick(BaseModel):
    instrument_id: int
    ticker: str
    timestamp: datetime
    price: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    source: str = "yfinance"
    quality: float = 1.0


class OHLCV(BaseModel):
    instrument_id: int
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None


class OrderBookSnapshot(BaseModel):
    instrument_id: int
    timestamp: datetime
    bid_prices: List[float]
    bid_volumes: List[int]
    ask_prices: List[float]
    ask_volumes: List[int]
    spread: float
    mid_price: float


# =====================================================
# Asset State Models
# =====================================================

class AssetState(BaseModel):
    """Complete state of a single asset."""
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
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None

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
    """Global macro state."""
    timestamp: datetime
    geopolitical_risk: float = 0.0
    global_risk_appetite: float = 0.5
    usd_strength: float = 0.5
    us_rate_pressure: float = 0.5
    commodity_pressure: float = 0.5
    oil_pressure: float = 0.5
    turkey_macro_risk: float = 0.5
    vix_level: float = 20.0
    news_shock: float = 0.0
    emerging_market_risk: float = 0.5


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
    """Trading signal."""
    id: Optional[int] = None
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


# =====================================================
# Portfolio Models
# =====================================================

class Position(BaseModel):
    instrument_id: int
    ticker: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    weight_pct: float = 0.0
    entry_date: Optional[datetime] = None


class Portfolio(BaseModel):
    id: Optional[int] = None
    name: str
    initial_capital: float = 100000
    current_capital: float = 100000
    cash_balance: float = 100000
    invested_value: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    positions: List[Position] = Field(default_factory=list)
    is_paper: bool = True


# =====================================================
# Prediction & Outcome Models
# =====================================================

class Prediction(BaseModel):
    id: Optional[int] = None
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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Outcome(BaseModel):
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
    scenario_name: str
    market_change_pct: float
    portfolio_impact: Dict[str, Any]
    probability: float


class SimulationResult(BaseModel):
    id: Optional[int] = None
    name: str
    simulation_type: str
    parameters: Dict[str, Any]
    scenarios: List[ScenarioResult] = Field(default_factory=list)
    expected_return: float = 0.0
    expected_drawdown: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    status: str = "PENDING"


# =====================================================
# Alert Models
# =====================================================

class Alert(BaseModel):
    id: Optional[int] = None
    alert_type: str
    severity: RiskLevel
    title: str
    message: str
    instrument_id: Optional[int] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
