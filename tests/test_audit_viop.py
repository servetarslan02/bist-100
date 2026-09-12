"""
ALPHA BIST — VIOP ve Opsiyon Modülü Kapsamlı Denetim ve Doğrulama Testleri
"""

from datetime import date

from services.viop import (
    BacktestTrade,
    OptionContract,
    OptionQuote,
    OptionsChain,
    black_scholes,
    calculate_greeks,
    check_put_call_parity,
    delta_hedger,
    futures_spot_arbitrage,
    implied_volatility,
    options_backtest,
    options_strategies,
    portfolio_greeks,
    span_margin,
    viop_catalog,
    viop_risk,
)
from services.viop.hedging import hedge_portfolio
from services.viop.margin import calculate_span_margin
from services.viop.strategies import create_covered_call, create_protective_put


def test_black_scholes_and_greeks():
    """Black-Scholes fiyatlama ve Greeks hesaplaması doğrulaması."""
    # Call opsiyonu fiyatı
    call_price = black_scholes(S=100.0, K=100.0, T=1.0, r=0.15, sigma=0.20, option_type="call")
    assert call_price > 0.0

    # Put opsiyonu fiyatı
    put_price = black_scholes(S=100.0, K=100.0, T=1.0, r=0.15, sigma=0.20, option_type="put")
    assert put_price > 0.0

    # Greeks
    greeks = calculate_greeks(S=100.0, K=100.0, T=1.0, r=0.15, sigma=0.20, option_type="call")
    assert 0.0 < greeks["delta"] < 1.0
    assert greeks["gamma"] > 0.0
    assert greeks["vega"] > 0.0

    # Put-Call Parity
    parity = check_put_call_parity(call_price=call_price, put_price=put_price, spot_price=100.0, strike=100.0, r=0.15, T=1.0)
    assert "deviation" in parity
    assert parity["arbitrage_opportunity"] is False


def test_implied_volatility():
    """Implied Volatility hesaplayıcısı ve __repr__ doğrulaması."""
    assert "ImpliedVolatility" in repr(implied_volatility)

    # 100 TL spot, 100 TL strike, 1 yıl, %15 r, %20 sigma için hesaplanan fiyat
    call_price = black_scholes(S=100.0, K=100.0, T=1.0, r=0.15, sigma=0.20, option_type="call")
    iv = implied_volatility.calculate(market_price=call_price, S=100.0, K=100.0, T=1.0, r=0.15, option_type="call")
    assert abs(iv - 0.20) < 1e-4


def test_options_chain_and_quotes():
    """OptionQuote ve OptionsChain veri modelleri ve __repr__ doğrulaması."""
    quote = OptionQuote(
        strike=105.0,
        expiry=date(2026, 12, 31),
        option_type="call",
        bid=5.20,
        ask=5.60,
        last=5.40,
        volume=120,
        implied_vol=0.22,
    )
    assert "OptionQuote" in repr(quote)
    assert quote.mid == 5.40
    assert abs(quote.spread - 0.40) < 1e-5
    assert quote.spread_pct > 0.0

    chain = OptionsChain(underlying="THYAO", spot_price=300.0, risk_free_rate=0.15)
    assert "OptionsChain" in repr(chain)
    chain.add_quote(quote)
    assert len(chain.get_strikes()) == 1
    fetched = chain.get_quote(strike=105.0, expiry=date(2026, 12, 31), option_type="call")
    assert fetched is not None
    assert fetched.strike == 105.0


def test_portfolio_greeks():
    """PortfolioGreeks, PortfolioGreeksResult ve aggregation."""
    assert "PortfolioGreeks" in repr(portfolio_greeks)

    positions = [
        {
            "option_type": "call",
            "S": 100.0,
            "K": 100.0,
            "T": 0.5,
            "r": 0.15,
            "sigma": 0.20,
            "quantity": 10,
            "side": "long",
        },
        {
            "option_type": "put",
            "S": 100.0,
            "K": 95.0,
            "T": 0.5,
            "r": 0.15,
            "sigma": 0.25,
            "quantity": 5,
            "side": "short",
        },
    ]
    res = portfolio_greeks.aggregate(positions)
    assert "PortfolioGreeksResult" in repr(res)
    d = res.to_dict()
    assert "total_delta" in d
    assert d["n_positions"] == 2


def test_options_strategies():
    """OptionsStrategies ve StrategyResult doğrulaması."""
    assert "OptionsStrategies" in repr(options_strategies)

    cc = options_strategies.covered_call(spot=100.0, call_strike=105.0, call_premium=4.0, shares=100)
    assert "StrategyResult" in repr(cc)
    d = cc.to_dict()
    assert d["strategy"] == "COVERED_CALL"
    assert d["max_profit"] > 0.0

    # Wrapper test
    wrapper_cc = create_covered_call(spot=100.0, call_strike=105.0, call_premium=4.0)
    assert wrapper_cc["strategy"] == "COVERED_CALL"

    wrapper_pp = create_protective_put(spot=100.0, put_strike=95.0, put_premium=3.0)
    assert wrapper_pp["strategy"] == "PROTECTIVE_PUT"


