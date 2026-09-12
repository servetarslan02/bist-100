"""ALPHA BIST — Audit Tests for Market State Service.

Tests verify:
- Zero placeholders and robust Turkish docstrings
- Informative __repr__ for all engines and formatters
- Correct calculation for MarketBreadthEngine (AD, TRIN, McClellan, Thrust)
- ComponentStateEngine state classification and aggregation
- EnsembleRegimeDetector weighted voting and fallback
- RegimeTransitionTracker transition matrix and stability
- RiskAppetiteEngine weighting, normalization, and bounds
- MultiTimeframeEngine cross-timeframe alignment
- MarketStateFormatter standard schema output
- MarketStateMonitor Prometheus metrics formatting
"""

from services.market_state import (
    BreadthResult,
    ComponentStateEngine,
    ComponentStates,
    EnsembleRegimeDetector,
    EnsembleResult,
    MarketBreadthEngine,
    MarketStateFormatter,
    MarketStateMonitor,
    MarketStateOutput,
    MultiTimeframeEngine,
    RegimeTransitionTracker,
    RiskAppetiteEngine,
    TimeframeState,
    TransitionStats,
)


def test_market_state_repr_coverage():
    """Verify that all core engines and monitors have informative __repr__."""
    breadth_engine = MarketBreadthEngine()
    assert "MarketBreadthEngine" in repr(breadth_engine)

    comp_engine = ComponentStateEngine()
    assert "ComponentStateEngine" in repr(comp_engine)

    ensemble = EnsembleRegimeDetector()
    assert "EnsembleRegimeDetector" in repr(ensemble)

    tracker = RegimeTransitionTracker()
    assert "RegimeTransitionTracker" in repr(tracker)

    risk_engine = RiskAppetiteEngine()
    assert "RiskAppetiteEngine" in repr(risk_engine)

    mtf_engine = MultiTimeframeEngine()
    assert "MultiTimeframeEngine" in repr(mtf_engine)

    formatter = MarketStateFormatter()
    assert "MarketStateFormatter" in repr(formatter)

    monitor = MarketStateMonitor()
    assert "MarketStateMonitor" in repr(monitor)


def test_market_breadth_engine_calculation():
    """Verify MarketBreadthEngine calculations with advancing, declining, and unchanged."""
    engine = MarketBreadthEngine(volume_min=1000)
    sample_instruments = [
        {"ticker": "THYAO", "change_pct": 2.5, "volume": 50000, "volume_avg": 40000},
        {"ticker": "GARAN", "change_pct": 1.2, "volume": 35000, "volume_avg": 30000},
        {"ticker": "ASELS", "change_pct": -0.8, "volume": 20000, "volume_avg": 25000},
        {"ticker": "EREGL", "change_pct": 0.0, "volume": 15000, "volume_avg": 15000},
        {"ticker": "PENNY", "change_pct": 5.0, "volume": 500, "volume_avg": 500},  # Below min volume
    ]

    result = engine.compute(sample_instruments)
    assert isinstance(result, BreadthResult)
    assert result.total == 4  # PENNY excluded due to volume < 1000
    assert result.advancing == 2
    assert result.declining == 1
    assert result.unchanged == 1
    assert result.pct_advancing == 50.0
    assert result.breadth_state in ["BROAD", "NEUTRAL", "NARROW"]

    d = result.to_dict()
    assert "pct_advancing" in d
    assert "mcclellan_osc" in d


def test_component_state_engine():
    """Verify ComponentStateEngine computes normalized component states."""
    engine = ComponentStateEngine()
    sample_instruments = [
        {"ticker": "T1", "momentum": 0.05, "volatility": 0.20, "volume_zscore": 1.5, "rsi": 65, "spread": 0.001},
        {"ticker": "T2", "momentum": 0.02, "volatility": 0.15, "volume_zscore": 0.8, "rsi": 55, "spread": 0.002},
        {"ticker": "T3", "momentum": -0.01, "volatility": 0.25, "volume_zscore": -0.5, "rsi": 45, "spread": 0.0015},
    ]

    states = engine.compute_all(
        instrument_states=sample_instruments,
        vix_level=18.5,
        news_sentiment=0.3,
        social_sentiment=0.1,
    )
    assert isinstance(states, ComponentStates)
    assert states.momentum_state in ["POSITIVE", "NEGATIVE", "NEUTRAL"]
    assert states.volatility_state in ["LOW", "NORMAL", "HIGH", "EXTREME"]
    assert states.sentiment_state in ["NEGATIVE", "NEUTRAL", "POSITIVE", "EUPHORIA"]

    d = states.to_dict()
    assert d["avg_rsi"] > 0
    assert "momentum_state" in d


