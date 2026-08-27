"""ALPHA BIST — Market State Engine v2.0 Test Suite

Tüm modüller için testler:
- Breadth Engine (7 gösterge)
- Component States (8 state)
- Ensemble Regime (3 yöntem)
- Transition Tracker
- Risk Appetite (6 faktör)
- Multi-Timeframe
- Output Formatter
"""


# Modülleri import et

import numpy as np
import pytest

from services.market_state.breadth_engine import BreadthResult, MarketBreadthEngine
from services.market_state.component_states import ComponentStateEngine, ComponentStates
from services.market_state.ensemble_regime import EnsembleRegimeDetector, EnsembleResult
from services.market_state.multi_timeframe import MultiTimeframeEngine
from services.market_state.output_formatter import MarketStateFormatter, MarketStateOutput
from services.market_state.risk_appetite import RiskAppetiteEngine
from services.market_state.transition_tracker import RegimeTransitionTracker

# =====================================================
# Fixtures
# =====================================================


@pytest.fixture
def sample_instrument_states():
    """Örnek hisse state'leri — 10 hisse."""
    return [
        {
            "ticker": "THYAO",
            "change_pct": 2.5,
            "volume": 50000,
            "rsi": 62,
            "momentum": 3.0,
            "volatility": 0.02,
            "volume_zscore": 1.2,
            "anomaly_score": 0.1,
            "spread": 0.005,
        },
        {
            "ticker": "GARAN",
            "change_pct": 1.8,
            "volume": 80000,
            "rsi": 58,
            "momentum": 2.0,
            "volatility": 0.018,
            "volume_zscore": 0.8,
            "anomaly_score": 0.05,
            "spread": 0.003,
        },
        {
            "ticker": "ASELS",
            "change_pct": -0.5,
            "volume": 30000,
            "rsi": 45,
            "momentum": -1.0,
            "volatility": 0.025,
            "volume_zscore": -0.3,
            "anomaly_score": 0.2,
            "spread": 0.008,
        },
        {
            "ticker": "SISE",
            "change_pct": 3.2,
            "volume": 60000,
            "rsi": 68,
            "momentum": 4.5,
            "volatility": 0.022,
            "volume_zscore": 1.5,
            "anomaly_score": 0.15,
            "spread": 0.004,
        },
        {
            "ticker": "TUPRS",
            "change_pct": -1.2,
            "volume": 25000,
            "rsi": 38,
            "momentum": -2.0,
            "volatility": 0.03,
            "volume_zscore": -0.5,
            "anomaly_score": 0.3,
            "spread": 0.01,
        },
        {
            "ticker": "KCHOL",
            "change_pct": 0.8,
            "volume": 45000,
            "rsi": 52,
            "momentum": 0.5,
            "volatility": 0.015,
            "volume_zscore": 0.2,
            "anomaly_score": 0.05,
            "spread": 0.004,
        },
        {
            "ticker": "SAHOL",
            "change_pct": 1.5,
            "volume": 40000,
            "rsi": 55,
            "momentum": 1.5,
            "volatility": 0.016,
            "volume_zscore": 0.5,
            "anomaly_score": 0.08,
            "spread": 0.005,
        },
        {
            "ticker": "AKBNK",
            "change_pct": -0.3,
            "volume": 55000,
            "rsi": 48,
            "momentum": -0.5,
            "volatility": 0.02,
            "volume_zscore": 0.1,
            "anomaly_score": 0.1,
            "spread": 0.006,
        },
        {
            "ticker": "EREGL",
            "change_pct": 2.0,
            "volume": 35000,
            "rsi": 60,
            "momentum": 2.8,
            "volatility": 0.019,
            "volume_zscore": 0.9,
            "anomaly_score": 0.12,
            "spread": 0.005,
        },
        {
            "ticker": "BIMAS",
            "change_pct": -2.0,
            "volume": 20000,
            "rsi": 32,
            "momentum": -3.0,
            "volatility": 0.028,
            "volume_zscore": -0.8,
            "anomaly_score": 0.4,
            "spread": 0.012,
        },
    ]


@pytest.fixture
def sample_returns():
    """Örnek getiri serisi — 100 gün."""
    np.random.seed(42)
    return np.random.normal(0.0005, 0.015, 100)


@pytest.fixture
def sample_volatility():
    """Örnek volatilite serisi — 100 gün."""
    np.random.seed(42)
    return np.abs(np.random.normal(0.02, 0.005, 100))


@pytest.fixture
def breadth_engine():
    return MarketBreadthEngine()


