"""
ALPHA BIST — FAZ 15+ Test Suite

Extended Indicators, Analysis Engines, Research Memory, Event Infrastructure,
Forecasting, Notification/Alert, Snapshot, Cache, Job Queue testleri.
"""

import sys
import os
import asyncio


def test_extended_indicators():
    """Extended Technical Indicators testleri."""
    from services.features.extended_indicators import extended_indicators
    import numpy as np

    passed = 0
    failed = 0

    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.random.rand(n) * 2
    low = close - np.random.rand(n) * 2
    open_ = close - np.random.rand(n) + 0.5
    volume = (np.random.rand(n) * 1000000 + 100000).astype(int)

    # 1. Ichimoku
    ich = extended_indicators.compute_ichimoku(high, low, close)
    assert "ichimoku_tenkan" in ich
    assert "ichimoku_kijun" in ich
    passed += 1
    print(f"  ✓ Ichimoku: tenkan={ich['ichimoku_tenkan']:.2f}, kijun={ich['ichimoku_kijun']:.2f}")

    # 2. Fibonacci
    fib = extended_indicators.compute_fibonacci(high, low, close)
    assert "fib_0" in fib
    assert "fib_618" in fib
    assert fib["fib_0"] < fib["fib_100"]
    passed += 1
    print(f"  ✓ Fibonacci: {fib['fib_0']:.2f} - {fib['fib_100']:.2f}")

    # 3. VWAP
    vwap = extended_indicators.compute_vwap(high, low, close, volume)
    assert "vwap" in vwap
    assert vwap["vwap"] > 0
    passed += 1
    print(f"  ✓ VWAP: {vwap['vwap']:.2f}")

    # 4. Pivot Points
    pivot = extended_indicators.compute_pivot_points(high, low, close)
    assert "pivot" in pivot
    assert pivot["pivot_r1"] > pivot["pivot"]
    assert pivot["pivot_s1"] < pivot["pivot"]
    passed += 1
    print(f"  ✓ Pivot: {pivot['pivot']:.2f}, R1={pivot['pivot_r1']:.2f}, S1={pivot['pivot_s1']:.2f}")

    # 5. Heikin-Ashi
    ha = extended_indicators.compute_heikin_ashi(open_, high, low, close)
    assert "ha_close" in ha
    assert "ha_bullish" in ha
    passed += 1
    print(f"  ✓ Heikin-Ashi: close={ha['ha_close']:.2f}, bullish={ha['ha_bullish']}")

    # 6. Elder Ray
    elder = extended_indicators.compute_elder_ray(close)
    assert "elder_bull_power" in elder
    passed += 1
    print(f"  ✓ Elder Ray: bull={elder['elder_bull_power']:.2f}")

    # 7. Keltner
    keltner = extended_indicators.compute_keltner(high, low, close)
    assert "keltner_upper" in keltner
    assert keltner["keltner_upper"] > keltner["keltner_lower"]
    passed += 1
    print(f"  ✓ Keltner: {keltner['keltner_lower']:.2f} - {keltner['keltner_upper']:.2f}")

    # 8. Donchian
    donchian = extended_indicators.compute_donchian(high, low, close)
    assert "donchian_upper" in donchian
    assert donchian["donchian_upper"] > donchian["donchian_lower"]
    passed += 1
    print(f"  ✓ Donchian: {donchian['donchian_lower']:.2f} - {donchian['donchian_upper']:.2f}")

    # 9. ROC multi
    roc = extended_indicators.compute_roc_multi(close)
    assert "roc_5d" in roc
    assert "roc_20d" in roc
    passed += 1
    print(f"  ✓ ROC multi: {roc}")

    # 10. ATR multi
    atr = extended_indicators.compute_atr_multi(high, low, close)
    assert "atr_14" in atr
    assert atr["atr_14"] > 0
    passed += 1
    print(f"  ✓ ATR multi: {atr}")

    # 11. All extended
    all_ext = extended_indicators.compute_all_extended(high, low, close, volume, open_)
    assert len(all_ext) > 30
    passed += 1
    print(f"  ✓ All extended: {len(all_ext)} features")

    return passed, failed


