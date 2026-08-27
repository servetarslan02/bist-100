"""
ALPHA BIST — Paper Trading Unit + Integration Tests v1.0

Test coverage:
1. PaperStateStore (persistent state)
2. VirtualPortfolio (positions, P&L, mark-to-market)
3. PaperExecutionEngine (slippage, commission, liquidity)
4. PaperRiskGate (position, sector, drawdown, kill-switch, NO_TRADE)
5. PerformanceTracker (Sharpe, Sortino, MaxDD, Alpha)
6. PaperTradingOrchestrator (full daily cycle, replay mode)
7. Champion protection (challenger sinyalleri reddedilmeli)
8. Paper trading sonuclari model egitimine geri beslenmemeli (leakage test)
9. Fail-safe (hata durumunda NO_TRADE)
10. Persistence (program kapanip acilinca veri kaybolmamali)
"""

import os
import tempfile
import unittest
from datetime import date, timedelta

import numpy as np
import orjson
import polars as pl

from services.paper_trading.paper_execution import PaperExecutionEngine
from services.paper_trading.paper_orchestrator import PaperTradingOrchestrator
from services.paper_trading.paper_risk_gate import PaperRiskGate
from services.paper_trading.performance_tracker import PerformanceTracker

# Add parent to path
from services.paper_trading.state_store import PaperStateStore
from services.paper_trading.virtual_portfolio import VirtualPortfolio