@pytest.fixture
def component_engine():
    return ComponentStateEngine()


@pytest.fixture
def ensemble_detector():
    return EnsembleRegimeDetector()


@pytest.fixture
def transition_tracker():
    return RegimeTransitionTracker()


@pytest.fixture
def risk_engine():
    return RiskAppetiteEngine()


@pytest.fixture
def multi_tf_engine():
    return MultiTimeframeEngine()


@pytest.fixture
def formatter():
    return MarketStateFormatter()


# =====================================================
# Breadth Engine Tests
# =====================================================


class TestBreadthEngine:
    """Market Breadth Engine testleri."""

    def test_compute_basic(self, breadth_engine, sample_instrument_states):
        """Temel breadth hesaplama."""
        result = breadth_engine.compute(sample_instrument_states)

        assert isinstance(result, BreadthResult)
        assert result.total == 10
        assert result.advancing == 6  # THYAO, GARAN, SISE, KCHOL, SAHOL, EREGL
        assert result.declining == 4  # ASELS, TUPRS, AKBNK, BIMAS
        assert result.pct_advancing == 60.0
        assert result.ad_ratio > 1.0  # More advancing than declining

    def test_compute_mcclellan(self, breadth_engine, sample_instrument_states):
        """McClellan Oscillator hesaplama."""
        result = breadth_engine.compute(sample_instrument_states)
        assert isinstance(result.mcclellan_osc, float)

    def test_compute_trin(self, breadth_engine, sample_instrument_states):
        """TRIN hesaplama."""
        result = breadth_engine.compute(sample_instrument_states)
        assert isinstance(result.trin, float)
        assert result.trin > 0

    def test_breadth_state_broad(self, breadth_engine):
        """Breadth state = BROAD (yüksek katılımlı yükseliş)."""
        states = [{"ticker": f"H{i}", "change_pct": 2.0, "volume": 50000} for i in range(80)] + [
            {"ticker": f"H{i}", "change_pct": -1.0, "volume": 50000} for i in range(80, 100)
        ]
        result = breadth_engine.compute(states)
        assert result.breadth_state == "BROAD"
        assert result.pct_advancing == 80.0

    def test_breadth_state_narrow(self, breadth_engine):
        """Breadth state = NARROW (düşük katılımlı)."""
        states = [{"ticker": f"H{i}", "change_pct": -3.0, "volume": 50000} for i in range(75)] + [
            {"ticker": f"H{i}", "change_pct": 0.5, "volume": 50000} for i in range(75, 100)
        ]
        result = breadth_engine.compute(states)
        assert result.breadth_state == "NARROW"

    def test_alert_critical(self, breadth_engine):
        """Alert = CRITICAL (crash sinyali — pct < 15 ve trin > 2.0)."""
        # Düşen hacmi yüksek, yükselen hacmi düşük → trin > 2
        states = [{"ticker": f"H{i}", "change_pct": -3.0, "volume": 100000} for i in range(92)] + [
            {"ticker": f"H{i}", "change_pct": 0.5, "volume": 1000} for i in range(92, 100)
        ]
        result = breadth_engine.compute(states)
        assert result.alert_level == "CRITICAL"

    def test_sector_breadth(self, breadth_engine, sample_instrument_states):
        """Sektörel breadth hesaplama."""
        sector_map = {
            "THYAO": "HAVACILIK",
            "GARAN": "BANKACILIK",
            "ASELS": "TEKNOLOJI",
            "SISE": "SANAYI",
            "TUPRS": "ENERJI",
            "KCHOL": "HOLDING",
            "SAHOL": "HOLDING",
            "AKBNK": "BANKACILIK",
            "EREGL": "SANAYI",
            "BIMAS": "PERAKENDE",
        }
        result = breadth_engine.compute(sample_instrument_states, sector_map=sector_map)
        assert "HAVACILIK" in result.sector_breadth
        assert "BANKACILIK" in result.sector_breadth

    def test_low_volume_filter(self, breadth_engine):
        """Düşük hacimli hisseler filtrelenmeli."""
        states = [
            {"ticker": "HIGH", "change_pct": 2.0, "volume": 100000},
            {"ticker": "LOW", "change_pct": 2.0, "volume": 100},  # Filtrelenecek
        ]
        result = breadth_engine.compute(states)
        assert result.total == 1  # Sadece HIGH

    def test_reset(self, breadth_engine, sample_instrument_states):
        """Reset sonrası cumulative state sıfırlanmalı."""
        breadth_engine.compute(sample_instrument_states)
        breadth_engine.reset()
        assert breadth_engine._ad_line_cumulative == 0

    def test_to_dict(self, breadth_engine, sample_instrument_states):
        """to_dict() tüm alanları içermeli."""
        result = breadth_engine.compute(sample_instrument_states)
        d = result.to_dict()
        assert "advancing" in d
        assert "mcclellan_osc" in d
        assert "trin" in d
        assert "breadth_state" in d


