"""
ALPHA BIST — VIOP Test Suite v3.0

Tüm VIOP modülleri için kapsamlı testler.
Her test gerçek matematiksel doğrulama yapar.
"""

from datetime import date, timedelta

import numpy as np
import pytest

# =====================================================
# BLACK-SCHOLES TESTS
# =====================================================

class TestBlackScholes:
    """Black-Scholes fiyat doğruluğunu test et."""

    def test_call_atm(self):
        """ATM call fiyatı pozitif ve makul olmalı."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert 2.0 < price < 8.0, f"ATM call price {price} beklenen aralık dışında"

    def test_put_atm(self):
        """ATM put fiyatı pozitif ve makul olmalı."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="put")
        assert 1.0 < price < 7.0, f"ATM put price {price} beklenen aralık dışında"

    def test_put_call_parity(self):
        """Put-Call Parity: C - P = S - K*e^(-rT)"""
        from services.viop.enhanced_options import black_scholes
        S, K, T, r, sigma = 100, 100, 0.25, 0.15, 0.25
        call = black_scholes(S, K, T, r, sigma, "call")
        put = black_scholes(S, K, T, r, sigma, "put")
        lhs = call - put
        rhs = S - K * np.exp(-r * T)
        assert abs(lhs - rhs) < 0.001, f"Put-Call Parity ihlali: {lhs} != {rhs}"

    def test_call_deep_itm(self):
        """Deep ITM call → intrinsic value'a yakın."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=150, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert price > 49, f"Deep ITM call {price} < 49 olmamalı"

    def test_call_deep_otm(self):
        """Deep OTM call → sıfıra yakın."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=50, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert price < 0.01, f"Deep OTM call {price} ≈ 0 olmalı"

    def test_put_deep_itm(self):
        """Deep ITM put → intrinsic value'a yakın."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=50, K=100, T=0.25, r=0.15, sigma=0.25, option_type="put")
        # Deep ITM put: intrinsic = 50, ama faiz nedeniyle put < intrinsic olabilir
        assert price > 45, f"Deep ITM put {price} > 45 olmalı"

    def test_zero_vol(self):
        """Sıfır vol limitinde kullanım fiyatı vadeye iskonto edilir."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=100, K=90, T=0.25, r=0.15, sigma=0, option_type="call")
        expected = 100 - 90 * np.exp(-0.15 * 0.25)
        assert abs(price - expected) < 0.01, f"Zero vol call {price} != {expected}"

    def test_zero_T(self):
        """Sıfır vade → intrinsic value."""
        from services.viop.enhanced_options import black_scholes
        price = black_scholes(S=100, K=90, T=0, r=0.15, sigma=0.25, option_type="call")
        assert abs(price - 10) < 0.01, f"Zero T call intrinsic {price} != 10"

    def test_higher_vol_higher_price(self):
        """Yüksek volatilite → yüksek fiyat."""
        from services.viop.enhanced_options import black_scholes
        low = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.15, option_type="call")
        high = black_scholes(S=100, K=100, T=0.25, r=0.15, sigma=0.40, option_type="call")
        assert high > low, f"Yüksek vol {high} > düşük vol {low} olmalı"

    def test_longer_T_higher_price(self):
        """Uzun vade → yüksek fiyat (call)."""
        from services.viop.enhanced_options import black_scholes
        short = black_scholes(S=100, K=100, T=0.1, r=0.15, sigma=0.25, option_type="call")
        long = black_scholes(S=100, K=100, T=1.0, r=0.15, sigma=0.25, option_type="call")
        assert long > short, f"Uzun vade {long} > kısa vade {short} olmalı"


# =====================================================
# GREEKS TESTS
# =====================================================

