"""
ALPHA BIST — Live Scanner v1.0

Tick/event geldiğinde çalışan hafif tarayıcı.
800 hisseyi baştan indirmez.
Sadece değişen hisseyi günceller.

Pipeline:
  market.tick → state update → feature update → light scan → candidate?
"""

from typing import Dict, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class LiveScanner:
    """
    Canlı tarayıcı — her tick'te çalışır.
    Çok düşük maliyetli: sadece değişen hissenin state'ini günceller.
    """

    def __init__(self):
        self._states: Dict[str, Dict] = {}  # ticker -> state
        self._scan_count: int = 0
        self._candidates: Dict[str, float] = {}  # ticker -> score

    def process_tick(self, ticker: str, price: float, volume: int,
                     timestamp: Optional[datetime] = None) -> Optional[Dict]:
        """
        Tick işle → state güncelle → aday mı?

        Returns: None (normal) veya candidate dict (ilginç hareket)
        """
        ts = timestamp or datetime.utcnow()

        # State yoksa oluştur
        if ticker not in self._states:
            self._states[ticker] = {
                "price": 0, "prev_price": 0, "volume": 0,
                "change_pct": 0, "vol_z": 0, "momentum": 0,
                "last_update": None, "tick_count": 0,
                "prices": [], "volumes": [],
            }

        state = self._states[ticker]

        # State güncelle
        state["prev_price"] = state["price"]
        state["price"] = price
        state["volume"] = volume
        state["last_update"] = ts.isoformat()
        state["tick_count"] += 1

        # Fiyat geçmişi (son 100 tick)
        state["prices"].append(price)
        state["prices"] = state["prices"][-100:]

        # Hacim geçmişi
        state["volumes"].append(volume)
        state["volumes"] = state["volumes"][-100:]

        # Değişim hesapla (tick bazlı, günlük değil)
        if state["prev_price"] > 0:
            state["tick_change_pct"] = (price / state["prev_price"] - 1) * 100

        # Hacim z-score
        if len(state["volumes"]) >= 20:
            import numpy as np
            vols = np.array(state["volumes"][-20:])
            mean_v = np.mean(vols)
            std_v = np.std(vols)
            state["vol_z"] = (volume - mean_v) / std_v if std_v > 0 else 0

        # Tick momentum (son 5 tick — günlük momentum değil)
        if len(state["prices"]) >= 5:
            state["tick_momentum"] = (state["prices"][-1] / state["prices"][-5] - 1) * 100

        # Aday kontrolü
        candidate = self._check_candidate(ticker, state)
        if candidate:
            self._candidates[ticker] = candidate["score"]
            return candidate

        return None

    def _check_candidate(self, ticker: str, state: Dict) -> Optional[Dict]:
        """Bu hisse aday mı?"""
        vol_z = state.get("vol_z", 0)
        tick_change = abs(state.get("tick_change_pct", 0))
        tick_momentum = abs(state.get("tick_momentum", 0))

        # Kriter 1: Hacim anomalisi
        if vol_z > 3.0:
            return {
                "ticker": ticker,
                "reason": "VOLUME_ANOMALY",
                "score": min(vol_z * 20, 100),
                "vol_z": vol_z,
                "price": state["price"],
                "timestamp": state["last_update"],
            }

        # Kriter 2: Ani fiyat hareketi (tick bazlı)
        tick_change = abs(state.get("tick_change_pct", 0))
        if tick_change > 2.0:
            return {
                "ticker": ticker,
                "reason": "PRICE_SHOCK",
                "score": min(tick_change * 15, 100),
                "tick_change_pct": tick_change,
                "price": state["price"],
                "timestamp": state["last_update"],
            }

        # Kriter 3: Güçlü tick momentum
        tick_momentum = abs(state.get("tick_momentum", 0))
        if tick_momentum > 3.0 and vol_z > 1.5:
            return {
                "ticker": ticker,
                "reason": "MOMENTUM_BUILD",
                "score": min(momentum * 10 + vol_z * 10, 100),
                "momentum": momentum,
                "vol_z": vol_z,
                "price": state["price"],
                "timestamp": state["last_update"],
            }

        return None

    def get_candidates(self) -> Dict[str, float]:
        """Aktif adayları döndür."""
        return self._candidates.copy()

    def clear_candidate(self, ticker: str):
        """Adayı temizle."""
        self._candidates.pop(ticker, None)

    def get_state(self, ticker: str) -> Optional[Dict]:
        """Hisse state'ini döndür."""
        return self._states.get(ticker)

    def get_stats(self) -> Dict:
        """İstatistikler."""
        return {
            "tracked_tickers": len(self._states),
            "total_ticks": sum(s.get("tick_count", 0) for s in self._states.values()),
            "active_candidates": len(self._candidates),
        }


# Singleton
live_scanner = LiveScanner()
