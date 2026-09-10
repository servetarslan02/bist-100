"""ALPHA BIST — Event Impact Decay Analysis.

Event etkisinin zamanla nasıl azaldığını analiz eder.
Exponential decay modeli ile half-life hesaplama.
"""

from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# --- Sabitler ---
DEFAULT_DECAY_RATE: float = 0.0
DEFAULT_R_SQUARED: float = 0.0
MIN_VALID_POINTS_FOR_FIT: int = 2
ZERO_THRESHOLD: float = 1e-10

# Decay pattern eşikleri
PERSISTENCE_HIGH: float = 0.8
PERSISTENCE_MODERATE: float = 0.5
PERSISTENCE_LOW: float = 0.2


class EventImpactDecay:
    """Event etkisinin zamanla azalma analizi."""

    def _validate_ar_series(self, ar_series: Any, param_name: str = "ar_series") -> np.ndarray:
        """AR serisi doğrulama ve ndarray'e dönüştürme.

        Args:
            ar_series: Kontrol edilecek AR serisi (np.ndarray, list veya tuple)
            param_name: Parametre adı (hata mesajı için)

        Returns:
            Doğrulanmış numpy array

        Raises:
            TypeError: Desteklenmeyen tip ise
            ValueError: Boş array ise veya NaN/Inf içeriyorsa
        """
        if isinstance(ar_series, (list, tuple)):
            ar_series = np.asarray(ar_series, dtype=float)
        if not isinstance(ar_series, np.ndarray):
            raise TypeError(f"{param_name} numpy.ndarray, list veya tuple olmalı, alınan: {type(ar_series).__name__}")
        if ar_series.size == 0:
            raise ValueError(f"{param_name} boş olamaz")
        if not np.all(np.isfinite(ar_series)):
            raise ValueError(f"{param_name} NaN veya Inf değerler içeriyor")
        return ar_series

    def _validate_event_day_idx(self, event_day_idx: int, n: int) -> None:
        """Event day indeks aralık kontrolü.

        Args:
            event_day_idx: Kontrol edilecek indeks
            n: Seri uzunluğu

        Raises:
            ValueError: İndeks aralık dışındaysa
        """
        if not isinstance(event_day_idx, int):
            raise TypeError(f"event_day_idx tamsayı olmalı, alınan: {type(event_day_idx).__name__}")
        if event_day_idx < 0 or event_day_idx >= n:
            raise ValueError(
                f"event_day_idx [0, {n - 1}] aralığında olmalı, alınan: {event_day_idx}"
            )

    def calculate_decay(
        self, ar_series: np.ndarray, event_day_idx: int = 0
    ) -> dict[str, Any]:
        """Event etkisinin zamanla nasıl azaldığını hesapla.

        Exponential decay: |AR(t)| = A × exp(-λ × t)
        Half-life: t_half = ln(2) / λ

        Args:
            ar_series: AR serisi (event window boyunca)
            event_day_idx: Event günü indeksi (varsayılan: 0)

        Returns:
            Dict with decay_rate, half_life, day_impacts, fit_quality

        Raises:
            TypeError: Parametre tipleri uygun değilse
            ValueError: Değerler geçersiz ise
        """
        ar_series = self._validate_ar_series(ar_series)
        self._validate_event_day_idx(event_day_idx, len(ar_series))

        if len(ar_series) < MIN_VALID_POINTS_FOR_FIT:
            logger.warning(
                "azalma_yetersiz_veri",
                seri_uzunlugu=len(ar_series),
                gereken_minimum=MIN_VALID_POINTS_FOR_FIT,
            )
            return {
                "decay_rate": DEFAULT_DECAY_RATE,
                "half_life_days": float("inf"),
                "day_impacts": {},
                "fit_r_squared": DEFAULT_R_SQUARED,
                "pattern": "YETERSIZ_VERI",
            }

        abs_ar = np.abs(ar_series)
        n = len(abs_ar)

        # Gün bazlı etkiler
        day_impacts: dict[int, float] = {}
        for i, val in enumerate(abs_ar):
            day_offset = i - event_day_idx
            day_impacts[day_offset] = round(float(val), 6)

        # Exponential decay fit (log-linear regression)
        # Tek seferde pozitif değerlerin indekslerini bul (performans)
        valid_indices = np.where(abs_ar > ZERO_THRESHOLD)[0]
        if len(valid_indices) < MIN_VALID_POINTS_FOR_FIT:
            logger.warning(
                "azalma_pozitif_deger_yok",
                pozitif_sayisi=len(valid_indices),
            )
            return {
                "decay_rate": DEFAULT_DECAY_RATE,
                "half_life_days": float("inf"),
                "day_impacts": day_impacts,
                "fit_r_squared": DEFAULT_R_SQUARED,
                "pattern": "AZALMA_YOK",
            }

        log_ar = np.log(abs_ar[valid_indices])
        valid_days = valid_indices.astype(float)

        # Log-linear regression: log(|AR|) = log(A) - λ × t
        try:
            coeffs = np.polyfit(valid_days, log_ar, 1)
            decay_rate = -coeffs[0]  # λ
            # Negatif decay_rate → etki artıyor demektir, half-life tanımsız
            if decay_rate > 0:
                half_life = np.log(2) / decay_rate
            else:
                half_life = float("inf")
                logger.warning(
                    "azalma_negatif_decay_rate",
                    decay_rate=round(float(decay_rate), 4),
                    aciklama="Etki zamanla artıyor, half-life hesaplanamaz",
                )

            # R² hesapla
            log_pred = np.polyval(coeffs, valid_days)
            ss_res = np.sum((log_ar - log_pred) ** 2)
            ss_tot = np.sum((log_ar - np.mean(log_ar)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else DEFAULT_R_SQUARED

        except np.linalg.LinAlgError as exc:
            logger.warning(
                "azalma_regresyon_hatasi",
                hata=str(exc),
            )
            decay_rate = DEFAULT_DECAY_RATE
            half_life = float("inf")
            r_squared = DEFAULT_R_SQUARED

        # Decay pattern
        pattern = self._classify_decay_pattern(abs_ar, event_day_idx)

        result: dict[str, Any] = {
            "decay_rate": round(float(decay_rate), 4),
            "half_life_days": round(float(half_life), 1) if half_life != float("inf") else "sonsuz",
            "day_impacts": day_impacts,
            "fit_r_squared": round(float(r_squared), 4),
            "pattern": pattern,
            "initial_impact": round(float(abs_ar[event_day_idx]) if event_day_idx < n else 0, 6),
            "final_impact": round(float(abs_ar[-1]), 6),
            "persistence": round(
                float(abs_ar[-1] / abs_ar[event_day_idx]) if abs_ar[event_day_idx] > 0 else 0, 4
            ),
        }

        logger.debug(
            "azalma_hesaplandi",
            decay_rate=result["decay_rate"],
            half_life_days=result["half_life_days"],
            pattern=pattern,
            fit_r_squared=result["fit_r_squared"],
        )

        return result

    def calculate_decay_batch(
        self, ar_series_list: list[np.ndarray]
    ) -> dict[str, Any]:
        """Birden fazla event için toplu decay analizi.

        Args:
            ar_series_list: AR serisi listesi

        Returns:
            Dict with average decay stats

        Raises:
            TypeError: Liste değilse veya elemanlar numpy array değilse
            ValueError: Boş liste ise veya elemanlar geçersiz ise
        """
        if not isinstance(ar_series_list, list):
            raise TypeError(f"ar_series_list liste olmalı, alınan: {type(ar_series_list).__name__}")
        if len(ar_series_list) == 0:
            raise ValueError("ar_series_list boş olamaz")

        decays: list[dict[str, Any]] = []
        for idx, ar_series in enumerate(ar_series_list):
            if isinstance(ar_series, (list, tuple)):
                ar_series = np.asarray(ar_series, dtype=float)
            if not isinstance(ar_series, np.ndarray):
                raise TypeError(
                    f"ar_series_list[{idx}] numpy.ndarray, list veya tuple olmalı, alınan: {type(ar_series).__name__}"
                )
            if ar_series.size == 0:
                raise ValueError(f"ar_series_list[{idx}] boş olamaz")
            decay = self.calculate_decay(ar_series)
            decays.append(decay)

        # Ortalama decay rate (pozitif olanlardan)
        rates = [d["decay_rate"] for d in decays if d["decay_rate"] > 0]
        half_lives = [
            d["half_life_days"]
            for d in decays
            if isinstance(d["half_life_days"], (int, float)) and d["half_life_days"] != float("inf")
        ]

        summary: dict[str, Any] = {
            "average_decay_rate": round(float(np.mean(rates)), 4) if rates else DEFAULT_DECAY_RATE,
            "average_half_life": round(float(np.mean(half_lives)), 1) if half_lives else "sonsuz",
            "n_events": len(decays),
            "pattern_distribution": self._pattern_distribution(decays),
            "individual_decays": decays,
        }

        logger.debug(
            "azalma_toplu_hesaplandi",
            n_events=summary["n_events"],
            average_decay_rate=summary["average_decay_rate"],
            average_half_life=summary["average_half_life"],
        )

        return summary

    def _classify_decay_pattern(self, abs_ar: np.ndarray, event_day_idx: int) -> str:
        """Decay pattern sınıflandırması.

        Args:
            abs_ar: Mutlak AR serisi
            event_day_idx: Event günü indeksi

        Returns:
            Pattern adı (Türkçe)
        """
        n = len(abs_ar)
        if n < 3:
            return "YETERSIZ_VERI"

        event_impact = abs_ar[event_day_idx] if event_day_idx < n else 0
        final_impact = abs_ar[-1]
        persistence = final_impact / event_impact if event_impact > 0 else 0

        if persistence > PERSISTENCE_HIGH:
            return "KALICI"
        elif persistence > PERSISTENCE_MODERATE:
            return "YAVAS_AZALMA"
        elif persistence > PERSISTENCE_LOW:
            return "ORTA_AZALMA"
        else:
            return "HIZLI_AZALMA"

    def _pattern_distribution(self, decays: list[dict[str, Any]]) -> dict[str, int]:
        """Pattern dağılımı.

        Args:
            decays: Decay sonuçları listesi

        Returns:
            Pattern → adet sözlüğü
        """
        patterns: dict[str, int] = {}
        for d in decays:
            p = d.get("pattern", "BILINMEYEN")
            patterns[p] = patterns.get(p, 0) + 1
        return patterns