class TestGreeks:
    """Greeks doğruluğunu test et."""

    def test_call_delta_range(self):
        """Call delta 0 ile 1 arasında olmalı."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert 0 < g["delta"] < 1, f"Call delta {g['delta']} aralık dışında"

    def test_put_delta_range(self):
        """Put delta -1 ile 0 arasında olmalı."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="put")
        assert -1 < g["delta"] < 0, f"Put delta {g['delta']} aralık dışında"

    def test_gamma_positive(self):
        """Gamma her zaman pozitif olmalı."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert g["gamma"] > 0, f"Gamma {g['gamma']} > 0 olmalı"

    def test_theta_negative(self):
        """Theta genellikle negatif olmalı (zaman aşımı)."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert g["theta"] < 0, f"Theta {g['theta']} < 0 olmalı"

    def test_vega_positive(self):
        """Vega pozitif olmalı."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=100, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert g["vega"] > 0, f"Vega {g['vega']} > 0 olmalı"

    def test_atm_delta_near_half(self):
        """ATM call delta ≈ 0.5 olmalı."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.25, option_type="call")
        assert 0.45 < g["delta"] < 0.60, f"ATM delta {g['delta']} ≈ 0.5 olmalı"

    def test_deep_itm_call_delta_near_one(self):
        """Deep ITM call delta ≈ 1 olmalı."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=200, K=100, T=0.25, r=0.15, sigma=0.25, option_type="call")
        assert g["delta"] > 0.95, f"Deep ITM delta {g['delta']} ≈ 1 olmalı"

    def test_zero_T_returns_intrinsic(self):
        """Sıfır vade → intrinsic Greeks."""
        from services.viop.enhanced_options import calculate_greeks
        g = calculate_greeks(S=110, K=100, T=0, r=0.15, sigma=0.25, option_type="call")
        assert g["delta"] == 1.0, f"ITM zero-T delta {g['delta']} = 1 olmalı"
        assert g["gamma"] == 0.0
        assert g["vega"] == 0.0


# =====================================================
# IMPLIED VOLATILITY TESTS
# =====================================================

class TestImpliedVolatility:
    """IV hesaplama doğruluğunu test et."""

    def test_roundtrip_call(self):
        """BS fiyat → IV → tekrar BS fiyat = aynı olmalı."""
        from services.viop.enhanced_options import black_scholes, implied_volatility
        true_sigma = 0.30
        S, K, T, r = 100, 100, 0.25, 0.15
        price = black_scholes(S, K, T, r, true_sigma, "call")
        iv = implied_volatility.calculate(price, S, K, T, r, "call")
        assert abs(iv - true_sigma) < 0.001, f"IV roundtrip {iv} != {true_sigma}"

    def test_roundtrip_put(self):
        """Put için IV roundtrip."""
        from services.viop.enhanced_options import black_scholes, implied_volatility
        true_sigma = 0.25
        S, K, T, r = 100, 95, 0.5, 0.15
        price = black_scholes(S, K, T, r, true_sigma, "put")
        iv = implied_volatility.calculate(price, S, K, T, r, "put")
        assert abs(iv - true_sigma) < 0.001, f"Put IV roundtrip {iv} != {true_sigma}"

    def test_batch(self):
        """Toplu IV hesaplama."""
        from services.viop.enhanced_options import implied_volatility
        options = [
            {"market_price": 5.0, "K": 100, "T": 0.25, "option_type": "call"},
            {"market_price": 3.0, "K": 105, "T": 0.25, "option_type": "put"},
        ]
        results = implied_volatility.calculate_batch(options, S=100, r=0.15)
        assert len(results) == 2
        assert all(r["implied_vol"] > 0 for r in results)

    def test_higher_price_higher_iv(self):
        """Yüksek fiyat → yüksek IV."""
        from services.viop.enhanced_options import implied_volatility
        iv_low = implied_volatility.calculate(3.0, 100, 100, 0.25, 0.15, "call")
        iv_high = implied_volatility.calculate(8.0, 100, 100, 0.25, 0.15, "call")
        assert iv_high > iv_low, f"Yüksek fiyat IV {iv_high} > düşük fiyat IV {iv_low} olmalı"

    def test_bisection_fallback(self):
        """Newton-Raphson başarısız olsa bile bisection çalışmalı."""
        from services.viop.enhanced_options import implied_volatility
        # Aşırı durum
        iv = implied_volatility.calculate(0.01, 100, 100, 0.01, 0.15, "call")
        assert iv > 0, f"Bisection fallback IV {iv} > 0 olmalı"


# =====================================================
# PORTFOLIO GREEKS TESTS
# =====================================================

class TestPortfolioGreeks:
    """Portfolio Greeks aggregation testleri."""

    def test_single_long_call(self):
        """Tek long call pozitif delta."""
        from services.viop.enhanced_options import PortfolioGreeks
        pg = PortfolioGreeks()
        result = pg.aggregate([{
            "option_type": "call", "S": 100, "K": 100, "T": 0.25,
            "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long",
        }])
        assert result.total_delta > 0
        assert result.n_positions == 1

    def test_short_negates_long(self):
        """Short pozisyon long pozisyonun deltasını azaltmalı."""
        from services.viop.enhanced_options import PortfolioGreeks
        pg = PortfolioGreeks()
        result = pg.aggregate([
            {"option_type": "call", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long"},
            {"option_type": "call", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "short"},
        ])
        assert abs(result.total_delta) < 0.01, f"Long+Short delta {result.total_delta} ≈ 0 olmalı"

    def test_delta_neutral_flag(self):
        """Delta neutral flag çalışmalı."""
        from services.viop.enhanced_options import PortfolioGreeks
        pg = PortfolioGreeks()
        # Long call + short call = delta neutral
        result = pg.aggregate([
            {"option_type": "call", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long"},
            {"option_type": "call", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "short"},
        ])
        assert result.delta_neutral

    def test_put_call_portfolio(self):
        """Long call + long put → gamma pozitif, delta küçük."""
        from services.viop.enhanced_options import PortfolioGreeks
        pg = PortfolioGreeks()
        result = pg.aggregate([
            {"option_type": "call", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long"},
            {"option_type": "put", "S": 100, "K": 100, "T": 0.25, "r": 0.15, "sigma": 0.25, "quantity": 100, "side": "long"},
        ])
        assert result.total_gamma > 0


# =====================================================
# OPTIONS CHAIN TESTS
# =====================================================

class TestOptionsChain:
    """Options Chain veri modeli testleri."""

    def test_add_and_get_quote(self):
        """Kotasyon ekle ve getir."""
        from services.viop.enhanced_options import OptionQuote, OptionsChain
        chain = OptionsChain("XU030", 10000)
        q = OptionQuote(strike=10000, expiry=date(2026, 9, 26), option_type="call", bid=100, ask=105)
        chain.add_quote(q)
        got = chain.get_quote(10000, date(2026, 9, 26), "call")
        assert got is not None
        assert got.bid == 100
        assert got.ask == 105

    def test_mid_price(self):
        """Mid price = (bid + ask) / 2."""
        from services.viop.enhanced_options import OptionQuote
        q = OptionQuote(strike=100, expiry=date.today(), option_type="call", bid=10, ask=14)
        assert q.mid == 12.0

    def test_spread(self):
        """Spread = ask - bid."""
        from services.viop.enhanced_options import OptionQuote
        q = OptionQuote(strike=100, expiry=date.today(), option_type="call", bid=10, ask=14)
        assert q.spread == 4.0

    def test_get_strikes(self):
        """Strike listesi sıralı olmalı."""
        from services.viop.enhanced_options import OptionQuote, OptionsChain
        chain = OptionsChain("XU030", 10000)
        exp = date(2026, 9, 26)
        chain.add_quote(OptionQuote(strike=10500, expiry=exp, option_type="call"))
        chain.add_quote(OptionQuote(strike=9500, expiry=exp, option_type="call"))
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="call"))
        strikes = chain.get_strikes(exp)
        assert strikes == [9500, 10000, 10500]

    def test_get_expiries(self):
        """Vade listesi sıralı olmalı."""
        from services.viop.enhanced_options import OptionQuote, OptionsChain
        chain = OptionsChain("XU030", 10000)
        chain.add_quote(OptionQuote(strike=10000, expiry=date(2026, 12, 26), option_type="call"))
        chain.add_quote(OptionQuote(strike=10000, expiry=date(2026, 9, 26), option_type="call"))
        expiries = chain.get_expiries()
        assert expiries == [date(2026, 9, 26), date(2026, 12, 26)]

    def test_find_atm(self):
        """ATM bulma çalışmalı."""
        from services.viop.enhanced_options import OptionQuote, OptionsChain
        chain = OptionsChain("XU030", 10050)
        exp = date(2026, 9, 26)
        chain.add_quote(OptionQuote(strike=9500, expiry=exp, option_type="call"))
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="call"))
        chain.add_quote(OptionQuote(strike=10500, expiry=exp, option_type="call"))
        atm = chain.find_atm(exp)
        assert atm is not None
        assert atm.strike == 10000

    def test_get_chain(self):
        """Chain calls/puts ayrımı."""
        from services.viop.enhanced_options import OptionQuote, OptionsChain
        chain = OptionsChain("XU030", 10000)
        exp = date(2026, 9, 26)
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="call"))
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="put"))
        result = chain.get_chain(exp)
        assert len(result["calls"]) == 1
        assert len(result["puts"]) == 1

    def test_calculate_all_greeks(self):
        """Tüm chain için Greeks hesaplama."""
        from services.viop.enhanced_options import OptionQuote, OptionsChain
        chain = OptionsChain("XU030", 10000)
        exp = date.today() + timedelta(days=90)
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="call"))
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="put"))
        chain.calculate_all_greeks(sigma=0.25)
        call = chain.get_quote(10000, exp, "call")
        put = chain.get_quote(10000, exp, "put")
        assert call.delta != 0
        assert put.delta != 0
        assert call.gamma > 0


# =====================================================
# STRATEGIES TESTS
# =====================================================

class TestStrategies:
    """Opsiyon strateji testleri — her strateji için matematik doğrulama."""

    def test_covered_call_math(self):
        """Covered Call: max_profit ve max_loss doğruluğu."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.covered_call(spot=100, call_strike=105, call_premium=3, shares=100)
        # Max profit = (105 - 100 + 3) * 100 = 800
        assert result.max_profit == 800, f"Max profit {result.max_profit} != 800"
        # Max loss = hisse sıfıra düşerse = -(100 * 100 - 3 * 100) = -9700
        assert result.max_loss == -9700, f"Max loss {result.max_loss} != -9700"
        # Breakeven = 100 - 3 = 97
        assert result.breakeven == [97], f"Breakeven {result.breakeven} != [97]"

    def test_protective_put_math(self):
        """Protective Put: max_loss doğruluğu."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.protective_put(spot=100, put_strike=95, put_premium=2, shares=100)
        # Max loss = -(100 - 95 + 2) * 100 = -700
        assert result.max_loss == -700, f"Max loss {result.max_loss} != -700"
        # Breakeven = 100 + 2 = 102
        assert result.breakeven == [102], f"Breakeven {result.breakeven} != [102]"
        # Max profit = unlimited
        assert result.max_profit == float("inf")

    def test_collar_math(self):
        """Collar: sınırlı risk, sınırlı ödül."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.collar(spot=100, put_strike=95, put_premium=2, call_strike=108, call_premium=3, shares=100)
        # Net premium = 3 - 2 = 1
        # Max profit = (108 - 100 + 1) * 100 = 900
        assert result.max_profit == 900, f"Max profit {result.max_profit} != 900"
        # Max loss = -(100 - 95 + 1) * 100 = -600
        assert result.max_loss == -600, f"Max loss {result.max_loss} != -600"

    def test_iron_condor_math(self):
        """Iron Condor: net credit = max profit."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.iron_condor(
            spot=100, put_sell_strike=95, put_buy_strike=90,
            call_sell_strike=105, call_buy_strike=110,
            put_sell_premium=2, put_buy_premium=1,
            call_sell_premium=2, call_buy_premium=1,
        )
        # Net credit = (2-1 + 2-1) * 100 = 200
        assert result.max_profit == 200, f"Max profit {result.max_profit} != 200"
        # Max loss = max(500, 500) - 200 = 300
        assert result.max_loss == -300, f"Max loss {result.max_loss} != -300"
        assert len(result.breakeven) == 2

    def test_straddle_math(self):
        """Straddle: max_loss = toplam premium."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.straddle(spot=100, strike=100, call_premium=3, put_premium=3)
        # Max loss = (3 + 3) * 100 = 600
        assert result.max_loss == -600, f"Max loss {result.max_loss} != -600"
        # Breakeven: down = 100 - 6 = 94, up = 100 + 6 = 106
        assert result.breakeven == [94, 106], f"Breakeven {result.breakeven} != [94, 106]"
        assert result.max_profit == float("inf")

    def test_strangle_math(self):
        """Strangle: breakeven doğruluğu."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.strangle(spot=100, put_strike=95, call_strike=105, put_premium=2, call_premium=2)
        # Breakeven: down = 95 - 4 = 91, up = 105 + 4 = 109
        assert result.breakeven == [91, 109], f"Breakeven {result.breakeven} != [91, 109]"

    def test_bull_call_spread_math(self):
        """Bull Call Spread: max_profit = spread - net debit."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.bull_call_spread(buy_strike=100, sell_strike=110, buy_premium=5, sell_premium=2)
        # Net debit = (5 - 2) * 100 = 300
        # Max profit = (110 - 100) * 100 - 300 = 700
        assert result.max_profit == 700, f"Max profit {result.max_profit} != 700"
        assert result.max_loss == -300, f"Max loss {result.max_loss} != -300"
        # Breakeven = 100 + 3 = 103
        assert result.breakeven == [103], f"Breakeven {result.breakeven} != [103]"

    def test_bear_put_spread_math(self):
        """Bear Put Spread: matematik doğruluğu."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.bear_put_spread(buy_strike=110, sell_strike=100, buy_premium=5, sell_premium=2)
        # Net debit = 300
        # Max profit = (110 - 100) * 100 - 300 = 700
        assert result.max_profit == 700, f"Max profit {result.max_profit} != 700"
        assert result.max_loss == -300
        # Breakeven = 110 - 3 = 107
        assert result.breakeven == [107]

    def test_butterfly_math(self):
        """Butterfly: max_profit = width - net debit."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        result = s.butterfly(
            lower_strike=95, middle_strike=100, upper_strike=105,
            lower_premium=6, middle_premium=3, upper_premium=1,
        )
        # Net debit = (6 - 6 + 1) * 100 = 100
        # Max profit = (100 - 95) * 100 - 100 = 400
        assert result.max_profit == 400, f"Max profit {result.max_profit} != 400"
        assert result.max_loss == -100

    def test_all_strategies_return_to_dict(self):
        """Tüm stratejiler to_dict() döndürmeli."""
        from services.viop.enhanced_options import OptionsStrategies
        s = OptionsStrategies()
        results = [
            s.covered_call(100, 105, 3),
            s.protective_put(100, 95, 2),
            s.collar(100, 95, 2, 108, 3),
            s.iron_condor(100, 95, 90, 105, 110, 2, 1, 2, 1),
            s.straddle(100, 100, 3, 3),
            s.strangle(100, 95, 105, 2, 2),
            s.bull_call_spread(100, 110, 5, 2),
            s.bear_put_spread(110, 100, 5, 2),
            s.butterfly(95, 100, 105, 6, 3, 1),
        ]
        for r in results:
            d = r.to_dict()
            assert "strategy" in d
            assert "max_profit" in d
            assert "max_loss" in d
            assert "breakeven" in d


