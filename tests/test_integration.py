import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Integration Test Suite v1.0

Pipeline E2E test:
1. Veri cekme (yfinance)
2. Feature engineering
3. Ranking
4. Backtest
5. Rapor

Kural: Bu test Gercek veri ile calisir. Mock yok.
"""

import sys
from datetime import UTC, date, datetime, timedelta

import polars as pl


def test_yahoo_finance_fetch() -> Any:
    """Yahoo Finance'ten THYAO verisi cek."""
    logger.info("\n[Test] Yahoo Finance fetch...")
    from services.data.data_source import data_source

    df = data_source.get_stock_data("THYAO.IS", period="1mo", interval="1d")
    assert not df.empty, "THYAO verisi bos!"
    assert "Close" in df.columns, "Close kolonu yok!"
    assert len(df) > 5, "Yetersiz veri!"
    logger.info(f"  ✅ THYAO: {len(df)} gun, son fiyat: {df['Close'].iloc[-1]:.2f}")
    return True


def test_bist_source_fetch() -> Any:
    """BISTSource'tan veri cekmeye calis."""
    logger.info("\n[Test] BISTSource fetch...")
    from services.data.data_source import BISTSource

    bist = BISTSource()
    df = bist.fetch("THYAO")
    if df is not None and not df.empty:
        logger.info(f"  ✅ BISTSource: {len(df)} satir")
    else:
        logger.info("  ⚠️ BISTSource bos dondu (web scrape basarisiz olabilir)")
    return True


def test_multiple_stocks() -> Any:
    """Coklu hisse verisi cek."""
    logger.info("\n[Test] Multiple stocks fetch...")
    from services.data.data_source import data_source

    tickers = ["THYAO.IS", "GARAN.IS", "XU100.IS"]
    results = data_source.get_multiple_stocks(tickers, period="1mo", interval="1d")

    assert len(results) > 0, "Hic veri cekilemedi!"
    for t, df in results.items():
        assert not df.empty, f"{t} bos!"
        assert "Close" in df.columns, f"{t} Close yok!"
    logger.info(f"  ✅ Coklu hisse: {len(results)} hisse yuklendi")
    return True


def test_universe_loaded() -> Any:
    """Evren yuklendi mi?"""
    logger.info("\n[Test] Universe loaded...")
    from services.ingestion.bist_universe import bist_universe

    assert len(bist_universe.BIST_100_TICKERS) > 0, "BIST 100 bos!"
    assert len(bist_universe.BIST_ALL_TICKERS) > 0, "BIST ALL bos!"
    logger.info(f"  ✅ Universe: BIST100={len(bist_universe.BIST_100_TICKERS)}, ALL={len(bist_universe.BIST_ALL_TICKERS)}")
    return True


def test_sector_map() -> Any:
    """Sektor haritasi calisiyor mu?"""
    logger.info("\n[Test] Sector map...")
    from services.ingestion.bist_universe import bist_universe

    sector = bist_universe.get_ticker_sector("THYAO")
    logger.info(f"  ✅ THYAO sektoru: {sector}")
    return True


def test_daily_pipeline() -> Any:
    """Gunluk pipeline calistir."""
    logger.info("\n[Test] Daily pipeline...")
    from services.core.orchestrator import orchestrator
    from services.data.data_source import data_source
    from services.ingestion.bist_universe import bist_universe

    # Sadece 3 hisse ile test (hizli)
    test_tickers = ["THYAO.IS", "GARAN.IS", "XU100.IS"]
    market_data = data_source.get_multiple_stocks(test_tickers, period="3mo", interval="1d")
    market_data = {k.replace(".IS", ""): v for k, v in market_data.items()}

    assert len(market_data) > 0, "Veri yuklenemedi!"

    sector_map = {t: bist_universe.get_ticker_sector(t) for t in market_data}

    date = datetime.now(UTC).strftime("%Y-%m-%d")
    report = orchestrator.run_full_pipeline(
        date=date,
        market_data=market_data,
        sector_map=sector_map,
    )

    assert report is not None, "Rapor None!"
    assert report.system_health["status"] != "CRITICAL", "Pipeline kritik hata!"
    logger.info(f"  ✅ Pipeline: status={report.system_health['status']}, opportunities={len(report.top_opportunities)}")
    return True


