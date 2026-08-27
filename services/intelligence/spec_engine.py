"""ALPHA BIST - SPEC Engine v1.2

SPEC = Anormal davranış + Kanıt birleşimi + Rejim uyumu + Beklenen değer
        + Risk/asimetri + İstatistiksel benzerlik - Penalty

v1.2: NaN/None güvenli, _safe_float ile tüm değerler korumalı.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


def _safe(val) -> float:
    """NaN ve None güvenli float dönüşümü."""
    if val is None:
        return 0.0
    try:
        f = float(val)
        return 0.0 if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return 0.0


@dataclass
class SPECConfig:
    """SPEC skor hesaplama ağırlıkları ve eşikleri."""
    w_anomaly: float = 0.20
    w_evidence: float = 0.25
    w_regime: float = 0.15
    w_expected_value: float = 0.20
    w_risk_asymmetry: float = 0.10
    w_historical_similarity: float = 0.10

    anomaly_threshold: float = 0.5
    evidence_min_ratio: float = 0.57
    regime_compatibility_min: float = 0.6
    expected_value_min: float = 0.0
    risk_asymmetry_min: float = 1.0
    penalty_max: float = 0.5

    anomaly_volume_weight: float = 0.33
    anomaly_price_weight: float = 0.33
    anomaly_volatility_weight: float = 0.34


@dataclass
class SPECResult:
    ticker: str
    timestamp: datetime
    spec_score: float
    category: str
    anomaly_score: float
    evidence_consensus: float
    regime_compatibility: float
    expected_value: float
    risk_asymmetry: float
    historical_similarity: float
    penalty_factors: float
    evidence_list: list[dict[str, Any]]
    regime_fit: dict[str, Any]
    penalty_details: dict[str, float]
    edge_decomposition: dict[str, float]


class SPECEngine:
    """SPEC skor hesaplama motoru."""

    def __init__(self, config: SPECConfig | None = None):
        self.config = config or SPECConfig()

    def compute_spec(
        self,
        ticker: str,
        asset_state: dict[str, Any],
        market_state: dict[str, Any],
        historical_analogues: list[dict] | None = None,
        ml_predictions: dict[str, float] | None = None,
    ) -> SPECResult:
        """SPEC skoru hesapla."""
        anomaly = self._compute_anomaly(asset_state)
        evidence_consensus, evidence_list = self._compute_evidence(asset_state)
        regime_compat, regime_fit = self._compute_regime_compatibility(asset_state, market_state)
        expected_value = self._compute_expected_value(asset_state, ml_predictions)
        risk_asymmetry = self._compute_risk_asymmetry(asset_state, ml_predictions)
        historical_sim = self._compute_historical_similarity(historical_analogues)
        penalty, penalty_details = self._compute_penalties(asset_state, market_state)

        # Config eşiklerini uygula
        if anomaly < self.config.anomaly_threshold:
            anomaly *= 0.5
        if evidence_consensus < self.config.evidence_min_ratio:
            evidence_consensus *= 0.7
        if regime_compat < self.config.regime_compatibility_min:
            regime_compat *= 0.6
        if expected_value < self.config.expected_value_min:
            expected_value *= 0.5
        if risk_asymmetry < self.config.risk_asymmetry_min:
            risk_asymmetry *= 0.7
        penalty = min(penalty, self.config.penalty_max)

        raw_score = (
            self.config.w_anomaly * anomaly
            + self.config.w_evidence * evidence_consensus
            + self.config.w_regime * regime_compat
            + self.config.w_expected_value * expected_value
            + self.config.w_risk_asymmetry * risk_asymmetry
            + self.config.w_historical_similarity * historical_sim
        )

        spec_score = raw_score / (1 + penalty) if penalty > 0 else raw_score
        spec_score_100 = min(max(spec_score * 100, 0), 100)
        category = self._categorize(spec_score_100)

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
            ticker=ticker, timestamp=datetime.now(UTC),
            spec_score=round(spec_score_100, 2), category=category,
            anomaly_score=round(anomaly, 4), evidence_consensus=round(evidence_consensus, 4),
            regime_compatibility=round(regime_compat, 4), expected_value=round(expected_value, 4),
            risk_asymmetry=round(risk_asymmetry, 4), historical_similarity=round(historical_sim, 4),
            penalty_factors=round(penalty, 4),
            evidence_list=evidence_list, regime_fit=regime_fit,
            penalty_details=penalty_details, edge_decomposition=edge,
        )

    def _compute_anomaly(self, state: dict[str, Any]) -> float:
        vol_z = abs(_safe(state.get("volume_zscore", 0)))
        price_z = abs(_safe(state.get("price_change_1d_zscore", 0)))
        volat_z = abs(_safe(state.get("volatility_zscore", 0)))
        raw = (
            self.config.anomaly_volume_weight * vol_z ** 2
            + self.config.anomaly_price_weight * price_z ** 2
            + self.config.anomaly_volatility_weight * volat_z ** 2
        )
        return min(raw / 4.0, 1.0)

    def _compute_evidence(self, state: dict[str, Any]) -> tuple[float, list[dict]]:
        """Evidence hesapla.

        P1 düzeltmesi: Evidence'lar source reliability, confidence,
        freshness, correlation ile ağırlıklandırılmalı.
        Aynı haberin 10 farklı kaynaktan kopyalanması 10 bağımsız evidence sayılmamalı.
        """
        evidence = []
        vol_z = _safe(state.get("volume_zscore", 0))
        bb_pos = _safe(state.get("bb_position", 0.5))
        near_high = _safe(state.get("near_20d_high", 0))
        sector_str = _safe(state.get("relative_strength_vs_sector", 0))
        kap_sent = _safe(state.get("kap_sentiment", 0))
        roc_5d = _safe(state.get("roc_5d", 0))
        accel = _safe(state.get("price_acceleration", 0))
        vol_regime = state.get("volatility_regime", "NORMAL")
        flow_score = _safe(state.get("flow_score", 0))

        # Her evidence için reliability/confidence/freshness ağırlığı
        evidence.append({
            "name": "volume_anomaly", "active": vol_z > 2.0,
            "value": vol_z, "threshold": 2.0,
            "reliability": 0.95, "confidence": min(vol_z / 4.0, 1.0), "freshness": 1.0,
        })
        evidence.append({
            "name": "price_breakout", "active": bb_pos > 0.95 or near_high == 1,
            "value": bb_pos, "threshold": 0.95,
            "reliability": 0.9, "confidence": min(bb_pos, 1.0), "freshness": 1.0,
        })
        evidence.append({
            "name": "sector_strength", "active": sector_str > 1.5,
            "value": sector_str, "threshold": 1.5,
            "reliability": 0.85, "confidence": min(sector_str / 3.0, 1.0), "freshness": 0.9,
        })
        evidence.append({
            "name": "kap_positive", "active": kap_sent > 0.3,
            "value": kap_sent, "threshold": 0.3,
            "reliability": 0.95, "confidence": abs(kap_sent), "freshness": 1.0,
        })
        evidence.append({
            "name": "momentum_build", "active": roc_5d > 2.0 and accel > 0,
            "value": roc_5d, "threshold": 2.0,
            "reliability": 0.8, "confidence": min(roc_5d / 5.0, 1.0), "freshness": 0.95,
        })
        evidence.append({
            "name": "low_vol_expansion", "active": vol_regime == "LOW" and vol_z > 1.5,
            "value": vol_z if vol_regime == "LOW" else 0, "threshold": 1.5,
            "reliability": 0.75, "confidence": 0.7, "freshness": 0.85,
        })
        evidence.append({
            "name": "institutional_flow", "active": flow_score > 0.7,
            "value": flow_score, "threshold": 0.7,
            "reliability": 0.7, "confidence": flow_score, "freshness": 0.8,
        })

        # Ağırlıklı evidence consensus (basit ortalama değil)
        if not evidence:
            return 0, evidence

        weighted_sum = 0
        total_weight = 0
        for e in evidence:
            weight = e.get("reliability", 0.5) * e.get("confidence", 0.5) * e.get("freshness", 0.5)
            if e["active"]:
                weighted_sum += weight
            total_weight += weight

        consensus = weighted_sum / total_weight if total_weight > 0 else 0
        return consensus, evidence

    def _compute_regime_compatibility(self, state: dict[str, Any], market_state: dict[str, Any]) -> tuple[float, dict]:
        current_regime = market_state.get("regime", "UNKNOWN")
        asset_direction = "LONG" if _safe(state.get("momentum_20d", 0)) > 0 else "SHORT"

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
        return score, {"regime": current_regime, "direction": asset_direction, "fit_score": score}

    def _compute_expected_value(self, state: dict[str, Any], ml_predictions: dict | None) -> float:
        """Expected value hesapla.

        P1 düzeltmesi: Keyfi normalization (EV / 10) kaldırıldı.
        EV calibration: probability × return formülü ile.
        """
        if ml_predictions:
            p_pos = _safe(ml_predictions.get("probability_positive", 0.5))
            e_pos = _safe(ml_predictions.get("expected_return_positive", 3.0))
            p_neg = 1 - p_pos
            e_neg = _safe(ml_predictions.get("expected_return_negative", -3.0))
            raw_ev = p_pos * e_pos - p_neg * abs(e_neg)
        else:
            roc_20d = _safe(state.get("roc_20d", 0))
            vol = _safe(state.get("realized_vol_20d", 20))
            # Risk-adjusted return (Sharpe-like)
            raw_ev = roc_20d / max(vol, 1)

        # P1: Keyfi normalization (EV / 10) yerine sigmoid calibration
        # raw_ev tipik olarak -3 ile +3 arası
        # sigmoid: 1 / (1 + exp(-x)) → [0, 1]
        import math
        try:
            normalized = 1.0 / (1.0 + math.exp(-raw_ev))
        except (OverflowError, ValueError):
            normalized = 0.5

        return min(max(normalized, 0), 1)

    def _compute_risk_asymmetry(self, state: dict[str, Any], ml_predictions: dict | None) -> float:
        if ml_predictions:
            upside = _safe(ml_predictions.get("upside_75pct", 3.0))
            downside = abs(_safe(ml_predictions.get("downside_25pct", 3.0)))
        else:
            vol = _safe(state.get("realized_vol_20d", 20))
            upside = vol * 0.5
            downside = vol * 0.5
        if downside == 0:
            return 0.5
        ratio = upside / downside
        return min(ratio / 3.0, 1.0)

    def _compute_historical_similarity(self, analogues: list[dict] | None) -> float:
        if not analogues or len(analogues) == 0:
            return 0.5
        positive_count = sum(1 for a in analogues if _safe(a.get("outcome_return", 0)) > 0)
        return positive_count / len(analogues)

    def _compute_penalties(self, state: dict[str, Any], market_state: dict[str, Any]) -> tuple[float, dict[str, float]]:
        penalties = {}
        vol_regime = state.get("volatility_regime", "NORMAL")
        if vol_regime == "EXTREME":
            penalties["high_volatility"] = 1.0
        elif vol_regime == "HIGH":
            penalties["high_volatility"] = 0.5
        else:
            penalties["high_volatility"] = 0.0

        amihud = _safe(state.get("amihud_illiquidity", 0))
        if amihud > 0.01:
            penalties["low_liquidity"] = 1.0
        elif amihud > 0.005:
            penalties["low_liquidity"] = 0.5
        else:
            penalties["low_liquidity"] = 0.0

        corr = abs(_safe(state.get("correlation_to_index", 0.5)))
        if corr > 0.9:
            penalties["correlation_risk"] = 1.0
        elif corr > 0.8:
            penalties["correlation_risk"] = 0.5
        else:
            penalties["correlation_risk"] = 0.0

        similar_signals = _safe(market_state.get("similar_signal_count", 0))
        if similar_signals > 20:
            penalties["overcrowding"] = 1.0
        elif similar_signals > 10:
            penalties["overcrowding"] = 0.5
        else:
            penalties["overcrowding"] = 0.0

        total_penalty = sum(penalties.values()) / len(penalties) if penalties else 0
        return total_penalty, penalties

    def _categorize(self, score: float) -> str:
        if score >= 85:
            return "HIGH_CONVICTION"
        elif score >= 70:
            return "CANDIDATE"
        elif score >= 55:
            return "WATCH"
        else:
            return "NORMAL"


spec_engine = SPECEngine()
