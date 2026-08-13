"""ALPHA BIST - SPEC Engine v1.1

SPEC = Anormal davranış + Kanıt birleşimi + Rejim uyumu + Beklenen değer
        + Risk/asimetri + İstatistiksel benzerlik - Penalty

Matematiksel tanımlar ve hesaplama formülleri.
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class SPECConfig:
    """SPEC skor hesaplama ağırlıkları ve eşikleri."""
    # Ağırlıklar (toplam = 1.0)
    w_anomaly: float = 0.20
    w_evidence: float = 0.25
    w_regime: float = 0.15
    w_expected_value: float = 0.20
    w_risk_asymmetry: float = 0.10
    w_historical_similarity: float = 0.10

    # Eşikler
    anomaly_threshold: float = 0.5
    evidence_min_ratio: float = 0.57  # 4/7
    regime_compatibility_min: float = 0.6
    expected_value_min: float = 0.0
    risk_asymmetry_min: float = 1.0
    penalty_max: float = 0.5

    # Anomaly bileşen ağırlıkları
    anomaly_volume_weight: float = 0.33
    anomaly_price_weight: float = 0.33
    anomaly_volatility_weight: float = 0.34


@dataclass
class SPECResult:
    """SPEC hesaplama sonucu."""
    ticker: str
    timestamp: datetime
    spec_score: float
    category: str  # HIGH_CONVICTION | CANDIDATE | WATCH | NORMAL

    # Bileşen skorlar
    anomaly_score: float
    evidence_consensus: float
    regime_compatibility: float
    expected_value: float
    risk_asymmetry: float
    historical_similarity: float
    penalty_factors: float

    # Detay
    evidence_list: List[Dict[str, Any]]
    regime_fit: Dict[str, Any]
    penalty_details: Dict[str, float]

    # Edge decomposition
    edge_decomposition: Dict[str, float]


class SPECEngine:
    """SPEC skor hesaplama motoru."""

    def __init__(self, config: Optional[SPECConfig] = None):
        self.config = config or SPECConfig()

    def compute_spec(
        self,
        ticker: str,
        asset_state: Dict[str, Any],
        market_state: Dict[str, Any],
        historical_analogues: Optional[List[Dict]] = None,
        ml_predictions: Optional[Dict[str, float]] = None,
    ) -> SPECResult:
        """Compute full SPEC score for an asset."""

        # 1. Anomaly Score
        anomaly = self._compute_anomaly(asset_state)

        # 2. Evidence Consensus
        evidence_consensus, evidence_list = self._compute_evidence(asset_state)

        # 3. Regime Compatibility
        regime_compat, regime_fit = self._compute_regime_compatibility(
            asset_state, market_state
        )

        # 4. Expected Value
        expected_value = self._compute_expected_value(
            asset_state, ml_predictions
        )

        # 5. Risk Asymmetry
        risk_asymmetry = self._compute_risk_asymmetry(
            asset_state, ml_predictions
        )

        # 6. Historical Similarity
        historical_sim = self._compute_historical_similarity(
            asset_state, historical_analogues
        )

        # 7. Penalty Factors
        penalty, penalty_details = self._compute_penalties(
            asset_state, market_state
        )

        # Weighted sum
        raw_score = (
            self.config.w_anomaly * anomaly
            + self.config.w_evidence * evidence_consensus
            + self.config.w_regime * regime_compat
            + self.config.w_expected_value * expected_value
            + self.config.w_risk_asymmetry * risk_asymmetry
            + self.config.w_historical_similarity * historical_sim
        )

        # Apply penalty
        spec_score = raw_score / (1 + penalty)

        # Normalize to [0, 100]
        spec_score_100 = min(max(spec_score * 100, 0), 100)

        # Category
        category = self._categorize(spec_score_100)

        # Edge decomposition
        edge = {
            "anomaly": anomaly * self.config.w_anomaly * 100,
            "evidence": evidence_consensus * self.config.w_evidence * 100,
            "regime": regime_compat * self.config.w_regime * 100,
            "expected_value": expected_value * self.config.w_expected_value * 100,
            "risk_asymmetry": risk_asymmetry * self.config.w_risk_asymmetry * 100,
            "historical_similarity": historical_sim * self.config.w_historical_similarity * 100,
            "penalty": -penalty * 100,
            "total": spec_score_100,
        }

        return SPECResult(
            ticker=ticker,
            timestamp=datetime.utcnow(),
            spec_score=round(spec_score_100, 2),
            category=category,
            anomaly_score=round(anomaly, 4),
            evidence_consensus=round(evidence_consensus, 4),
            regime_compatibility=round(regime_compat, 4),
            expected_value=round(expected_value, 4),
            risk_asymmetry=round(risk_asymmetry, 4),
            historical_similarity=round(historical_sim, 4),
            penalty_factors=round(penalty, 4),
            evidence_list=evidence_list,
            regime_fit=regime_fit,
            penalty_details=penalty_details,
            edge_decomposition=edge,
        )

    # =====================================================
    # Bileşen 1: AnomalyScore
    # =====================================================

    def _compute_anomaly(self, state: Dict[str, Any]) -> float:
        """
        AnomalyScore = f(volume_zscore, price_zscore, volatility_zscore)

        raw = (volume_zscore² + price_zscore² + volatility_zscore²) / 3
        AnomalyScore = min(raw / 4.0, 1.0)
        """
        vol_z = abs(state.get("volume_zscore", 0))
        price_z = abs(state.get("price_change_1d_zscore", 0))
        volat_z = abs(state.get("volatility_zscore", 0))

        raw = (
            self.config.anomaly_volume_weight * vol_z ** 2
            + self.config.anomaly_price_weight * price_z ** 2
            + self.config.anomaly_volatility_weight * volat_z ** 2
        )

        return min(raw / 4.0, 1.0)

    # =====================================================
    # Bileşen 2: EvidenceConsensus
    # =====================================================

    def _compute_evidence(self, state: Dict[str, Any]) -> Tuple[float, List[Dict]]:
        """
        EvidenceConsensus = count(evidence_i > threshold) / total

        Kanıtlar:
          1. volume_anomaly: volume_zscore > 2.0
          2. price_breakout: price > bb_upper or near_20d_high
          3. sector_strength: strength_vs_sector > 1.5
          4. kap_positive: kap_sentiment > 0.3
          5. momentum_build: roc_5d > 2.0 and acceleration > 0
          6. low_vol_expansion: vol_regime == "LOW" and vol_z > 1.5
          7. institutional_flow: (varsa)
        """
        evidence = []

        # 1. Volume anomaly
        vol_z = state.get("volume_zscore", 0)
        evidence.append({
            "name": "volume_anomaly",
            "active": vol_z > 2.0,
            "value": vol_z,
            "threshold": 2.0,
        })

        # 2. Price breakout
        bb_pos = state.get("bb_position", 0.5)
        near_high = state.get("near_20d_high", 0)
        evidence.append({
            "name": "price_breakout",
            "active": bb_pos > 0.95 or near_high == 1,
            "value": bb_pos,
            "threshold": 0.95,
        })

        # 3. Sector strength
        sector_str = state.get("relative_strength_vs_sector", 0)
        evidence.append({
            "name": "sector_strength",
            "active": sector_str > 1.5,
            "value": sector_str,
            "threshold": 1.5,
        })

        # 4. KAP positive
        kap_sent = state.get("kap_sentiment", 0)
        evidence.append({
            "name": "kap_positive",
            "active": kap_sent > 0.3,
            "value": kap_sent,
            "threshold": 0.3,
        })

        # 5. Momentum building
        roc_5d = state.get("roc_5d", 0)
        accel = state.get("price_acceleration", 0)
        evidence.append({
            "name": "momentum_build",
            "active": roc_5d > 2.0 and accel > 0,
            "value": roc_5d,
            "threshold": 2.0,
        })

        # 6. Low volatility expansion
        vol_regime = state.get("volatility_regime", "NORMAL")
        evidence.append({
            "name": "low_vol_expansion",
            "active": vol_regime == "LOW" and vol_z > 1.5,
            "value": vol_z if vol_regime == "LOW" else 0,
            "threshold": 1.5,
        })

        # 7. Institutional flow (placeholder - order-flow verisi varsa)
        flow_score = state.get("flow_score", 0)
        evidence.append({
            "name": "institutional_flow",
            "active": flow_score > 0.7,
            "value": flow_score,
            "threshold": 0.7,
        })

        active_count = sum(1 for e in evidence if e["active"])
        total_count = len(evidence)

        consensus = active_count / total_count if total_count > 0 else 0

        return consensus, evidence

    # =====================================================
    # Bileşen 3: RegimeCompatibility
    # =====================================================

    def _compute_regime_compatibility(
        self, state: Dict[str, Any], market_state: Dict[str, Any]
    ) -> Tuple[float, Dict]:
        """
        RegimeCompatibility = regime_fit_score(current_regime, historical_returns)

        Mevcut rejimde benzer sinyallerin geçmiş performansı.
        """
        current_regime = market_state.get("regime", "UNKNOWN")
        asset_direction = "LONG" if state.get("momentum_20d", 0) > 0 else "SHORT"

        # Rejim-yön uyum matrisi
        regime_fit_matrix = {
            "TRENDING-UP": {"LONG": 0.9, "SHORT": 0.1},
            "MOMENTUM-EXPANSION": {"LONG": 0.85, "SHORT": 0.15},
            "RISK-ON": {"LONG": 0.8, "SHORT": 0.2},
            "RECOVERY": {"LONG": 0.75, "SHORT": 0.25},
            "RANGE": {"LONG": 0.5, "SHORT": 0.5},
            "LOW-VOLATILITY": {"LONG": 0.6, "SHORT": 0.4},
            "HIGH-VOLATILITY": {"LONG": 0.4, "SHORT": 0.6},
            "TRENDING-DOWN": {"LONG": 0.15, "SHORT": 0.85},
            "RISK-OFF": {"LONG": 0.2, "SHORT": 0.8},
            "PANIC": {"LONG": 0.1, "SHORT": 0.9},
            "UNKNOWN": {"LONG": 0.5, "SHORT": 0.5},
        }

        fit = regime_fit_matrix.get(current_regime, {"LONG": 0.5, "SHORT": 0.5})
        score = fit.get(asset_direction, 0.5)

        return score, {
            "regime": current_regime,
            "direction": asset_direction,
            "fit_score": score,
        }

    # =====================================================
    # Bileşen 4: ExpectedValue
    # =====================================================

    def _compute_expected_value(
        self, state: Dict[str, Any], ml_predictions: Optional[Dict]
    ) -> float:
        """
        EV = P(positive) * E[return|positive] - P(negative) * E[return|negative]

        Normalize: EV = (raw_EV - min_EV) / (max_EV - min_EV)
        """
        if ml_predictions:
            p_pos = ml_predictions.get("probability_positive", 0.5)
            e_pos = ml_predictions.get("expected_return_positive", 3.0)
            p_neg = 1 - p_pos
            e_neg = ml_predictions.get("expected_return_negative", -3.0)

            raw_ev = p_pos * e_pos - p_neg * abs(e_neg)
        else:
            # Fallback: momentum bazlı basit EV
            roc_20d = state.get("roc_20d", 0)
            vol = state.get("realized_vol_20d", 20)
            raw_ev = roc_20d / max(vol, 1)

        # Normalize to [0, 1]
        # Max EV kabaca +5%, min EV kabaca -5%
        normalized = (raw_ev + 5) / 10
        return min(max(normalized, 0), 1)

    # =====================================================
    # Bileşen 5: RiskAsymmetry
    # =====================================================

    def _compute_risk_asymmetry(
        self, state: Dict[str, Any], ml_predictions: Optional[Dict]
    ) -> float:
        """
        RiskAsymmetry = ExpectedUpside / ExpectedDownside

        Upside: %75 percentile of simulated returns
        Downside: %25 percentile of simulated returns
        Ratio = Upside / |Downside|
        Normalize: RA = min(Ratio / 3.0, 1.0)
        """
        if ml_predictions:
            upside = ml_predictions.get("upside_75pct", 3.0)
            downside = abs(ml_predictions.get("downside_25pct", 3.0))
        else:
            # Fallback
            vol = state.get("realized_vol_20d", 20)
            upside = vol * 0.5
            downside = vol * 0.5

        if downside == 0:
            return 0.5

        ratio = upside / downside
        return min(ratio / 3.0, 1.0)

    # =====================================================
    # Bileşen 6: HistoricalSimilarity
    # =====================================================

    def _compute_historical_similarity(
        self, state: Dict[str, Any], analogues: Optional[List[Dict]]
    ) -> float:
        """
        HistoricalSimilarity = positive_rate among top-10 similar states

        Benzer durumların sonraki getirileri pozitif çıkma oranı.
        """
        if not analogues or len(analogues) == 0:
            return 0.5  # nötr

        positive_count = sum(
            1 for a in analogues if a.get("outcome_return", 0) > 0
        )
        return positive_count / len(analogues)

    # =====================================================
    # Bileşen 7: PenaltyFactors
    # =====================================================

    def _compute_penalties(
        self, state: Dict[str, Any], market_state: Dict[str, Any]
    ) -> Tuple[float, Dict[str, float]]:
        """
        Penalty = p1*high_vol + p2*low_liq + p3*corr_risk + p4*overcrowding
        """
        penalties = {}

        # High volatility penalty
        vol_regime = state.get("volatility_regime", "NORMAL")
        if vol_regime == "EXTREME":
            penalties["high_volatility"] = 1.0
        elif vol_regime == "HIGH":
            penalties["high_volatility"] = 0.5
        else:
            penalties["high_volatility"] = 0.0

        # Low liquidity penalty
        amihud = state.get("amihud_illiquidity", 0)
        if amihud > 0.01:
            penalties["low_liquidity"] = 1.0
        elif amihud > 0.005:
            penalties["low_liquidity"] = 0.5
        else:
            penalties["low_liquidity"] = 0.0

        # Correlation risk
        corr = abs(state.get("correlation_to_index", 0.5))
        if corr > 0.9:
            penalties["correlation_risk"] = 1.0
        elif corr > 0.8:
            penalties["correlation_risk"] = 0.5
        else:
            penalties["correlation_risk"] = 0.0

        # Overcrowding (benzer sinyal sayısı)
        similar_signals = market_state.get("similar_signal_count", 0)
        if similar_signals > 20:
            penalties["overcrowding"] = 1.0
        elif similar_signals > 10:
            penalties["overcrowding"] = 0.5
        else:
            penalties["overcrowding"] = 0.0

        total_penalty = sum(penalties.values()) / len(penalties)
        return total_penalty, penalties

    # =====================================================
    # Kategorilendirme
    # =====================================================

    def _categorize(self, score: float) -> str:
        """
        >= 85  → HIGH_CONVICTION_SPEC
        >= 70  → SPEC_CANDIDATE
        >= 55  → WATCH
        < 55   → NORMAL
        """
        if score >= 85:
            return "HIGH_CONVICTION"
        elif score >= 70:
            return "CANDIDATE"
        elif score >= 55:
            return "WATCH"
        else:
            return "NORMAL"


# Singleton
spec_engine = SPECEngine()
