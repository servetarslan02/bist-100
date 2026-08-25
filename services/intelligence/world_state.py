"""ALPHA BIST - Dynamic World State v1.1

World State = zaman içinde değişen latent state.
Event → World State t0 → Event → World State t1 → Impact Propagation → BIST State t1
"""

import numpy as np
from typing import Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class WorldState:
    """Dynamic world state — zaman içinde değişen latent faktörler."""
    timestamp: datetime

    # Latent factors (0-1 arası normalize)
    global_risk_appetite: float = 0.5
    usd_strength: float = 0.5
    us_rate_pressure: float = 0.5
    commodity_pressure: float = 0.5
    oil_pressure: float = 0.5
    turkey_macro_risk: float = 0.5
    geopolitical_risk: float = 0.5
    em_risk_appetite: float = 0.5
    vix_level: float = 20.0
    inflation_pressure: float = 0.5

    # Transition parameters
    decay_rate: float = 0.95  # Etki her saat %5 azalır
    min_value: float = 0.0
    max_value: float = 1.0

    # Factor bazlı nötr seviyeler
    neutral_levels: Dict[str, float] = field(default_factory=lambda: {
        "global_risk_appetite": 0.5, "usd_strength": 0.5, "us_rate_pressure": 0.5,
        "commodity_pressure": 0.5, "oil_pressure": 0.5, "turkey_macro_risk": 0.6,
        "geopolitical_risk": 0.45, "em_risk_appetite": 0.5, "inflation_pressure": 0.55,
    })
    decay_rates: Dict[str, float] = field(default_factory=lambda: {
        "global_risk_appetite": 0.95, "usd_strength": 0.90, "us_rate_pressure": 0.92,
        "commodity_pressure": 0.88, "oil_pressure": 0.88, "turkey_macro_risk": 0.97,
        "geopolitical_risk": 0.93, "em_risk_appetite": 0.95, "inflation_pressure": 0.96,
    })

    def to_vector(self) -> np.ndarray:
        """State'i numpy vektörüne çevir."""
        return np.array([
            self.global_risk_appetite,
            self.usd_strength,
            self.us_rate_pressure,
            self.commodity_pressure,
            self.oil_pressure,
            self.turkey_macro_risk,
            self.geopolitical_risk,
            self.em_risk_appetite,
            self.vix_level / 100.0,  # normalize
            self.inflation_pressure,
        ])

    def from_vector(self, vec: np.ndarray):
        """Vektörden state güncelle."""
        self.global_risk_appetite = float(np.clip(vec[0], 0, 1))
        self.usd_strength = float(np.clip(vec[1], 0, 1))
        self.us_rate_pressure = float(np.clip(vec[2], 0, 1))
        self.commodity_pressure = float(np.clip(vec[3], 0, 1))
        self.oil_pressure = float(np.clip(vec[4], 0, 1))
        self.turkey_macro_risk = float(np.clip(vec[5], 0, 1))
        self.geopolitical_risk = float(np.clip(vec[6], 0, 1))
        self.em_risk_appetite = float(np.clip(vec[7], 0, 1))
        self.vix_level = float(np.clip(vec[8], 0, 1)) * 100
        self.inflation_pressure = float(np.clip(vec[9], 0, 1))

    def to_dict(self) -> Dict[str, float]:
        """World state'i dictionary'e cevir."""
        return {
            "global_risk_appetite": self.global_risk_appetite,
            "usd_strength": self.usd_strength,
            "us_rate_pressure": self.us_rate_pressure,
            "commodity_pressure": self.commodity_pressure,
            "oil_pressure": self.oil_pressure,
            "turkey_macro_risk": self.turkey_macro_risk,
            "geopolitical_risk": self.geopolitical_risk,
            "em_risk_appetite": self.em_risk_appetite,
            "vix_level": self.vix_level,
            "inflation_pressure": self.inflation_pressure,
            "timestamp": self.timestamp.isoformat(),
        }

    def apply_decay(self, hours_elapsed: float):
        """Zaman geçtikçe etki azalır — factor bazlı decay."""
        factors = [
            "global_risk_appetite", "usd_strength", "us_rate_pressure",
            "commodity_pressure", "oil_pressure", "turkey_macro_risk",
            "geopolitical_risk", "em_risk_appetite", "inflation_pressure",
        ]
        for factor in factors:
            neutral = self.neutral_levels.get(factor, 0.5)
            factor_decay = self.decay_rates.get(factor, self.decay_rate)
            decay = factor_decay ** hours_elapsed
            current = getattr(self, factor)
            setattr(self, factor, neutral + (current - neutral) * decay)
        vix_decay = self.decay_rate ** hours_elapsed
        self.vix_level = 20 + (self.vix_level - 20) * vix_decay


