"""
ALPHA BIST — API Response Schemas (Pydantic Models)

Tüm API endpoint'leri için standart response modelleri.
Bu modeller:
- OpenAPI/Swagger dokümantasyonunu otomatik oluşturur
- Response validasyonu sağlar
- API sözleşmesini tanımlar
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# =====================================================
# BASE RESPONSES
# =====================================================


class BaseResponse(BaseModel):
    """Tüm API response'ları için base model."""

    success: bool = True
    message: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Hata response modeli."""

    success: bool = False
    error: str
    detail: str | None = None
    status_code: int = 500
    request_id: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PaginatedResponse(BaseModel):
    """Sayfalı response modeli."""

    success: bool = True
    data: list[Any]
    total: int
    page: int = 1
    page_size: int = 50


# =====================================================
# MARKET DATA
# =====================================================


class InstrumentInfo(BaseModel):
    """Hisse bilgisi."""

    ticker: str
    name: str | None = None
    sector: str | None = None
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0


class OHLCVData(BaseModel):
    """OHLCV verisi."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketStateResponse(BaseModel):
    """Piyasa durumu."""

    regime: str = "UNKNOWN"
    confidence: float = 0.0
    istanbul_time: str | None = None
    is_trading: bool = False
    is_open: bool = False


class RadarResponse(BaseModel):
    """Piyasa radarı."""

    data: list[dict[str, Any]]
    count: int
    errors: int = 0
    status: str = "ok"
    cached_at: str | None = None
    from_cache: bool = False


# =====================================================
# PORTFOLIO
# =====================================================


class PositionInfo(BaseModel):
    """Pozisyon bilgisi."""

    ticker: str
    direction: str
    quantity: int
    entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


class PortfolioSummary(BaseModel):
    """Portföy özeti."""

    cash: float
    invested_value: float
    total_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    realized_pnl_total: float
    commission_total: float
    positions_count: int
    positions: list[PositionInfo]


class TradeInfo(BaseModel):
    """Trade bilgisi."""

    trade_id: str
    ticker: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    commission: float
    holding_days: int


class PortfolioMetrics(BaseModel):
    """Portföy metrikleri."""

    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate_pct: float
    total_trades: int
    profit_factor: float
    total_commission: float


# =====================================================
# RISK
# =====================================================


class RiskOverview(BaseModel):
    """Risk özeti."""

    risk_level: str
    max_position_pct: float
    sector_concentration: float
    portfolio_correlation: float
    max_drawdown: float
    var_95: float
    cvar_95: float
    hhi: float


class VaRResult(BaseModel):
    """VaR sonucu."""

    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    method: str
    sample_size: int
    portfolio_value: float


# =====================================================
# SCANNER
# =====================================================


class OpportunityInfo(BaseModel):
    """Fırsat bilgisi."""

    ticker: str
    tier: int
    opportunity_score: float
    momentum: float
    volume_anomaly: float
    breakout: float
    volatility: float
    relative_strength: float
    price: float
    change_pct: float
    escalated: bool


class ScannerStatus(BaseModel):
    """Scanner durumu."""

    total_assets: int
    tier_0_continuous: int
    tier_1_quant: int
    tier_2_opportunity: int
    tier_3_deep: int
    tier_4_gemma: int
    tier_5_decision: int
    regime: str
    regime_confidence: float
    scan_count: int


# =====================================================
# LEARNING
# =====================================================


class LearningStatus(BaseModel):
    """Öğrenme durumu."""

    total_cycles: int
    active_version: str | None = None
    champion_version: str | None = None
    drift_detected: bool = False
    retrain_needed: bool = False


class ModelInfo(BaseModel):
    """Model bilgisi."""

    model_name: str
    version: str
    trust_score: float
    last_trained: str | None = None
    status: str = "active"


# =====================================================
# INTELLIGENCE
# =====================================================


class RegimeInfo(BaseModel):
    """Rejim bilgisi."""

    regime: str
    confidence: float
    description: str | None = None


class SimulationResult(BaseModel):
    """Simülasyon sonucu."""

    ticker: str
    expected_return: float
    volatility: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    prob_positive: float
    var_95: float
    cvar_95: float


# =====================================================
# BACKTEST
# =====================================================


class BacktestResult(BaseModel):
    """Backtest sonucu."""

    run_id: str
    start_date: str
    end_date: str
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    profit_factor: float


# =====================================================
# VIOP
# =====================================================


class OptionPrice(BaseModel):
    """Opsiyon fiyatı."""

    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


class GreeksResult(BaseModel):
    """Greeks sonucu."""

    total_delta: float
    total_gamma: float
    total_theta: float
    total_vega: float
    total_rho: float
    n_positions: int
    delta_neutral: bool


# =====================================================
# SYSTEM
# =====================================================


class SystemStatus(BaseModel):
    """Sistem durumu."""

    status: str
    uptime_hours: float
    predictions_today: int
    accuracy_today: float
    drift_detected: bool
    retrain_needed: bool


class HealthCheck(BaseModel):
    """Health check."""

    status: str = "ok"
    version: str = "1.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    services: dict[str, str] = {}