def test_analysis_engines():
    """Analysis Engines testleri."""
    from services.intelligence.analysis_engines import (
        price_action_engine, support_resistance_engine, volume_engine,
        drawdown_engine, position_risk_engine, model_risk_engine,
        data_confidence_engine, portfolio_optimization,
    )
    import numpy as np

    passed = 0
    failed = 0

    np.random.seed(42)
    n = 30
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.random.rand(n) * 2
    low = close - np.random.rand(n) * 2
    open_ = close - np.random.rand(n) + 0.5
    volume = (np.random.rand(n) * 1000000 + 100000).astype(int)

    # 1. Price Action
    pa = price_action_engine.detect_patterns(open_, high, low, close)
    assert isinstance(pa, dict)
    passed += 1
    print(f"  ✓ Price Action: {len(pa)} patterns")

    # 2. Support/Resistance
    sr = support_resistance_engine.compute_levels(high, low, close)
    assert "resistance_1" in sr
    assert "support_1" in sr
    passed += 1
    print(f"  ✓ S/R: R1={sr.get('resistance_1', 0):.2f}, S1={sr.get('support_1', 0):.2f}")

    # 3. Volume Engine
    vol = volume_engine.compute(close, volume)
    assert isinstance(vol, dict)
    passed += 1
    print(f"  ✓ Volume: {vol}")

    # 4. Drawdown
    equity = [100000, 102000, 99000, 97000, 101000, 103000, 98000, 105000]
    dd = drawdown_engine.compute(equity)
    assert "max_drawdown_pct" in dd
    assert dd["max_drawdown_pct"] > 0
    passed += 1
    print(f"  ✓ Drawdown: {dd['max_drawdown_pct']:.2f}%")

    # 5. Position Risk
    pr = position_risk_engine.compute(10000, 100000, 0.25, 0.6)
    assert "position_weight" in pr
    assert pr["position_weight"] == 0.1
    passed += 1
    print(f"  ✓ Position Risk: weight={pr['position_weight']:.2f}")

    # 6. Model Risk
    predictions = [1.0, 2.0, 3.0, 4.0, 5.0]
    actuals = [1.1, 1.9, 3.2, 3.8, 5.1]
    mr = model_risk_engine.compute_reliability(predictions, actuals)
    assert "model_reliability" in mr
    assert mr["model_reliability"] > 0.5
    passed += 1
    print(f"  ✓ Model Risk: reliability={mr['model_reliability']:.2f}")

    # 7. Data Confidence
    dc = data_confidence_engine.compute(0.9, 0.8, 0.7, 0.85)
    assert "data_confidence" in dc
    assert 0 < dc["data_confidence"] < 1
    passed += 1
    print(f"  ✓ Data Confidence: {dc['data_confidence']:.2f}")

    # 8. Portfolio Optimization
    returns = np.array([0.10, 0.15, 0.12])
    cov = np.array([[0.04, 0.01, 0.02], [0.01, 0.09, 0.03], [0.02, 0.03, 0.06]])
    weights = portfolio_optimization.compute_optimal_weights(returns, cov, "min_volatility")
    assert len(weights) == 3
    assert abs(weights.sum() - 1.0) < 0.01
    passed += 1
    print(f"  ✓ Portfolio Optimization: weights={weights.round(2)}")

    return passed, failed


def test_research_memory():
    """Research Memory testleri."""
    from services.intelligence.research_memory import (
        research_memory, research_context_engine, data_lineage,
        ResearchRecord, LineageNode,
    )

    passed = 0
    failed = 0

    # 1. Add record
    record = ResearchRecord(
        record_id="R001", ticker="THYAO", date="2026-08-15",
        thesis="Momentum strong", evidence=["volume spike", "breakout"],
        risks=["high volatility"], prediction={"return": 5.0, "prob": 0.7},
    )
    research_memory.add_record(record)
    assert len(research_memory._records) >= 1
    passed += 1
    print(f"  ✓ Record added")

    # 2. Get ticker history
    history = research_memory.get_ticker_history("THYAO")
    assert len(history) >= 1
    passed += 1
    print(f"  ✓ Ticker history: {len(history)} records")

    # 3. Get recent
    recent = research_memory.get_recent()
    assert len(recent) >= 1
    passed += 1
    print(f"  ✓ Recent: {len(recent)} records")

    # 4. Data lineage
    data_lineage._nodes.clear()
    data_lineage._index.clear()

    data_lineage.add_node(LineageNode("raw_data", "price_THYAO", "2026-08-15T10:00:00"))
    data_lineage.add_node(LineageNode("feature", "rsi_THYAO", "2026-08-15T10:00:01", ["raw_data:price_THYAO"]))
    data_lineage.add_node(LineageNode("prediction", "pred_THYAO", "2026-08-15T10:00:02", ["feature:rsi_THYAO"]))

    forward = data_lineage.trace_forward("raw_data", "price_THYAO")
    assert len(forward) >= 1
    passed += 1
    print(f"  ✓ Lineage forward: {len(forward)} nodes")

    backward = data_lineage.trace_backward("prediction", "pred_THYAO")
    assert len(backward) >= 1
    passed += 1
    print(f"  ✓ Lineage backward: {len(backward)} nodes")

    # 5. Context engine
    context = research_context_engine.build_context(
        "THYAO", {"rsi": 65}, {"regime": "BULL"}, [], [], [], []
    )
    assert context["ticker"] == "THYAO"
    passed += 1
    print(f"  ✓ Context built for {context['ticker']}")

    return passed, failed