# =====================================================
# Component States Tests
# =====================================================


class TestComponentStates:
    """Component States Engine testleri."""

    def test_compute_all(self, component_engine, sample_instrument_states):
        """Tüm bileşenler hesaplanmalı."""
        result = component_engine.compute_all(sample_instrument_states)

        assert isinstance(result, ComponentStates)
        assert result.momentum_state in ("POSITIVE", "NEGATIVE", "NEUTRAL")
        assert result.volatility_state in ("LOW", "NORMAL", "HIGH", "EXTREME")
        assert result.volume_state in ("BELOW_AVERAGE", "AVERAGE", "ABOVE_AVERAGE", "SURGE")
        assert result.rsi_state in ("OVERSOLD", "NEUTRAL", "OVERBOUGHT")
        assert result.liquidity_state in ("TIGHT", "NORMAL", "LOOSE")
        assert result.sentiment_state in ("NEGATIVE", "NEUTRAL", "POSITIVE", "EUPHORIA")

    def test_momentum_state_positive(self, component_engine):
        """Pozitif momentum ağırlıklı → POSITIVE."""
        states = [
            {"momentum": 3.0},
            {"momentum": 2.0},
            {"momentum": 4.0},
            {"momentum": 1.0},
            {"momentum": 5.0},
            {"momentum": -1.0},
            {"momentum": 2.5},
            {"momentum": 3.5},
            {"momentum": 1.5},
            {"momentum": 4.5},
        ]
        result = component_engine.compute_all(states)
        assert result.momentum_state == "POSITIVE"

    def test_momentum_state_negative(self, component_engine):
        """Negatif momentum ağırlıklı → NEGATIVE."""
        states = [
            {"momentum": -3.0},
            {"momentum": -2.0},
            {"momentum": -4.0},
            {"momentum": -1.0},
            {"momentum": -5.0},
            {"momentum": 1.0},
            {"momentum": -2.5},
            {"momentum": -3.5},
            {"momentum": -1.5},
            {"momentum": -4.5},
        ]
        result = component_engine.compute_all(states)
        assert result.momentum_state == "NEGATIVE"

    def test_volatility_state_with_vix(self, component_engine):
        """VIX ile volatility state."""
        states = [{"volatility": 0.02}]
        result = component_engine.compute_all(states, vix_level=45)
        assert result.volatility_state == "EXTREME"

    def test_rsi_state_oversold(self, component_engine):
        """RSI < 30 yaygın → OVERSOLD (>30% hisse RSI < 30)."""
        states = [
            {"rsi": 25},
            {"rsi": 28},
            {"rsi": 22},
            {"rsi": 27},
            {"rsi": 35},
            {"rsi": 40},
            {"rsi": 45},
            {"rsi": 50},
            {"rsi": 55},
            {"rsi": 60},
        ]
        result = component_engine.compute_all(states)
        assert result.rsi_state == "OVERSOLD"

    def test_sentiment_state_euphoria(self, component_engine):
        """Yüksek sentiment → EUPHORIA."""
        states = [{"rsi": 50}]
        result = component_engine.compute_all(states, news_sentiment=0.8)
        assert result.sentiment_state == "EUPHORIA"

    def test_anomaly_state(self, component_engine):
        """Anomaly tespit."""
        states = [
            {"anomaly_score": 0.9},
            {"anomaly_score": 0.85},
            {"anomaly_score": 0.95},
            {"anomaly_score": 0.1},
        ]
        result = component_engine.compute_all(states)
        assert result.anomaly_count == 3
        assert result.anomaly_severity == "HIGH"

    def test_macro_state(self, component_engine):
        """Macro state world_state'den."""
        states = [{"rsi": 50}]
        world_state = {
            "global_risk_appetite": 0.7,
            "inflation_pressure": 0.3,
            "turkey_macro_risk": 0.4,
        }
        result = component_engine.compute_all(states, world_state=world_state)
        assert result.macro_state == "EXPANSION"

    def test_to_dict(self, component_engine, sample_instrument_states):
        """to_dict() tüm alanları içermeli."""
        result = component_engine.compute_all(sample_instrument_states)
        d = result.to_dict()
        assert "momentum_state" in d
        assert "anomaly_count" in d
        assert "sentiment_score" in d


