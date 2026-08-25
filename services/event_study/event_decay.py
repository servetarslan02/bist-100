"""ALPHA BIST — Event Impact Decay Analysis.

Event etkisinin zamanla nasıl azaldığını analiz eder.
Exponential decay modeli ile half-life hesaplama.
"""
import numpy as np
from typing import Dict, List, Any
import structlog

logger = structlog.get_logger()


class EventImpactDecay:
    """Event etkisinin zamanla azalma analizi."""

    def calculate_decay(
        self, ar_series: np.ndarray, event_day_idx: int = 0
    ) -> Dict[str, Any]:
        """Event etkisinin zamanla nasıl azaldığını hesapla.

        Exponential decay: |AR(t)| = A × exp(-λ × t)
        Half-life: t_half = ln(2) / λ

        Args:
            ar_series: AR serisi (event window boyunca)
            event_day_idx: Event günü indeksi (varsayılan: 0)

        Returns:
            Dict with decay_rate, half_life, day_impacts, fit_quality
        """
        if len(ar_series) < 2:
            return {
                "decay_rate": 0.0,
                "half_life_days": float("inf"),
                "day_impacts": {},
                "fit_r_squared": 0.0,
                "pattern": "INSUFFICIENT_DATA",
            }

        abs_ar = np.abs(ar_series)
        n = len(abs_ar)

        # Gün bazlı etkiler
        day_impacts = {}
        for i, val in enumerate(abs_ar):
            day_offset = i - event_day_idx
            day_impacts[day_offset] = round(float(val), 6)

        # Exponential decay fit (log-linear regression)
        days = np.arange(n, dtype=float)

        # Sadece pozitif değerlerle çalış
        valid_mask = abs_ar > 1e-10
        if np.sum(valid_mask) < 2:
            return {
                "decay_rate": 0.0,
                "half_life_days": float("inf"),
                "day_impacts": day_impacts,
                "fit_r_squared": 0.0,
                "pattern": "NO_DECAY",
            }

        log_ar = np.log(abs_ar[valid_mask])
        valid_days = days[valid_mask]

        # Log-linear regression: log(|AR|) = log(A) - λ × t
        try:
            coeffs = np.polyfit(valid_days, log_ar, 1)
            decay_rate = -coeffs[0]  # λ
            half_life = np.log(2) / decay_rate if decay_rate > 0 else float("inf")

            # R² hesapla
            log_pred = np.polyval(coeffs, valid_days)
            ss_res = np.sum((log_ar - log_pred) ** 2)
            ss_tot = np.sum((log_ar - np.mean(log_ar)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        except Exception:
            decay_rate = 0.0
            half_life = float("inf")
            r_squared = 0.0

        # Decay pattern
        pattern = self._classify_decay_pattern(abs_ar, event_day_idx)

        result = {
            "decay_rate": round(float(decay_rate), 4),
            "half_life_days": round(float(half_life), 1) if half_life != float("inf") else "infinite",
            "day_impacts": day_impacts,
            "fit_r_squared": round(float(r_squared), 4),
            "pattern": pattern,
            "initial_impact": round(float(abs_ar[event_day_idx]) if event_day_idx < n else 0, 6),
            "final_impact": round(float(abs_ar[-1]), 6),
            "persistence": round(float(abs_ar[-1] / abs_ar[event_day_idx]) if abs_ar[event_day_idx] > 0 else 0, 4),
        }

        return result

    def calculate_decay_batch(
        self, ar_series_list: List[np.ndarray]
    ) -> Dict[str, Any]:
        """Birden fazla event için toplu decay analizi.

        Args:
            ar_series_list: AR serisi listesi

        Returns:
            Dict with average decay stats
        """
        decays = []
        for ar_series in ar_series_list:
            decay = self.calculate_decay(ar_series)
            decays.append(decay)

        # Ortalama decay rate
        rates = [d["decay_rate"] for d in decays if d["decay_rate"] > 0]
        half_lives = [
            d["half_life_days"]
            for d in decays
            if isinstance(d["half_life_days"], (int, float)) and d["half_life_days"] != float("inf")
        ]

        return {
            "average_decay_rate": round(float(np.mean(rates)), 4) if rates else 0.0,
            "average_half_life": round(float(np.mean(half_lives)), 1) if half_lives else "infinite",
            "n_events": len(decays),
            "pattern_distribution": self._pattern_distribution(decays),
            "individual_decays": decays,
        }

    def _classify_decay_pattern(
        self, abs_ar: np.ndarray, event_day_idx: int
    ) -> str:
        """Decay pattern sınıflandırması."""
        n = len(abs_ar)
        if n < 3:
            return "INSUFFICIENT_DATA"

        # Event günü etkisi
        event_impact = abs_ar[event_day_idx] if event_day_idx < n else 0

        # Son gün etkisi
        final_impact = abs_ar[-1]

        # Persistence ratio
        persistence = final_impact / event_impact if event_impact > 0 else 0

        if persistence > 0.8:
            return "PERSISTENT"  # Etki azalmıyor
        elif persistence > 0.5:
            return "SLOW_DECAY"  # Yavaş azalma
        elif persistence > 0.2:
            return "MODERATE_DECAY"  # Orta hızda azalma
        else:
            return "FAST_DECAY"  # Hızlı azalma

    def _pattern_distribution(self, decays: List[Dict]) -> Dict[str, int]:
        """Pattern dağılımı."""
        patterns = {}
        for d in decays:
            p = d.get("pattern", "UNKNOWN")
            patterns[p] = patterns.get(p, 0) + 1
        return patterns
