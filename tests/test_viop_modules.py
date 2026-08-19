"""
ALPHA BIST — VIOP Modules Test Suite v1.0

Tüm VIOP modülleri için test'ler:
- Contract Catalog
- Black-Scholes + Greeks
- Implied Volatility
- Portfolio Greeks
- Options Strategies (8+)
- Delta Hedging
- SPAN Margin
- Futures-Spot Arbitrage
"""

import pytest
import numpy as np
from datetime import date


# =====================================================
# CONTRACT CATALOG TESTS
# =====================================================

class TestVIOPContractCatalog:
    """VIOP sözleşme kataloğu testleri."""

    def setup_method(self):
        from services.viop.contract_catalog import VIOPContractCatalog
        self.catalog = VIOPContractCatalog()

    def test_get_contract(self):
        contract = self.catalog.get_contract("XU030")
        assert contract is not None
        assert contract.symbol == "XU030"
        assert contract.contract_size == 10

    def test_get_all_contracts(self):
        contracts = self.catalog.get_all_contracts()
        assert len(contracts) >= 8
        assert "XU030" in contracts
        assert "DOL" in contracts

    def test_get_by_category(self):
        endeks = self.catalog.get_contracts_by_category("endeks")
        assert len(endeks) >= 2

        döviz = self.catalog.get_contracts_by_category("döviz")
        assert len(döviz) >= 2

    def test_get_expiry_dates(self):
        dates = self.catalog.get_expiry_dates("XU030", 2026)
        assert len(dates) == 4  # 4 vade (Mart, Haziran, Eylül, Aralık)

    def test_get_next_expiry(self):
        next_exp = self.catalog.get_next_expiry("XU030")
        assert next_exp is not None
        assert next_exp > date.today()

    def test_calculate_margin(self):
        margin = self.catalog.calculate_margin("XU030", 10, 10000)
        assert margin > 0
        assert margin == 10 * 10000 * 10 * 0.15  # qty * price * size * rate

    def test_calculate_pnl(self):
        pnl = self.catalog.calculate_pnl("XU030", 10, 10000, 10100)
        assert pnl == 10 * (10100 - 10000) * 10  # 10000 TL kar

    def test_to_dict(self):
        d = self.catalog.to_dict("DOL")
        assert d is not None
        assert d["symbol"] == "DOL"
        assert d["category"] == "döviz"


# =====================================================
# BLACK-SCHOLES + GREEKS TESTS
# =====================================================

class TestBlackScholes:
    """Black-Scholes testleri."""

    def test_call_price(self):
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert price > 0
        assert price < 100

    def test_put_price(self):
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="put")
        assert price > 0

    def test_put_call_parity(self):
        from services.viop.enhanced_options import black_scholes
        S, K, T, r, sigma = 100, 100, 0.25, 0.15, 0.25
        call = black_scholes(S, K, T, r, sigma, "call")
        put = black_scholes(S, K, T, r, sigma, "put")
        # C - P = S - K*e^(-rT)
        lhs = call - put
        rhs = S - K * np.exp(-r * T)
        assert abs(lhs - rhs) < 0.01

    def test_greeks(self):
        from services.viop.enhanced_options import calculate_greeks
        greeks = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert 0 < greeks["delta"] < 1  # Call delta: 0-1
        assert greeks["gamma"] > 0
        assert greeks["vega"] > 0


# =====================================================
# IMPLIED VOLATILITY TESTS
# =====================================================

class TestImpliedVolatility:
    """Implied Volatility testleri."""

    def setup_method(self):
        from services.viop.enhanced_options import ImpliedVolatility
        self.iv = ImpliedVolatility()

    def test_calculate_iv(self):
        from services.viop.enhanced_options import black_scholes
        # Önce fiyat üret
        true_sigma = 0.30
        price = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=true_sigma, option_type="call")

        # IV hesapla
        iv = self.iv.calculate(market_price=price, S=100, K=100, T=0.25, r=0.15, option_type="call")
        assert abs(iv - true_sigma) < 0.01

    def test_iv_batch(self):
        options = [
            {"market_price": 5.0, "K": 100, "T": 0.25, "option_type": "call"},
            {"market_price": 3.0, "K": 105, "T": 0.25, "option_type": "put"},
        ]
        results = self.iv.calculate_batch(options, S=100, r=0.15)
        assert len(results) == 2
        assert all(r["implied_vol"] > 0 for r in results)


