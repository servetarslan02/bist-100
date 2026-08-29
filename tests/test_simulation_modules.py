from typing import Any
"""
ALPHA BIST — Simulation Modules Test Suite v1.0

Tüm yeni simulation modülleri için test'ler:
- Enhanced Execution Simulator
- Jump-Diffusion Monte Carlo
- Correlated Monte Carlo
- Regime-Conditioned Monte Carlo
- Enhanced Stress Test
"""

import numpy as np
import pytest

# =====================================================
# ENHANCED EXECUTION TESTS
# =====================================================


class TestSquareRootMarketImpact:
    """Square root market impact testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.enhanced_execution import SquareRootMarketImpact

        self.model = SquareRootMarketImpact(eta=0.3)

    def test_small_order_low_impact(self) -> Any:
        """Otomatik eklendi."""
        impact = self.model.calculate(
            order_value=10000,
            adv_value=100000000,
            volatility=0.02,
        )
        assert impact < 0.001  # Küçük emir → düşük impact

    def test_large_order_higher_impact(self) -> Any:
        """Otomatik eklendi."""
        impact = self.model.calculate(
            order_value=10000000,
            adv_value=100000000,
            volatility=0.02,
        )
        assert impact > 0.001  # Büyük emir → yüksek impact

    def test_higher_volatility_higher_impact(self) -> Any:
        """Otomatik eklendi."""
        low_vol = self.model.calculate(1000000, 100000000, 0.01)
        high_vol = self.model.calculate(1000000, 100000000, 0.05)
        assert high_vol > low_vol

    def test_max_impact_capped(self) -> Any:
        """Otomatik eklendi."""
        impact = self.model.calculate(
            order_value=50000000,
            adv_value=100000000,
            volatility=0.05,
        )
        assert impact <= 0.05  # Max %5

    def test_zero_adv_returns_default(self) -> Any:
        """Otomatik eklendi."""
        impact = self.model.calculate(1000000, 0, 0.02)
        assert impact == 0.001


class TestRegimeAwareSlippage:
    """Regime-aware slippage testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.enhanced_execution import RegimeAwareSlippage

        self.model = RegimeAwareSlippage()

    def test_bull_lower_slippage(self) -> Any:
        """Otomatik eklendi."""
        base = 0.01
        bull = self.model.adjust_slippage(base, "BULL")
        assert bull < base

    def test_panic_higher_slippage(self) -> Any:
        """Otomatik eklendi."""
        base = 0.01
        panic = self.model.adjust_slippage(base, "PANIC")
        assert panic > base * 1.5

    def test_crisis_highest_slippage(self) -> Any:
        """Otomatik eklendi."""
        base = 0.01
        crisis = self.model.adjust_slippage(base, "CRISIS")
        assert crisis > base * 2

    def test_unknown_regime_returns_base(self) -> Any:
        """Otomatik eklendi."""
        base = 0.01
        result = self.model.adjust_slippage(base, "UNKNOWN")
        assert result == base


