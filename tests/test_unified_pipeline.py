from typing import Any

"""
UNIFIED BIST PIPELINE INTEGRATION TESTS
=======================================
18:15 EOD Sinyal Kuyruğa Alma + 09:55 Sabah Açılışı Mikro-Yapı Yürütme Akışı Testleri
"""

import os
import tempfile
import unittest
from datetime import date, timedelta

import numpy as np
import polars as pl

from services.paper_trading.paper_orchestrator import PaperTradingOrchestrator
from services.paper_trading.state_store import PaperStateStore


class TestUnifiedPipeline(unittest.TestCase):
    """Otomatik eklendi."""
    def setUp(self) -> Any:
        """Otomatik eklendi."""
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_unified.db")
        self.store = PaperStateStore(db_path=self.db_path)
        self.orch = PaperTradingOrchestrator(
            champion_version="LambdaRank_v3_LOCKED",
            initial_capital=1_000_000.0,
            require_next_open=True,
            state_store=self.store,
        )

    def _make_mock_history(self, tickers, dates) -> Any:
        """Otomatik eklendi."""
        market_data = {}
        for t in tickers:
            prices = 100.0 + np.cumsum(np.random.randn(len(dates)) * 1.5)
            df = pl.DataFrame(
                {
                    "Open": prices * 0.995,
                    "High": prices * 1.015,
                    "Low": prices * 0.985,
                    "Close": prices,
                    "Volume": np.random.randint(1_000_000, 5_000_000, len(dates)),
                }.Series(dates)
            )
            market_data[t] = df
        return market_data

    def test_eod_signal_queuing_does_not_execute_immediately(self) -> Any:
        """18:15 EOD anında sinyal üretildiğinde hemen kapanıştan işlem yapılmaz, beklemeye alınır."""
        signals = [
            {
                "ticker": "THYAO",
                "direction": "LONG",
                "rank": 1,
                "score": 9.5,
                "confidence": 0.85,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
            {
                "ticker": "GARAN",
                "direction": "LONG",
                "rank": 2,
                "score": 8.5,
                "confidence": 0.80,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
        ]

        # 1. 18:15 EOD Sinyalleri kuyruğa al
        res = self.orch.queue_pending_signals(signals, "2024-01-01")
        self.assertEqual(res["status"], "QUEUED")
        self.assertEqual(res["count"], 2)

        # 2. Portföyde hemen işlem gerçekleşmemiş olmalı (0 pozisyon, 1M nakit)
        summary = self.orch.portfolio.get_summary()
        self.assertEqual(summary["num_positions"], 0)
        self.assertEqual(summary["cash"], 1_000_000.0)

        # 3. Store'da 2 bekleyen sinyal olmalı
        pending = self.store.load_pending_signals()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["ticker"], "THYAO")

    def test_morning_execution_with_microstructure_and_t2_settlement(self) -> Any:
        """09:55 Sabah açılışında bekleyen emirler T+1 açılış fiyatları ve mikro-yapı ile yürütülür."""
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 15), timedelta(days=1), eager=True).head(5)
        market_data = self._make_mock_history(["THYAO", "GARAN"], dates)
        sector_map = {"THYAO": "Havacilik", "GARAN": "Bankacilik"}

        signals = [
            {
                "ticker": "THYAO",
                "direction": "LONG",
                "rank": 1,
                "score": 9.5,
                "confidence": 0.85,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
            {
                "ticker": "GARAN",
                "direction": "LONG",
                "rank": 2,
                "score": 8.5,
                "confidence": 0.80,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
        ]
        self.orch.queue_pending_signals(signals, "2024-01-01")

        # Sabah yürütmesini tetikle (T gününün piyasa verisiyle)
        report = self.orch.execute_pending_signals(
            date="2024-01-01",
            market_data=market_data,
            sector_map=sector_map,
        )

        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["num_orders"], 2)

        # İşlem sonrası bekleyen sinyaller temizlenmiş olmalı
        pending_after = self.store.load_pending_signals()
        self.assertEqual(len(pending_after), 0)

        # Portföyde 2 pozisyon açılmış ve T+2 takas kaydı yapılmış olmalı
        summary = self.orch.portfolio.get_summary()
        self.assertEqual(summary["num_positions"], 2)
        self.assertLess(summary["cash"], 1_000_000.0)

    def test_blocking_pre_trade_risk_gate_blocks_excessive_order(self) -> Any:
        """Risk kapısı shadow modda değildir; kural ihlalinde emri derhal engeller."""
        signals = [
            {
                "ticker": "THYAO",
                "direction": "LONG",
                "rank": 1,
                "score": 9.5,
                "confidence": 0.85,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
        ]
        self.orch.queue_pending_signals(signals, "2024-01-01")

        # Portföy nakdini 0 yaparak alım gücünü tüket
        self.orch.portfolio.cash = 0.0
        self.orch.portfolio.settled_cash = 0.0

        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 15), timedelta(days=1), eager=True).head(5)
        market_data = self._make_mock_history(["THYAO"], dates)

        report = self.orch.execute_pending_signals(
            date="2024-01-01",
            market_data=market_data,
            sector_map={"THYAO": "Havacilik"},
        )

        # Yetersiz bakiye nedeniyle emir açılmamalıdır (Risk kapısı bloklar)
        self.assertEqual(report["num_orders"], 0)

    def test_friday_eod_to_monday_morning_open_execution(self) -> Any:
        """Cuma akşamı üretilen sinyal Pazartesi sabahı Pazartesi açılış fiyatıyla yürütülmelidir."""
        # Cuma (2024-01-05) ve Pazartesi (2024-01-08)
        dates = pl.date_range(date(2024, 1, 1), date(2024, 1, 20), timedelta(days=1), eager=True).head(10)
        # 2024-01-05 Cuma = index 4, 2024-01-08 Pazartesi = index 5
        market_data = self._make_mock_history(["THYAO"], dates)

        # Pazartesi açılış fiyatını belirgin bir değere sabitleyelim
        df = market_data["THYAO"]
        pazartesi_ts = pl.Series("2024-01-08")
        df.loc[pazartesi_ts, "Open"] = 285.50
        df.loc[pazartesi_ts, "Close"] = 290.00

        # Cuma akşamı sinyal üretildi
        signals = [
            {
                "ticker": "THYAO",
                "direction": "LONG",
                "rank": 1,
                "score": 9.5,
                "confidence": 0.85,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
        ]
        self.orch.queue_pending_signals(signals, "2024-01-05")

        # Pazartesi sabahı açılış yürütmesi
        report = self.orch.execute_pending_signals(
            date="2024-01-08",
            market_data=market_data,
            sector_map={"THYAO": "Havacilik"},
        )

        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["num_orders"], 1)

        # Gerçekleşen fiyat Pazartesi açılışı (285.50) + mikro-yapı kayması olmalıdır (asla Salı açılışı değil!)
        pos = self.orch.portfolio._positions["THYAO"]
        self.assertAlmostEqual(pos["avg_cost"], 285.50, delta=5.0)
        self.assertLess(pos["avg_cost"], 290.0)

    def test_pending_signals_retained_on_failed_morning_run(self) -> Any:
        """Sabah yürütmesi veri kalitesi / kesinti nedeniyle başarısız olursa bekleyen sinyaller silinmez."""
        signals = [
            {
                "ticker": "THYAO",
                "direction": "LONG",
                "rank": 1,
                "score": 9.5,
                "confidence": 0.85,
                "model_version": "LambdaRank_v3_LOCKED",
                "target_weight": 0.10,
            },
        ]
        self.orch.queue_pending_signals(signals, "2024-01-05")

        # Veri kalitesi hatasıyla sabah çalıştırması
        report = self.orch.execute_pending_signals(
            date="2024-01-08",
            market_data={},
            data_quality_ok=False,
        )

        self.assertEqual(report["status"], "NO_TRADE")

        # Hata durumunda bekleyen sinyaller silinmeyip korunmalıdır
        pending = self.store.load_pending_signals()
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
