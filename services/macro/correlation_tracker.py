"""
ALPHA BIST — Macro Correlation Tracker v1.0

Makro değişkenler arası korelasyon takibi:
- Rolling correlation matrix (60 gün)
- Korelasyon bozulma tespiti
- Korelasyon feature'ları üretme
- Anlamlılık testi

KURAL: Korelasyon zamanla değişir — rolling window ile takip et.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import scipy.stats as stats
import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class CorrelationResult:
    """Korelasyon sonucu."""

    var1: str
    var2: str
    correlation: float
    p_value: float
    significant: bool
    sample_count: int
    window_days: int
    ewma_correlation: float = 0.0
    spearman_correlation: float = 0.0
    lead_lag_dominant: str = "SYNCHRONOUS"

    def __repr__(self) -> str:
        """Korelasyon sonucunun okunabilir string temsili."""
        return (
            f"CorrelationResult({self.var1} vs {self.var2}: "
            f"corr={self.correlation:.4f}, ewma={self.ewma_correlation:.4f}, "
            f"spearman={self.spearman_correlation:.4f}, lead_lag={self.lead_lag_dominant}, "
            f"p={self.p_value:.4f}, significant={self.significant}, n={self.sample_count})"
        )


@dataclass
class CorrelationBreakdown:
    """Korelasyon bozulma tespiti."""

    var1: str
    var2: str
    historical_corr: float
    current_corr: float
    breakdown_magnitude: float
    alert: bool

    def __repr__(self) -> str:
        """Korelasyon bozulma tespiti okunabilir string temsili."""
        return (
            f"CorrelationBreakdown({self.var1} vs {self.var2}: "
            f"hist={self.historical_corr:.2f} -> curr={self.current_corr:.2f}, "
            f"breakdown={self.breakdown_magnitude:.2f}, alert={self.alert})"
        )


class MacroCorrelationTracker:
    """Makro değişkenler arası korelasyon takip motoru."""

    # Takip edilen korelasyon çiftleri
    DEFAULT_PAIRS = [
        ("usdtry", "gold"),
        ("interest_rate", "inflation"),
        ("vix", "bist100"),
        ("oil", "energy_sector"),
        ("sp500", "bist100"),
        ("cds", "usdtry"),
    ]

    def __init__(self) -> None:
        """Makro korelasyon takip motoru başlatıcı.

        Değişken geçmişi, zaman damgaları ve korelasyon serilerini ilklendirir.
        """
        self._window = macro_config.correlation.window_days
        self._history: dict[str, list[float]] = {}
        self._timestamps: dict[str, list[str]] = {}
        self._correlation_history: dict[str, list[float]] = {}  # pair → [corr1, corr2, ...]
        self._pair_key = lambda v1, v2: f"{v1}_{v2}" if v1 < v2 else f"{v2}_{v1}"

    def __repr__(self) -> str:
        """Makro korelasyon motoru okunabilir string temsili."""
        return (
            f"MacroCorrelationTracker(window={self._window}, "
            f"variables={len(self._history)}, "
            f"tracked_corrs={len(self._correlation_history)})"
        )

    def update(self, macro_data: dict[str, float]) -> Any:
        """Günlük veri güncelle.

        Args:
            macro_data: {variable_name: value}
        """
        now = datetime.now(UTC).isoformat()

        for key, value in macro_data.items():
            if key not in self._history:
                self._history[key] = []
                self._timestamps[key] = []

            self._history[key].append(value)
            self._timestamps[key].append(now)

            # Rolling window
            if len(self._history[key]) > self._window * 2:
                self._history[key] = self._history[key][-self._window * 2 :]
                self._timestamps[key] = self._timestamps[key][-self._window * 2 :]

    def _calc_ewma_corr(self, x: np.ndarray, y: np.ndarray, decay: float = 0.94) -> float:
        """RiskMetrics standardı EWMA (Exponentially Weighted Moving Average) korelasyonu."""
        n = len(x)
        if n < 5:
            return 0.0
        weights = np.array([(1.0 - decay) * (decay ** (n - 1 - i)) for i in range(n)])
        w_sum = np.sum(weights)
        if w_sum <= 0:
            return 0.0
        weights = weights / w_sum

        mu_x = np.sum(weights * x)
        mu_y = np.sum(weights * y)

        cov_xy = np.sum(weights * (x - mu_x) * (y - mu_y))
        var_x = np.sum(weights * (x - mu_x) ** 2)
        var_y = np.sum(weights * (y - mu_y) ** 2)

        denom = np.sqrt(var_x * var_y)
        if denom < 1e-9:
            return 0.0
        return float(np.clip(cov_xy / denom, -1.0, 1.0))

    def _calc_lead_lag(self, x: np.ndarray, y: np.ndarray) -> str:
        """Lag-1 ve Lag-2 çapraz korelasyonu inceleyerek öncü-artçı ilişkiyi belirler."""
        if len(x) < 8:
            return "SYNCHRONOUS"

        # x leads y: corr(x[:-1], y[1:])
        corr_x_leads = np.corrcoef(x[:-1], y[1:])[0, 1]
        # y leads x: corr(y[:-1], x[1:])
        corr_y_leads = np.corrcoef(y[:-1], x[1:])[0, 1]

        corr_x_leads = 0.0 if np.isnan(corr_x_leads) else corr_x_leads
        corr_y_leads = 0.0 if np.isnan(corr_y_leads) else corr_y_leads

        diff = abs(corr_x_leads) - abs(corr_y_leads)
        if diff > 0.15:
            return "VAR1_LEADS"
        elif diff < -0.15:
            return "VAR2_LEADS"
        return "SYNCHRONOUS"

    def get_correlation(
        self,
        var1: str,
        var2: str,
    ) -> CorrelationResult | None:
        """İki değişken arası çok boyutlu korelasyon hesapla."""
        cfg = macro_config.correlation

        h1 = self._history.get(var1, [])
        h2 = self._history.get(var2, [])

        if len(h1) < cfg.min_samples or len(h2) < cfg.min_samples:
            return None

        # Son N gözlemi kullan
        n = min(len(h1), len(h2), self._window)
        arr1 = np.array(h1[-n:])
        arr2 = np.array(h2[-n:])

        # NaN temizle
        mask = np.isfinite(arr1) & np.isfinite(arr2)
        arr1, arr2 = arr1[mask], arr2[mask]

        if len(arr1) < cfg.min_samples:
            return None

        # Standart Pearson Korelasyonu
        corr = np.corrcoef(arr1, arr2)[0, 1]
        if np.isnan(corr):
            corr = 0.0

        # EWMA Korelasyonu (Rejim duyarlılığı yüksek)
        ewma_corr = self._calc_ewma_corr(arr1, arr2, decay=0.94)

        # Spearman Sıra Korelasyonu (Aykırı değer ve ağır kuyruklara dirençli)
        spearman_res = stats.spearmanr(arr1, arr2)
        spearman_corr = float(spearman_res.statistic) if not np.isnan(spearman_res.statistic) else 0.0

        # Öncü - Artçı Dinamik Analizi
        lead_lag = self._calc_lead_lag(arr1, arr2)

        # P-value hesapla (t-test)
        n_obs = len(arr1)
        if abs(corr) < 1.0 and n_obs > 2:
            t_stat = corr * np.sqrt((n_obs - 2) / (1 - corr**2))
            p_value = float(2 * (1 - stats.t.cdf(abs(t_stat), n_obs - 2)))
        else:
            p_value = 0.0

        significant = p_value < 0.05

        # Korelasyon geçmişini güncelle
        pair_key = self._pair_key(var1, var2)
        if pair_key not in self._correlation_history:
            self._correlation_history[pair_key] = []
        self._correlation_history[pair_key].append(corr)
        self._correlation_history[pair_key] = self._correlation_history[pair_key][-self._window :]

        return CorrelationResult(
            var1=var1,
            var2=var2,
            correlation=round(float(corr), 4),
            p_value=round(float(p_value), 4),
            significant=significant,
            sample_count=n_obs,
            window_days=n,
            ewma_correlation=round(float(ewma_corr), 4),
            spearman_correlation=round(float(spearman_corr), 4),
            lead_lag_dominant=lead_lag,
        )

    def get_correlation_matrix(self) -> dict[str, dict[str, float]]:
        """Tüm değişkenler arası korelasyon matrisi."""
        variables = list(self._history.keys())
        matrix = {}

        for v1 in variables:
            matrix[v1] = {}
            for v2 in variables:
                if v1 == v2:
                    matrix[v1][v2] = 1.0
                else:
                    result = self.get_correlation(v1, v2)
                    matrix[v1][v2] = result.correlation if result else None

        return matrix

    def detect_correlation_breakdown(self) -> list[CorrelationBreakdown]:
        """Korelasyon bozulması tespit et."""
        cfg = macro_config.correlation
        breakdowns = []

        for v1, v2 in cfg.tracked_pairs:
            pair_key = self._pair_key(v1, v2)
            hist_corr = self._correlation_history.get(pair_key, [])

            if len(hist_corr) < 20:
                continue

            # Tarihsel ortalama
            historical_avg = np.mean(hist_corr[:-5]) if len(hist_corr) > 5 else np.mean(hist_corr)

            # Mevcut korelasyon
            current = self.get_correlation(v1, v2)
            if not current:
                continue

            breakdown_magnitude = abs(current.correlation - historical_avg)

            breakdown = CorrelationBreakdown(
                var1=v1,
                var2=v2,
                historical_corr=round(float(historical_avg), 4),
                current_corr=current.correlation,
                breakdown_magnitude=round(float(breakdown_magnitude), 4),
                alert=breakdown_magnitude > cfg.breakdown_threshold,
            )

            if breakdown.alert:
                logger.warning(
                    "Correlation breakdown detected",
                    var1=v1,
                    var2=v2,
                    historical=historical_avg,
                    current=current.correlation,
                )

            breakdowns.append(breakdown)

        return breakdowns

    def compute_correlation_features(self) -> dict[str, float]:
        """Korelasyon feature'ları üret."""
        cfg = macro_config.correlation
        features = {}

        all_corrs = []
        for v1, v2 in cfg.tracked_pairs:
            result = self.get_correlation(v1, v2)
            pair_key = self._pair_key(v1, v2)

            if result:
                features[f"corr_{v1}_{v2}"] = result.correlation
                features[f"corr_{v1}_{v2}_significant"] = 1.0 if result.significant else 0.0
                features[f"corr_{v1}_{v2}_ewma"] = result.ewma_correlation
                features[f"corr_{v1}_{v2}_spearman"] = result.spearman_correlation
                all_corrs.append(abs(result.correlation))
            else:
                features[f"corr_{v1}_{v2}"] = 0.0
                features[f"corr_{v1}_{v2}_significant"] = 0.0
                features[f"corr_{v1}_{v2}_ewma"] = 0.0
                features[f"corr_{v1}_{v2}_spearman"] = 0.0

            # Korelasyon stabilitesi (son 30 günün std'si)
            hist = self._correlation_history.get(pair_key, [])
            if len(hist) >= 10:
                features[f"corr_{v1}_{v2}_stability"] = round(float(1.0 - np.std(hist[-30:])), 4)
            else:
                features[f"corr_{v1}_{v2}_stability"] = 0.0

        # Genel korelasyon stresi (kaç çiftte bozulma var?)
        breakdowns = self.detect_correlation_breakdown()
        features["correlation_stress"] = float(sum(1 for b in breakdowns if b.alert))
        features["correlation_stress_pct"] = round(sum(1 for b in breakdowns if b.alert) / max(len(breakdowns), 1), 4)
        # Sistemik Kohezyon: Piyasa krizlerinde korelasyonların 1.0'e kilitlenme derecesi
        features["systemic_correlation_cohesion"] = round(float(np.mean(all_corrs)), 4) if all_corrs else 0.0

        return features

    def get_report(self) -> dict[str, Any]:
        """Korelasyon raporu."""
        cfg = macro_config.correlation
        pairs_data = []

        for v1, v2 in cfg.tracked_pairs:
            result = self.get_correlation(v1, v2)
            if result:
                pairs_data.append(
                    {
                        "pair": f"{v1}-{v2}",
                        "correlation": result.correlation,
                        "significant": result.significant,
                        "p_value": result.p_value,
                    }
                )

        breakdowns = self.detect_correlation_breakdown()

        return {
            "tracked_pairs": len(cfg.tracked_pairs),
            "correlations": pairs_data,
            "breakdowns": [
                {
                    "pair": f"{b.var1}-{b.var2}",
                    "historical": b.historical_corr,
                    "current": b.current_corr,
                    "breakdown": b.breakdown_magnitude,
                    "alert": b.alert,
                }
                for b in breakdowns
            ],
            "data_points": {k: len(v) for k, v in self._history.items()},
        }


# Singleton
macro_correlation_tracker = MacroCorrelationTracker()

__all__ = [
    "CorrelationResult",
    "CorrelationBreakdown",
    "MacroCorrelationTracker",
    "macro_correlation_tracker",
]