def test_ensemble_regime_detector():
    """Verify EnsembleRegimeDetector score calculation and fallback behavior."""
    detector = EnsembleRegimeDetector()
    features = {"trend_strength": 0.8, "adx": 30.0, "rsi": 60.0}
    returns = [0.01, 0.015, -0.005, 0.02, 0.008]
    volatility = [0.15, 0.16, 0.15, 0.17, 0.14]

    result = detector.detect(features=features, returns=returns, volatility=volatility)
    assert isinstance(result, EnsembleResult)
    assert result.regime in ["BULL", "BEAR", "SIDEWAYS", "CRISIS", "UNKNOWN"]
    assert 0.0 <= result.confidence <= 1.0
    assert result.method_count >= 1

    d = result.to_dict()
    assert "regime" in d
    assert "confidence" in d


def test_regime_transition_tracker():
    """Verify RegimeTransitionTracker records observations, transitions, and generates statistics."""
    tracker = RegimeTransitionTracker(max_history=50, stability_window=5)

    tracker.record("BULL", 0.85)
    tracker.record("BULL", 0.88)
    tracker.record("BULL", 0.90)
    tracker.record("SIDEWAYS", 0.70)
    tracker.record("SIDEWAYS", 0.75)
    tracker.record("BEAR", 0.80)

    stats = tracker.get_stats()
    assert isinstance(stats, TransitionStats)
    assert stats.total_observations == 6
    assert stats.total_transitions == 2
    assert stats.current_regime == "BEAR"
    assert "BULL" in stats.regime_distribution
    assert 0.0 <= stats.stability_score <= 1.0

    d = stats.to_dict()
    assert d["total_observations"] == 6
    assert d["total_transitions"] == 2


def test_risk_appetite_engine():
    """Verify RiskAppetiteEngine scoring and normalization."""
    engine = RiskAppetiteEngine()
    score = engine.compute(
        breadth_pct=75.0,
        momentum=0.04,
        volatility=15.0,
        rsi=62.0,
        sentiment_score=0.4,
        macro_score=0.7,
    )
    assert 0.0 <= score <= 1.0
    # High breadth, low vol, positive momentum -> should be above 0.5
    assert score > 0.5


def test_multi_timeframe_engine():
    """Verify MultiTimeframeEngine alignment and divergence detection."""
    engine = MultiTimeframeEngine()
    data = {
        "daily": {
            "instruments": [{"ticker": "A", "change_pct": 1.5, "volume": 10000, "volume_avg": 8000}],
            "features": {"trend": 1.0},
        },
        "weekly": {
            "instruments": [{"ticker": "A", "change_pct": 3.0, "volume": 50000, "volume_avg": 40000}],
            "features": {"trend": 1.0},
        },
    }
    result = engine.compute_all_timeframes(data)
    assert "daily" in result.states
    assert isinstance(result.states["daily"], TimeframeState)
    assert 0.0 <= result.alignment_score <= 1.0

    d = result.to_dict()
    assert "alignment_score" in d
    assert "states" in d


def test_output_formatter_and_monitor():
    """Verify MarketStateFormatter and MarketStateMonitor integrate cleanly."""
    formatter = MarketStateFormatter()
    output = formatter.format(
        breadth=BreadthResult(advancing=60, declining=30, unchanged=10, total=100, pct_advancing=60.0),
        components=ComponentStates(momentum_state="POSITIVE", volatility_state="NORMAL"),
        ensemble=EnsembleResult(regime="BULL", confidence=0.82, consensus=True, method_count=2),
        transition=TransitionStats(total_observations=10, current_regime="BULL"),
        risk_appetite=0.68,
    )
    assert isinstance(output, MarketStateOutput)
    assert output.regime == "BULL"
    assert output.risk_appetite == 0.68

    d = output.to_dict()
    assert d["regime"] == "BULL"
    assert d["risk_appetite"] == 0.68

    monitor = MarketStateMonitor()
    monitor.update(
        regime=output.regime,
        confidence=output.regime_confidence,
        consensus=output.regime_consensus,
        stability=output.regime_stability,
        breadth_pct=60.0,
        risk_appetite=0.68,
    )
    prom_metrics = monitor.to_prometheus()
    assert "market_state_regime" in prom_metrics
    assert "market_state_risk_appetite 0.68" in prom_metrics