def test_event_infrastructure():
    """Event Infrastructure testleri."""
    from services.core.infrastructure import (
        catalyst_engine, notification_system, alert_engine,
        snapshot_system, cache_system, job_queue,
        CatalystEvent,
    )

    passed = 0
    failed = 0

    # 1. Catalyst
    catalyst_engine._catalysts.clear()
    catalyst_engine.add_catalyst(CatalystEvent(
        catalyst_id="C001", ticker="THYAO", catalyst_type="earnings",
        date="2026-08-20", importance=0.9, expected_impact="UNKNOWN",
        uncertainty=0.5,
    ))
    upcoming = catalyst_engine.get_upcoming(days=30)
    assert len(upcoming) >= 1
    passed += 1
    print(f"  ✓ Catalyst: {len(upcoming)} upcoming")

    # 2. Notification
    notification_system._notifications.clear()
    notification_system.notify("RISK", "Test Alert", "Test message", "HIGH")
    unread = notification_system.get_unread()
    assert len(unread) >= 1
    passed += 1
    print(f"  ✓ Notification: {len(unread)} unread")

    # 3. Alert Engine
    alert_engine._notifications._notifications.clear()
    alert_engine.check_drawdown(20.0)
    alerts = alert_engine._notifications.get_unread()
    assert len(alerts) >= 1
    passed += 1
    print(f"  ✓ Alert: drawdown alert triggered")

    # 4. Snapshot
    snapshot_system._snapshots.clear()
    snapshot_system.take_snapshot({"portfolio_value": 100000, "positions": 5})
    latest = snapshot_system.get_latest()
    assert latest is not None
    assert latest["state"]["portfolio_value"] == 100000
    passed += 1
    print(f"  ✓ Snapshot: {latest['state']['portfolio_value']}")

    # 5. Cache
    cache_system._cache.clear()
    cache_system.set("test_key", "test_value", ttl_seconds=60)
    assert cache_system.get("test_key") == "test_value"
    cache_system.invalidate("test_key")
    assert cache_system.get("test_key") is None
    passed += 1
    print(f"  ✓ Cache: set/get/invalidate")

    # 6. Job Queue
    job_queue._queue.clear()
    job_queue._running.clear()
    job_queue._completed.clear()
    job_id = job_queue.enqueue("backtest", {"strategy": "test"})
    assert job_id is not None
    job = job_queue.dequeue()
    assert job is not None
    assert job["status"] == "RUNNING"
    job_queue.complete(job_id, {"result": "ok"})
    passed += 1
    print(f"  ✓ Job Queue: enqueue/dequeue/complete")

    return passed, failed


def test_forecasting():
    """Forecasting & Ensemble testleri."""
    from services.intelligence.forecasting import (
        forecasting_engine, ensemble_forecasting, news_impact_engine,
        news_duplication_engine, event_timeline_engine,
    )

    passed = 0
    failed = 0

    # 1. Forecasting
    features = {"momentum_20d": 5.0, "realized_vol_20d": 20, "rsi_14": 60}
    forecasts = forecasting_engine.compute_forecasts("THYAO", features, [1, 2, -1, 3, -2])
    assert len(forecasts) == 5  # 5 horizon
    for f in forecasts:
        assert f.predicted_return != 0 or f.horizon_days == 120
        assert 0 < f.probability_positive < 1
    passed += 1
    print(f"  ✓ Forecasting: {len(forecasts)} horizons")

    # 2. Ensemble
    combined = ensemble_forecasting.combine_forecasts(forecasts)
    assert combined.model_source == "ensemble"
    passed += 1
    print(f"  ✓ Ensemble: return={combined.predicted_return:.2f}, prob={combined.probability_positive:.2f}")

    # 3. News Impact
    impact = news_impact_engine.compute_impact({
        "sentiment": 0.8, "importance": 0.9, "novelty": 0.7, "credibility": 0.9,
    })
    assert impact["direction"] == "POSITIVE"
    assert impact["magnitude"] > 0
    passed += 1
    print(f"  ✓ News Impact: {impact['direction']}, magnitude={impact['magnitude']:.4f}")

    # 4. News Duplication
    news_duplication_engine._seen_hashes.clear()
    assert not news_duplication_engine.is_duplicate("Test news", "Reuters")
    assert news_duplication_engine.is_duplicate("Test news", "Bloomberg")
    assert news_duplication_engine.get_source_count("Test news") == 2
    passed += 1
    print(f"  ✓ News Duplication: 2 sources detected")

    # 5. Event Timeline
    event_timeline_engine._timelines.clear()
    event_timeline_engine.add_event("THYAO", "KAP", {"title": "test"}, "2026-08-15T10:00:00")
    event_timeline_engine.add_event("THYAO", "NEWS", {"title": "test2"}, "2026-08-15T10:05:00")
    timeline = event_timeline_engine.get_timeline("THYAO")
    assert len(timeline) == 2
    passed += 1
    print(f"  ✓ Event Timeline: {len(timeline)} events")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 15+ — Comprehensive Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Extended Indicators", test_extended_indicators),
        ("Analysis Engines", test_analysis_engines),
        ("Research Memory", test_research_memory),
        ("Event Infrastructure", test_event_infrastructure),
        ("Forecasting & Ensemble", test_forecasting),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