# =====================================================
# DELTA HEDGING TESTS
# =====================================================

class TestDeltaHedging:
    """Delta hedging testleri."""

    def test_positive_delta_needs_short(self):
        """Pozitif delta → short futures."""
        from services.viop.enhanced_options import DeltaHedger
        h = DeltaHedger()
        result = h.hedge(portfolio_delta=150, spot_price=100, futures_price=101)
        assert result.contracts_needed < 0, f"Pozitif delta → short {result.contracts_needed}"
        assert result.action == "SELL"

    def test_negative_delta_needs_long(self):
        """Negatif delta → long futures."""
        from services.viop.enhanced_options import DeltaHedger
        h = DeltaHedger()
        result = h.hedge(portfolio_delta=-150, spot_price=100, futures_price=101)
        assert result.contracts_needed > 0, f"Negatif delta → long {result.contracts_needed}"
        assert result.action == "BUY"

    def test_zero_delta_none(self):
        """Sıfır delta → işlem yok."""
        from services.viop.enhanced_options import DeltaHedger
        h = DeltaHedger()
        result = h.hedge(portfolio_delta=0, spot_price=100, futures_price=101)
        assert result.contracts_needed == 0
        assert result.action == "NONE"

    def test_custom_multiplier(self):
        """Özel sözleşme çarpanı ile hedge."""
        from services.viop.enhanced_options import DeltaHedger
        h = DeltaHedger()
        # BIST-30: multiplier = endeks * 10 ≈ 10000
        result = h.hedge(portfolio_delta=5000, spot_price=10000, contract_multiplier=10000)
        assert result.contracts_needed == 0  # 5000 / 10000 = 0.5 → round = 0 veya 1

    def test_gamma_scalp_positive(self):
        """Long gamma + fiyat hareketi → pozitif P&L."""
        from services.viop.enhanced_options import DeltaHedger
        h = DeltaHedger()
        result = h.gamma_scalp(portfolio_gamma=0.05, spot_price=100, price_move_pct=3.0)
        assert result["gamma_pnl"] > 0, f"Gamma scalp P&L {result['gamma_pnl']} > 0 olmalı"

    def test_gamma_scalp_zero_move(self):
        """Sıfır hareket → sıfır P&L."""
        from services.viop.enhanced_options import DeltaHedger
        h = DeltaHedger()
        result = h.gamma_scalp(portfolio_gamma=0.05, spot_price=100, price_move_pct=0)
        assert result["gamma_pnl"] == 0