def test_delta_hedger():
    """DeltaHedger ve DeltaHedgeResult doğrulaması."""
    assert "DeltaHedger" in repr(delta_hedger)

    hedge = delta_hedger.hedge(
        portfolio_delta=15.0,
        spot_price=10000.0,
        futures_price=10100.0,
        contract_multiplier=100.0,
    )
    assert "DeltaHedgeResult" in repr(hedge)
    d = hedge.to_dict()
    assert "contracts_needed" in d
    assert d["action"] in ["BUY", "SELL", "NONE"]

    # Wrapper test
    res = hedge_portfolio(portfolio_value=1_000_000.0, beta=1.2, futures_price=10000.0)
    assert "contracts_needed" in res


def test_span_margin_calculator():
    """SPANMarginCalculator ve calculate_span_margin wrapper doğrulaması."""
    assert "SPANMarginCalculator" in repr(span_margin)

    positions = [
        {"value": 100000.0, "margin_rate": 0.15, "position_type": "LONG", "is_option": False},
        {"value": 50000.0, "margin_rate": 0.15, "position_type": "SHORT", "is_option": False},
    ]
    margin_res = span_margin.calculate(positions)
    assert "total_margin" in margin_res
    assert margin_res["scenarios_tested"] == 16

    # Wrapper test
    wrap_margin = calculate_span_margin(positions)
    assert wrap_margin["total_margin"] > 0.0


def test_arbitrage_and_risk_calculator():
    """FuturesSpotArbitrage ve VIOPRiskCalculator doğrulaması."""
    assert "FuturesSpotArbitrage" in repr(futures_spot_arbitrage)
    arb = futures_spot_arbitrage.analyze(
        spot_price=100.0,
        futures_price=105.0,
        risk_free_rate=0.15,
        dividend_yield=0.02,
        time_to_expiry=0.25,
    )
    assert "ArbitrageResult" in repr(arb)
    d = arb.to_dict()
    assert "basis" in d

    assert "VIOPRiskCalculator" in repr(viop_risk)
    risk_res = viop_risk.calculate_portfolio_viop_risk(
        viop_positions=[
            {
                "ticker": "F_XU0301026",
                "type": "futures",
                "side": "long",
                "quantity": 2,
                "entry_price": 10500.0,
                "current_price": 10600.0,
                "delta": 1.0,
                "gamma": 0.0,
                "vega": 0.0,
                "contract_multiplier": 10.0,
            }
        ],
        portfolio_value=500000.0,
    )
    assert "total_delta_exposure" in risk_res


def test_options_backtest_engine():
    """OptionsBacktestEngine, BacktestResult ve BacktestTrade doğrulaması."""
    assert "OptionsBacktestEngine" in repr(options_backtest)

    trade = BacktestTrade(
        entry_date=date(2026, 1, 15),
        exit_date=date(2026, 2, 15),
        strategy="Covered Call",
        spot_price=100.0,
        entry_premium=5.0,
        exit_premium=1.0,
        pnl=400.0,
    )
    assert "BacktestTrade" in repr(trade)

    from datetime import timedelta

    start_date = date(2026, 1, 1)
    price_series = [
        {"date": start_date + timedelta(days=i), "close": 100.0 + i * 0.5}
        for i in range(60)
    ]
    bt_res = options_backtest.backtest_covered_call(price_series)
    assert "BacktestResult" in repr(bt_res)
    d = bt_res.to_dict()
    assert "total_trades" in d
    assert "win_rate" in d


def test_contract_catalog():
    """VIOPContractCatalog, VIOPContract ve OptionContract doğrulaması."""
    assert "VIOPContractCatalog" in repr(viop_catalog)

    contract = viop_catalog.get_contract("XU030")
    assert contract is not None
    assert "VIOPContract" in repr(contract)

    opt_contract = OptionContract(
        symbol="O_THYAO1026C300",
        underlying="THYAO",
        option_type="call",
        strike=300.0,
        expiry=date(2026, 10, 31),
    )
    assert "OptionContract" in repr(opt_contract)

    pnl = viop_catalog.calculate_pnl("XU030", entry_price=10000.0, exit_price=10200.0, quantity=2)
    assert pnl > 0.0

    d = viop_catalog.to_dict("XU030")
    assert d is not None
    assert d["symbol"] == "XU030"