class TestEnhancedExecutionSimulator:
    """Enhanced execution simulator testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.enhanced_execution import EnhancedExecutionSimulator, LiquidityProfile
        from services.simulation.execution_simulator import Order, OrderSide, OrderType

        self.sim = EnhancedExecutionSimulator()
        self.LiquidityProfile = LiquidityProfile
        self.Order = Order
        self.OrderSide = OrderSide
        self.OrderType = OrderType

    def test_buy_order_slippage(self) -> Any:
        """Otomatik eklendi."""
        order = self.Order(
            order_id="test_1",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=self.OrderSide.BUY,
            order_type=self.OrderType.MARKET,
            quantity=100,
        )
        liquidity = self.LiquidityProfile(
            avg_daily_volume=1000000,
            spread_pct=0.2,
        )
        result = self.sim.execute_order(
            order=order,
            market_price=250.0,
            liquidity=liquidity,
            regime="RANGE",
            volatility=0.02,
        )
        assert result["fill_price"] > 250.0  # BUY → fiyat yukarı
        assert result["slippage_pct"] > 0

    def test_sell_order_slippage(self) -> Any:
        """Otomatik eklendi."""
        order = self.Order(
            order_id="test_2",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=self.OrderSide.SELL,
            order_type=self.OrderType.MARKET,
            quantity=100,
        )
        liquidity = self.LiquidityProfile(
            avg_daily_volume=1000000,
            spread_pct=0.2,
        )
        result = self.sim.execute_order(
            order=order,
            market_price=250.0,
            liquidity=liquidity,
            regime="RANGE",
            volatility=0.02,
        )
        assert result["fill_price"] < 250.0  # SELL → fiyat aşağı

    def test_regime_impact(self) -> Any:
        """Otomatik eklendi."""
        order = self.Order(
            order_id="test_3",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=self.OrderSide.BUY,
            order_type=self.OrderType.MARKET,
            quantity=100,
        )
        liquidity = self.LiquidityProfile(avg_daily_volume=1000000, spread_pct=0.2)

        normal = self.sim.execute_order(order, 250.0, liquidity, "RANGE", 0.02)
        panic = self.sim.execute_order(order, 250.0, liquidity, "PANIC", 0.02)

        assert panic["slippage_pct"] > normal["slippage_pct"]

    def test_partial_fill(self) -> Any:
        """Otomatik eklendi."""
        order = self.Order(
            order_id="test_4",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=self.OrderSide.BUY,
            order_type=self.OrderType.MARKET,
            quantity=200000,  # ADV'nin %20'si
        )
        liquidity = self.LiquidityProfile(avg_daily_volume=1000000, spread_pct=0.2)
        result = self.sim.execute_order(order, 250.0, liquidity)
        assert result["partial_fill"] is True
        assert result["fill_quantity"] == 100000  # Max %10

    def test_compare_slippage_models(self) -> Any:
        """Otomatik eklendi."""
        comparison = self.sim.compare_slippage_models(
            order_value=5000000,
            adv_value=100000000,
            volatility=0.02,
            regime="RANGE",
        )
        assert "linear_impact_pct" in comparison
        assert "sqrt_impact_pct" in comparison


# =====================================================
# JUMP-DIFFUSION MONTE CARLO TESTS
# =====================================================


class TestJumpDiffusionMonteCarlo:
    """Jump-diffusion Monte Carlo testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.monte_carlo_enhanced import JumpDiffusionMonteCarlo

        self.mc = JumpDiffusionMonteCarlo()

    def test_simulate(self) -> Any:
        """Otomatik eklendi."""
        result = self.mc.simulate(
            current_price=100.0,
            daily_return=0.0004,
            daily_vol=0.02,
            num_sims=1000,
            horizon=20,
            seed=42,
        )
        assert result.num_simulations == 1000
        assert result.horizon_days == 20
        assert result.current_price == 100.0

    def test_percentiles_exist(self) -> Any:
        """Otomatik eklendi."""
        result = self.mc.simulate(100.0, 0.0004, 0.02, 1000, 20, seed=42)
        assert 5 in result.percentiles
        assert 50 in result.percentiles
        assert 95 in result.percentiles

    def test_var_cvar(self) -> Any:
        """Otomatik eklendi."""
        result = self.mc.simulate(100.0, 0.0004, 0.02, 5000, 20, seed=42)
        assert result.var_95 < 0  # VaR negatif olmalı
        assert result.cvar_95 < result.var_95  # CVaR daha kötü

    def test_probabilities(self) -> Any:
        """Otomatik eklendi."""
        result = self.mc.simulate(100.0, 0.0004, 0.02, 5000, 20, seed=42)
        assert 0 <= result.prob_positive <= 100
        assert 0 <= result.prob_down_5pct <= 100

    def test_jump_increases_volatility(self) -> Any:
        """Otomatik eklendi."""
        # Yüksek jump intensity ile volatilite artmalı
        # Daha fazla simülasyon ile istatistiksel güvenilirlik
        no_jump = self.mc.simulate(100.0, 0.0004, 0.02, 50000, 20, jump_intensity=0, seed=42)
        with_jump = self.mc.simulate(100.0, 0.0004, 0.02, 50000, 20, jump_intensity=0.10, seed=42)
        assert with_jump.std_return_pct > no_jump.std_return_pct

    def test_daily_drift_is_accumulated_over_horizon(self) -> Any:
        """daily_return günlük parametredir; yıllık gibi tekrar ölçeklenmemeli."""
        result = self.mc.simulate(
            100.0,
            daily_return=0.001,
            daily_vol=0.0,
            num_sims=100,
            horizon=20,
            jump_intensity=0,
            seed=42,
        )
        expected_return_pct = (np.exp(0.001 * 20) - 1) * 100
        assert abs(result.expected_return_pct - expected_return_pct) < 0.01


# =====================================================
# CORRELATED MONTE CARLO TESTS
# =====================================================