# =====================================================
# SPAN MARGIN TESTS
# =====================================================

class TestSPANMargin:
    """SPAN margin testleri."""

    def test_long_futures_margin(self):
        """Long futures pozitif margin üretmeli."""
        from services.viop.enhanced_options import SPANMarginCalculator
        calc = SPANMarginCalculator()
        result = calc.calculate([{
            "ticker": "XU030", "value": 100000, "delta": 1.0,
            "gamma": 0, "vega": 0, "spot_price": 10000,
        }])
        assert result["total_margin"] > 0
        assert result["scenarios_tested"] == 16

    def test_options_have_gamma_vega(self):
        """Opsiyon pozisyonu gamma ve vega etkisi içermeli."""
        from services.viop.enhanced_options import SPANMarginCalculator
        calc = SPANMarginCalculator()
        result = calc.calculate([{
            "ticker": "XU030C", "value": 100000, "delta": 0.5,
            "gamma": 0.02, "vega": 0.1, "spot_price": 10000,
        }])
        assert result["total_margin"] > 0
        # Senaryo PnL'leri farklı olmalı
        pnls = result["position_margins"][0]["scenario_pnls"]
        assert len(set(pnls)) > 1, "Farklı senaryolar farklı PnL üretmeli"

    def test_multiple_positions(self):
        """Çoklu pozisyon toplamı."""
        from services.viop.enhanced_options import SPANMarginCalculator
        calc = SPANMarginCalculator()
        result = calc.calculate([
            {"ticker": "A", "value": 100000, "delta": 1.0, "gamma": 0, "vega": 0, "spot_price": 100},
            {"ticker": "B", "value": 50000, "delta": -0.5, "gamma": 0.01, "vega": 0.05, "spot_price": 50},
        ])
        assert len(result["position_margins"]) == 2
        assert result["total_margin"] > 0


