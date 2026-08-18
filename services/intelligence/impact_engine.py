"""ALPHA BIST - Event → Asset Impact Propagation Engine v1.1

Olayların varlıklara nasıl yayıldığını modelleyen motor.
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import structlog

logger = structlog.get_logger()


@dataclass
class PropagationRule:
    """Tek bir yayılım kuralı."""
    source_event: str
    target: str
    impact: float  # -1.0 ile +1.0 arası
    lag_hours: float
    confidence: float
    decay_hours: float = 24.0  # etki ne kadar sürede azalır


@dataclass
class PropagationResult:
    """Yayılım sonucu."""
    source_event_type: str
    source_event_id: str
    timestamp: datetime
    affected_instruments: List[Dict[str, Any]]
    world_state_delta: Dict[str, float]
    propagation_chain: List[Dict[str, Any]]


# =====================================================
# Propagation Rules (50+ kural)
# =====================================================

PROPAGATION_RULES: List[PropagationRule] = [
    # === FED ===
    PropagationRule("FED_RATE_HIKE", "USD_INDEX", +0.8, 0, 0.9),
    PropagationRule("FED_RATE_HIKE", "EM_RISK", -0.6, 0, 0.85),
    PropagationRule("FED_RATE_HIKE", "BIST_BANK", -0.7, 1, 0.8),
    PropagationRule("FED_RATE_HIKE", "BIST_TECH", -0.3, 2, 0.6),
    PropagationRule("FED_RATE_HIKE", "GOLD", +0.5, 0, 0.7),
    PropagationRule("FED_RATE_HIKE", "US_10Y", +0.6, 0, 0.85),

    PropagationRule("FED_RATE_CUT", "USD_INDEX", -0.6, 0, 0.85),
    PropagationRule("FED_RATE_CUT", "EM_RISK", +0.5, 0, 0.8),
    PropagationRule("FED_RATE_CUT", "BIST_BANK", +0.6, 1, 0.75),
    PropagationRule("FED_RATE_CUT", "GOLD", +0.4, 0, 0.7),

    # === TCMB ===
    PropagationRule("TCMB_RATE_CUT", "USD_TRY", +0.4, 0, 0.85),
    PropagationRule("TCMB_RATE_CUT", "BIST_BANK", +0.6, 1, 0.8),
    PropagationRule("TCMB_RATE_CUT", "BIST_REAL_ESTATE", +0.5, 2, 0.7),
    PropagationRule("TCMB_RATE_CUT", "BIST_RETAIL", +0.3, 2, 0.6),

    PropagationRule("TCMB_RATE_HIKE", "USD_TRY", -0.3, 0, 0.8),
    PropagationRule("TCMB_RATE_HIKE", "BIST_BANK", -0.4, 1, 0.75),

    # === OIL ===
    PropagationRule("OIL_SHOCK_UP", "TUPRS", +0.8, 0, 0.9),
    PropagationRule("OIL_SHOCK_UP", "THYAO", -0.6, 0, 0.85),
    PropagationRule("OIL_SHOCK_UP", "PETKM", +0.4, 0, 0.7),
    PropagationRule("OIL_SHOCK_UP", "BIST_ENERGY", +0.5, 0, 0.8),
    PropagationRule("OIL_SHOCK_UP", "BIST_AVIATION", -0.5, 0, 0.8),
    PropagationRule("OIL_SHOCK_UP", "TURKEY_MACRO", -0.3, 1, 0.7),

    PropagationRule("OIL_SHOCK_DOWN", "TUPRS", -0.6, 0, 0.85),
    PropagationRule("OIL_SHOCK_DOWN", "THYAO", +0.5, 0, 0.8),
    PropagationRule("OIL_SHOCK_DOWN", "BIST_ENERGY", -0.4, 0, 0.75),

    # === USD ===
    PropagationRule("USD_STRENGTHEN", "BIST_EXPORTERS", +0.3, 1, 0.7),
    PropagationRule("USD_STRENGTHEN", "BIST_IMPORTERS", -0.3, 1, 0.7),
    PropagationRule("USD_STRENGTHEN", "GOLD_TRY", +0.4, 0, 0.8),
    PropagationRule("USD_STRENGTHEN", "TURKEY_MACRO", -0.2, 2, 0.6),

    PropagationRule("USD_WEAKEN", "BIST_EXPORTERS", -0.2, 1, 0.65),
    PropagationRule("USD_WEAKEN", "BIST_IMPORTERS", +0.2, 1, 0.65),

    # === GEOPOLITICAL ===
    PropagationRule("GEOPOLITICAL_TENSION", "VIX", +0.7, 0, 0.85),
    PropagationRule("GEOPOLITICAL_TENSION", "EM_RISK", -0.6, 0, 0.8),
    PropagationRule("GEOPOLITICAL_TENSION", "BIST", -0.5, 0, 0.75),
    PropagationRule("GEOPOLITICAL_TENSION", "GOLD", +0.6, 0, 0.8),
    PropagationRule("GEOPOLITICAL_TENSION", "OIL", +0.4, 0, 0.7),

    # === INFLATION ===
    PropagationRule("INFLATION_HIGH", "TCMB_RATE_EXPECTATION", +0.6, 0, 0.8),
    PropagationRule("INFLATION_HIGH", "BIST_BANK", -0.4, 1, 0.7),
    PropagationRule("INFLATION_HIGH", "BIST_RETAIL", -0.3, 2, 0.65),
    PropagationRule("INFLATION_HIGH", "GOLD", +0.5, 0, 0.75),

    # === COMPANY EVENTS ===
    PropagationRule("KAP_POSITIVE", "STOCK", +0.6, 0, 0.8),
    PropagationRule("KAP_NEGATIVE", "STOCK", -0.6, 0, 0.8),
    PropagationRule("KAP_INVESTMENT", "STOCK", +0.4, 0, 0.7),
    PropagationRule("KAP_FINANCIAL_BEAT", "STOCK", +0.7, 0, 0.85),
    PropagationRule("KAP_FINANCIAL_MISS", "STOCK", -0.7, 0, 0.85),

    # === SECTOR ===
    PropagationRule("SECTOR_ROTATION_IN", "SECTOR_STOCKS", +0.4, 0, 0.7),
    PropagationRule("SECTOR_ROTATION_OUT", "SECTOR_STOCKS", -0.4, 0, 0.7),

    # === VIX ===
    PropagationRule("VIX_SPIKE", "BIST", -0.5, 0, 0.8),
    PropagationRule("VIX_SPIKE", "BIST_BANK", -0.6, 0, 0.8),
    PropagationRule("VIX_SPIKE", "GOLD", +0.4, 0, 0.7),

    # === BIST INDEX ===
    PropagationRule("BIST_CRASH", "ALL_STOCKS", -0.8, 0, 0.9),
    PropagationRule("BIST_SURGE", "ALL_STOCKS", +0.6, 0, 0.8),
]


class ImpactEngine:
    """Event → Asset Impact Propagation Engine."""

    def __init__(self):
        self.rules = PROPAGATION_RULES
        self._instrument_sector_map: Dict[str, List[str]] = {}
        self._sector_stocks: Dict[str, List[int]] = {}

    def load_sector_map(self, instrument_sector: Dict[str, str]):
        """Load instrument → sector mapping."""
        self._instrument_sector_map = instrument_sector

        # Reverse: sector → instruments
        sector_stocks: Dict[str, List[str]] = {}
        for ticker, sector in instrument_sector.items():
            if sector not in sector_stocks:
                sector_stocks[sector] = []
            sector_stocks[sector].append(ticker)
        self._sector_stocks = sector_stocks

    def propagate(
        self,
        event_type: str,
        event_data: Dict[str, Any],
        event_id: str,
        current_world_state: Dict[str, float],
        instrument_states: Dict[str, Dict],
    ) -> PropagationResult:
        """
        Propagate an event through the impact graph.

        Returns affected instruments with impact magnitudes.
        """
        chain = []
        affected = []
        world_delta = {}

        # Find matching rules
        matching_rules = [r for r in self.rules if r.source_event == event_type]

        if not matching_rules:
            return PropagationResult(
                source_event_type=event_type,
                source_event_id=event_id,
                timestamp=datetime.now(timezone.utc),
                affected_instruments=[],
                world_state_delta={},
                propagation_chain=[],
            )

        for rule in matching_rules:
            # Apply rule
            impact_magnitude = rule.impact * rule.confidence

            # World state update
            if rule.target in [
                "USD_INDEX", "EM_RISK", "GOLD", "US_10Y", "VIX",
                "TURKEY_MACRO", "USD_TRY", "TCMB_RATE_EXPECTATION",
            ]:
                world_delta[rule.target] = world_delta.get(rule.target, 0) + impact_magnitude

            # Instrument-specific
            elif rule.target == "STOCK":
                # Direct stock impact (KAP events)
                ticker = event_data.get("ticker", "")
                if ticker:
                    affected.append({
                        "ticker": ticker,
                        "instrument_id": event_data.get("instrument_id"),
                        "impact": impact_magnitude,
                        "lag_hours": rule.lag_hours,
                        "confidence": rule.confidence,
                        "source_rule": rule.source_event,
                    })

            elif rule.target.startswith("BIST_"):
                # Sector impact
                sector = rule.target.replace("BIST_", "")
                for ticker in self._sector_stocks.get(sector, []):
                    affected.append({
                        "ticker": ticker,
                        "impact": impact_magnitude,
                        "lag_hours": rule.lag_hours,
                        "confidence": rule.confidence,
                        "source_rule": rule.source_event,
                    })

            elif rule.target == "ALL_STOCKS":
                # Market-wide impact
                for ticker in self._instrument_sector_map.keys():
                    affected.append({
                        "ticker": ticker,
                        "impact": impact_magnitude,
                        "lag_hours": rule.lag_hours,
                        "confidence": rule.confidence,
                        "source_rule": rule.source_event,
                    })

            elif rule.target in ["TUPRS", "THYAO", "PETKM", "AKBNK", "GARAN", "YKBNK"]:
                # Specific stock
                affected.append({
                    "ticker": rule.target,
                    "impact": impact_magnitude,
                    "lag_hours": rule.lag_hours,
                    "confidence": rule.confidence,
                    "source_rule": rule.source_event,
                })

            chain.append({
                "source": event_type,
                "target": rule.target,
                "impact": rule.impact,
                "lag_hours": rule.lag_hours,
                "confidence": rule.confidence,
            })

        # Aggregate affected instruments (same ticker can appear multiple times)
        aggregated = {}
        for a in affected:
            ticker = a["ticker"]
            if ticker not in aggregated:
                aggregated[ticker] = {
                    "ticker": ticker,
                    "instrument_id": a.get("instrument_id"),
                    "total_impact": 0,
                    "max_lag_hours": 0,
                    "avg_confidence": 0,
                    "rules": [],
                    "count": 0,
                }
            aggregated[ticker]["total_impact"] += a["impact"]
            aggregated[ticker]["max_lag_hours"] = max(
                aggregated[ticker]["max_lag_hours"], a["lag_hours"]
            )
            aggregated[ticker]["rules"].append(a["source_rule"])
            aggregated[ticker]["count"] += 1

        # Compute average confidence
        for ticker, data in aggregated.items():
            matching_affected = [a for a in affected if a["ticker"] == ticker]
            data["avg_confidence"] = np.mean([a["confidence"] for a in matching_affected])
            # Normalize impact
            data["total_impact"] = min(max(data["total_impact"], -1.0), 1.0)

        return PropagationResult(
            source_event_type=event_type,
            source_event_id=event_id,
            timestamp=datetime.now(timezone.utc),
            affected_instruments=list(aggregated.values()),
            world_state_delta=world_delta,
            propagation_chain=chain,
        )


# Singleton
impact_engine = ImpactEngine()


# =====================================================
# B31 Event Study entegrasyonu
# =====================================================
def analyze_event_impact(ticker: str, event_type: str, stock_returns: list, market_returns: list) -> Dict[str, Any]:
    """Event study ile olay etkisi analizi."""
    try:
        from services.event_study.kap_event import analyze_kap_event
        from services.event_study.impact import calculate_event_impact
        from datetime import datetime
        result = analyze_kap_event(
            ticker=ticker,
            event_description=event_type,
            event_date=datetime.now(),
            stock_returns=np.array(stock_returns),
            market_returns=np.array(market_returns),
        )
        p_value = result.get("significance", {}).get("p_value", 1.0)
        impact = calculate_event_impact(result.get("car", 0), p_value)
        result["impact"] = impact
        return result
    except ImportError:
        return {"ticker": ticker, "event_type": event_type, "error": "event_study not available"}
