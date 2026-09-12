"""ALPHA BIST — Pipeline Servisleri Kapsamlı Denetim Testleri.

Bu test modülü `services/pipeline/` altındaki tüm bileşenleri ve akışları test eder:
- `main_backtest.py`: Sabitler, docstringler, `run_final` döngüsü.
- `run_daily_inference.py`: Çıkarım döngüsü, veri kontrolü, rejim değerlendirmesi, veritabanı kaydı.
- `run_unified_daily.py`: EOD sinyal döngüsü, sabah yürütme döngüsü, rebalance kontrolü, birleşik döngü.
- `startup_catchup.py`: `MasterStartupCatchup`, kaçırılan seans tespiti, tam telafi döngüsü.
- `__init__.py`: Dışa aktarılan tüm sembol ve sabitlerin doğrulanması.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.pipeline as pipeline
from services.pipeline.main_backtest import (
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_TOP_PICKS,
    run_final,
)
from services.pipeline.run_daily_inference import (
    DEFAULT_LOOKBACK_DAYS,
    MIN_COMMON_DATES_THRESHOLD,
    run_alpha_engine_sync,
)
from services.pipeline.run_unified_daily import (
    DEFAULT_MAX_POSITION_CAP,
    HOLDING_PERIOD_DAYS,
    get_last_rebalance_date,
    run_eod_signal_cycle,
    run_morning_execution_cycle,
    run_unified_daily_cycle,
)
from services.pipeline.startup_catchup import (
    MasterStartupCatchup,
    master_catchup,
)


def test_pipeline_exports_and_constants() -> None:
    """Pipeline paketinin tüm modül seviyesi sabit ve sembolleri eksiksiz dışa aktardığını doğrular."""
    assert DEFAULT_INITIAL_CAPITAL == 100_000.0
    assert DEFAULT_TOP_PICKS == 10
    assert DEFAULT_LOOKBACK_DAYS == 400
    assert MIN_COMMON_DATES_THRESHOLD == 200
    assert DEFAULT_MAX_POSITION_CAP == 0.20
    assert HOLDING_PERIOD_DAYS == 63
    assert hasattr(pipeline, "run_final")
    assert hasattr(pipeline, "run_alpha_engine_sync")
    assert hasattr(pipeline, "run_eod_signal_cycle")
    assert hasattr(pipeline, "run_morning_execution_cycle")
    assert hasattr(pipeline, "run_unified_daily_cycle")
    assert hasattr(pipeline, "MasterStartupCatchup")
    assert hasattr(pipeline, "master_catchup")


def test_master_startup_catchup_repr_and_init() -> None:
    """MasterStartupCatchup sınıfının başlatılmasını ve __repr__ temsilini doğrular."""
    catchup = MasterStartupCatchup()
    rep = repr(catchup)
    assert "MasterStartupCatchup" in rep
    assert repr(master_catchup).startswith("MasterStartupCatchup")


def test_master_startup_catchup_missed_days() -> None:
    """MasterStartupCatchup sınıfının kaçırılan seans günlerini tatil/hafta sonu filtreleriyle doğru hesapladığını doğrular."""
    catchup = MasterStartupCatchup()

    # Boş veya geçersiz tarih testi
    assert catchup.get_missed_trading_days(None, date(2026, 3, 10)) == []
    assert catchup.get_missed_trading_days("invalid-date", date(2026, 3, 10)) == []

    # 2026-03-02 (Pazartesi) ile 2026-03-06 (Cuma) arası (Salı, Çarşamba, Perşembe seansları)
    with patch.object(catchup.calendar, "is_holiday", return_value=False):
        missed = catchup.get_missed_trading_days("2026-03-02", date(2026, 3, 6))
        expected_days = [date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5)]
        assert missed == expected_days

    # Hafta sonu içeren aralık: Cuma'dan Pazartesi'ye kaçırılmış gün olmamalı
    with patch.object(catchup.calendar, "is_holiday", return_value=False):
        missed = catchup.get_missed_trading_days("2026-03-06", date(2026, 3, 9))
        assert missed == []


@pytest.mark.asyncio
async def test_master_startup_catchup_execute_full() -> None:
    """MasterStartupCatchup execute_full_catchup döngüsünün tüm adımlarını başarıyla tamamladığını doğrular."""
    catchup = MasterStartupCatchup()

    with (
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.store.get_config", return_value="2026-03-05"),
        patch.object(catchup, "get_missed_trading_days", return_value=[date(2026, 3, 6)]),
        patch("services.ingestion.backfill.backfill_manager.detect_all_gaps", new_callable=AsyncMock, return_value=[]),
        patch("services.pipeline.startup_catchup.run_morning_execution_cycle", new_callable=AsyncMock, return_value={"executed_trades_count": 2}),
        patch("services.pipeline.startup_catchup.run_eod_signal_cycle", new_callable=AsyncMock, return_value={"status": "COMPLETED"}),
        patch.object(catchup.learning_pipeline, "check_and_catchup_if_needed", return_value={"status": "up_to_date"}),
        patch("services.scanner.bist_ml_scanner.bist_ml_scanner.scan_all_opportunities", return_value=[{"ticker": "THYAO", "score": 85.0}]),
        patch("redis.Redis") as mock_redis,
    ):
        mock_r_instance = MagicMock()
        mock_redis.return_value = mock_r_instance

        results = await catchup.execute_full_catchup()
        assert results["status"] == "COMPLETED"
        assert results["missed_days_count"] == 1
        assert results["trades_replayed"] == 2
        assert results["ml_retrained"] is False


@pytest.mark.asyncio
async def test_get_last_rebalance_date() -> None:
    """get_last_rebalance_date fonksiyonunun veritabanı yanıtını doğru dönüştürdüğünü doğrular."""
    fake_date = date(2026, 2, 15)
    fake_row = [{"created_at": MagicMock(date=lambda: fake_date)}]

    with patch("services.pipeline.run_unified_daily.pg_fetch", new_callable=AsyncMock, return_value=fake_row):
        res = await get_last_rebalance_date()
        assert res == fake_date

    # Hata durumu fallback testi
    with patch("services.pipeline.run_unified_daily.pg_fetch", new_callable=AsyncMock, side_effect=RuntimeError("DB Error")):
        res_error = await get_last_rebalance_date()
        assert res_error is None


@pytest.mark.asyncio
async def test_run_eod_signal_cycle_and_unified_cycle() -> None:
    """run_eod_signal_cycle ve run_unified_daily_cycle fonksiyonlarının doğru çalıştığını doğrular."""
    with (
        patch("services.pipeline.run_unified_daily.init_databases", new_callable=AsyncMock),
        patch("services.pipeline.run_unified_daily.get_last_rebalance_date", new_callable=AsyncMock, return_value=date(2026, 1, 1)),
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.portfolio.get_all_positions", return_value=[]),
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.mark_to_market_cycle", return_value={"portfolio_value": 100_000.0}),
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.queue_pending_signals"),
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.store.load_pending_signals", return_value=[]),
        patch("services.scanner.bist_ml_scanner.bist_ml_scanner.scan_all_opportunities", return_value=[{"ticker": "ASELS", "score": 88.0, "expected_return_pct": 18.0}]),
        patch("services.core.redis_helper.set_cached"),
        patch("services.pipeline.run_unified_daily.pg_execute", new_callable=AsyncMock),
    ):
        res = await run_eod_signal_cycle(target_date="2026-03-09", force_rebalance=True)
        assert res["status"] == "COMPLETED"
        assert res["phase"] == "EOD_SIGNAL_PHASE"
        assert res["needs_rebalance"] is True
        assert res["queued_signals_count"] >= 1

        # run_unified_daily_cycle testi
        with patch("services.pipeline.run_unified_daily.run_morning_execution_cycle", new_callable=AsyncMock, return_value={"status": "MORNING_OK"}):
            unified_res = await run_unified_daily_cycle()
            assert unified_res.get("status") in ["MORNING_OK", "COMPLETED"]


@pytest.mark.asyncio
async def test_run_morning_execution_cycle() -> None:
    """run_morning_execution_cycle fonksiyonunun bekleyen emirleri çekip yürütüme aktardığını doğrular."""
    pending_signals = [{"ticker": "GARAN", "direction": "LONG", "target_weight": 0.10}]
    fake_report = {"status": "SUCCESS", "executed_trades_count": 1}

    with (
        patch("services.pipeline.run_unified_daily.init_databases", new_callable=AsyncMock),
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.store.load_pending_signals", return_value=pending_signals),
        patch("services.core.alpha_engine.AlphaEngine.fetch_data", return_value=({}, MagicMock(index=[], empty=True), {})),
        patch("services.paper_trading.paper_orchestrator.paper_orchestrator.execute_pending_signals", return_value=fake_report),
    ):
        res = await run_morning_execution_cycle(target_date="2026-03-09")
        assert res == fake_report


def test_run_daily_inference_sync() -> None:
    """run_alpha_engine_sync çıkarım fonksiyonunu taklitli bağımlılıklarla doğrular."""
    from datetime import timedelta

    fake_bm_df = MagicMock()
    fake_bm_df.empty = False
    base_date = date(2025, 1, 1)
    fake_bm_df.index = [
        MagicMock(strftime=lambda fmt, d=(base_date + timedelta(days=i)): d.strftime(fmt))
        for i in range(210)
    ]

    with (
        patch("services.core.alpha_engine.AlphaEngine.fetch_data", return_value=({"THYAO": MagicMock()}, fake_bm_df, {})),
        patch("services.core.alpha_engine.AlphaEngine.train", return_value=True),
        patch("services.core.alpha_engine.AlphaEngine.predict", return_value=[{"ticker": "THYAO", "score": 90.0}]),
        patch("services.core.risk_manager.RiskManager.get_market_regime", return_value=1.0),
        patch("services.pipeline.run_daily_inference.pg_execute", new_callable=AsyncMock),
    ):
        res = run_alpha_engine_sync()
        assert res is not None
        assert res["status"] == "SUCCESS"
        assert res["is_cash_regime"] is False
        assert len(res["top_picks"]) == 1


def test_run_final_backtest() -> None:
    """run_final fonksiyonunun walk-forward ve optuna adımlarını simüle ederek rapor döndürdüğünü doğrular."""
    from datetime import timedelta

    fake_bm_df = MagicMock()
    base_date = date(2024, 1, 1)
    fake_bm_df.index = [
        MagicMock(strftime=lambda fmt, d=(base_date + timedelta(days=i)): d.strftime(fmt))
        for i in range(10)
    ]

    fake_report = MagicMock()
    fake_report.metrics.cagr_pct = 45.2
    fake_report.metrics.max_drawdown_pct = 12.1
    fake_report.metrics.sharpe_ratio = 2.45
    fake_report.metrics.sortino_ratio = 3.10
    fake_report.metrics.win_rate = 0.65
    fake_report.metrics.total_trades = 40
    fake_report.metrics.profit_factor = 2.1

    with (
        patch("services.core.alpha_engine.AlphaEngine.fetch_data", return_value=({}, fake_bm_df, {})),
        patch("services.backtest.walk_forward.WalkForwardEngine.create_folds", return_value=[]),
        patch("services.backtest.execution_engine.BacktestEngine.run_backtest", return_value=fake_report),
    ):
        report = run_final()
        assert report == fake_report
        assert report.metrics.sharpe_ratio == 2.45