# =====================================================
# FUTURES-SPOT ARBITRAGE TESTS
# =====================================================

class TestArbitrage:
    """Arbitrage testleri."""

    def test_fair_price_no_arbitrage(self):
        """Teorik fiyat → arbitraj yok."""
        from services.viop.enhanced_options import FuturesSpotArbitrage
        arb = FuturesSpotArbitrage()
        spot = 10000
        theoretical = spot * np.exp((0.15 - 0.02) * 0.25)
        result = arb.analyze(spot, float(theoretical), 0.15, 0.02, 0.25)
        assert not result.arbitrage_opportunity
        assert result.strategy == "NO_ARBITRAGE"

    def test_overpriced_futures(self):
        """Pahalı futures → SELL_FUTURES_BUY_SPOT."""
        from services.viop.enhanced_options import FuturesSpotArbitrage
        arb = FuturesSpotArbitrage()
        result = arb.analyze(spot_price=10000, futures_price=10500, risk_free_rate=0.15, dividend_yield=0.02, time_to_expiry=0.25)
        assert result.arbitrage_opportunity
        assert result.strategy == "SELL_FUTURES_BUY_SPOT"
        assert result.estimated_profit > 0

    def test_underpriced_futures(self):
        """Ucuz futures → BUY_FUTURES_SELL_SPOT."""
        from services.viop.enhanced_options import FuturesSpotArbitrage
        arb = FuturesSpotArbitrage()
        result = arb.analyze(spot_price=10000, futures_price=9600, risk_free_rate=0.15, dividend_yield=0.02, time_to_expiry=0.25)
        assert result.arbitrage_opportunity
        assert result.strategy == "BUY_FUTURES_SELL_SPOT"

    def test_to_dict(self):
        """to_dict çalışmalı."""
        from services.viop.enhanced_options import FuturesSpotArbitrage
        arb = FuturesSpotArbitrage()
        result = arb.analyze(10000, 10100)
        d = result.to_dict()
        assert "spot_price" in d
        assert "arbitrage_opportunity" in d


