"""
Tests for Enterprise Modules:
1. Feature Store (Feast-compatible PIT & Online/Offline)
2. NATS JetStream Event Bus
3. pgvector Market Regime Embedding & Historical Analogy
4. Evidently Data Quality & Drift Suite
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from services.core.nats_bus import NATSJetStreamBus
from services.data.evidently_monitor import EvidentlyDataMonitor
from services.features.feature_store_feast import BISTFeatureStore
from services.ml.vector_regime import MarketRegimeEmbeddingEngine


def test_feast_feature_store_basics():
    fs = BISTFeatureStore()
    schema = fs.get_schema_summary()
    assert schema["total_views"] >= 3
    assert schema["total_features"] >= 10

    # Online write & read
    fs.write_online_features("GARAN", {"rsi_14": 58.5, "momentum_20d": 0.08})
    online_res = fs.get_online_features(["GARAN"], ["bist_technical_fv:rsi_14", "momentum_20d"])
    assert len(online_res) == 1
    assert online_res[0]["ticker"] == "GARAN"
    assert online_res[0]["rsi_14"] == 58.5

    # PIT Historical Features
    hist = fs.get_historical_features(
        {"ticker": ["GARAN", "AKBNK", "THYAO"], "timestamp": ["2025-01-02", "2025-01-02", "2025-01-02"]},
        ["rsi_14", "amihud_illiquidity"],
    )
    assert hist.num_rows == 3
    assert hist.is_pit_clean is True
    assert "rsi_14" in hist.data


async def test_nats_jetstream_bus():
    bus = NATSJetStreamBus()
    received = []

    async def test_handler(msg):
        received.append(msg)

    bus.subscribe("signals.alpha.*", test_handler)

    # Publish
    ok = await bus.publish("signals.alpha.garan", {"ticker": "GARAN", "score": 0.85}, msg_id="test_msg_1")
    assert ok is True
    assert len(received) == 1
    assert received[0].data["ticker"] == "GARAN"

    # Dedup test: same msg_id should be dropped
    dup_ok = await bus.publish("signals.alpha.garan", {"ticker": "GARAN", "score": 0.85}, msg_id="test_msg_1")
    assert dup_ok is False
    assert len(received) == 1  # No duplicate delivery

    metrics = bus.get_metrics()
    assert metrics["published_count"] == 1
    assert metrics["duplicate_dropped"] == 1


def test_market_regime_embedding():
    engine = MarketRegimeEmbeddingEngine()
    current_vec = engine.vectorize_market_state(
        bist_return_20d=-0.25,
        bist_volatility_20d=0.45,
        usdtry_change_20d=0.15,
        cds_5y_level=550.0,
        vix_level=42.0,
        advance_decline_ratio=0.30,
        foreign_flow_ratio=-0.50,
        rate_change_bps=250.0,
    )

    assert len(current_vec) == 16
    assert abs(np.linalg.norm(current_vec) - 1.0) < 1e-4

    # Nearest analogies
    matches = engine.find_nearest_analogies(current_vec, top_k=2)
    assert len(matches) == 2
    assert matches[0].similarity_score > 0

    advice = engine.get_regime_protection_advice(matches)
    assert "recommended_cash_pct" in advice
    assert "strategy" in advice


def test_evidently_data_quality():
    monitor = EvidentlyDataMonitor()

    # Valid OHLCV
    valid_ohlcv = {
        "open": [100.0, 102.0],
        "high": [105.0, 106.0],
        "low": [98.0, 101.0],
        "close": [103.0, 104.0],
        "volume": [10000.0, 15000.0],
    }
    q_results = monitor.audit_ohlcv_integrity(valid_ohlcv)
    assert all(q.status == "PASS" for q in q_results)

    # Invalid OHLCV (High < Low violation)
    invalid_ohlcv = {
        "open": [100.0],
        "high": [90.0],  # Invalid: High < Low
        "low": [98.0],
        "close": [95.0],
        "volume": [1000.0],
    }
    bad_results = monitor.audit_ohlcv_integrity(invalid_ohlcv)
    assert any(q.status == "FAIL" for q in bad_results)

    # Drift tests
    rng = np.random.default_rng(42)
    ref = rng.normal(0.0, 1.0, 500)
    cur = ref.copy()
    ks_res = monitor.compute_ks_drift(ref, cur, "feature_1")
    assert ks_res.is_drifted is False

    # Shifted feature (drift should trigger)
    cur_shifted = ref + 3.0
    ks_drifted = monitor.compute_ks_drift(ref, cur_shifted, "feature_shifted")
    assert ks_drifted.is_drifted is True
    assert ks_drifted.severity == "SEVERE"

    psi_res = monitor.compute_psi(ref, cur, "feature_1")
    assert psi_res.is_drifted is False

    report = monitor.generate_full_audit(valid_ohlcv, {"f1": ref}, {"f1": cur})
    assert report.is_pipeline_allowed is True
    assert report.overall_score >= 90.0


if __name__ == "__main__":
    import asyncio
    print("Running enterprise module tests...")
    test_feast_feature_store_basics()
    print("  [PASS] test_feast_feature_store_basics")
    asyncio.run(test_nats_jetstream_bus())
    print("  [PASS] test_nats_jetstream_bus")
    test_market_regime_embedding()
    print("  [PASS] test_market_regime_embedding")
    test_evidently_data_quality()
    print("  [PASS] test_evidently_data_quality")
    print("All enterprise module tests PASSED successfully!")