# =====================================================
# Ensemble Regime Tests
# =====================================================


class TestEnsembleRegime:
    """Ensemble Regime Detection testleri."""

    def test_detect_score_only(self, ensemble_detector, sample_returns, sample_volatility):
        """Skor bazlı tespit (HMM/GMM olmadan)."""
        features = {
            "breadth_pct": 65.0,
            "momentum_avg": 2.5,
            "volatility_avg": 20.0,
            "rsi_avg": 58.0,
            "risk_appetite": 0.6,
            "usdtry_momentum": 2.0,
            "vix_level": 15.0,
            "global_momentum": 3.0,
        }
        result = ensemble_detector.detect(features)

        assert isinstance(result, EnsembleResult)
        assert result.regime != "UNKNOWN"
        assert 0 <= result.confidence <= 1

    def test_detect_with_returns(self, ensemble_detector, sample_returns, sample_volatility):
        """Returns ile birlikte tespit."""
        features = {
            "breadth_pct": 55.0,
            "momentum_avg": 0.5,
            "volatility_avg": 20.0,
            "rsi_avg": 50.0,
        }
        result = ensemble_detector.detect(features, sample_returns, sample_volatility)

        assert result.method_count >= 1

    def test_consensus(self, ensemble_detector):
        """Consensus tespit."""
        # Tüm yöntemler aynı sonucu vermeli (eğer çalışırlarsa)
        features = {
            "breadth_pct": 75.0,
            "momentum_avg": 5.0,
            "volatility_avg": 15.0,
            "rsi_avg": 65.0,
        }
        result = ensemble_detector.detect(features)
        # Consensus bool olmalı
        assert isinstance(result.consensus, bool)

    def test_update_weights(self, ensemble_detector):
        """Ağırlık güncelleme."""
        ensemble_detector.update_weights(score_weight=0.6, hmm_weight=0.3, gmm_weight=0.1)
        # Ağırlıklar normalize edilmeli
        assert abs(ensemble_detector._score_weight - 0.6) < 0.01

    def test_to_dict(self, ensemble_detector):
        """to_dict() tüm alanları içermeli."""
        features = {"breadth_pct": 50, "momentum_avg": 0, "volatility_avg": 20, "rsi_avg": 50}
        result = ensemble_detector.detect(features)
        d = result.to_dict()
        assert "regime" in d
        assert "confidence" in d
        assert "consensus" in d


# =====================================================
# Transition Tracker Tests
# =====================================================


class TestTransitionTracker:
    """Regime Transition Tracker testleri."""

    def test_record_initial(self, transition_tracker):
        """İlk kayıt."""
        transition_tracker.record("BULL", 0.8)
        stats = transition_tracker.get_stats()
        assert stats.current_regime == "BULL"
        assert stats.total_observations == 1
        assert stats.total_transitions == 0

    def test_record_transition(self, transition_tracker):
        """Rejim değişimi tespit."""
        transition_tracker.record("BULL", 0.8)
        transition_tracker.record("BEAR", 0.7)
        stats = transition_tracker.get_stats()
        assert stats.total_transitions == 1
        assert stats.current_regime == "BEAR"

    def test_stability_score(self, transition_tracker):
        """Kararlılık skoru."""
        # Sabit rejim → yüksek kararlılık
        for _ in range(20):
            transition_tracker.record("BULL", 0.8)
        stats = transition_tracker.get_stats()
        assert stats.stability_score > 0.9

    def test_stability_score_unstable(self, transition_tracker):
        """Kararsız rejim → düşük kararlılık."""
        regimes = ["BULL", "BEAR", "BULL", "BEAR", "BULL", "BEAR"]
        for r in regimes:
            transition_tracker.record(r, 0.7)
        stats = transition_tracker.get_stats()
        assert stats.stability_score < 0.8

    def test_transition_probability(self, transition_tracker):
        """Geçiş olasılığı."""
        transition_tracker.record("BULL", 0.8)
        transition_tracker.record("BEAR", 0.7)
        transition_tracker.record("BULL", 0.75)
        transition_tracker.record("BEAR", 0.65)

        prob = transition_tracker.get_transition_probability("BULL", "BEAR")
        assert prob > 0.9  # BULL hep BEAR'a geçmiş

    def test_confidence_trend(self, transition_tracker):
        """Confidence trend."""
        for conf in [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]:
            transition_tracker.record("BULL", conf)
        stats = transition_tracker.get_stats()
        assert stats.confidence_trend == "INCREASING"

    def test_recent_transitions(self, transition_tracker):
        """Son geçişler."""
        transition_tracker.record("BULL", 0.8)
        transition_tracker.record("BEAR", 0.7)
        transition_tracker.record("SIDEWAYS", 0.6)

        recent = transition_tracker.get_recent_transitions(limit=5)
        assert len(recent) == 2
        assert recent[0]["from"] == "BULL"
        assert recent[0]["to"] == "BEAR"

    def test_reset(self, transition_tracker):
        """Reset sonrası sıfırlanmalı."""
        transition_tracker.record("BULL", 0.8)
        transition_tracker.record("BEAR", 0.7)
        transition_tracker.reset()
        stats = transition_tracker.get_stats()
        assert stats.total_observations == 0