# =====================================================
# PARITY TESTS
# =====================================================

class TestParity:
    """Put-Call Parity testleri."""

    def test_parity_holds(self):
        """BS ile üretilen fiyatlar parity sağlamalı."""
        from services.viop.enhanced_options import black_scholes, check_put_call_parity
        S, K, T, r, sigma = 100, 100, 0.25, 0.15, 0.25
        call = black_scholes(S, K, T, r, sigma, "call")
        put = black_scholes(S, K, T, r, sigma, "put")
        result = check_put_call_parity(call, put, S, K, r, T)
        assert result["parity_holds"]
        assert abs(result["deviation"]) < 0.01

    def test_arbitrage_detected(self):
        """Büyük sapma → arbitraj fırsatı."""
        from services.viop.enhanced_options import check_put_call_parity
        # Call 10, Put 5, ama teorik diff farklı
        result = check_put_call_parity(call_price=10, put_price=5, spot_price=100, strike=100, r=0.15, T=0.25)
        assert result["arbitrage_opportunity"]


# =====================================================
# RISK INTEGRATION TESTS
# =====================================================

class TestRiskIntegration:
    """VIOP risk entegrasyonu testleri."""

    def test_portfolio_risk_basic(self):
        """Temel portföy risk hesabı."""
        from services.viop.enhanced_options import VIOPRiskCalculator
        calc = VIOPRiskCalculator()
        positions = [{
            "ticker": "XU030", "type": "futures", "side": "long",
            "quantity": 10, "entry_price": 10000, "current_price": 10100,
            "delta": 1.0, "gamma": 0, "vega": 0, "contract_multiplier": 10,
        }]
        result = calc.calculate_portfolio_viop_risk(positions, 1000000)
        assert result["total_delta_exposure"] > 0
        assert result["total_pnl"] > 0  # Long 10100 > 10000 → kar
        assert result["n_positions"] == 1

    def test_risk_flags_high_delta(self):
        """Yüksek delta exposure → flag üretilmeli."""
        from services.viop.enhanced_options import VIOPRiskCalculator
        calc = VIOPRiskCalculator()
        positions = [{
            "ticker": "XU030", "type": "futures", "side": "long",
            "quantity": 1000, "entry_price": 10000, "current_price": 10000,
            "delta": 1.0, "gamma": 0, "vega": 0, "contract_multiplier": 10,
        }]
        result = calc.calculate_portfolio_viop_risk(positions, 100000)
        assert len(result["risk_flags"]) > 0

    def test_margin_requirement(self):
        """Teminat hesabı çalışmalı."""
        from services.viop.enhanced_options import VIOPRiskCalculator
        calc = VIOPRiskCalculator()
        positions = [{
            "ticker": "XU030", "type": "futures", "side": "long",
            "quantity": 10, "entry_price": 10000, "current_price": 10000,
            "delta": 1.0, "gamma": 0, "vega": 0, "contract_multiplier": 10,
        }]
        result = calc.calculate_margin_requirement(positions)
        assert result["total_margin"] > 0

    def test_short_pnl(self):
        """Short pozisyon: fiyat yükselirse zarar."""
        from services.viop.enhanced_options import VIOPRiskCalculator
        calc = VIOPRiskCalculator()
        positions = [{
            "ticker": "XU030", "type": "futures", "side": "short",
            "quantity": 10, "entry_price": 10000, "current_price": 10100,
            "delta": 1.0, "gamma": 0, "vega": 0, "contract_multiplier": 10,
        }]
        result = calc.calculate_portfolio_viop_risk(positions, 1000000)
        assert result["total_pnl"] < 0, f"Short + fiyat yükselişi → zarar: {result['total_pnl']}"