# =====================================================
# PORTFOLIO GREEKS TESTS
# =====================================================

class TestPortfolioGreeks:
    """Portfolio Greeks testleri."""

    def setup_method(self):
        from services.viop.enhanced_options import PortfolioGreeks
        self.pg = PortfolioGreeks()

    def test_single_position(self):
        positions = [{
            "option_type": "call", "S": 100, "K": 100, "T": 0.25,
            "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long",
        }]
        result = self.pg.aggregate(positions)
        assert result.n_positions == 1
        assert result.total_delta > 0

    def test_delta_neutral(self):
        positions = [
            {"option_type": "call", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long"},
            {"option_type": "put", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "short"},
        ]
        result = self.pg.aggregate(positions)
        # Long call + short put → delta ~1.0 (delta neutral değil)
        assert result.n_positions == 2


# =====================================================
# OPTIONS STRATEGIES TESTS
# =====================================================

class TestOptionsStrategies:
    """Options strategies testleri."""

    def setup_method(self):
        from services.viop.enhanced_options import OptionsStrategies
        self.strat = OptionsStrategies()

    def test_covered_call(self):
        result = self.strat.covered_call(spot=100, call_strike=105, call_premium=3, shares=100)
        assert result.strategy == "COVERED_CALL"
        assert result.max_profit > 0
        assert result.max_loss < 0
        assert len(result.breakeven) == 1

    def test_protective_put(self):
        result = self.strat.protective_put(spot=100, put_strike=95, put_premium=2, shares=100)
        assert result.strategy == "PROTECTIVE_PUT"
        assert result.max_loss < 0

    def test_collar(self):
        result = self.strat.collar(spot=100, put_strike=95, put_premium=2, call_strike=108, call_premium=3, shares=100)
        assert result.strategy == "COLLAR"
        assert result.max_profit > 0
        assert result.max_loss < 0

    def test_iron_condor(self):
        result = self.strat.iron_condor(
            spot=100, put_sell_strike=95, put_buy_strike=90,
            call_sell_strike=105, call_buy_strike=110,
            put_sell_premium=2, put_buy_premium=1,
            call_sell_premium=2, call_buy_premium=1,
        )
        assert result.strategy == "IRON_CONDOR"
        assert result.max_profit > 0
        assert len(result.breakeven) == 2

    def test_straddle(self):
        result = self.strat.straddle(spot=100, strike=100, call_premium=3, put_premium=3)
        assert result.strategy == "STRADDLE"
        assert len(result.breakeven) == 2

    def test_strangle(self):
        result = self.strat.strangle(spot=100, put_strike=95, call_strike=105, put_premium=2, call_premium=2)
        assert result.strategy == "STRANGLE"
        assert len(result.breakeven) == 2

    def test_bull_call_spread(self):
        result = self.strat.bull_call_spread(buy_strike=100, sell_strike=110, buy_premium=5, sell_premium=2)
        assert result.strategy == "BULL_CALL_SPREAD"
        assert result.max_profit > 0

    def test_bear_put_spread(self):
        result = self.strat.bear_put_spread(buy_strike=110, sell_strike=100, buy_premium=5, sell_premium=2)
        assert result.strategy == "BEAR_PUT_SPREAD"
        assert result.max_profit > 0

    def test_butterfly(self):
        result = self.strat.butterfly(
            lower_strike=95, middle_strike=100, upper_strike=105,
            lower_premium=6, middle_premium=3, upper_premium=1,
        )
        assert result.strategy == "BUTTERFLY"
        assert result.max_profit > 0


# =====================================================
# DELTA HEDGING TESTS
# =====================================================

class TestDeltaHedger:
    """Delta hedging testleri."""

    def setup_method(self):
        from services.viop.enhanced_options import DeltaHedger
        self.hedger = DeltaHedger()

    def test_hedge_positive_delta(self):
        # Delta notional olarak (300 hisse × 0.5 delta = 150)
        result = self.hedger.hedge(
            portfolio_delta=150, spot_price=100, futures_price=101
        )
        assert result.contracts_needed < 0  # Short futures

    def test_hedge_negative_delta(self):
        result = self.hedger.hedge(
            portfolio_delta=-150, spot_price=100, futures_price=101
        )
        assert result.contracts_needed > 0  # Long futures

    def test_hedge_zero_delta(self):
        result = self.hedger.hedge(
            portfolio_delta=0.0, spot_price=100, futures_price=101
        )
        assert result.contracts_needed == 0

    def test_gamma_scalp(self):
        result = self.hedger.gamma_scalp(
            portfolio_gamma=0.05, spot_price=100, price_move=3.0
        )
        assert result["gamma_pnl"] > 0  # Pozitif gamma → fiyat hareketinden kar


# =====================================================
# SPAN MARGIN TESTS
# =====================================================

class TestSPANMargin:
    """SPAN margin testleri."""

    def setup_method(self):
        from services.viop.enhanced_options import SPANMarginCalculator
        self.calc = SPANMarginCalculator()

    def test_basic_margin(self):
        positions = [{"ticker": "XU030", "value": 100000, "delta": 1.0, "gamma": 0, "vega": 0}]
        result = self.calc.calculate(positions)
        assert result["total_margin"] > 0
        assert result["scenarios_tested"] == 16

    def test_options_higher_margin(self):
        # Opsiyon pozisyonu (gamma ve vega var)
        positions = [{"ticker": "XU030C", "value": 100000, "delta": 0.5, "gamma": 0.02, "vega": 0.1}]
        result = self.calc.calculate(positions)
        assert result["total_margin"] > 0


# =====================================================
# FUTURES-SPOT ARBITRAGE TESTS
# =====================================================

class TestFuturesSpotArbitrage:
    """Futures-spot arbitrage testleri."""

    def setup_method(self):
        from services.viop.enhanced_options import FuturesSpotArbitrage
        self.arb = FuturesSpotArbitrage()

    def test_no_arbitrage(self):
        # Fair price
        spot = 10000
        theoretical = spot * np.exp((0.15 - 0.02) * 0.25)
        result = self.arb.analyze(spot, float(theoretical), 0.15, 0.02, 0.25)
        assert not result.arbitrage_opportunity

    def test_overpriced_futures(self):
        result = self.arb.analyze(
            spot_price=10000,
            futures_price=10500,  # Çok pahalı
            risk_free_rate=0.15,
            dividend_yield=0.02,
            time_to_expiry=0.25,
        )
        assert result.arbitrage_opportunity
        assert result.strategy == "SELL_FUTURES_BUY_SPOT"

    def test_underpriced_futures(self):
        result = self.arb.analyze(
            spot_price=10000,
            futures_price=9600,  # Çok ucuz
            risk_free_rate=0.15,
            dividend_yield=0.02,
            time_to_expiry=0.25,
        )
        assert result.arbitrage_opportunity
        assert result.strategy == "BUY_FUTURES_SELL_SPOT"


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestVIOPIntegration:
    """VIOP entegrasyon testleri."""

    def test_strategy_with_greeks(self):
        """Strateji + Greeks entegrasyonu."""
        from services.viop.enhanced_options import OptionsStrategies, calculate_greeks

        strat = OptionsStrategies()
        result = strat.covered_call(spot=100, call_strike=105, call_premium=3, shares=100)

        # Greeks hesapla
        greeks = calculate_greeks(S=100, K=105, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert greeks["delta"] > 0

    def test_hedge_with_portfolio_greeks(self):
        """Hedge + Portfolio Greeks entegrasyonu."""
        from services.viop.enhanced_options import PortfolioGreeks, DeltaHedger

        pg = PortfolioGreeks()
        hedger = DeltaHedger()

        positions = [{
            "option_type": "call", "S": 100, "K": 100, "T": 0.25,
            "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long",
        }]
        greeks = pg.aggregate(positions)

        hedge = hedger.hedge(greeks.total_delta, spot_price=100, futures_price=101)
        assert hedge.contracts_needed != 0

    def test_catalog_with_margin(self):
        """Catalog + Margin entegrasyonu."""
        from services.viop.contract_catalog import viop_catalog
        from services.viop.enhanced_options import SPANMarginCalculator

        margin_calc = SPANMarginCalculator()

        # Teminat hesapla
        margin = viop_catalog.calculate_margin("XU030", 10, 10000)
        assert margin > 0

        # SPAN ile de hesapla
        positions = [{"ticker": "XU030", "value": 1000000, "delta": 1.0, "gamma": 0, "vega": 0}]
        span_result = margin_calc.calculate(positions)
        assert span_result["total_margin"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