class TestCorrelatedMonteCarlo:
    """Correlated Monte Carlo testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.monte_carlo_enhanced import CorrelatedMonteCarlo

        self.mc = CorrelatedMonteCarlo()

    def test_portfolio_simulation(self) -> Any:
        """Otomatik eklendi."""
        tickers = ["THYAO", "GARAN", "ASELS"]
        prices = np.array([250.0, 100.0, 50.0])
        returns = np.random.normal(0.0004, 0.02, (252, 3))
        weights = np.array([0.4, 0.35, 0.25])

        result = self.mc.simulate_portfolio(
            tickers=tickers,
            prices=prices,
            returns_matrix=returns,
            weights=weights,
            num_sims=1000,
            horizon=20,
            seed=42,
        )
        assert "portfolio" in result
        assert "assets" in result
        assert "correlation_matrix" in result

    def test_portfolio_var(self) -> Any:
        """Otomatik eklendi."""
        tickers = ["A", "B"]
        prices = np.array([100.0, 50.0])
        returns = np.random.normal(0.0004, 0.02, (100, 2))
        weights = np.array([0.6, 0.4])

        result = self.mc.simulate_portfolio(tickers, prices, returns, weights, 1000, 20, seed=42)
        assert result["portfolio"]["var_95"] < 0

    def test_correlation_matrix_shape(self) -> Any:
        """Otomatik eklendi."""
        tickers = ["A", "B", "C"]
        prices = np.array([100, 50, 25])
        returns = np.random.normal(0, 0.02, (100, 3))
        weights = np.array([0.33, 0.33, 0.34])

        result = self.mc.simulate_portfolio(tickers, prices, returns, weights, 500, 10, seed=42)
        corr = np.array(result["correlation_matrix"])
        assert corr.shape == (3, 3)


# =====================================================
# REGIME-CONDITIONED MONTE CARLO TESTS
# =====================================================


class TestRegimeConditionedMonteCarlo:
    """Regime-conditioned MC testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.monte_carlo_enhanced import RegimeConditionedMonteCarlo

        self.mc = RegimeConditionedMonteCarlo()

    def test_bull_regime(self) -> Any:
        """Otomatik eklendi."""
        result = self.mc.simulate(100.0, 0.0004, 0.02, "BULL", 1000, 20, seed=42)
        assert "BULL" in result.model

    def test_panic_regime(self) -> Any:
        """Otomatik eklendi."""
        result = self.mc.simulate(100.0, 0.0004, 0.02, "PANIC", 1000, 20, seed=42)
        assert "PANIC" in result.model

    def test_regime_affects_results(self) -> Any:
        """Otomatik eklendi."""
        bull = self.mc.simulate(100.0, 0.0004, 0.02, "BULL", 2000, 20, seed=42)
        panic = self.mc.simulate(100.0, 0.0004, 0.02, "PANIC", 2000, 20, seed=42)
        # Panic'te volatilite daha yüksek olmalı
        assert panic.std_return_pct > bull.std_return_pct


# =====================================================
# ENHANCED STRESS TEST TESTS
# =====================================================


