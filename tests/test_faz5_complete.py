"""
ALPHA BIST — FAZ 5 Complete Integration Test Suite

E2E akış testleri:
market data → features → intelligence → ranking → prediction → signal → risk → paper broker
"""

import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_ohlcv(n=80, seed=42):
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2024-01-03", periods=n, freq="B")
    close = 100 + np.cumsum(rng.randn(n) * 1.5)
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "Open": close * 1.001, "High": close * 1.02,
        "Low": close * 0.98, "Close": close,
        "Volume": rng.randint(100000, 5000000, n).astype(float),
    }, index=dates)


# ────────────────────────────────────────────────────────────
# 1. E2E: features → intelligence → ranking → prediction → risk → broker
# ────────────────────────────────────────────────────────────

def test_e2e_full_pipeline():
    """Tam pipeline: features → intelligence → prediction → risk → broker."""
    from services.features.calculator import FeatureCalculator
    from services.intelligence.pipeline import intelligence_pipeline
    from services.intelligence.prediction_layer import compute_prediction
    from services.core.risk_gate import RiskGate
    from services.core.broker import PaperBroker, Order, OrderSide, OrderStatus
    from services.core.market_session import market_session

    passed = 0
    failed = 0

    calc = FeatureCalculator()
    df = _make_ohlcv(80, seed=42)
    feats = calc.compute_all_features(df.iloc[:70], ticker="E2E")

    assert feats, "Feature computation failed"
    print(f"  ✓ Features: {len(feats)} features computed")
    passed += 1

    # Intelligence pipeline
    intel = intelligence_pipeline.run(ticker="E2E", features=feats, regime="BULL")
    assert intel is not None
    assert "E2E" == intel.ticker
    print(f"  ✓ Intelligence: {len(intel.modules_used)} modules used, {len(intel.modules_failed)} failed")
    passed += 1

    # Prediction
    pred = compute_prediction(
        ticker="E2E", ml_prediction=2.5, ml_confidence=0.7,
        features=feats, horizon=5, model_source="test"
    )
    assert pred.direction == "UP"
    assert pred.quality_grade in ("A+", "A", "B", "C", "D")
    print(f"  ✓ Prediction: direction={pred.direction}, grade={pred.quality_grade}, conf={pred.confidence}")
    passed += 1

    # Risk gate
    gate = RiskGate()
    rd = gate.check_order(
        ticker="E2E", side="BUY", quantity=10, price=100,
        portfolio_value=1_000_000, current_positions={},
        model_confidence=pred.confidence, market_open=True, data_valid=True
    )
    assert rd.allowed, f"Risk gate rejected: {rd.reason}"
    print(f"  ✓ Risk gate: allowed, passed={rd.checks_passed}")
    passed += 1

    # Paper broker
    broker = PaperBroker(initial_capital=1_000_000)
    order = Order(
        order_id="", ticker="E2E", side=OrderSide.BUY.value,
        quantity=10, price=100.0, idempotency_key="e2e_test"
    )
    result = broker.submit_order(order)
    assert result.status == OrderStatus.FILLED.value
    print(f"  ✓ Paper broker: FILLED, qty={result.filled_quantity}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. Intelligence pipeline modül sağlık
# ────────────────────────────────────────────────────────────

def test_intelligence_health():
    """Intelligence pipeline modül sağlığı."""
    from services.intelligence.pipeline import intelligence_pipeline

    passed = 0
    failed = 0

    health = intelligence_pipeline.get_health()
    assert health["loaded_modules"] > 0
    assert len(health["available"]) > 0

    print(f"  ✓ Intelligence health: {health['loaded_modules']}/{health['total_modules']} loaded")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. Prediction layer — multi-horizon
# ────────────────────────────────────────────────────────────

def test_prediction_multi_horizon():
    """Multi-horizon prediction çalışmalı."""
    from services.intelligence.prediction_layer import compute_prediction

    passed = 0
    failed = 0

    features = {"volatility_20d": 25, "atr_pct": 3, "momentum_20d": 5}

    for horizon in [1, 5, 20, 60]:
        pred = compute_prediction(
            ticker="TEST", ml_prediction=3.0, ml_confidence=0.6,
            features=features, horizon=horizon
        )
        assert pred.time_horizon == horizon
        assert pred.direction == "UP"
        assert pred.quality_grade in ("A+", "A", "B", "C", "D")

    print(f"  ✓ Multi-horizon: 1d/5d/20d/60d predictions computed")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Quality grade computation
# ────────────────────────────────────────────────────────────

def test_quality_grades():
    """Quality grade doğru hesaplanmalı."""
    from services.intelligence.prediction_layer import compute_prediction

    passed = 0
    failed = 0

    features = {"volatility_20d": 20, "atr_pct": 2}

    # Yüksek confidence + yüksek return → A/A+
    pred_high = compute_prediction("T", 8.0, 0.9, features, 5)
    assert pred_high.quality_grade in ("A+", "A"), f"Expected A+/A, got {pred_high.quality_grade}"

    # Düşük confidence + düşük return → C/D
    pred_low = compute_prediction("T", 0.5, 0.2, features, 5)
    assert pred_low.quality_grade in ("C", "D"), f"Expected C/D, got {pred_low.quality_grade}"

    print(f"  ✓ Quality grades: high={pred_high.quality_grade}, low={pred_low.quality_grade}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Production metrics
# ────────────────────────────────────────────────────────────

def test_production_metrics():
    """Production metrics çalışmalı."""
    from services.core.production_metrics import production_metrics, Metrics

    passed = 0
    failed = 0

    production_metrics.reset()

    # Counter
    production_metrics.inc(Metrics.DATA_FETCH_TOTAL)
    production_metrics.inc(Metrics.DATA_FETCH_TOTAL)
    production_metrics.inc(Metrics.DATA_FETCH_ERRORS)

    # Gauge
    production_metrics.set_gauge(Metrics.MODEL_CONFIDENCE, 0.75)

    # Histogram
    production_metrics.observe(Metrics.DATA_FETCH_LATENCY, 0.5)
    production_metrics.observe(Metrics.DATA_FETCH_LATENCY, 1.2)
    production_metrics.observe(Metrics.DATA_FETCH_LATENCY, 0.8)

    all_metrics = production_metrics.get_all()

    assert all_metrics["counters"][Metrics.DATA_FETCH_TOTAL] == 2
    assert all_metrics["counters"][Metrics.DATA_FETCH_ERRORS] == 1
    assert all_metrics["gauges"][Metrics.MODEL_CONFIDENCE] == 0.75
    assert all_metrics["histograms"][Metrics.DATA_FETCH_LATENCY]["count"] == 3

    print(f"  ✓ Metrics: counters={len(all_metrics['counters'])}, gauges={len(all_metrics['gauges'])}, histograms={len(all_metrics['histograms'])}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Metric timer
# ────────────────────────────────────────────────────────────

def test_metric_timer():
    """Metric timer çalışmalı."""
    from services.core.production_metrics import production_metrics
    import time

    passed = 0
    failed = 0

    production_metrics.reset()

    with production_metrics.timer("test_operation"):
        time.sleep(0.05)

    all_metrics = production_metrics.get_all()
    hist = all_metrics["histograms"]["test_operation"]
    assert hist["count"] == 1
    assert hist["mean"] >= 0.04  # ~50ms

    print(f"  ✓ Timer: mean={hist['mean']:.3f}s")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Risk gate — all rejection reasons
# ────────────────────────────────────────────────────────────

def test_risk_gate_all_rejections():
    """Risk gate'in tüm red nedenleri çalışmalı."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate(max_position_pct=10, min_confidence=0.5)

    # Circuit open
    d = gate.check_order("T", "BUY", 10, 100, 1_000_000, {}, circuit_open=True)
    assert not d.allowed and "circuit" in d.reason.lower()

    # Market closed
    d = gate.check_order("T", "BUY", 10, 100, 1_000_000, {}, market_open=False)
    assert not d.allowed and "market" in d.reason.lower()

    # Stale data
    d = gate.check_order("T", "BUY", 10, 100, 1_000_000, {}, data_valid=False)
    assert not d.allowed and "data" in d.reason.lower()

    # Low confidence
    d = gate.check_order("T", "BUY", 10, 100, 1_000_000, {}, model_confidence=0.1)
    assert not d.allowed and "confidence" in d.reason.lower()

    # Position too large
    d = gate.check_order("T", "BUY", 1000, 300, 1_000_000, {})
    assert not d.allowed and ("position" in d.reason.lower() or "order" in d.reason.lower())

    # All pass
    d = gate.check_order("T", "BUY", 10, 100, 1_000_000, {}, model_confidence=0.7, market_open=True, data_valid=True)
    assert d.allowed

    print(f"  ✓ Risk gate: 5 rejection types + 1 pass verified")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Paper broker — full lifecycle
# ────────────────────────────────────────────────────────────

def test_paper_broker_lifecycle():
    """Paper broker tam yaşam döngüsü."""
    from services.core.broker import PaperBroker, Order, OrderSide, OrderStatus

    passed = 0
    failed = 0

    broker = PaperBroker(initial_capital=1_000_000)

    # BUY
    buy = broker.submit_order(Order("", "THYAO", OrderSide.BUY.value, 100, 300.0, idempotency_key="l1"))
    assert buy.status == OrderStatus.FILLED.value

    # Position check
    pos = broker.get_positions()
    assert pos["THYAO"]["qty"] == 100

    # SELL
    sell = broker.submit_order(Order("", "THYAO", OrderSide.SELL.value, 50, 310.0, idempotency_key="l2"))
    assert sell.status == OrderStatus.FILLED.value

    # Position after partial sell
    pos2 = broker.get_positions()
    assert pos2["THYAO"]["qty"] == 50

    # Duplicate
    dup = broker.submit_order(Order("", "THYAO", OrderSide.BUY.value, 100, 300.0, idempotency_key="l1"))
    assert dup.order_id == buy.order_id  # Same order returned

    print(f"  ✓ Broker lifecycle: buy→sell→partial→duplicate")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Circuit breaker — integration with data adapter
# ────────────────────────────────────────────────────────────

def test_circuit_breaker_data_adapter():
    """Data adapter circuit breaker'ları çalışmalı."""
    from services.features.data_adapter import DataAdapter

    passed = 0
    failed = 0

    adapter = DataAdapter()

    # Circuit breaker'lar başlatılmış olmalı
    assert adapter._cb_fundamental is not None
    assert adapter._cb_kap is not None
    assert adapter._cb_news is not None

    # Başlangıçta CLOSED (çağrı yapılabilir)
    assert adapter._cb_fundamental.can_execute()
    assert adapter._cb_kap.can_execute()
    assert adapter._cb_news.can_execute()

    print(f"  ✓ Data adapter CB: fundamental/kap/news all CLOSED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 10. Corporate actions module exists
# ────────────────────────────────────────────────────────────

def test_corporate_actions():
    """Corporate actions modülü mevcut olmalı."""
    from services.ingestion.corporate_actions import CorporateAction, ActionType

    passed = 0
    failed = 0

    # Modül import edilebilmeli
    assert ActionType.DIVIDEND.value == "DIVIDEND"
    assert ActionType.STOCK_SPLIT.value == "STOCK_SPLIT"
    assert ActionType.DELISTING.value == "DELISTING"

    print(f"  ✓ Corporate actions: {len(ActionType)} action types defined")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 11. Market session — full coverage
# ────────────────────────────────────────────────────────────

def test_market_session_full():
    """Market session tüm durumları kapsamalı."""
    from services.core.market_session import MarketSessionManager, MarketPhase
    from datetime import datetime, timezone, timedelta

    passed = 0
    failed = 0

    IST = timezone(timedelta(hours=3))

    class Fake(MarketSessionManager):
        def __init__(self, dt, h=set()):
            self._dt = dt
            self._holidays = h
        def now_istanbul(self):
            return self._dt

    # Hafta içi aktif
    m = Fake(datetime(2026, 8, 18, 14, 0, tzinfo=IST))
    assert m.is_trading_hours()
    assert not m.is_closed()

    # Hafta sonu
    m = Fake(datetime(2026, 8, 22, 14, 0, tzinfo=IST))
    assert m.is_closed()
    assert not m.is_trading_hours()

    # Tatil
    m = Fake(datetime(2026, 1, 1, 14, 0, tzinfo=IST), {"2026-01-01"})
    assert m.is_closed()

    # Pre-market
    m = Fake(datetime(2026, 8, 18, 9, 55, tzinfo=IST))
    assert m.is_pre_market()
    assert not m.is_trading_hours()

    # Post-market
    m = Fake(datetime(2026, 8, 18, 18, 15, tzinfo=IST))
    assert m.is_post_market()

    # Status
    status = m.get_status()
    assert "phase" in status
    assert "istanbul_time" in status

    print(f"  ✓ Market session: active/weekend/holiday/pre/post covered")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 12. Model persistence contract
# ────────────────────────────────────────────────────────────

def test_model_persistence_contract():
    """Model persistence contract doğrulanmalı."""
    from services.core.model_persistence import ModelPersistence

    passed = 0
    failed = 0

    # Mock model
    class MockModel:
        feature_names = ["f1", "f2"]
        cs_features = ["f1_cs_zscore"]
        validation_metrics = {"mae": 5.0, "ic": 0.05}
        confidence_score = 0.7
        confidence_details = {}
        target_horizon = 5
        train_samples = 500
        train_date_range = ("2024-01-01", "2024-06-01")
        scaler_mean = None
        scaler_std = None
        impute_values = {}
        feature_importance = {}

    mp = ModelPersistence()

    # Metadata serialization test (DB yoksa None döner ama crash olmaz)
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop = asyncio.new_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()

    result = loop.run_until_complete(
        mp.save_model_metadata("test_model", "v1", MockModel(), "/tmp/test.pkl")
    )
    # DB yoksa None
    assert result is None  # No DB available

    print(f"  ✓ Model persistence: contract valid, graceful without DB")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("E2E full pipeline", test_e2e_full_pipeline),
        ("Intelligence health", test_intelligence_health),
        ("Prediction multi-horizon", test_prediction_multi_horizon),
        ("Quality grades", test_quality_grades),
        ("Production metrics", test_production_metrics),
        ("Metric timer", test_metric_timer),
        ("Risk gate all rejections", test_risk_gate_all_rejections),
        ("Paper broker lifecycle", test_paper_broker_lifecycle),
        ("Circuit breaker data adapter", test_circuit_breaker_data_adapter),
        ("Corporate actions", test_corporate_actions),
        ("Market session full", test_market_session_full),
        ("Model persistence contract", test_model_persistence_contract),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 5 — Complete Integration Test Suite")
    print("=" * 70)

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            p, f = test_fn()
            total_passed += p
            total_failed += f
            if f > 0:
                print(f"  ⚠ {f} FAILED")
        except Exception as e:
            import traceback
            print(f"  ✗ EXCEPTION: {e}")
            traceback.print_exc()
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
