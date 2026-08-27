"""
ALPHA BIST — VIOP (Vadeli İşlem ve Opsiyon Piyasası) Modülü

Modüller:
- enhanced_options: Black-Scholes, Greeks, IV, Options Chain, Strategies, Hedging, SPAN, Arbitrage, Risk, Backtest
- contract_catalog: VIOP sözleşme kataloğu (BIST resmi)
"""

from .contract_catalog import (
    OptionContract,
    VIOPContract,
    VIOPContractCatalog,
    viop_catalog,
)
from .enhanced_options import (
    ArbitrageResult,
    BacktestResult,
    BacktestTrade,
    DeltaHedger,
    DeltaHedgeResult,
    FuturesSpotArbitrage,
    OptionQuote,
    OptionsBacktestEngine,
    # Options Chain
    OptionsChain,
    OptionsStrategies,
    PortfolioGreeks,
    PortfolioGreeksResult,
    SPANMarginCalculator,
    StrategyResult,
    VIOPRiskCalculator,
    # Pricing
    black_scholes,
    # Greeks
    calculate_greeks,
    # Parity
    check_put_call_parity,
    # Delta Hedging
    delta_hedger,
    # Arbitrage
    futures_spot_arbitrage,
    # Implied Volatility
    implied_volatility,
    # Backtest
    options_backtest,
    # Strategies
    options_strategies,
    # Portfolio Greeks
    portfolio_greeks,
    # SPAN Margin
    span_margin,
    # Risk Integration
    viop_risk,
)

__all__ = [
    # Pricing
    "black_scholes",
    # Greeks
    "calculate_greeks",
    # IV
    "implied_volatility",
    # Chain
    "OptionsChain",
    "OptionQuote",
    # Portfolio Greeks
    "portfolio_greeks",
    "PortfolioGreeks",
    "PortfolioGreeksResult",
    # Strategies
    "options_strategies",
    "OptionsStrategies",
    "StrategyResult",
    # Hedging
    "delta_hedger",
    "DeltaHedger",
    "DeltaHedgeResult",
    # Margin
    "span_margin",
    "SPANMarginCalculator",
    # Arbitrage
    "futures_spot_arbitrage",
    "FuturesSpotArbitrage",
    "ArbitrageResult",
    # Parity
    "check_put_call_parity",
    # Risk
    "viop_risk",
    "VIOPRiskCalculator",
    # Backtest
    "options_backtest",
    "OptionsBacktestEngine",
    "BacktestResult",
    "BacktestTrade",
    # Catalog
    "VIOPContractCatalog",
    "VIOPContract",
    "OptionContract",
    "viop_catalog",
]