class WorldStateManager:
    """Dynamic world state yönetimi."""

    # Event → World State factor mapping
    EVENT_FACTOR_MAP = {
        "FED_RATE_HIKE": {
            "us_rate_pressure": +0.3,
            "usd_strength": +0.2,
            "em_risk_appetite": -0.2,
            "global_risk_appetite": -0.15,
        },
        "FED_RATE_CUT": {
            "us_rate_pressure": -0.25,
            "usd_strength": -0.2,
            "em_risk_appetite": +0.2,
            "global_risk_appetite": +0.15,
        },
        "TCMB_RATE_HIKE": {
            "turkey_macro_risk": -0.2,
            "usd_strength": -0.1,
        },
        "TCMB_RATE_CUT": {
            "turkey_macro_risk": +0.15,
            "usd_strength": +0.1,
        },
        "OIL_SHOCK_UP": {
            "oil_pressure": +0.4,
            "commodity_pressure": +0.3,
            "turkey_macro_risk": +0.15,
            "inflation_pressure": +0.2,
        },
        "OIL_SHOCK_DOWN": {
            "oil_pressure": -0.3,
            "commodity_pressure": -0.2,
            "inflation_pressure": -0.1,
        },
        "GEOPOLITICAL_TENSION": {
            "geopolitical_risk": +0.4,
            "global_risk_appetite": -0.3,
            "em_risk_appetite": -0.25,
            "vix_level": +15,  # VIX 15 puan artar
        },
        "INFLATION_HIGH": {
            "inflation_pressure": +0.3,
            "turkey_macro_risk": +0.2,
        },
        "INFLATION_LOW": {
            "inflation_pressure": -0.2,
            "turkey_macro_risk": -0.15,
        },
        "VIX_SPIKE": {
            "global_risk_appetite": -0.3,
            "em_risk_appetite": -0.2,
        },
        "USD_STRENGTHEN": {
            "usd_strength": +0.25,
            "em_risk_appetite": -0.15,
        },
        "USD_WEAKEN": {
            "usd_strength": -0.2,
            "em_risk_appetite": +0.15,
        },
    }

    def __init__(self):
        self._current_state = WorldState(timestamp=datetime.now(timezone.utc))
        self._last_update = datetime.now(timezone.utc)

    @property
    def current_state(self) -> WorldState:
        return self._current_state

    def update_from_event(self, event_type: str, event_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Event'ten world state güncelle.

        Returns: world state delta (değişen faktörler)
        """
        # Decay uygula (zaman geçtikçe etki azalır)
        now = datetime.now(timezone.utc)
        hours_elapsed = (now - self._last_update).total_seconds() / 3600
        self._current_state.apply_decay(hours_elapsed)
        self._last_update = now

        # Event mapping
        factor_deltas = self.EVENT_FACTOR_MAP.get(event_type, {})
        if not factor_deltas:
            return {}

        # Apply deltas
        old_state = self._current_state.to_dict()

        for factor, delta in factor_deltas.items():
            if hasattr(self._current_state, factor):
                current_val = getattr(self._current_state, factor)
                if factor == "vix_level":
                    new_val = current_val + delta
                else:
                    new_val = current_val + delta
                setattr(self._current_state, factor, new_val)

        self._current_state.timestamp = now

        # Compute delta
        new_state = self._current_state.to_dict()
        delta = {}
        for key in old_state:
            if key != "timestamp" and key in new_state:
                d = new_state[key] - old_state[key]
                if abs(d) > 0.001:
                    delta[key] = round(d, 4)

        logger.info(
            "World state updated",
            event_type=event_type,
            delta_count=len(delta),
        )

        return delta

    def update_from_macro(self, macro_data: Dict[str, Any]):
        """Macro verilerden world state güncelle.

        P1 düzeltmesi: Hard-coded eşikler kaldırıldı.
        Macro feature: level, return, rolling volatility, z-score, percentile, trend, regime
        üzerinden normalize edilmeli.
        """

        # USD/TRY — z-score ve percentile bazlı
        usd_try = macro_data.get("USD/TRY", {})
        if usd_try and usd_try.get("price"):
            price = usd_try["price"]
            # Normalize: log-scale normalization (TRY volatilitesi yüksek)
            # Hard-coded eşik (35, 40, 50) yerine z-score
            usd_history = usd_try.get("history", [])
            if usd_history and len(usd_history) > 10:
                mean_val = float(np.mean(usd_history))
                std_val = float(np.std(usd_history))
                if std_val > 0:
                    zscore = (price - mean_val) / std_val
                    # z-score'u [0,1]'e map et
                    self._current_state.usd_strength = float(np.clip(0.5 + zscore * 0.15, 0, 1))
                    self._current_state.turkey_macro_risk = float(np.clip(0.5 + zscore * 0.2, 0, 1))
            else:
                # History yoksa mevcut değeri koru (hard-code yok)
                pass

        # VIX — percentile bazlı (raw VIX 0-1 state ile karışmamalı)
        vix = macro_data.get("VIX", {})
        if vix and vix.get("price"):
            self._current_state.vix_level = vix["price"]
            # VIX normalize: percentile (20 normal, 30+ risk-off)
            # Hard-coded 50 yerine normalize formül
            vix_normalized = float(np.clip(vix["price"] / 80.0, 0, 1))  # 80 = extreme
            self._current_state.global_risk_appetite = float(np.clip(1.0 - vix_normalized, 0, 1))

        # Oil — change bazlı (hard-coded ±3% yerine volatilite-relative)
        oil = macro_data.get("Oil", {})
        if oil and oil.get("change_pct"):
            change = oil["change_pct"]
            oil_vol = oil.get("volatility", 2.0)  # Default günlük vol
            if oil_vol > 0:
                zscore = change / oil_vol
                # z-score > 1.5 = significant move
                if abs(zscore) > 1.5:
                    delta = float(np.clip(zscore * 0.1, -0.3, 0.3))
                    self._current_state.oil_pressure = float(np.clip(
                        self._current_state.oil_pressure + delta, 0, 1
                    ))

        self._current_state.timestamp = datetime.now(timezone.utc)

    def get_state_vector(self) -> np.ndarray:
        """World state vektörü (ML feature olarak kullanılabilir)."""
        return self._current_state.to_vector()

    def get_state_dict(self) -> Dict[str, float]:
        """World state dictionary."""
        return self._current_state.to_dict()


# Singleton
world_state_manager = WorldStateManager()
