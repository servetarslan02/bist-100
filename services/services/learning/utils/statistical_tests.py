"""
ALPHA BIST — Statistical Tests for Learning System

Merkezi istatistiksel test fonksiyonları.
Drift detection, A/B test, calibration için temel.

KURAL: Tekrar kullanılabilir, test edilebilir, production-ready.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class PSIResult:
    """PSI sonucu."""
    psi: float
    drift_detected: bool
    severity: str  # STABLE, WARNING, ALERT, CRITICAL
    bin_details: List[Dict] = field(default_factory=list)


@dataclass
class KSTestResult:
    """KS test sonucu."""
    statistic: float
    p_value: float
    drift_detected: bool
    interpretation: str


@dataclass
class PageHinkleyResult:
    """Page-Hinkley test sonucu."""
    drift_detected: bool
    max_deviation: float
    threshold: float
    change_point_index: Optional[int] = None


@dataclass
class ADWINResult:
    """ADWIN test sonucu."""
    drift_detected: bool
    window_size: int
    t_statistic: float
    p_value: float


@dataclass
class WelchTTestResult:
    """Welch's t-test sonucu."""
    t_statistic: float
    p_value: float
    significant: bool
    interpretation: str


class StatisticalTests:
    """Merkezi istatistiksel test fonksiyonları."""

    # ===================== PSI =====================

    @staticmethod
    def compute_psi(
        expected: np.ndarray,
        actual: np.ndarray,
        bins: int = 10,
        eps: float = 1e-4,
    ) -> PSIResult:
        """Population Stability Index (PSI) hesapla.

        PSI < 0.1: Stabil
        PSI 0.1-0.2: Uyarı
        PSI 0.2-0.5: Alarm
        PSI > 0.5: Kritik

        Args:
            expected: Beklenen dağılım (baseline)
            actual: Gerçek dağılım (current)
            bins: Bin sayısı (default 10)
            eps: Sıfır bölme önleme

        Returns:
            PSIResult
        """
        expected = np.asarray(expected, dtype=np.float64)
        actual = np.asarray(actual, dtype=np.float64)

        # Geçersiz değerleri temizle
        expected = expected[np.isfinite(expected)]
        actual = actual[np.isfinite(actual)]

        if len(expected) < 10 or len(actual) < 10:
            logger.warning("PSI: Insufficient data", expected=len(expected), actual=len(actual))
            return PSIResult(psi=0.0, drift_detected=False, severity="INSUFFICIENT_DATA")

        # Percentile-based breakpoints (daha robust)
        breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
        breakpoints[0] = -np.inf
        breakpoints[-1] = np.inf

        # Histogram hesapla
        expected_counts = np.histogram(expected, breakpoints)[0].astype(np.float64)
        actual_counts = np.histogram(actual, breakpoints)[0].astype(np.float64)

        # Normalize
        expected_pct = expected_counts / len(expected)
        actual_pct = actual_counts / len(actual)

        # Sıfır bölme önleme
        expected_pct = np.clip(expected_pct, eps, None)
        actual_pct = np.clip(actual_pct, eps, None)

        # PSI hesapla
        psi_values = (actual_pct - expected_pct) * np.log(actual_pct / expected_pct)
        psi = float(np.sum(psi_values))

        # Severity belirle
        if psi < 0.1:
            severity = "STABLE"
        elif psi < 0.2:
            severity = "WARNING"
        elif psi < 0.5:
            severity = "ALERT"
        else:
            severity = "CRITICAL"

        # Bin detayları
        bin_details = []
        for i in range(len(expected_pct)):
            bin_details.append({
                "bin_index": i,
                "expected_pct": round(float(expected_pct[i]), 4),
                "actual_pct": round(float(actual_pct[i]), 4),
                "psi_contribution": round(float(psi_values[i]), 4),
            })

        return PSIResult(
            psi=round(psi, 4),
            drift_detected=psi >= 0.2,
            severity=severity,
            bin_details=bin_details,
        )

    # ===================== KS TEST =====================

    @staticmethod
    def ks_test(
        sample1: np.ndarray,
        sample2: np.ndarray,
        alpha: float = 0.05,
    ) -> KSTestResult:
        """Kolmogorov-Smirnov iki örnek testi.

        H0: İki örnek aynı dağılımdan geliyor.
        H1: Farklı dağılımlardan geliyorlar.

        Args:
            sample1: Birinci örnek
            sample2: İkinci örnek
            alpha: Anlamlılık düzeyi

        Returns:
            KSTestResult
        """
        from scipy import stats

        sample1 = np.asarray(sample1, dtype=np.float64)
        sample2 = np.asarray(sample2, dtype=np.float64)

        sample1 = sample1[np.isfinite(sample1)]
        sample2 = sample2[np.isfinite(sample2)]

        if len(sample1) < 5 or len(sample2) < 5:
            return KSTestResult(
                statistic=0.0, p_value=1.0, drift_detected=False,
                interpretation="Insufficient data"
            )

        ks_result = stats.ks_2samp(sample1, sample2)
        ks_stat = ks_result.statistic
        p_value = ks_result.pvalue

        drift_detected = p_value < alpha

        if p_value < 0.01:
            interpretation = "Highly significant difference (p < 0.01)"
        elif p_value < 0.05:
            interpretation = "Significant difference (p < 0.05)"
        elif p_value < 0.10:
            interpretation = "Marginal difference (p < 0.10)"
        else:
            interpretation = "No significant difference"

        return KSTestResult(
            statistic=round(float(ks_stat), 4),
            p_value=round(float(p_value), 4),
            drift_detected=bool(drift_detected),
            interpretation=interpretation,
        )

    # ===================== PAGE-HINKLEY =====================

    @staticmethod
    def page_hinkley_test(
        data: np.ndarray,
        threshold: float = 0.5,
        delta: float = 0.005,
    ) -> PageHinkleyResult:
        """Page-Hinkley drift testi.

        Kümülatif sapma hesaplayarak drift tespit eder.
        Ani değişimleri tespit etmek için kullanılır.

        Args:
            data: Test verisi
            threshold: Eşik değeri
            delta: Ortalama değişim toleransı

        Returns:
            PageHinkleyResult
        """
        data = np.asarray(data, dtype=np.float64)
        data = data[np.isfinite(data)]

        if len(data) < 10:
            return PageHinkleyResult(
                drift_detected=False, max_deviation=0.0,
                threshold=threshold, change_point_index=None
            )

        # Kümülatif ortalama
        cumulative_mean = np.cumsum(data) / np.arange(1, len(data) + 1)

        # Kümülatif sapma
        cumulative_deviation = np.cumsum(data - cumulative_mean + delta)

        # M_t = X_t - cumulative_mean_t + delta
        m_t = data - cumulative_mean + delta

        # Kümülatif minimum
        cumulative_min = np.minimum.accumulate(cumulative_deviation)

        # Page-Hinkley statistic
        ph_stat = cumulative_deviation - cumulative_min

        # Maksimum sapma
        max_deviation = float(np.max(ph_stat))
        change_point = int(np.argmax(ph_stat)) if max_deviation > threshold else None

        return PageHinkleyResult(
            drift_detected=max_deviation > threshold,
            max_deviation=round(max_deviation, 4),
            threshold=round(threshold, 4),
            change_point_index=change_point,
        )

    # ===================== ADWIN =====================

    @staticmethod
    def adwin_test(
        data: np.ndarray,
        delta: float = 0.002,
        min_window: int = 10,
    ) -> ADWINResult:
        """ADWIN (Adaptive Windowing) drift testi.

        Adaptif pencere boyutu kullanarak drift tespit eder.
        Pencere boyutu otomatik olarak ayarlanır.

        Args:
            data: Test verisi
            delta: Anlamlılık düzeyi
            min_window: Minimum pencere boyutu

        Returns:
            ADWINResult
        """
        from scipy import stats

        data = np.asarray(data, dtype=np.float64)
        data = data[np.isfinite(data)]

        if len(data) < min_window * 2:
            return ADWINResult(
                drift_detected=False, window_size=0,
                t_statistic=0.0, p_value=1.0
            )

        # Adaptif pencere boyutu
        best_drift = False
        best_window = 0
        best_t = 0.0
        best_p = 1.0

        # Farklı pencere boyutlarını dene
        for window_size in range(min_window, len(data) // 2 + 1, max(1, len(data) // 20)):
            left_window = data[:window_size]
            right_window = data[-window_size:]

            t_result = stats.ttest_ind(left_window, right_window)
            t_stat = t_result.statistic
            p_value = t_result.pvalue

            if p_value < delta and abs(t_stat) > abs(best_t):
                best_drift = True
                best_window = window_size
                best_t = t_stat
                best_p = p_value

        return ADWINResult(
            drift_detected=best_drift,
            window_size=best_window,
            t_statistic=round(float(best_t), 4),
            p_value=round(float(best_p), 4),
        )

    # ===================== Z-SCORE =====================

    @staticmethod
    def zscore_test(
        baseline_mean: float,
        baseline_std: float,
        current_value: float,
        warning_threshold: float = 2.5,
        critical_threshold: float = 3.5,
    ) -> Dict[str, Any]:
        """Z-score drift testi.

        Args:
            baseline_mean: Baseline ortalama
            baseline_std: Baseline standart sapma
            current_value: Mevcut değer
            warning_threshold: Uyarı eşiği
            critical_threshold: Kritik eşik

        Returns:
            Z-score sonucu
        """
        if baseline_std <= 0:
            baseline_std = 0.001  # Sıfır bölme önleme

        z_score = abs(current_value - baseline_mean) / baseline_std

        if z_score >= critical_threshold:
            severity = "CRITICAL"
        elif z_score >= warning_threshold:
            severity = "WARNING"
        else:
            severity = "NORMAL"

        return {
            "z_score": round(float(z_score), 4),
            "baseline_mean": round(float(baseline_mean), 4),
            "baseline_std": round(float(baseline_std), 4),
            "current_value": round(float(current_value), 4),
            "severity": severity,
            "drift_detected": z_score >= warning_threshold,
        }

    # ===================== WELCH'S T-TEST =====================

    @staticmethod
    def welch_t_test(
        sample1: np.ndarray,
        sample2: np.ndarray,
        alpha: float = 0.05,
    ) -> WelchTTestResult:
        """Welch's t-test (eşit varyans varsayımı yok).

        A/B test ve champion-challenger karşılaştırması için.

        Args:
            sample1: Champion sonuçları
            sample2: Challenger sonuçları
            alpha: Anlamlılık düzeyi

        Returns:
            WelchTTestResult
        """
        from scipy import stats

        sample1 = np.asarray(sample1, dtype=np.float64)
        sample2 = np.asarray(sample2, dtype=np.float64)

        sample1 = sample1[np.isfinite(sample1)]
        sample2 = sample2[np.isfinite(sample2)]

        if len(sample1) < 5 or len(sample2) < 5:
            return WelchTTestResult(
                t_statistic=0.0, p_value=1.0, significant=False,
                interpretation="Insufficient data"
            )

        t_result = stats.ttest_ind(sample1, sample2, equal_var=False)
        t_stat = t_result.statistic
        p_value = t_result.pvalue

        significant = p_value < alpha

        if significant:
            mean1 = np.mean(sample1)
            mean2 = np.mean(sample2)
            if mean2 > mean1:
                interpretation = f"Challenger significantly better (p={p_value:.4f})"
            else:
                interpretation = f"Champion significantly better (p={p_value:.4f})"
        else:
            interpretation = f"No significant difference (p={p_value:.4f})"

        return WelchTTestResult(
            t_statistic=round(float(t_stat), 4),
            p_value=round(float(p_value), 4),
            significant=bool(significant),
            interpretation=interpretation,
        )

    # ===================== BRIER SCORE =====================

    @staticmethod
    def brier_score(
        predicted_probabilities: np.ndarray,
        actual_outcomes: np.ndarray,
    ) -> float:
        """Brier score hesapla.

        Düşük = iyi kalibrasyon.

        Args:
            predicted_probabilities: Tahmin edilen olasılıklar [0, 1]
            actual_outcomes: Gerçek sonuçlar (0 veya 1)

        Returns:
            Brier score (0-1, düşük iyi)
        """
        predicted_probabilities = np.asarray(predicted_probabilities, dtype=np.float64)
        actual_outcomes = np.asarray(actual_outcomes, dtype=np.float64)

        # Sınırla
        predicted_probabilities = np.clip(predicted_probabilities, 0, 1)

        return float(np.mean((predicted_probabilities - actual_outcomes) ** 2))

    # ===================== SHARPE RATIO =====================

    @staticmethod
    def sharpe_ratio(
        returns: np.ndarray,
        risk_free_rate: float = 0.0,
        annualize: bool = True,
        periods_per_year: int = 252,
    ) -> float:
        """Sharpe ratio hesapla.

        Args:
            returns: Getiri serisi
            risk_free_rate: Risksiz faiz oranı
            annualize: Yıllıklandırılmış mı
            periods_per_year: Yıllık periyot sayısı

        Returns:
            Sharpe ratio
        """
        returns = np.asarray(returns, dtype=np.float64)
        returns = returns[np.isfinite(returns)]

        if len(returns) < 2:
            return 0.0

        excess_returns = returns - risk_free_rate
        mean_return = np.mean(excess_returns)
        std_return = np.std(excess_returns, ddof=1)

        if std_return <= 0:
            # Sabit getiri: pozitifse yüksek Sharpe, negatifse düşük
            return round(float(np.sign(mean_return) * 10.0), 4) if mean_return != 0 else 0.0

        sharpe = mean_return / std_return

        if annualize:
            sharpe *= np.sqrt(periods_per_year)

        return round(float(sharpe), 4)

    # ===================== INFORMATION COEFFICIENT =====================

    @staticmethod
    def information_coefficient(
        scores: np.ndarray,
        actual_returns: np.ndarray,
    ) -> float:
        """Information Coefficient (IC) — Spearman rank korelasyon.

        Args:
            scores: Model skorları
            actual_returns: Gerçek getiriler

        Returns:
            IC (-1 ile 1 arası)
        """
        from scipy import stats

        scores = np.asarray(scores, dtype=np.float64)
        actual_returns = np.asarray(actual_returns, dtype=np.float64)

        # Geçersiz değerleri temizle
        mask = np.isfinite(scores) & np.isfinite(actual_returns)
        scores = scores[mask]
        actual_returns = actual_returns[mask]

        if len(scores) < 5:
            return 0.0

        ic, _ = stats.spearmanr(scores, actual_returns)

        if np.isnan(ic):
            return 0.0

        return round(float(ic), 4)

    # ===================== DEFLATED SHARPE =====================

    @staticmethod
    def deflated_sharpe(
        observed_sharpe: float,
        n_trials: int,
        n_observations: int,
        skewness: float = 0.0,
        kurtosis: float = 3.0,
    ) -> float:
        """Deflated Sharpe Ratio — multiple testing correction.

        Marcos López de Prado'nun yöntemi.
        Birden fazla model denendiğinde Sharpe'ı düzeltir.

        Args:
            observed_sharpe: Gözlenen Sharpe
            n_trials: Denenen model sayısı
            n_observations: Gözlem sayısı
            skewness: çarpıklık
            kurtosis: basıklık

        Returns:
            Deflated Sharpe ratio
        """
        from scipy import stats

        if n_trials <= 1 or n_observations <= 1:
            return observed_sharpe

        # Expected maximum Sharpe under null
        # E[max(SR)] ≈ sqrt(2 * log(n_trials)) * (1 - γ/log(n_trials)) + γ/sqrt(2*log(n_trials))
        # where γ = Euler-Mascheroni constant
        euler_gamma = 0.5772
        log_n = np.log(n_trials)
        expected_max_sr = (
            np.sqrt(2 * log_n) * (1 - euler_gamma / log_n)
            + euler_gamma / np.sqrt(2 * log_n)
        )

        # Standard error of Sharpe
        se_sharpe = np.sqrt(
            (1 + 0.5 * observed_sharpe**2
             - skewness * observed_sharpe
             + (kurtosis - 3) / 4 * observed_sharpe**2)
            / (n_observations - 1)
        )

        # Deflated Sharpe
        if se_sharpe > 0:
            z = (observed_sharpe - expected_max_sr) / se_sharpe
            deflated = float(stats.norm.cdf(z))
        else:
            deflated = 0.5

        return round(deflated, 4)


# Singleton
stat_tests = StatisticalTests()