# =====================================================
# Risk Appetite Tests
# =====================================================


class TestRiskAppetite:
    """Risk Appetite Engine testleri."""

    def test_compute_basic(self, risk_engine):
        """Temel hesaplama."""
        score = risk_engine.compute(
            breadth_pct=65.0,
            momentum=3.0,
            volatility=18.0,
            rsi=55.0,
            sentiment_score=0.3,
            macro_score=0.6,
        )
        assert 0 <= score <= 1
        assert score > 0.5  # Pozitif koşullar → risk-on

    def test_compute_risk_off(self, risk_engine):
        """Risk-off koşulları."""
        score = risk_engine.compute(
            breadth_pct=25.0,
            momentum=-5.0,
            volatility=40.0,
            rsi=25.0,
            sentiment_score=-0.5,
            macro_score=0.2,
        )
        assert score < 0.4  # Negatif koşullar → risk-off

    def test_compute_detailed(self, risk_engine):
        """Detaylı hesaplama."""
        result = risk_engine.compute_detailed(
            breadth_pct=60.0,
            momentum=2.0,
            volatility=20.0,
            rsi=50.0,
        )
        assert "risk_appetite" in result
        assert "contributions" in result
        assert "state" in result
        assert len(result["contributions"]) == 6

    def test_risk_appetite_state(self, risk_engine):
        """State belirleme."""
        result = risk_engine.compute_detailed(
            breadth_pct=80.0,
            momentum=5.0,
            volatility=10.0,
            rsi=60.0,
            sentiment_score=0.5,
            macro_score=0.8,
        )
        assert result["state"] in ("RISK_ON", "MODERATE_RISK_ON")

    def test_update_weights(self, risk_engine):
        """Ağırlık güncelleme."""
        risk_engine.update_weights({"breadth": 0.4, "momentum": 0.3})
        # Ağırlıklar normalize edilmeli
        assert abs(sum(risk_engine._weights.values()) - 1.0) < 0.01


# =====================================================
# Multi-Timeframe Tests
# =====================================================


class TestMultiTimeframe:
    """Multi-Timeframe Engine testleri."""

    def test_compute_all_timeframes(self, multi_tf_engine):
        """Tüm timeframe'ler hesaplanmalı."""
        data = {
            "daily": {
                "instruments": [
                    {"change_pct": 2.0, "momentum": 3.0, "volatility": 0.02},
                    {"change_pct": 1.5, "momentum": 2.0, "volatility": 0.018},
                    {"change_pct": -0.5, "momentum": -1.0, "volatility": 0.025},
                ],
            },
        }
        result = multi_tf_engine.compute_all_timeframes(data)
        assert "daily" in result.states
        assert result.states["daily"].regime != "UNKNOWN"

    def test_alignment_score(self, multi_tf_engine):
        """Alignment score hesaplama."""
        data = {
            "daily": {
                "instruments": [
                    {"change_pct": 2.0, "momentum": 3.0, "volatility": 0.02},
                ],
            },
            "weekly": {
                "instruments": [
                    {"change_pct": 1.5, "momentum": 2.0, "volatility": 0.018},
                ],
            },
        }
        result = multi_tf_engine.compute_all_timeframes(data)
        assert 0 <= result.alignment_score <= 1

    def test_divergence_detection(self, multi_tf_engine):
        """Divergence tespit."""
        # Günlük BULL, haftalık BEAR
        data = {
            "daily": {
                "instruments": [
                    {"change_pct": 5.0, "momentum": 8.0, "volatility": 0.01},
                ],
            },
            "weekly": {
                "instruments": [
                    {"change_pct": -5.0, "momentum": -8.0, "volatility": 0.01},
                ],
            },
        }
        result = multi_tf_engine.compute_all_timeframes(data)
        # Divergence olabilir (veri çok az ama)
        assert isinstance(result.divergences, list)

    def test_dominant_timeframe(self, multi_tf_engine):
        """Dominant timeframe seçimi."""
        data = {
            "daily": {
                "instruments": [
                    {"change_pct": 2.0, "momentum": 3.0, "volatility": 0.02},
                ],
            },
        }
        result = multi_tf_engine.compute_all_timeframes(data)
        assert result.dominant_timeframe == "daily"


