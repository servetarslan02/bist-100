"""
ALPHA BIST — Multi-Asset Engine Comprehensive Test Suite

MultiAssetBacktestEngine, MultiAssetConfig, MultiAssetResult ve SectorExposure
sınıflarının tüm parametre, risk limiti, T+1 kuralı, gap kilidi, likidite tavanı,
sektör maruziyeti ve Polars veri tipleri entegrasyonunu doğrular.
"""

from __future__ import annotations

import concurrent.futures
from datetime import date

import polars as pl
import pytest

from services.backtest.multi_asset_engine import (
    MultiAssetBacktestEngine,
    MultiAssetConfig,
    MultiAssetResult,
    SectorExposure,
)


def _generate_synthetic_market_data(days: int = 10) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Deterministik piyasa ve sinyal verisi üretir."""
    dates = [date(2025, 1, 1 + i) for i in range(days)]
    tickers = ["THYAO", "ASELS", "BIMAS"]

    market_records = []
    signal_records = []

    for i, d in enumerate(dates):
        for ticker in tickers:
            base_price = 100.0 if ticker == "THYAO" else (50.0 if ticker == "ASELS" else 80.0)
            price = base_price + i * 2.0
            market_records.append({
                "date": d,
                "ticker": ticker,
                "open": price,
                "high": price + 2.0,
                "low": price - 1.0,
                "close": price + 1.0,
                "volume": 50000,
            })

        # THYAO için ilk 2 günde AL sinyali, sonra SAT sinyali
        if i < 2:
            signal_records.append({
                "date": d,
                "ticker": "THYAO",
                "score": 85.0,
                "confidence": 0.9,
            })
        elif i == 4:
            signal_records.append({
                "date": d,
                "ticker": "THYAO",
                "score": -20.0,
                "confidence": 0.85,
            })

    market_df = pl.DataFrame(market_records)
    signal_df = pl.DataFrame(signal_records)
    return market_df, signal_df


def test_sector_exposure_logic() -> None:
    """SectorExposure sınıfının limit ve string gösterim mantığını doğrular."""
    sector = SectorExposure(sector_name="Bankacilik", max_weight_pct=25.0, current_weight_pct=15.0)
    assert sector.is_within_limit(5.0) is True
    assert sector.is_within_limit(10.0) is True
    assert sector.is_within_limit(10.1) is False
    assert "Bankacilik" in repr(sector)
    assert "15.0%" in repr(sector)


def test_multi_asset_config_defaults_and_repr() -> None:
    """MultiAssetConfig varsayılan parametrelerini ve repr doğruluğunu test eder."""
    cfg = MultiAssetConfig(
        initial_capital=500_000.0,
        max_positions=10,
        max_position_pct=15.0,
        gap_limit_pct=8.0,
    )
    assert cfg.initial_capital == 500_000.0
    assert cfg.max_positions == 10
    assert cfg.gap_limit_pct == 8.0
    assert "500,000" in repr(cfg)


def test_multi_asset_engine_basic_lifecycle() -> None:
    """MultiAssetBacktestEngine tam alım-satım ve sonuç metrik döngüsünü doğrular."""
    market_df, signal_df = _generate_synthetic_market_data(days=8)
    sector_map = {"THYAO": "Ulastirma", "ASELS": "Savunma", "BIMAS": "Perakende"}

    cfg = MultiAssetConfig(
        initial_capital=100_000.0,
        max_positions=5,
        use_realistic_costs=False,
        enable_bias_detection=False,
    )
    engine = MultiAssetBacktestEngine(config=cfg)
    result = engine.run(
        market_data=market_df,
        signal_data=signal_df,
        sector_mapping=sector_map,
    )

    assert isinstance(result, MultiAssetResult)
    assert result.total_trades >= 1
    assert len(result.equity_curve) == 8
    assert len(result.daily_metrics) == 8
    assert "run_id" in result.to_dict()
    assert "metrics" in result.to_dict()
    assert repr(result).startswith("MultiAssetResult")


def test_multi_asset_engine_gap_lock() -> None:
    """Tavan/taban gap kilidi aktifken emrin gerçekleşmediğini doğrular."""
    dates = [date(2025, 2, 1), date(2025, 2, 2), date(2025, 2, 3)]
    # 1. gün kapanış 100, 2. gün açılış 120 (%20 gap > %10 gap_limit)
    market_df = pl.DataFrame({
        "date": [dates[0], dates[1], dates[2]],
        "ticker": ["THYAO", "THYAO", "THYAO"],
        "open": [100.0, 120.0, 122.0],
        "high": [102.0, 125.0, 124.0],
        "low": [99.0, 119.0, 120.0],
        "close": [100.0, 121.0, 123.0],
        "volume": [100000, 100000, 100000],
    })

    signal_df = pl.DataFrame({
        "date": [dates[0]],
        "ticker": ["THYAO"],
        "score": [90.0],
        "confidence": 0.95,
    })

    cfg = MultiAssetConfig(gap_limit_pct=10.0, enable_bias_detection=False)
    engine = MultiAssetBacktestEngine(config=cfg)
    result = engine.run(
        market_data=market_df,
        signal_data=signal_df,
        sector_mapping={"THYAO": "Ulastirma"},
    )

    # Gap kilidi nedeniyle AL emri gerçekleşmemeli
    assert result.total_trades == 0


def test_multi_asset_engine_volume_participation_limit() -> None:
    """Düşük hacimde likidite tavanı gereği pay miktarının sınırlandığını doğrular."""
    dates = [date(2025, 3, 1), date(2025, 3, 2), date(2025, 3, 3)]
    market_df = pl.DataFrame({
        "date": [dates[0], dates[1], dates[2]],
        "ticker": ["THYAO", "THYAO", "THYAO"],
        "open": [10.0, 10.0, 10.0],
        "high": [11.0, 11.0, 11.0],
        "low": [9.0, 9.0, 9.0],
        "close": [10.0, 10.0, 10.0],
        "volume": [100, 100, 100],  # Çok düşük hacim
    })

    signal_df = pl.DataFrame({
        "date": [dates[0]],
        "ticker": ["THYAO"],
        "score": [80.0],
        "confidence": 0.8,
    })

    # %5 max hacim katılımı -> 100 hacmin %5'i = max 5 pay
    cfg = MultiAssetConfig(
        initial_capital=100_000.0,
        max_volume_participation_pct=5.0,
        enable_bias_detection=False,
    )
    engine = MultiAssetBacktestEngine(config=cfg)
    result = engine.run(
        market_data=market_df,
        signal_data=signal_df,
        sector_mapping={"THYAO": "Ulastirma"},
    )

    assert result.total_trades == 1
    assert result.trade_log[0]["quantity"] <= 5


def test_multi_asset_engine_universe_tickers_filter() -> None:
    """Evren dışı hisselerin filtrelendiğini doğrular."""
    dates = [date(2025, 4, 1), date(2025, 4, 2)]
    market_df = pl.DataFrame({
        "date": [dates[0], dates[0], dates[1], dates[1]],
        "ticker": ["THYAO", "ASELS", "THYAO", "ASELS"],
        "open": [100.0, 50.0, 101.0, 51.0],
        "high": [102.0, 52.0, 103.0, 52.0],
        "low": [99.0, 49.0, 100.0, 50.0],
        "close": [101.0, 51.0, 102.0, 51.0],
        "volume": [10000, 10000, 10000, 10000],
    })

    signal_df = pl.DataFrame({
        "date": [dates[0]],
        "ticker": ["ASELS"],
        "score": [90.0],
        "confidence": 0.9,
    })

    engine = MultiAssetBacktestEngine(MultiAssetConfig(enable_bias_detection=False))
    # Sadece THYAO evrende, ASELS yok
    result = engine.run(
        market_data=market_df,
        signal_data=signal_df,
        sector_mapping={"THYAO": "Ulastirma", "ASELS": "Savunma"},
        universe_tickers={"THYAO"},
    )

    # ASELS sinyali elenmiş olmalı
    assert result.total_trades == 0


def test_multi_asset_engine_fail_closed_validation() -> None:
    """None veya geçersiz veri verildiğinde ValueError fırlatılmasını doğrular."""
    engine = MultiAssetBacktestEngine()
    with pytest.raises(ValueError, match="market_data None olamaz"):
        engine.run(market_data=None, signal_data=pl.DataFrame(), sector_mapping={})  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="signal_data None olamaz"):
        engine.run(market_data=pl.DataFrame(), signal_data=None, sector_mapping={})  # type: ignore[arg-type]


def test_multi_asset_engine_thread_concurrency() -> None:
    """Eşzamanlı thread'lerde bağımsız backtest koşturulmasını test eder."""
    market_df, signal_df = _generate_synthetic_market_data(days=5)
    sector_map = {"THYAO": "Ulastirma", "ASELS": "Savunma", "BIMAS": "Perakende"}

    def _task(idx: int) -> tuple[int, str]:
        cfg = MultiAssetConfig(initial_capital=50_000.0 * (idx + 1), enable_bias_detection=False)
        eng = MultiAssetBacktestEngine(config=cfg)
        res = eng.run(market_data=market_df, signal_data=signal_df, sector_mapping=sector_map)
        return idx, res.run_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_task, i) for i in range(3)]
        results = [f.result() for f in futures]

    run_ids = {r[1] for r in results}
    assert len(run_ids) == 3  # Her koşunun kendine has benzersiz run_id'si olmalı