def test_walk_forward_folds() -> Any:
    """Walk-forward fold olusturma."""
    logger.info("\n[Test] Walk-forward folds...")
    from services.backtest.walk_forward import WalkForwardEngine

    wf = WalkForwardEngine(train_days=20, test_days=5, step_days=5)
    dates = pl.date_range(date(2023, 1, 1), date(2023, 3, 1), timedelta(days=1), eager=True).cast(pl.Utf8).to_list()
    folds = wf.create_folds(dates)

    assert len(folds) > 0, "Fold olusmadi!"
    for f in folds:
        assert f["train_start"] < f["test_start"], "Train/Test overlap!"
        assert f["purge_start"] <= f["test_start"], "Purge gap yok!"
    logger.info(f"  ✅ Walk-forward: {len(folds)} fold olusturuldu")
    return True


def test_backtest_engine() -> Any:
    """Backtest engine calistir."""
    logger.info("\n[Test] Backtest engine...")
    from services.backtest.engine import BacktestEngine

    bt = BacktestEngine()

    signals = [
        {"date": "2023-01-01", "ticker": "THYAO", "action": "BUY", "price": 100, "confidence": 0.8},
        {"date": "2023-01-10", "ticker": "THYAO", "action": "SELL", "price": 110, "confidence": 0.8},
    ]
    price_data = {
        "THYAO": [
            {"date": "2023-01-01", "close": 100, "volume": 1000000},
            {"date": "2023-01-10", "close": 110, "volume": 1000000},
        ]
    }

    result = bt.run_backtest("test", signals, price_data, initial_capital=100000)

    assert result is not None, "Backtest sonucu None!"
    assert result.metrics.total_trades > 0, "Islem yapilmadi!"
    logger.info(f"  ✅ Backtest: {result.metrics.total_trades} islem, getiri={result.metrics.total_return_pct:.2f}%")
    return True


def test_llm_fallback() -> Any:
    """LLM fallback calisiyor mu?"""
    logger.info("\n[Test] LLM fallback...")
    from services.agents.agent_system import AIFallback

    features = {"roc_5d": 5.0, "volume_zscore": 2.5, "rsi_14": 45, "trend_slope_20d": 0.01}
    result = AIFallback.rule_based_analysis(features, "THYAO")

    assert "direction" in result, "Direction yok!"
    assert result["direction"] in ["LONG", "SHORT", "NEUTRAL"], "Gecersiz direction!"
    logger.info(f"  ✅ Fallback: direction={result['direction']}, confidence={result['confidence']:.2f}")
    return True


def run_all_tests() -> Any:
    """Tum testleri calistir."""
    tests = [
        test_yahoo_finance_fetch,
        test_bist_source_fetch,
        test_multiple_stocks,
        test_universe_loaded,
        test_sector_map,
        test_daily_pipeline,
        test_walk_forward_folds,
        test_backtest_engine,
        test_llm_fallback,
    ]

    passed = 0
    failed = 0
    errors = []

    logger.info("=" * 70)
    logger.info("ALPHA BIST — INTEGRATION TEST SUITE v1.0")
    logger.info("=" * 70)

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append(f"{test.__name__}: {e}")
            logger.info(f"  ❌ FAILED: {e}")

    logger.info("\n" + "=" * 70)
    logger.info(f"SONUC: {passed} passed, {failed} failed, {len(tests)} total")
    logger.info("=" * 70)

    if errors:
        logger.info("\nHATALAR:")
        for err in errors:
            logger.info(f"  • {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