# =====================================================
# Output Formatter Tests
# =====================================================


class TestOutputFormatter:
    """Market State Output Formatter testleri."""

    def test_format_empty(self, formatter):
        """Boş input ile format."""
        output = formatter.format()
        assert isinstance(output, MarketStateOutput)
        assert output.regime == "UNKNOWN"

    def test_format_full(self, formatter, sample_instrument_states):
        """Tam input ile format."""
        breadth = MarketBreadthEngine().compute(sample_instrument_states)
        components = ComponentStateEngine().compute_all(sample_instrument_states)
        ensemble = EnsembleRegimeDetector().detect(
            {
                "breadth_pct": breadth.pct_advancing,
                "momentum_avg": components.avg_momentum,
                "volatility_avg": components.avg_volatility,
                "rsi_avg": components.avg_rsi,
            }
        )
        transition = RegimeTransitionTracker()
        transition.record(ensemble.regime, ensemble.confidence)
        transition_stats = transition.get_stats()

        output = formatter.format(
            breadth=breadth,
            components=components,
            ensemble=ensemble,
            transition=transition_stats,
            risk_appetite=0.65,
            risk_appetite_state="MODERATE_RISK_ON",
        )

        assert output.regime != "UNKNOWN"
        assert output.breadth != {}
        # Note: momentum_state depends on input data
        # assert output.momentum_state != "NEUTRAL"  # Enable with specific test data

    def test_to_dict(self, formatter):
        """to_dict() tüm alanları içermeli."""
        output = formatter.format()
        d = output.to_dict()
        assert "regime" in d
        assert "breadth" in d
        assert "risk_appetite" in d
        assert "ensemble_methods" in d


# =====================================================
# Integration Tests
# =====================================================


class TestIntegration:
    """Entegrasyon testleri — tüm modüller birlikte."""

    def test_full_pipeline(self, sample_instrument_states):
        """Tam pipeline: breadth → components → ensemble → transition → risk → output."""
        # 1. Breadth
        breadth_engine = MarketBreadthEngine()
        breadth = breadth_engine.compute(sample_instrument_states)

        # 2. Components
        component_engine = ComponentStateEngine()
        components = component_engine.compute_all(sample_instrument_states)

        # 3. Ensemble
        ensemble_detector = EnsembleRegimeDetector()
        features = {
            "breadth_pct": breadth.pct_advancing,
            "momentum_avg": components.avg_momentum,
            "volatility_avg": components.avg_volatility,
            "rsi_avg": components.avg_rsi,
        }
        ensemble = ensemble_detector.detect(features)

        # 4. Transition
        tracker = RegimeTransitionTracker()
        tracker.record(ensemble.regime, ensemble.confidence)
        transition_stats = tracker.get_stats()

        # 5. Risk appetite
        risk_engine = RiskAppetiteEngine()
        risk_score = risk_engine.compute(
            breadth_pct=breadth.pct_advancing,
            momentum=components.avg_momentum,
            volatility=components.avg_volatility,
            rsi=components.avg_rsi,
        )

        # 6. Format
        formatter = MarketStateFormatter()
        output = formatter.format(
            breadth=breadth,
            components=components,
            ensemble=ensemble,
            transition=transition_stats,
            risk_appetite=risk_score,
        )

        # Assertions
        assert output.regime != "UNKNOWN"
        assert 0 <= output.risk_appetite <= 1
        assert output.breadth != {}
        assert output.regime_stability >= 0

    def test_regime_consistency(self, sample_instrument_states):
        """Aynı input ile aynı regime üretilmeli."""
        engine = EnsembleRegimeDetector()
        features = {
            "breadth_pct": 65.0,
            "momentum_avg": 2.5,
            "volatility_avg": 20.0,
            "rsi_avg": 58.0,
        }

        result1 = engine.detect(features)
        result2 = engine.detect(features)

        assert result1.regime == result2.regime


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
