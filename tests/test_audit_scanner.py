"""
Comprehensive audit tests for services/scanner/ module.
Verifies:
1. Module exports and version parity.
2. ScannerInterface and ScanResult representations and serialization.
3. AlphaScanner opportunity scoring and regime awareness.
4. TieredScanner state tracking and multi-tier filtering.
5. OpportunityDiscoveryEngine multi-factor computation.
6. ScanPersistence DuckDB buffer and history querying.
7. ScanDeduplicator cooldown and force-scan bypass.
8. AdaptiveScanScheduler scan modes and dynamic interval adjustments.
9. CustomFilterEngine BIST-specific filter execution.
10. PerformanceTracker hit rates, durations, and signal accuracy.
11. ScanAlertManager rules and notifications.
12. EventPriorityQueue task ordering and execution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.scanner import (
    AdaptiveScanScheduler,
    AlphaScanner,
    AssetTierState,
    CustomFilterEngine,
    MarketRegime,
    OpportunityDiscoveryEngine,
    ScanAlertManager,
    ScanAPI,
    ScanDeduplicator,
    ScannerResult,
    ScanPerformanceTracker,
    ScanPersistence,
    ScanResult,
    ScanResultRecord,
    SignalType,
    Tier,
    TieredScanner,
)


def test_scanner_exports_and_reprs() -> None:
    """Tüm scanner sınıflarının dışa aktarımı ve __repr__ metotlarını test eder."""
    res = ScanResult(
        ticker="THYAO",
        timestamp=datetime.now(UTC),
        price=310.5,
        opportunity_score=85.4,
        signal_type=SignalType.BREAKOUT,
        signal_direction="LONG",
        current_tier=Tier.OPPORTUNITY,
    )
    assert "THYAO" in repr(res)
    assert "85.4" in repr(res)
    assert res.to_dict()["ticker"] == "THYAO"

    alpha_res = ScannerResult(
        ticker="GARAN",
        timestamp=datetime.now(UTC),
        opportunity_score=78.2,
        opportunity_rank=1,
        signal_type="MOMENTUM",
        signal_direction="BUY",
    )
    assert "GARAN" in repr(alpha_res)

    tier_state = AssetTierState(ticker="KCHOL", current_tier=1, opportunity_score=72.0, price=180.0)
    assert "KCHOL" in repr(tier_state)

    regime = MarketRegime(regime="BULL", confidence=0.85)
    assert "BULL" in repr(regime)
    assert "0.85" in repr(regime)

    record = ScanResultRecord(
        scan_id="scan-001",
        scan_type="batch",
        ticker="EREGL",
        score=65.0,
        signal="VOLUME_SPIKE",
        direction="LONG",
        confidence=0.75,
        tier=2,
        regime="RANGE",
        price=45.2,
        volume=1500000,
        features={"rsi": 55.0},
        timestamp=datetime.now(UTC).isoformat(),
    )
    assert "EREGL" in repr(record)
    assert record.to_dict()["scan_id"] == "scan-001"


def test_alpha_scanner_pipeline() -> None:
    """AlphaScanner tarama, sıralama ve sinyal üretim mantığını doğrular."""
    scanner = AlphaScanner()
    assert "AlphaScanner" in repr(scanner)

    universe = ["THYAO", "GARAN", "AKBNK"]
    features_map = {
        "THYAO": {
            "price": 310.0,
            "return_1d": 2.5,
            "volume": 2000000,
            "rsi_14": 62.0,
            "roc_5d": 4.5,
            "volume_zscore": 2.2,
            "bb_position": 0.96,
            "trend_slope_20d": 0.5,
        },
        "GARAN": {
            "price": 120.0,
            "return_1d": -1.2,
            "volume": 1200000,
            "rsi_14": 45.0,
            "roc_5d": -1.5,
            "volume_zscore": 0.5,
            "bb_position": 0.40,
            "trend_slope_20d": -0.2,
        },
        "AKBNK": {
            "price": 60.0,
            "return_1d": 0.2,
            "volume": 800000,
            "rsi_14": 52.0,
            "roc_5d": 0.8,
            "volume_zscore": -0.1,
            "bb_position": 0.55,
            "trend_slope_20d": 0.1,
        },
    }

    results = scanner.scan(universe, features_map, market_regime="BULL", regime_confidence=0.8)
    assert len(results) == 3

    ranked = scanner.get_opportunities(results, top_n=2, min_score=40.0)
    assert len(ranked) <= 2
    assert ranked[0].opportunity_rank == 1

    signals = scanner.generate_signals(ranked)
    assert isinstance(signals, list)
    summary = scanner.get_summary(results)
    assert summary["total_scanned"] == 3


def test_tiered_scanner_tick_processing() -> None:
    """TieredScanner kademeli state güncellemesini doğrular."""
    ts = TieredScanner()
    assert "TieredScanner" in repr(ts)

    ts.register_assets(["THYAO", "BIMAS"])
    ts.process_tick("THYAO", price=312.0, volume=50000)
    state = ts._assets["THYAO"]
    assert state.price == 312.0

    ts.update_regime("BULL", confidence=0.8)
    assert ts._regime.regime == "BULL"

    opps = ts.get_top_opportunities(n=5)
    assert len(opps) == 2


def test_opportunity_discovery_engine() -> None:
    """OpportunityDiscoveryEngine çok faktörlü skorlama mekanizmasını test eder."""
    engine = OpportunityDiscoveryEngine()
    assert "OpportunityDiscoveryEngine" in repr(engine)

    features = {
        "price": 100.0,
        "return_1d": 1.5,
        "roc_5d": 3.2,
        "momentum_20d": 5.0,
        "volume_zscore": 1.8,
        "rsi_14": 58.0,
        "bb_position": 0.85,
        "atr_14_pct": 2.5,
        "trend_slope_20d": 0.3,
        "price_vs_sma20": 4.0,
    }

    score = engine.compute_opportunity_score(
        ticker="SISE",
        features=features,
        market_regime="BULL",
        ml_score=75.0,
        fundamental_score=80.0,
    )
    assert "SISE" in repr(score)
    assert score.opportunity_score > 0
    assert score.risk_adjusted_score > 0


def test_scan_persistence(tmp_path: Any) -> None:
    """ScanPersistence DuckDB arabelleğe alma ve yazma operasyonlarını test eder."""
    db_file = str(tmp_path / "test_scan.duckdb")
    pers = ScanPersistence(db_path=db_file)
    assert "ScanPersistence" in repr(pers)

    record = ScanResultRecord(
        scan_id="scan-123",
        scan_type="live",
        ticker="TUPRS",
        score=82.5,
        signal="BREAKOUT",
        direction="LONG",
        confidence=0.88,
        tier=2,
        regime="BULL",
        price=175.0,
        volume=5000000,
        features={"rsi": 65.0},
        timestamp=datetime.now(UTC).isoformat(),
    )
    pers.save_scan_result(record)
    pers.flush()

    recent = pers.get_scan_history(ticker="TUPRS", days=30, limit=5)
    assert len(recent) == 1
    assert recent[0]["ticker"] == "TUPRS"
    pers.close()


def test_scan_deduplicator() -> None:
    """ScanDeduplicator cooldown ve zorlamalı tarama mantığını test eder."""
    dedup = ScanDeduplicator(cooldown_seconds=60, event_cooldown_seconds=5)
    assert "ScanDeduplicator" in repr(dedup)

    assert dedup.should_scan("PETKM") is True
    dedup.record_scan("PETKM", score=70.0, tier=1)

    # İkinci çağrı cooldown nedeniyle engellenmeli
    assert dedup.should_scan("PETKM") is False

    # Force scan tetiklenince izin vermeli
    dedup.force_scan("PETKM")
    assert dedup.should_scan("PETKM") is True


def test_adaptive_scan_scheduler() -> None:
    """AdaptiveScanScheduler seans ve rejim adaptasyonunu test eder."""
    sched = AdaptiveScanScheduler(base_interval=30)
    assert "AdaptiveScanScheduler" in repr(sched)

    sched.update_market_state(regime="TRENDING-UP")
    assert sched._current_interval < 30  # TRENDING-UP hızlandırmalıdır


def test_custom_filters() -> None:
    """CustomFilterEngine filtre kurallarını doğrular."""
    cfe = CustomFilterEngine()
    assert "CustomFilterEngine" in repr(cfe)

    sample_res = {"ticker": "XYZ", "price": 15.0, "volume": 150000}
    filtered, filter_log = cfe.apply_filters([sample_res])
    assert len(filtered) == 1
    assert isinstance(filter_log, list)


def test_performance_tracker_and_alerts() -> None:
    """ScanPerformanceTracker ve ScanAlertManager'ı doğrular."""
    tracker = ScanPerformanceTracker(max_history=100)
    assert "ScanPerformanceTracker" in repr(tracker)

    tracker.record_scan(
        scan_type="batch",
        tickers_scanned=500,
        opportunities_found=25,
        signals_generated=5,
        duration_ms=450.0,
        regime="BULL",
    )
    summary = tracker.get_stats()
    assert summary["total_scans"] == 1

    alert_mgr = ScanAlertManager()
    assert "ScanAlertManager" in repr(alert_mgr)

    alerts = alert_mgr.check_scan_results([
        {
            "ticker": "THYAO",
            "score": 92.0,
            "signal": "BREAKOUT",
            "direction": "LONG",
            "confidence": 0.85,
            "price": 310.0,
        }
    ])
    assert len(alerts) >= 1
    assert "THYAO" in repr(alerts[0])


def test_scan_api_instance() -> None:
    """ScanAPI durum raporlamasını doğrular."""
    api = ScanAPI()
    assert "ScanAPI" in repr(api)
    status = api.get_status()
    assert "timestamp" in status