class TestPaperStateStore(unittest.TestCase):
    """StateStore persistence tests."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = PaperStateStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_save_and_load_portfolio_state(self):
        snap = {"date": "2024-01-15", "cash": 900000, "initial_capital": 1000000, "positions": [], "trades": [], "orders": [], "equity_curve": [], "last_updated": ""}
        self.store.save_portfolio_state(snap)
        loaded = self.store.load_portfolio_state()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["cash"], 900000)
        self.assertEqual(loaded["initial_capital"], 1000000)

    def test_positions_persistence(self):
        pos = [{"ticker": "THYAO", "quantity": 100, "avg_cost": 250, "current_price": 260, "sector": "Havacilik", "market_value": 26000}]
        self.store.save_positions(pos)
        loaded = self.store.load_positions()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["ticker"], "THYAO")

    def test_audit_log_append_only(self):
        entry = {"timestamp": "2024-01-15T10:00:00", "date": "2024-01-15", "entry_type": "SIGNAL", "ticker": "THYAO"}
        self.store.append_audit(entry)
        logs = self.store.load_audit_log(date="2024-01-15")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["ticker"], "THYAO")

    def test_equity_curve(self):
        self.store.save_equity_point("2024-01-15", 1050000, 500000, 550000)
        self.store.save_equity_point("2024-01-16", 1060000, 500000, 560000)
        curve = self.store.load_equity_curve()
        self.assertEqual(len(curve), 2)
        self.assertEqual(curve[0]["equity"], 1050000)

    def test_backup(self):
        path = self.store.backup()
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_reset_all(self):
        self.store.save_equity_point("2024-01-15", 1000000, 500000, 500000)
        self.store.reset_all()
        curve = self.store.load_equity_curve()
        self.assertEqual(len(curve), 0)


class TestVirtualPortfolio(unittest.TestCase):
    """VirtualPortfolio tests."""

    def setUp(self):
        self.portfolio = VirtualPortfolio(initial_capital=1_000_000)

    def test_open_position(self):
        result = self.portfolio.open_position("THYAO", 100, 250, sector="Havacilik", date="2024-01-15")
        self.assertTrue(result["success"])
        self.assertEqual(self.portfolio.cash, 1_000_000 - 100 * 250)

    def test_insufficient_cash(self):
        result = self.portfolio.open_position("THYAO", 10000, 250, date="2024-01-15")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "INSUFFICIENT_CASH")

    def test_close_position(self):
        self.portfolio.open_position("THYAO", 100, 250, date="2024-01-15")
        result = self.portfolio.close_position("THYAO", 260, date="2024-01-16")
        self.assertTrue(result["success"])
        self.assertEqual(result["realized_pnl"], (260 - 250) * 100)
        self.assertNotIn("THYAO", self.portfolio._positions)

    def test_mark_to_market(self):
        self.portfolio.open_position("THYAO", 100, 250, date="2024-01-15")
        self.portfolio.update_prices({"THYAO": 260}, "2024-01-16")
        self.assertEqual(len(self.portfolio._equity_curve), 1)
        expected_equity = 1_000_000 - 100 * 250 + 100 * 260
        self.assertEqual(self.portfolio._equity_curve[0]["equity"], expected_equity)

    def test_sector_weights(self):
        self.portfolio.open_position("THYAO", 100, 250, sector="Havacilik", date="2024-01-15")
        self.portfolio.open_position("GARAN", 200, 100, sector="Bankacilik", date="2024-01-15")
        weights = self.portfolio.get_sector_weights()
        self.assertIn("Havacilik", weights)
        self.assertIn("Bankacilik", weights)

    def test_max_drawdown(self):
        self.portfolio._equity_curve = [
            {"equity": 1000000}, {"equity": 1100000}, {"equity": 1050000},
            {"equity": 950000}, {"equity": 1000000},
        ]
        self.portfolio._max_equity = 1100000
        dd = self.portfolio.get_max_drawdown()
        self.assertAlmostEqual(dd, (1100000 - 950000) / 1100000 * 100, places=1)

    def test_persistence_roundtrip(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        store = PaperStateStore(tmp.name)

        p = VirtualPortfolio(1_000_000, store)
        p.open_position("THYAO", 100, 250, date="2024-01-15")
        p.save_to_store("2024-01-15")

        p2 = VirtualPortfolio(1_000_000, store)
        p2.load_from_store()
        self.assertIn("THYAO", p2._positions)
        self.assertEqual(p2._positions["THYAO"]["quantity"], 100)
        os.unlink(tmp.name)


class TestPaperExecutionEngine(unittest.TestCase):
    """Execution simulation tests."""

    def setUp(self):
        self.engine = PaperExecutionEngine()

    def test_buy_execution(self):
        order = self.engine.execute_signal(
            date="2024-01-15", ticker="THYAO", side="BUY",
            quantity=100, signal_price=250, market_price=250,
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertGreater(order["execution_price"], 0)
        self.assertGreater(order["commission"], 0)
        self.assertGreater(order["slippage_pct"], 0)

    def test_sell_execution(self):
        order = self.engine.execute_signal(
            date="2024-01-15", ticker="THYAO", side="SELL",
            quantity=100, signal_price=260, market_price=260,
        )
        self.assertEqual(order["status"], "FILLED")
        self.assertLess(order["execution_price"], 260)  # Slippage

    def test_liquidity_partial_fill(self):
        order = self.engine.execute_signal(
            date="2024-01-15", ticker="THYAO", side="BUY",
            quantity=1_000_000, signal_price=250, market_price=250,
            avg_volume=1_000,  # Cok dusuk hacim
        )
        self.assertEqual(order["status"], "PARTIAL_FILL")
        self.assertEqual(order["quantity"], 50)  # günlük hacmin %5'i
        self.assertIsNone(order["rejection_reason"])

    def test_commission_calculation(self):
        amount = 100 * 250
        comm = self.engine._compute_commission(amount)
        self.assertGreater(comm, 0)
        self.assertGreaterEqual(comm, 1.0)  # Min commission

    def test_slippage_bounds(self):
        slippage = self.engine._compute_slippage(
            quantity=1000, avg_volume=1_000_000,
            volatility=0.5, spread_pct=0.2, side="BUY",
        )
        self.assertLessEqual(slippage, 0.005)  # Max 0.5%
        self.assertGreaterEqual(slippage, 0)

    def test_signal_vs_execution_price_different(self):
        """Look-ahead bias test: signal_price != execution_price olabilmeli."""
        order = self.engine.execute_signal(
            date="2024-01-15", ticker="THYAO", side="BUY",
            quantity=100, signal_price=250, market_price=255,  # Farkli!
        )
        self.assertEqual(order["signal_price"], 250)
        self.assertNotEqual(order["execution_price"], 250)


class TestPaperRiskGate(unittest.TestCase):
    """Risk gate tests."""

    def setUp(self):
        self.gate = PaperRiskGate(max_position_pct=10, max_sector_pct=30, max_drawdown_pct=15)
        self.portfolio = VirtualPortfolio(initial_capital=1_000_000)

    def test_position_size_limit(self):
        checks = self.gate.check_all(
            self.portfolio, "THYAO", "BUY", 50000, 250, sector="Havacilik"
        )
        allowed = self.gate.is_trade_allowed(checks)
        self.assertFalse(allowed)
        block_reason = self.gate.get_block_reason(checks)
        self.assertIn("position_size", block_reason)

    def test_sector_concentration(self):
        self.portfolio.open_position("THYAO", 1000, 250, sector="Havacilik", date="2024-01-15")
        self.portfolio.open_position("PGSUS", 1000, 200, sector="Havacilik", date="2024-01-15")
        checks = self.gate.check_all(
            self.portfolio, "THYAO2", "BUY", 100, 250, sector="Havacilik"
        )
        self.assertTrue(any(c["check_name"] == "sector_concentration" for c in checks))

    def test_drawdown_kill_switch(self):
        self.portfolio._equity_curve = [
            {"equity": 1000000}, {"equity": 700000},  # %30 drawdown
        ]
        self.portfolio._max_equity = 1000000
        checks = self.gate.check_all(
            self.portfolio, "THYAO", "BUY", 100, 250
        )
        allowed = self.gate.is_trade_allowed(checks)
        self.assertFalse(allowed)
        self.assertTrue(self.gate._kill_switch_active)

    def test_data_quality_no_trade(self):
        checks = self.gate.check_all(
            self.portfolio, "THYAO", "BUY", 100, 250,
            data_quality_ok=False,
        )
        allowed = self.gate.is_trade_allowed(checks)
        self.assertFalse(allowed)
        self.assertTrue(any(c["result"] == "NO_TRADE" for c in checks))

    def test_model_validity_no_trade(self):
        checks = self.gate.check_all(
            self.portfolio, "THYAO", "BUY", 100, 250,
            model_version_valid=False,
        )
        allowed = self.gate.is_trade_allowed(checks)
        self.assertFalse(allowed)

    def test_consecutive_errors_kill_switch(self):
        self.gate.record_error()
        self.gate.record_error()
        self.gate.record_error()
        self.assertTrue(self.gate._kill_switch_active)


class TestPerformanceTracker(unittest.TestCase):
    """Performance metrics tests."""

    def setUp(self):
        self.engine = PerformanceTracker()

    def test_sharpe_ratio(self):
        returns = np.array([0.001, -0.002, 0.003, 0.001, -0.001])
        sharpe = self.engine._sharpe(returns)
        self.assertIsInstance(sharpe, float)

    def test_sortino_ratio(self):
        returns = np.array([0.001, -0.002, 0.003, 0.001, -0.001])
        sortino = self.engine._sortino(returns)
        self.assertIsInstance(sortino, float)

    def test_max_drawdown(self):
        equities = [100, 110, 105, 95, 100]
        dd = self.engine._max_drawdown(equities)
        self.assertAlmostEqual(dd, (110 - 95) / 110 * 100, places=1)

    def test_full_metrics(self):
        equity_curve = [
            {"equity": 1000000}, {"equity": 1010000}, {"equity": 1005000},
            {"equity": 1020000}, {"equity": 1015000},
        ]
        trades = [
            {"trade_id": "T1", "ticker": "THYAO", "side": "SELL", "quantity": 100, "entry_price": 250, "exit_price": 260, "realized_pnl": 1000, "commission": 10, "holding_days": 5},
            {"trade_id": "T2", "ticker": "GARAN", "side": "SELL", "quantity": 200, "entry_price": 100, "exit_price": 95, "realized_pnl": -1000, "commission": 10, "holding_days": 4},
        ]
        metrics = self.engine.compute_full_metrics(equity_curve, trades)
        self.assertIn("sharpe_ratio", metrics)
        self.assertIn("max_drawdown_pct", metrics)
        self.assertIn("win_rate", metrics)
        self.assertIn("profit_factor", metrics)
        self.assertIn("cagr_pct", metrics)

    def test_top_k_spread(self):
        returns = {"A": 0.05, "B": 0.03, "C": 0.01, "D": -0.02, "E": -0.04, "F": -0.06}
        spread = self.engine.compute_top_k_spread(returns, k=2)
        self.assertGreater(spread, 0)


class TestPaperTradingOrchestrator(unittest.TestCase):
    """Integration tests for full orchestrator."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.orch = PaperTradingOrchestrator(
            initial_capital=1_000_000,
            state_store=PaperStateStore(self.tmp.name),
            champion_version="LambdaRank_v3_LOCKED",
        )
        self.orch.risk_gate.max_position_pct = 20  # Test icin yuksek
        self.orch.risk_gate.data_quality_min_stocks = 1  # Test icin dusuk

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _make_market_data(self, tickers, dates):
        data = {}
        for t in tickers:
            prices = 100 + np.cumsum(np.random.randn(len(dates)) * 2)
            df = pl.DataFrame({
                'Open': prices * 0.99,
                'High': prices * 1.02,
                'Low': prices * 0.98,
                'Close': prices,
                'Volume': np.random.randint(1_000_000, 10_000_000, len(dates)),
            }.Series(dates))
            data[t] = df
        return data

    def test_daily_cycle_no_signals(self):
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 10), timedelta(days=1), eager=True).head(3)
        market_data = self._make_market_data(["THYAO", "GARAN"], dates)
        sector_map = {"THYAO": "Havacilik", "GARAN": "Bankacilik"}

        report = self.orch.run_daily_cycle(
            date="2024-01-01",
            market_data=market_data,
            sector_map=sector_map,
            champion_signals=None,
        )
        self.assertEqual(report["status"], "NO_TRADE")

    def test_daily_cycle_with_signals(self):
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 10), timedelta(days=1), eager=True).head(3)
        market_data = self._make_market_data(["THYAO", "GARAN"], dates)
        sector_map = {"THYAO": "Havacilik", "GARAN": "Bankacilik"}

        signals = [
            {"ticker": "THYAO", "direction": "LONG", "rank": 1, "score": 10,
             "confidence": 0.85, "model_version": "LambdaRank_v3_LOCKED", "regime": "BULL"},
        ]

        report = self.orch.run_daily_cycle(
            date="2024-01-01",
            market_data=market_data,
            sector_map=sector_map,
            champion_signals=signals,
        )
        self.assertEqual(report["status"], "COMPLETED")
        self.assertGreater(report["num_orders"], 0)

    def test_champion_protection(self):
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 10), timedelta(days=1), eager=True).head(3)
        market_data = self._make_market_data(["THYAO"], dates)
        sector_map = {"THYAO": "Havacilik"}

        signals = [
            {"ticker": "THYAO", "direction": "LONG", "rank": 1, "score": 10,
             "confidence": 0.85, "model_version": "Challenger_v1", "regime": "BULL"},
        ]

        report = self.orch.run_daily_cycle(
            date="2024-01-01",
            market_data=market_data,
            sector_map=sector_map,
            champion_signals=signals,
        )
        self.assertEqual(report["status"], "NO_TRADE")

    def test_replay_mode(self):
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 15), timedelta(days=1), eager=True).head(5)
        date_strs = [d.strftime("%Y-%m-%d") for d in dates]
        market_data = self._make_market_data(["THYAO", "GARAN", "ASELS"], dates)
        sector_map = {"THYAO": "Havacilik", "GARAN": "Bankacilik", "ASELS": "Savunma"}

        signals_by_date = {}
        for d in date_strs:
            signals_by_date[d] = [
                {"ticker": "THYAO", "direction": "LONG", "rank": 1, "score": 8,
                 "confidence": 0.8, "model_version": "LambdaRank_v3_LOCKED", "regime": "BULL"},
                {"ticker": "GARAN", "direction": "LONG", "rank": 2, "score": 12,
                 "confidence": 0.75, "model_version": "LambdaRank_v3_LOCKED", "regime": "BULL"},
            ]

        report = self.orch.run_backtest_replay(
            market_data=market_data,
            sector_map=sector_map,
            signals_by_date=signals_by_date,
        )

        self.assertIn("performance_metrics", report)
        self.assertIn("portfolio_summary", report)
        self.assertEqual(report["champion_version"], "LambdaRank_v3_LOCKED")
        print("\n=== REPLAY REPORT ===")
        print(orjson.dumps(report["performance_metrics"], option=orjson.OPT_INDENT_2).decode())
        print(f"Portfolio summary: {report['portfolio_summary']}")

    def test_fail_safe_on_error(self):
        report = self.orch.run_daily_cycle(
            date="2024-01-01",
            market_data={},  # Bos veri
            sector_map={},
            champion_signals=[],
            data_quality_ok=False,
        )
        self.assertEqual(report["status"], "NO_TRADE")

    def test_paper_results_not_leaking_to_training(self):
        self.assertFalse(hasattr(self.orch, 'train_model'))
        self.assertFalse(hasattr(self.orch, 'fit'))
        self.assertEqual(self.orch._champion_version, "LambdaRank_v3_LOCKED")