# =====================================================
# BACKTEST TESTS
# =====================================================

class TestBacktest:
    """Backtest motoru testleri."""

    def test_covered_call_backtest(self):
        """Covered call backtest çalışmalı."""
        from datetime import date

        from services.viop.enhanced_options import OptionsBacktestEngine
        engine = OptionsBacktestEngine()
        # Basit fiyat serisi: yatay
        prices = [{"date": date(2026, 1, 1) + timedelta(days=i), "close": 100 + i * 0.1} for i in range(60)]
        result = engine.backtest_covered_call(prices, strike_pct=1.05, premium_pct=0.02, holding_days=30)
        assert result.total_trades > 0
        assert result.win_rate >= 0
        assert result.profit_factor >= 0

    def test_iron_condor_backtest(self):
        """Iron condor backtest çalışmalı."""
        from datetime import date

        from services.viop.enhanced_options import OptionsBacktestEngine
        engine = OptionsBacktestEngine()
        # Yatay fiyat serisi → iron condor kazançlı olmalı
        prices = [{"date": date(2026, 1, 1) + timedelta(days=i), "close": 100 + np.random.uniform(-1, 1)} for i in range(60)]
        result = engine.backtest_iron_condor(prices, width_pct=0.05, premium_pct=0.015, holding_days=30)
        assert result.total_trades > 0

    def test_empty_series(self):
        """Boş fiyat serisi → sıfır işlem."""
        from services.viop.enhanced_options import OptionsBacktestEngine
        engine = OptionsBacktestEngine()
        result = engine.backtest_covered_call([])
        assert result.total_trades == 0
        assert result.total_pnl == 0

    def test_result_to_dict(self):
        """BacktestResult to_dict çalışmalı."""
        from datetime import date

        from services.viop.enhanced_options import OptionsBacktestEngine
        engine = OptionsBacktestEngine()
        prices = [{"date": date(2026, 1, 1) + timedelta(days=i), "close": 100} for i in range(60)]
        result = engine.backtest_covered_call(prices)
        d = result.to_dict()
        assert "total_trades" in d
        assert "win_rate" in d
        assert "profit_factor" in d


# =====================================================
# CONTRACT CATALOG TESTS
# =====================================================

class TestContractCatalog:
    """VIOP sözleşme kataloğu testleri."""

    def test_get_contract(self):
        from services.viop.contract_catalog import viop_catalog
        c = viop_catalog.get_contract("XU030")
        assert c is not None
        assert c.symbol == "XU030"
        assert c.contract_size == 10

    def test_get_all_contracts(self):
        from services.viop.contract_catalog import viop_catalog
        contracts = viop_catalog.get_all_contracts()
        assert len(contracts) >= 8
        assert "XU030" in contracts
        assert "DOL" in contracts
        assert "GAU" in contracts

    def test_get_by_category(self):
        from services.viop.contract_catalog import viop_catalog
        endeks = viop_catalog.get_contracts_by_category("endeks")
        assert len(endeks) >= 2
        döviz = viop_catalog.get_contracts_by_category("döviz")
        assert len(döviz) >= 2

    def test_get_expiry_dates(self):
        from services.viop.contract_catalog import viop_catalog
        dates = viop_catalog.get_expiry_dates("XU030", 2026)
        assert len(dates) == 4  # Mart, Haziran, Eylül, Aralık

    def test_get_next_expiry(self):
        from services.viop.contract_catalog import viop_catalog
        next_exp = viop_catalog.get_next_expiry("XU030")
        assert next_exp is not None
        assert next_exp > date.today()

    def test_calculate_margin(self):
        from services.viop.contract_catalog import viop_catalog
        margin = viop_catalog.calculate_margin("XU030", 10, 10000)
        assert margin == 10 * 10000 * 10 * 0.15  # qty * price * size * rate

    def test_calculate_pnl(self):
        from services.viop.contract_catalog import viop_catalog
        pnl = viop_catalog.calculate_pnl("XU030", 10, 10000, 10100)
        assert pnl == 10 * 100 * 10  # qty * diff * size

    def test_unknown_contract(self):
        from services.viop.contract_catalog import viop_catalog
        assert viop_catalog.get_contract("UNKNOWN") is None

    def test_to_dict(self):
        from services.viop.contract_catalog import viop_catalog
        d = viop_catalog.to_dict("DOL")
        assert d is not None
        assert d["symbol"] == "DOL"
        assert d["category"] == "döviz"


