from typing import Any

"""
ALPHA BIST — Synthetic Microstructure & Multi-Scenario Liquidity Tests
"""

import unittest
from datetime import date, timedelta

from services.core.bist_tick_size import get_bist_tick_size
from services.paper_trading.kap_market_restriction_registry import (
    KAPMarketRestrictionRegistry,
)
from services.paper_trading.scenario_manager import (
    LiquidityScenarioManager,
    ScenarioResult,
)
from services.paper_trading.synthetic_liquidity import (
    LiquidityScenario,
    SyntheticLiquidityEstimator,
    SyntheticOrderBookBuilder,
)


class TestSyntheticMicrostructure(unittest.TestCase):
    """Otomatik eklendi."""
    def setUp(self) -> Any:
        """Otomatik eklendi."""
        self.estimator = SyntheticLiquidityEstimator()
        self.builder = SyntheticOrderBookBuilder()
        self.kap_reg = KAPMarketRestrictionRegistry()

    def test_corwin_schultz_spread_and_bist_floor(self) -> Any:
        """Corwin-Schultz spread tahmini ve BIST kuruş adımı tabanı testi."""
        price = 100.0
        tick = get_bist_tick_size(price)  # 0.10 TL (%0.10)

        # 1. Normal spread hesaplama
        spread_pct = self.estimator.estimate_corwin_schultz_spread(
            high_prev=102.0,
            low_prev=98.0,
            high_curr=103.0,
            low_curr=99.0,
            price=price,
        )
        self.assertGreater(spread_pct, 0.0)
        self.assertGreaterEqual(spread_pct, (tick / price) * 100.0)

        # 2. Sıfır / Negatif spread durumunda BIST floor koruması
        spread_flat = self.estimator.estimate_corwin_schultz_spread(
            high_prev=100.0,
            low_prev=100.0,
            high_curr=100.0,
            low_curr=100.0,
            price=price,
        )
        self.assertAlmostEqual(spread_flat, (tick / price) * 100.0, places=2)

    def test_synthetic_order_book_generation_deterministic(self) -> Any:
        """10 kademeli deterministik defter üretimi testi."""
        book1 = self.builder.build_synthetic_book(
            ticker="THYAO",
            mid_price=250.0,
            adv=1_000_000,
            volatility=0.25,
            spread_pct=0.20,
            scenario=LiquidityScenario.NORMAL,
            num_levels=10,
        )
        book2 = self.builder.build_synthetic_book(
            ticker="THYAO",
            mid_price=250.0,
            adv=1_000_000,
            volatility=0.25,
            spread_pct=0.20,
            scenario=LiquidityScenario.NORMAL,
            num_levels=10,
        )

        self.assertEqual(len(book1.bids), 10)
        self.assertEqual(len(book1.asks), 10)
        # Deterministik eşitlik
        self.assertEqual(book1.bids[0].price, book2.bids[0].price)
        self.assertEqual(book1.asks[0].price, book2.asks[0].price)
        self.assertEqual(book1.bids[0].quantity, book2.bids[0].quantity)

    def test_walk_the_book_and_participation_cap(self) -> Any:
        """Kademe tüketme (Walk-the-Book) ve katılım tavanı testi."""
        adv = 1_000_000
        book = self.builder.build_synthetic_book(
            ticker="GARAN",
            mid_price=100.0,
            adv=adv,
            volatility=0.20,
            spread_pct=0.20,
            scenario=LiquidityScenario.NORMAL,
            num_levels=10,
        )

        # ADV = 1,000,000 -> Normal senaryoda max katılım %5 = 50,000 lot
        # 60,000 lotluk büyük emir girildiğinde %5 katılım tavanına takılmalı (kısmi dolum)
        res = self.builder.execute_market_order_walk(
            book=book,
            side="BUY",
            requested_quantity=60_000,
            adv=adv,
            scenario=LiquidityScenario.NORMAL,
        )

        self.assertEqual(res["requested_quantity"], 60_000)
        self.assertTrue(res["is_partial"])
        self.assertLessEqual(res["filled_quantity"], 50_000)  # ADV %5 tavanı
        self.assertGreater(res["levels_consumed"], 0)
        self.assertGreaterEqual(res["vwap_price"], book.best_ask)

    def test_multi_scenario_spread_and_depth_scaling(self) -> Any:
        """Kötümser / Normal / İyimser senaryo çarpanları testi."""
        adv = 1_000_000
        pess_book = self.builder.build_synthetic_book(
            ticker="KCHOL",
            mid_price=150.0,
            adv=adv,
            volatility=0.25,
            spread_pct=1.0,
            scenario=LiquidityScenario.PESSIMISTIC,
        )
        norm_book = self.builder.build_synthetic_book(
            ticker="KCHOL",
            mid_price=150.0,
            adv=adv,
            volatility=0.25,
            spread_pct=1.0,
            scenario=LiquidityScenario.NORMAL,
        )
        opt_book = self.builder.build_synthetic_book(
            ticker="KCHOL",
            mid_price=150.0,
            adv=adv,
            volatility=0.25,
            spread_pct=1.0,
            scenario=LiquidityScenario.OPTIMISTIC,
        )

        # Kötümser senaryoda spread daha geniş olmalı
        self.assertGreater(pess_book.spread, norm_book.spread)
        self.assertGreater(norm_book.spread, opt_book.spread)

        # Kötümser senaryoda derinlik daha sığ olmalı
        self.assertLess(pess_book.bids[0].quantity, norm_book.bids[0].quantity)
        self.assertLess(norm_book.bids[0].quantity, opt_book.bids[0].quantity)

    def test_kap_restriction_registry_timestamp_and_gating(self) -> Any:
        """KAP tedbirlerinde yayın tarihi vs yürürlük tarihi ve kısıt kapısı testi."""
        # Akşam 18:30'da yayımlanan tedbir, 2024-01-02'de yürürlüğe girer
        self.kap_reg.register_restriction(
            ticker="SASA",
            restriction_type="VBTS_SHORT_BAN",
            published_at="2024-01-01T18:30:00Z",
            effective_date="2024-01-02",
        )

        # 1. 2024-01-01 günü işlem serbest (henüz yürürlükte değil)
        ok_t1, _ = self.kap_reg.validate_trading_eligibility("SASA", "2024-01-01", "SHORT")
        self.assertTrue(ok_t1)

        # 2. 2024-01-02 günü açığa satış engellenmeli
        ok_t2, reason_t2 = self.kap_reg.validate_trading_eligibility("SASA", "2024-01-02", "SHORT")
        self.assertFalse(ok_t2)
        self.assertIn("VBTS_SHORT_BAN", reason_t2)

        # 3. Eksik / doğrulanmamış veri durumunda NO_TRADE
        ok_data, reason_data = self.kap_reg.validate_trading_eligibility(
            "SASA", "2024-01-02", "BUY", data_quality_ok=False
        )
        self.assertFalse(ok_data)
        self.assertIn("DATA_QUALITY_UNVERIFIED", reason_data)

    def test_scenario_manager_success_gate(self) -> Any:
        """3 Senaryolu Başarı Kapısı: Normal > BIST & Stres Drawdown Bounded."""
        pessimistic = ScenarioResult(
            scenario=LiquidityScenario.PESSIMISTIC,
            total_return_pct=5.0,
            cagr_pct=15.0,
            sharpe_ratio=0.8,
            max_drawdown_pct=12.0,
            win_rate=0.55,
            total_commission=100.0,
            total_slippage_cost=500.0,
            num_trades=20,
        )
        normal = ScenarioResult(
            scenario=LiquidityScenario.NORMAL,
            total_return_pct=12.0,
            cagr_pct=30.0,
            sharpe_ratio=1.4,
            max_drawdown_pct=6.0,
            win_rate=0.60,
            total_commission=100.0,
            total_slippage_cost=300.0,
            num_trades=20,
        )
        optimistic = ScenarioResult(
            scenario=LiquidityScenario.OPTIMISTIC,
            total_return_pct=18.0,
            cagr_pct=45.0,
            sharpe_ratio=1.9,
            max_drawdown_pct=4.0,
            win_rate=0.65,
            total_commission=100.0,
            total_slippage_cost=150.0,
            num_trades=20,
        )

        # 1. Başarılı Quant Stratejisi (Normal BIST'i geçti, Stres MaxDD <= %25)
        eval_pass = LiquidityScenarioManager.evaluate_strategy_validity(
            pessimistic_res=pessimistic,
            normal_res=normal,
            optimistic_res=optimistic,
            benchmark_return_pct=8.0,  # BIST %8 getirdi, Normal %12 getirdi
        )
        self.assertTrue(eval_pass["is_valid"])
        self.assertEqual(eval_pass["decision"], "VALID_QUANT_STRATEGY")

        # 2. Yalnızca İyimser Senaryoda Kârlı Olan Hatalı Strateji
        fake_pess = ScenarioResult(
            scenario=LiquidityScenario.PESSIMISTIC,
            total_return_pct=-8.0,
            cagr_pct=-15.0,
            sharpe_ratio=-0.5,
            max_drawdown_pct=28.0,
            win_rate=0.35,
            total_commission=100.0,
            total_slippage_cost=800.0,
            num_trades=20,
        )
        fake_norm = ScenarioResult(
            scenario=LiquidityScenario.NORMAL,
            total_return_pct=-2.0,
            cagr_pct=-5.0,
            sharpe_ratio=-0.1,
            max_drawdown_pct=18.0,
            win_rate=0.45,
            total_commission=100.0,
            total_slippage_cost=400.0,
            num_trades=20,
        )
        eval_fail = LiquidityScenarioManager.evaluate_strategy_validity(
            pessimistic_res=fake_pess,
            normal_res=fake_norm,
            optimistic_res=optimistic,
            benchmark_return_pct=0.0,
        )
        self.assertFalse(eval_fail["is_valid"])
        self.assertEqual(eval_fail["decision"], "INVALID_STRATEGY")
        self.assertTrue(any("OPTIMISTIC_ONLY_BIAS" in r for r in eval_fail["rejection_reasons"]))

    def test_missing_bars_and_date_mismatch_failsafe(self) -> Any:
        """Eksik bar veya tarih uyuşmazlığında sıfır sentetik varsayım ve kesin NO_TRADE testi."""
        import polars as pl

        from services.paper_trading.paper_orchestrator import PaperTradingOrchestrator

        orch = PaperTradingOrchestrator(
            champion_version="LambdaRank_v3_LOCKED",
            require_next_open=False,  # Yalnızca bar kontrolünü test ediyoruz
        )

        # 1. High/Low eksik/0 olan sinyal -> Kesin NO_TRADE
        sig_no_bars = {
            "ticker": "THYAO",
            "direction": "LONG",
            "rank": 1,
            "score": 10,
            "confidence": 0.85,
            "model_version": "LambdaRank_v3_LOCKED",
            "high": 0.0,
            "low": 0.0,
        }
        res = orch.process_daily_cycle(
            date="2024-01-01",
            signals=[sig_no_bars],
            prices={"THYAO": 100.0},
            volumes={"THYAO": 1_000_000},
        )
        self.assertEqual(res["num_orders"], 0)
        audit_log = orch.store.load_audit_log()
        self.assertTrue(any("INSUFFICIENT_HISTORICAL_BARS" in a.get("reason", "") for a in audit_log))

        # 2. DataFrame'de tarih bulunamadığında asla iloc[-1] (geleceğe bakış) kullanılmaz -> Kesin NO_TRADE
        pl.date_range(date(2024, 1, 10), date(2024, 1, 10) + timedelta(days=10), timedelta(days=1), eager=True).head(5)
        df = pl.DataFrame(
            {"Open": [100] * 5, "High": [102] * 5, "Low": [98] * 5, "Close": [101] * 5, "Volume": [1000000] * 5}
        )

        res_date_mismatch = orch.run_daily_cycle(
            date="2024-01-01",  # Veri 2024-01-10'dan başlıyor, bu tarih yok
            market_data={"THYAO": df},
            champion_signals=[sig_no_bars],
        )
        self.assertEqual(res_date_mismatch["num_orders"], 0)

    def test_exclusive_kap_registry_gross_settlement(self) -> Any:
        """Brüt takasın yalnızca KAP kısıt sicilinden teyit edilmesi testi."""
        from services.paper_trading.kap_market_restriction_registry import kap_restriction_registry

        # Sinyalde is_gross_settlement=True gelse bile KAP sicilinde yoksa brüt takas uygulanmaz
        self.assertFalse(kap_restriction_registry.is_gross_settlement("KCHOL", "2024-01-01"))

        # KAP siciline tescil edildiğinde devreye girer
        kap_restriction_registry.register_restriction(
            ticker="KCHOL",
            restriction_type="VBTS_GROSS_SETTLEMENT",
            published_at="2024-01-01T18:30:00Z",
            effective_date="2024-01-02",
        )
        self.assertFalse(kap_restriction_registry.is_gross_settlement("KCHOL", "2024-01-01"))
        self.assertTrue(kap_restriction_registry.is_gross_settlement("KCHOL", "2024-01-02"))


if __name__ == "__main__":
    unittest.main()