class TestPersistence(unittest.TestCase):
    """Persistence tests: program kapanip acilinca veri kaybolmamali."""

    def test_full_persistence(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()

        # Simulasyon 1: Portfoy olustur
        store = PaperStateStore(tmp.name)
        p = VirtualPortfolio(1_000_000, store)
        p.open_position("THYAO", 100, 250, date="2024-01-15")
        p.save_to_store("2024-01-15")

        # Simulasyon 2: Yeni instance, eski veriyi yukle
        store2 = PaperStateStore(tmp.name)
        p2 = VirtualPortfolio(1_000_000, store2)
        p2.load_from_store()

        self.assertIn("THYAO", p2._positions)
        self.assertEqual(p2._positions["THYAO"]["quantity"], 100)
        self.assertEqual(p2.cash, 1_000_000 - 100 * 250)

        os.unlink(tmp.name)


class TestNoLeakage(unittest.TestCase):
    """Paper trading sonuclarinin model egitimine leakage olusturmadigini dogrula."""

    def test_champion_is_read_only(self):
        orch = PaperTradingOrchestrator()
        self.assertEqual(orch._champion_version, "LambdaRank_v3_LOCKED")

    def test_no_training_methods(self):
        orch = PaperTradingOrchestrator()
        forbidden_methods = ['train', 'fit', 'update_weights', 'backpropagate']
        for method in forbidden_methods:
            self.assertFalse(hasattr(orch, method), f"Leakage risk: {method} exists")

    def test_audit_log_separation(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        store = PaperStateStore(tmp.name)

        entry = {"timestamp": "2024-01-15T10:00:00", "date": "2024-01-15", "entry_type": "TRADE", "ticker": "THYAO", "reason": "Test"}
        store.append_audit(entry)

        logs = store.load_audit_log(entry_type="TRADE")
        self.assertEqual(len(logs), 1)

        os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