class TestEnhancedStressTest:
    """Enhanced stress test testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.enhanced_stress_test import EnhancedStressTestEngine

        self.engine = EnhancedStressTestEngine()
        self.portfolio = {
            "total_value": 1000000,
            "positions": [
                {"ticker": "THYAO", "value": 300000, "sector": "INDUSTRY", "beta": 1.2, "usd_sensitivity": 0.3},
                {"ticker": "GARAN", "value": 250000, "sector": "BANKING", "beta": 1.0, "usd_sensitivity": 0.5},
                {"ticker": "ASELS", "value": 200000, "sector": "TECHNOLOGY", "beta": 0.8, "usd_sensitivity": 0.2},
                {"ticker": "EREGL", "value": 150000, "sector": "INDUSTRY", "beta": 1.1, "usd_sensitivity": 0.4},
                {"ticker": "AKBNK", "value": 100000, "sector": "BANKING", "beta": 1.0, "usd_sensitivity": 0.5},
            ],
        }

    def test_run_all_scenarios(self) -> Any:
        """Otomatik eklendi."""
        results = self.engine.run_stress_test(
            self.portfolio["total_value"],
            self.portfolio["positions"],
        )
        assert len(results) >= 8
        assert all(r.portfolio_impact_pct != 0 for r in results)

    def test_worst_scenario(self) -> Any:
        """Otomatik eklendi."""
        results = self.engine.run_stress_test(
            self.portfolio["total_value"],
            self.portfolio["positions"],
        )
        summary = self.engine.get_scenario_summary(results)
        assert summary["worst_impact_pct"] < -5

    def test_breaking_point(self) -> Any:
        """Otomatik eklendi."""
        result = self.engine.find_breaking_point(
            self.portfolio["total_value"],
            self.portfolio["positions"],
            max_loss_pct=15.0,
        )
        assert "is_robust" in result
        assert "breaking_scenarios" in result

    def test_custom_scenario(self) -> Any:
        """Otomatik eklendi."""
        self.engine.add_custom_scenario(
            name="Custom Test",
            market_shock=-0.10,
            sector_impacts={"BANKING": -0.15},
        )
        results = self.engine.run_stress_test(
            self.portfolio["total_value"],
            self.portfolio["positions"],
        )
        assert any(r.scenario == "Custom Test" for r in results)

    def test_sector_impacts_differ(self) -> Any:
        """Otomatik eklendi."""
        results = self.engine.run_stress_test(
            self.portfolio["total_value"],
            self.portfolio["positions"],
        )
        # Farklı senaryolarda farklı etkiler olmalı
        impacts = [r.portfolio_impact_pct for r in results]
        assert len(set(impacts)) > 1

    def test_get_scenario_summary(self) -> Any:
        """Otomatik eklendi."""
        results = self.engine.run_stress_test(
            self.portfolio["total_value"],
            self.portfolio["positions"],
        )
        summary = self.engine.get_scenario_summary(results)
        assert "total_scenarios" in summary
        assert "worst_scenario" in summary


# =====================================================
# INTEGRATION TESTS
# =====================================================


class TestSimulationIntegration:
    """Entegrasyon testleri."""

    def test_execution_with_stress(self) -> Any:
        """Execution + stress test entegrasyonu."""
        from services.simulation.enhanced_execution import EnhancedExecutionSimulator, LiquidityProfile
        from services.simulation.enhanced_stress_test import EnhancedStressTestEngine
        from services.simulation.execution_simulator import Order, OrderSide, OrderType

        exec_sim = EnhancedExecutionSimulator()
        stress = EnhancedStressTestEngine()

        # Stres testi
        positions = [
            {"ticker": "THYAO", "value": 500000, "sector": "INDUSTRY", "beta": 1.2, "usd_sensitivity": 0.3},
        ]
        stress_results = stress.run_stress_test(1000000, positions)
        min(stress_results, key=lambda r: r.portfolio_impact_pct)

        # Worst case'de execution
        order = Order(
            order_id="stress_test",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=1000,
        )
        liquidity = LiquidityProfile(avg_daily_volume=1000000, spread_pct=0.5)

        # Stres altında execution (PANIC rejimi)
        result = exec_sim.execute_order(order, 250.0, liquidity, "PANIC", 0.05)
        assert result["slippage_pct"] > 0  # Stres altında slippage artmalı

    def test_monte_carlo_with_stress(self) -> Any:
        """Monte Carlo + stress test entegrasyonu."""
        from services.simulation.enhanced_stress_test import EnhancedStressTestEngine
        from services.simulation.monte_carlo_enhanced import RegimeConditionedMonteCarlo

        mc = RegimeConditionedMonteCarlo()
        EnhancedStressTestEngine()

        # Normal rejim
        normal = mc.simulate(100.0, 0.0004, 0.02, "BULL", 1000, 20, seed=42)

        # Stres rejimi
        crisis = mc.simulate(100.0, 0.0004, 0.02, "CRISIS", 1000, 20, seed=42)

        # Crisis'te daha kötü sonuçlar
        assert crisis.var_95 < normal.var_95


# =====================================================
# ORDER BOOK TESTS
# =====================================================


class TestOrderBook:
    """Order book simülasyon testleri."""

    def setup_method(self) -> Any:
        """Otomatik eklendi."""
        from services.simulation.order_book import OrderBookSimulator

        self.sim = OrderBookSimulator()

    def test_generate_book(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        assert len(book.bids) == 5
        assert len(book.asks) == 5
        assert book.best_bid > 0
        assert book.best_ask > 0
        assert book.best_ask > book.best_bid

    def test_spread_positive(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        assert book.spread > 0
        assert book.spread_pct > 0

    def test_panic_wider_spread(self) -> Any:
        """Otomatik eklendi."""
        normal = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        panic = self.sim.generate_book(100.0, 1000000, 0.02, "PANIC")
        assert panic.spread_pct > normal.spread_pct

    def test_depth_positive(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        assert book.bid_depth > 0
        assert book.ask_depth > 0

    def test_imbalance_range(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        assert -1 <= book.imbalance <= 1

    def test_market_buy_order(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        result = self.sim.simulate_market_order(book, "BUY", 500)
        assert result["fill_quantity"] > 0
        assert result["avg_price"] > 0
        assert result["slippage_pct"] >= 0

    def test_market_sell_order(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        result = self.sim.simulate_market_order(book, "SELL", 500)
        assert result["fill_quantity"] > 0
        assert result["avg_price"] > 0

    def test_large_order_partial_fill(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 100000, 0.02, "RANGE")
        result = self.sim.simulate_market_order(book, "BUY", 100000)
        # Book'da yeterli likidite olmayabilir
        assert result["fill_quantity"] > 0

    def test_buy_walks_asks(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        result = self.sim.simulate_market_order(book, "BUY", 500)
        # BUY emri ask'lerden fill olmalı
        assert result["avg_price"] >= book.best_ask

    def test_liquidity_score(self) -> Any:
        """Otomatik eklendi."""
        book = self.sim.generate_book(100.0, 1000000, 0.02, "RANGE")
        score = self.sim.calculate_liquidity_score(book)
        assert 0 <= score["liquidity_score"] <= 100
        assert "spread_score" in score
        assert "depth_score" in score

    def test_spread_estimate(self) -> Any:
        """Otomatik eklendi."""
        spread = self.sim.estimate_spread_from_volume(1000000, 0.02)
        assert 0.01 <= spread <= 2.0


# =====================================================
# INTEGRATION TESTS (updated)
# =====================================================


class TestSimulationIntegrationUpdated:
    """Entegrasyon testleri."""

    def test_execution_with_stress(self) -> Any:
        """Execution + stress test entegrasyonu."""
        from services.simulation.enhanced_execution import EnhancedExecutionSimulator, LiquidityProfile
        from services.simulation.enhanced_stress_test import EnhancedStressTestEngine
        from services.simulation.execution_simulator import Order, OrderSide, OrderType

        exec_sim = EnhancedExecutionSimulator()
        stress = EnhancedStressTestEngine()

        positions = [
            {"ticker": "THYAO", "value": 500000, "sector": "INDUSTRY", "beta": 1.2, "usd_sensitivity": 0.3},
        ]
        stress_results = stress.run_stress_test(1000000, positions)
        min(stress_results, key=lambda r: r.portfolio_impact_pct)

        order = Order(
            order_id="stress_test",
            portfolio_id=1,
            instrument_id=1,
            ticker="THYAO",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=1000,
        )
        liquidity = LiquidityProfile(avg_daily_volume=1000000, spread_pct=0.5)
        result = exec_sim.execute_order(order, 250.0, liquidity, "PANIC", 0.05)
        assert result["slippage_pct"] > 0

    def test_monte_carlo_with_stress(self) -> Any:
        """Monte Carlo + stress test entegrasyonu."""
        from services.simulation.monte_carlo_enhanced import RegimeConditionedMonteCarlo

        mc = RegimeConditionedMonteCarlo()
        normal = mc.simulate(100.0, 0.0004, 0.02, "BULL", 1000, 20, seed=42)
        crisis = mc.simulate(100.0, 0.0004, 0.02, "CRISIS", 1000, 20, seed=42)
        assert crisis.var_95 < normal.var_95

    def test_order_book_with_execution(self) -> Any:
        """Order book + execution entegrasyonu."""
        from services.simulation.enhanced_execution import EnhancedExecutionSimulator, LiquidityProfile
        from services.simulation.execution_simulator import Order, OrderSide, OrderType
        from services.simulation.order_book import OrderBookSimulator

        book_sim = OrderBookSimulator()
        exec_sim = EnhancedExecutionSimulator()

        # Order book üret
        book = book_sim.generate_book(100.0, 1000000, 0.02, "RANGE")

        # Book'dan spread al, execution'a ver
        order = Order(
            order_id="ob_test",
            portfolio_id=1,
            instrument_id=1,
            ticker="TEST",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=500,
        )
        liquidity = LiquidityProfile(
            avg_daily_volume=1000000,
            spread_pct=book.spread_pct,
        )
        result = exec_sim.execute_order(
            order,
            book.mid_price,
            liquidity,
            "RANGE",
            0.02,
            bid=book.best_bid,
            ask=book.best_ask,
        )
        assert result["fill_price"] > 0
        assert result["slippage_pct"] > 0

    def test_order_book_large_order(self) -> Any:
        """Büyük emir order book'da daha fazla slippage yapmalı."""
        from services.simulation.order_book import OrderBookSimulator

        sim = OrderBookSimulator()
        book = sim.generate_book(100.0, 1000000, 0.02, "RANGE")

        small = sim.simulate_market_order(book, "BUY", 100)
        large = sim.simulate_market_order(book, "BUY", 5000)

        # Büyük emir daha fazla slippage yapmalı (veya partial fill)
        assert large["slippage_pct"] >= small["slippage_pct"] or large["partial_fill"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