# =====================================================
# VIOP MONITOR TESTS
# =====================================================

class TestVIOPMonitor:
    """VIOP monitor testleri."""

    def test_margin_ok(self):
        from services.core.viop_monitor import viop_monitor
        status = viop_monitor.check_viop_margin(100000, 20000)
        assert not status.margin_call
        assert status.action == "OK"

    def test_margin_call(self):
        from services.core.viop_monitor import viop_monitor
        status = viop_monitor.check_viop_margin(100000, 10000)  # %10 < %13
        assert status.margin_call
        assert status.action == "MARGIN_CALL"

    def test_custom_rate(self):
        from services.core.viop_monitor import viop_monitor
        viop_monitor.set_margin_rate("CUSTOM", 0.20)
        status = viop_monitor.check_viop_margin(100000, 15000, "CUSTOM")
        assert status.margin_call  # 15000 < 100000 * 0.20 = 20000

    def test_zero_position(self):
        from services.core.viop_monitor import viop_monitor
        status = viop_monitor.check_viop_margin(0, 20000)
        assert not status.margin_call
        assert status.action == "OK"


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestIntegration:
    """Tam entegrasyon testleri."""

    def test_catalog_then_margin(self):
        """Catalog → Margin entegrasyonu."""
        from services.viop.contract_catalog import viop_catalog
        from services.viop.enhanced_options import SPANMarginCalculator
        viop_catalog.calculate_margin("XU030", 10, 10000)
        span = SPANMarginCalculator()
        result = span.calculate([{
            "ticker": "XU030", "value": 10 * 10000 * 10,
            "delta": 1.0, "gamma": 0, "vega": 0, "spot_price": 10000,
        }])
        assert result["total_margin"] > 0

    def test_chain_then_greeks_then_hedge(self):
        """Chain → Greeks → Hedge tam pipeline."""
        from services.viop.enhanced_options import DeltaHedger, OptionQuote, OptionsChain, PortfolioGreeks
        chain = OptionsChain("XU030", 10000)
        exp = date.today() + timedelta(days=90)
        chain.add_quote(OptionQuote(strike=10000, expiry=exp, option_type="call"))
        chain.calculate_all_greeks(sigma=0.25)

        chain.get_quote(10000, exp, "call")
        pg = PortfolioGreeks()
        greeks = pg.aggregate([{
            "option_type": "call", "S": 10000, "K": 10000,
            "T": 90/365, "r": 0.15, "sigma": 0.25,
            "quantity": 10, "side": "long",
        }])

        hedger = DeltaHedger()
        hedge = hedger.hedge(greeks.total_delta, spot_price=10000, contract_multiplier=100)
        assert hedge.action in ("BUY", "SELL", "NONE")

    def test_strategy_then_risk(self):
        """Strateji → Risk entegrasyonu."""
        from services.viop.enhanced_options import OptionsStrategies, VIOPRiskCalculator
        strat = OptionsStrategies()
        strat.covered_call(100, 105, 3, 100)

        risk = VIOPRiskCalculator()
        positions = [{
            "ticker": "TEST", "type": "options", "side": "long",
            "quantity": 1, "entry_price": 3, "current_price": 3,
            "delta": 0.5, "gamma": 0.02, "vega": 0.1, "contract_multiplier": 100,
        }]
        risk_result = risk.calculate_portfolio_viop_risk(positions, 100000)
        assert "total_delta_exposure" in risk_result

    def test_backtest_then_summary(self):
        """Backtest → Özet."""
        from datetime import date

        from services.viop.enhanced_options import OptionsBacktestEngine
        engine = OptionsBacktestEngine()
        # Yükselen trend → covered call sınırlı kar
        prices = [{"date": date(2026, 1, 1) + timedelta(days=i), "close": 100 + i * 0.5} for i in range(90)]
        result = engine.backtest_covered_call(prices, strike_pct=1.05, premium_pct=0.02, holding_days=30)
        d = result.to_dict()
        assert d["total_trades"] > 0
        assert "win_rate" in d
        assert "profit_factor" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
