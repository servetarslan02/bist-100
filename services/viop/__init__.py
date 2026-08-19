"""
ALPHA BIST — VIOP (Vadeli İşlem ve Opsiyon Piyasası) Modülü

Modüller:
- enhanced_options: Black-Scholes, Greeks, IV, Options Chain, Strategies, Hedging, SPAN, Arbitrage, Risk, Backtest
- contract_catalog: VIOP sözleşme kataloğu (BIST resmi)
"""

from .enhanced_options import (
    # Pricing
    black_scholes,
    # Greeks
    calculate_greeks,
    # Implied Volatility
    implied_volatility,
    # Options Chain
    OptionsChain,
    OptionQuote,
    # Portfolio Greeks
    portfolio_greeks,
    PortfolioGreeks,
    PortfolioGreeksResult,
    # Strategies
    options_strategies,
    OptionsStrategies,
    StrategyResult,
    # Delta Hedging
    delta_hedger,
    DeltaHedger,
    DeltaHedgeResult,
    # SPAN Margin
    span_margin,
    SPANMarginCalculator,
    # Arbitrage
    futures_spot_arbitrage,
    FuturesSpotArbitrage,
    ArbitrageResult,
    # Parity
    check_put_call_parity,
    # Risk Integration
    viop_risk,
    VIOPRiskCalculator,
    # Backtest
    options_backtest,
    OptionsBacktestEngine,
    BacktestResult,
    BacktestTrade,
)

from .contract_catalog import (
    VIOPContractCatalog,
    VIOPContract,
    OptionContract,
    viop_catalog,
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
