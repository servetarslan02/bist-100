"""ALPHA BIST — Risk Management Configuration.

All risk parameters are centralized here.
Hardcoded values are PROHIBITED — everything is read from here.
"""

from pydantic import BaseModel, Field


class RiskManagerConfig(BaseModel):
    """Risk Manager parametreleri."""

    max_position_pct: float = Field(default=0.10, description="Tek hisse max ağırlık (%10)")
    max_sector_pct: float = Field(default=0.25, description="Tek sektör max ağırlık (%25)")
    max_drawdown_pct: float = Field(default=0.15, description="Max drawdown eşiği (%15)")
    stop_loss_pct: float = Field(default=0.07, description="Stop loss eşiği (%7)")
    trailing_stop_pct: float = Field(default=0.05, description="Trailing stop eşiği (%5)")
    max_open_positions: int = Field(default=15, description="Max açık pozisyon sayısı")
    min_cash_ratio: float = Field(default=0.10, description="Min nakit oranı (%10)")
    volatility_cap: float = Field(default=0.50, description="Max volatilite eşiği (%50)")
    correlation_threshold: float = Field(default=0.70, description="Korelasyon eşiği")


class BacktestConfig(BaseModel):
    """Backtest motoru parametreleri."""

    base_slippage_pct: float = Field(default=0.05, description="Baz slippage oranı (%)")
    max_participation: float = Field(default=0.10, description="ADV max katılım oranı (%10)")
    default_commission_pct: float = Field(default=0.0015, description="Varsayılan komisyon (%0.15)")
    min_commission_tl: float = Field(default=1.0, description="Min komisyon (TL)")


class PortfolioOptimizerConfig(BaseModel):
    """Portföy optimizasyon kısıtları."""

    max_position_pct: float = Field(default=0.10, description="Tek hissede max ağırlık (%10)")
    min_position_pct: float = Field(default=0.015, description="Min pozisyon eşiği — tozluluk filtresi (%1.5)")
    max_sector_pct: float = Field(default=0.35, description="Sektör tavanı (%35)")
    max_total_exposure: float = Field(default=0.92, description="Max maruziyet (%92)")
    min_cash_buffer_pct: float = Field(default=0.08, description="Zorunlu nakit rezervi (%8)")
    turnover_penalty_lambda: float = Field(default=0.015, description="Turnover ceza katsayısı")
    transaction_cost_pct: float = Field(default=0.0015, description="İşlem maliyeti (%0.15)")
    hysteresis_threshold: float = Field(default=0.02, description="Hysteresis eşiği (%2)")
    l2_regularization: float = Field(default=0.002, description="L2 regularization cezası")


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker parametreleri."""

    failure_threshold: int = Field(default=5, description="Failure eşiği")
    recovery_timeout_seconds: int = Field(default=60, description="Recovery timeout (saniye)")


# Singleton instances
risk_config = RiskManagerConfig()
backtest_config = BacktestConfig()
portfolio_config = PortfolioOptimizerConfig()
circuit_breaker_config = CircuitBreakerConfig()
