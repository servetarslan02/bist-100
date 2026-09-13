"""
ALPHA BIST — Walk-Forward Optimizasyon Motoru

Kurumsal düzeyde walk-forward optimization (WFO): Her walk-forward penceresinde
bağımsız olarak parametre optimizasyonu ve out-of-sample doğrulama yapar.

Temel Fark (Basit WFO'dan):
  - Bayesian, Genetik veya Grid Search ile entegre
  - Deflated Sharpe Ratio ile istatistiksel overfitting tespiti
  - Parametre istikrarı analizi (fold'lar arası varyans)
  - Kombinasyon sıklığı haritası (en çok seçilen parametreler)

Referans:
  - Bailey & López de Prado (2014): The Deflated Sharpe Ratio
  - Harvey & Liu (2015): Backtesting
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_N_SPLITS: int = 8
DEFAULT_TRAIN_PCTS: list[float] = [0.60, 0.70, 0.80]
DEFAULT_MIN_TRAIN_SIZE: int = 60    # Minimum eğitim seti uzunluğu (gün)
DEFAULT_MIN_TEST_SIZE: int = 20     # Minimum test seti uzunluğu (gün)
DEFAULT_SR_THRESHOLD: float = 0.0  # Minimum Sharpe Ratio kabul eşiği


@dataclass
class WFOFoldResult:
    """Tek bir WFO fold sonucu.

    Attributes:
        fold_id: Fold numarası.
        train_start: Eğitim seti başlangıç indeksi.
        train_end: Eğitim seti bitiş indeksi.
        test_start: Test seti başlangıç indeksi.
        test_end: Test seti bitiş indeksi.
        best_params: En iyi parametreler.
        in_sample_score: Eğitim seti performansı.
        out_of_sample_score: Test seti (OOS) performansı.
        is_oos_ratio: IS/OOS performans oranı (1.0 = mükemmel genelleme).
    """

    fold_id: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    best_params: dict[str, Any]
    in_sample_score: float
    out_of_sample_score: float
    is_oos_ratio: float

    def __repr__(self) -> str:
        """WFOFoldResult kısa temsili."""
        return (
            f"WFOFoldResult(fold={self.fold_id}, IS={self.in_sample_score:.4f}, "
            f"OOS={self.out_of_sample_score:.4f}, ratio={self.is_oos_ratio:.2f})"
        )


@dataclass
class ParameterStabilityReport:
    """Parametre istikrarı raporu.

    Attributes:
        param_name: Parametre adı.
        values_per_fold: Her fold için seçilen değer listesi.
        mean: Ortalama değer (sayısal parametre için).
        std: Standart sapma (sayısal parametre için).
        cv: Varyasyon katsayısı (std/mean). Düşük = istikrarlı.
        mode: En sık seçilen değer.
        stability_score: 0-100 istikrar skoru (yüksek = tutarlı).
    """

    param_name: str
    values_per_fold: list[Any]
    mean: float
    std: float
    cv: float
    mode: Any
    stability_score: float

    def __repr__(self) -> str:
        """ParameterStabilityReport kısa temsili."""
        return (
            f"ParameterStabilityReport({self.param_name!r}: "
            f"mean={self.mean:.4f}, cv={self.cv:.2f}, stability={self.stability_score:.1f})"
        )


@dataclass
class WalkForwardOptimizationResult:
    """Walk-Forward Optimizasyon ana sonucu.

    Attributes:
        fold_results: Her fold için WFOFoldResult listesi.
        mean_oos_score: Ortalama out-of-sample skor.
        std_oos_score: OOS skor standart sapması.
        mean_is_score: Ortalama in-sample skor.
        is_oos_degradation: IS → OOS performans düşüşü (%). Yüksek = overfitting.
        parameter_stability: Her parametre için istikrar raporu.
        recommended_params: Tavsiye edilen nihai parametre seti.
        deflated_sharpe: Deflated Sharpe Ratio (overfitting düzeltmesi).
        n_folds: Toplam fold sayısı.
        is_overfit: Overfitting tespiti bayrağı.
    """

    fold_results: list[WFOFoldResult]
    mean_oos_score: float
    std_oos_score: float
    mean_is_score: float
    is_oos_degradation: float
    parameter_stability: dict[str, ParameterStabilityReport]
    recommended_params: dict[str, Any]
    deflated_sharpe: float
    n_folds: int
    is_overfit: bool

    def __repr__(self) -> str:
        """WalkForwardOptimizationResult kısa temsili."""
        overfit_str = "OVERFIT⚠️" if self.is_overfit else "OK✅"
        return (
            f"WalkForwardOptimizationResult(folds={self.n_folds}, "
            f"OOS={self.mean_oos_score:.4f}±{self.std_oos_score:.4f}, "
            f"degrade={self.is_oos_degradation:.1f}%, {overfit_str})"
        )


class WalkForwardOptimizer:
    """Walk-Forward Aware Optimizasyon Motoru.

    Herhangi bir optimizasyon motorunu (Bayesian, Genetik, Grid) alarak
    walk-forward pencerelerinde çalıştırır. Her fold bağımsız olarak
    optimize edilir; parametre istikrarı ve IS/OOS oranı hesaplanır.
    """

    def __init__(
        self,
        n_splits: int = DEFAULT_N_SPLITS,
        train_pct: float = 0.70,
        min_train_size: int = DEFAULT_MIN_TRAIN_SIZE,
        min_test_size: int = DEFAULT_MIN_TEST_SIZE,
        sr_threshold: float = DEFAULT_SR_THRESHOLD,
    ) -> None:
        """WalkForwardOptimizer başlatıcı.

        Args:
            n_splits: Walk-forward fold sayısı.
            train_pct: Her fold içinde eğitim seti oranı.
            min_train_size: Minimum eğitim seti büyüklüğü.
            min_test_size: Minimum test seti büyüklüğü.
            sr_threshold: Minimum OOS Sharpe Ratio kabul eşiği.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if n_splits < 2:
            raise ValueError(f"n_splits >= 2 olmalıdır: {n_splits}")
        if not (0.0 < train_pct < 1.0):
            raise ValueError(f"train_pct (0,1) aralığında olmalıdır: {train_pct}")

        self.n_splits = n_splits
        self.train_pct = train_pct
        self.min_train_size = min_train_size
        self.min_test_size = min_test_size
        self.sr_threshold = sr_threshold

    def __repr__(self) -> str:
        """WalkForwardOptimizer kısa temsili."""
        return (
            f"WalkForwardOptimizer(splits={self.n_splits}, "
            f"train_pct={self.train_pct:.0%}, min_train={self.min_train_size})"
        )

    def _generate_folds(self, n: int) -> list[tuple[int, int, int, int]]:
        """Walk-forward pencere indekslerini üretir.

        Args:
            n: Toplam veri uzunluğu.

        Returns:
            (train_start, train_end, test_start, test_end) tuple listesi.
        """
        folds: list[tuple[int, int, int, int]] = []
        fold_size = n // self.n_splits

        for i in range(self.n_splits):
            test_start = (i + 1) * fold_size
            if i == 0:
                train_start = 0
            else:
                train_start = max(0, test_start - int(fold_size / (1 - self.train_pct)))

            train_end = test_start
            test_end = min(n, test_start + fold_size)

            if train_end - train_start < self.min_train_size:
                continue
            if test_end - test_start < self.min_test_size:
                continue
            if test_end > n:
                break

            folds.append((train_start, train_end, test_start, test_end))

        return folds

    def _compute_parameter_stability(
        self,
        fold_results: list[WFOFoldResult],
    ) -> dict[str, ParameterStabilityReport]:
        """Fold'lar arası parametre istikrarını analiz eder.

        Args:
            fold_results: Tüm fold sonuçları.

        Returns:
            Her parametre için ParameterStabilityReport sözlüğü.
        """
        if not fold_results:
            return {}

        all_params = fold_results[0].best_params.keys()
        reports: dict[str, ParameterStabilityReport] = {}

        for param in all_params:
            values = [r.best_params.get(param) for r in fold_results if param in r.best_params]
            if not values:
                continue

            numeric_values = [v for v in values if isinstance(v, (int, float))]

            if numeric_values:
                mean = float(np.mean(numeric_values))
                std = float(np.std(numeric_values))
                cv = std / abs(mean) if abs(mean) > 1e-10 else float("inf")
                # Varyasyon katsayısı 0.1'den az ise istikrarlı (0.1 → score 90)
                stability = float(np.clip(100.0 - cv * 100.0, 0.0, 100.0))
                unique, counts = np.unique(numeric_values, return_counts=True)
                mode = float(unique[int(np.argmax(counts))])
            else:
                mean, std, cv = 0.0, 0.0, float("inf")
                unique_cat, counts_cat = np.unique(values, return_counts=True)
                mode = unique_cat[int(np.argmax(counts_cat))]
                # Kategorik: mod frekansına göre istikrar
                stability = float(max(counts_cat) / len(values) * 100.0)

            reports[param] = ParameterStabilityReport(
                param_name=param,
                values_per_fold=values,
                mean=mean,
                std=std,
                cv=cv,
                mode=mode,
                stability_score=stability,
            )

        return reports

    def _compute_deflated_sharpe(self, oos_scores: list[float], n_trials: int) -> float:
        """Deflated Sharpe Ratio hesaplar (overfitting düzeltmesi).

        Çoklu test sorunundan kaynaklanan istatistiksel şişkinliği düzeltir.
        Yüksek n_trials ile düşük OOS değişkenliği kombine edilince SR düşer.

        Args:
            oos_scores: OOS skor listesi.
            n_trials: Toplam denenen parametre kombinasyonu sayısı.

        Returns:
            Deflated Sharpe Ratio (negatif = istatistiksel olarak anlamsız).
        """
        if len(oos_scores) < 2 or n_trials <= 1:
            return float(np.mean(oos_scores)) if oos_scores else 0.0

        sr = float(np.mean(oos_scores)) / max(float(np.std(oos_scores)), 1e-10)

        # Bonferroni düzeltmesi: çoklu test cezası
        # E[max(SR)] ≈ (1 - γ)Z^{-1}(1 - 1/n) + γZ^{-1}(1 - 1/(n*e))
        gamma = 0.5772  # Euler-Mascheroni sabiti
        try:
            z1 = _norm_ppf(1.0 - 1.0 / n_trials)
            z2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
            expected_max = (1.0 - gamma) * z1 + gamma * z2
        except (ValueError, ZeroDivisionError):
            expected_max = 0.0

        deflated = sr - expected_max
        return float(deflated)

    def optimize(
        self,
        optimizer_fn: Callable[[np.ndarray], dict[str, Any]],
        oos_eval_fn: Callable[[dict[str, Any], np.ndarray], float],
        data: np.ndarray,
        n_trials_per_fold: int = 100,
    ) -> WalkForwardOptimizationResult:
        """Walk-Forward Optimizasyon ana döngüsü.

        Args:
            optimizer_fn: (train_data) → {best_params, is_score, ...} döndüren fonksiyon.
                          Herhangi bir optimizatör (Bayesian, Genetik, Grid) wrap edilebilir.
            oos_eval_fn: (params, oos_data) → oos_score döndüren fonksiyon.
            data: Tüm zaman serisi dizisi.
            n_trials_per_fold: Her fold için denenen kombinasyon sayısı (DSR için).

        Returns:
            Tam WFO sonucunu içeren WalkForwardOptimizationResult.

        Raises:
            ValueError: data çok kısaysa.
        """
        n = len(data)
        min_required = self.n_splits * (self.min_train_size + self.min_test_size)
        if n < min_required:
            raise ValueError(
                f"Veri çok kısa ({n}). Minimum {min_required} gerekli."
            )

        folds = self._generate_folds(n)
        if not folds:
            raise ValueError("Geçerli fold üretilemedi. Veri daha uzun olmalı.")

        fold_results: list[WFOFoldResult] = []

        logger.info(
            "Walk-forward optimizasyon başlatıldı.",
            n=n,
            folds=len(folds),
        )

        for fold_id, (tr_start, tr_end, ts_start, ts_end) in enumerate(folds):
            train_data = data[tr_start:tr_end]
            test_data = data[ts_start:ts_end]

            try:
                opt_result = optimizer_fn(train_data)
                best_params = opt_result.get("best_params", opt_result)
                is_score = float(opt_result.get("is_score", 0.0))
            except Exception as e:
                logger.warning("Fold optimizasyonu başarısız.", fold=fold_id, hata=str(e))
                continue

            try:
                oos_score = oos_eval_fn(best_params, test_data)
            except Exception as e:
                logger.warning("OOS değerlendirme başarısız.", fold=fold_id, hata=str(e))
                oos_score = 0.0

            is_oos_ratio = oos_score / is_score if abs(is_score) > 1e-10 else 1.0

            fold_results.append(
                WFOFoldResult(
                    fold_id=fold_id,
                    train_start=tr_start,
                    train_end=tr_end,
                    test_start=ts_start,
                    test_end=ts_end,
                    best_params=best_params if isinstance(best_params, dict) else {},
                    in_sample_score=is_score,
                    out_of_sample_score=oos_score,
                    is_oos_ratio=is_oos_ratio,
                )
            )

            logger.info(
                "Fold tamamlandı.",
                fold=fold_id,
                is_score=round(is_score, 4),
                oos_score=round(oos_score, 4),
            )

        if not fold_results:
            logger.error("Hiç geçerli fold sonucu yok.")
            return WalkForwardOptimizationResult(
                fold_results=[],
                mean_oos_score=0.0,
                std_oos_score=0.0,
                mean_is_score=0.0,
                is_oos_degradation=0.0,
                parameter_stability={},
                recommended_params={},
                deflated_sharpe=0.0,
                n_folds=0,
                is_overfit=True,
            )

        oos_scores = [r.out_of_sample_score for r in fold_results]
        is_scores = [r.in_sample_score for r in fold_results]

        mean_oos = float(np.mean(oos_scores))
        std_oos = float(np.std(oos_scores))
        mean_is = float(np.mean(is_scores))
        degradation = ((mean_is - mean_oos) / abs(mean_is) * 100.0) if abs(mean_is) > 1e-10 else 0.0

        stability = self._compute_parameter_stability(fold_results)

        # Tavsiye edilen parametreler: en yüksek OOS scorlu fold
        best_fold = max(fold_results, key=lambda r: r.out_of_sample_score)
        recommended = best_fold.best_params

        deflated_sr = self._compute_deflated_sharpe(oos_scores, n_trials_per_fold * len(folds))

        is_overfit = degradation > 50.0 or deflated_sr < self.sr_threshold

        logger.info(
            "Walk-forward optimizasyon tamamlandı.",
            mean_oos=round(mean_oos, 4),
            std_oos=round(std_oos, 4),
            degradation=round(degradation, 2),
            deflated_sr=round(deflated_sr, 4),
            overfit=is_overfit,
        )

        return WalkForwardOptimizationResult(
            fold_results=fold_results,
            mean_oos_score=mean_oos,
            std_oos_score=std_oos,
            mean_is_score=mean_is,
            is_oos_degradation=degradation,
            parameter_stability=stability,
            recommended_params=recommended,
            deflated_sharpe=deflated_sr,
            n_folds=len(fold_results),
            is_overfit=is_overfit,
        )


def _norm_ppf(p: float) -> float:
    """Normal dağılım yüzdelik noktası (scipy olmadan yaklaşık).

    Args:
        p: Yüzdelik değeri (0-1).

    Returns:
        Yaklaşık normal dağılım quantile değeri.
    """
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    # Rational approximation (Abramowitz & Stegun)
    c = [2.515517, 0.802853, 0.010328]
    d = [1.432788, 0.189269, 0.001308]
    if p < 0.5:
        t = math.sqrt(-2.0 * math.log(p))
        sign = -1.0
    else:
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        sign = 1.0
    numerator = c[0] + c[1] * t + c[2] * t**2
    denominator = 1.0 + d[0] * t + d[1] * t**2 + d[2] * t**3
    return sign * (t - numerator / denominator)


__all__: list[str] = [
    "ParameterStabilityReport",
    "WFOFoldResult",
    "WalkForwardOptimizationResult",
    "WalkForwardOptimizer",
    "walk_forward_optimizer",
]

# Singleton
walk_forward_optimizer = WalkForwardOptimizer()
