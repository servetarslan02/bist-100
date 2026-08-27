"""ALPHA BIST — Cross-Sectional Event Study.

Birden fazla hisse için event study — ortalama CAR, t-test,
event type breakdown, sector breakdown, regression analysis.
MacKinlay (1997) metodolojisi.
"""
from typing import Any

import numpy as np
import structlog
from scipy import stats

logger = structlog.get_logger()


class CrossSectionalEventStudy:
    """Birden fazla event için cross-sectional analysis."""

    def analyze(
        self,
        event_cars: list[dict[str, Any]],
        group_by: str | None = None,
    ) -> dict[str, Any]:
        """Cross-sectional event study.

        Args:
            event_cars: [{ticker, event_type, sector, car, p_value, ...}]
            group_by: Gruplama değişkeni ("event_type", "sector", None)

        Returns:
            Dict with average_car, t_stat, p_value, breakdown, details
        """
        if not event_cars:
            return self._empty_result()

        cars = [e["car"] for e in event_cars]
        n = len(cars)

        # Genel istatistikler
        mean_car = float(np.mean(cars))
        if n >= 2:
            std_car = float(np.std(cars, ddof=1))
            std_error = std_car / np.sqrt(n)
            t_stat = mean_car / std_error if std_error > 1e-10 else 0.0
            df = n - 1
            p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=df))
        else:
            # n=1: t-test yapılamaz
            std_car = 0.0
            std_error = 0.0
            t_stat = 0.0
            df = 0
            p_value = 1.0

        result = {
            "average_car": round(mean_car, 4),
            "std_car": round(std_car, 4),
            "std_error": round(std_error, 6),
            "t_statistic": round(float(t_stat), 4),
            "p_value": round(float(p_value), 4),
            "significant": bool(p_value < 0.05),
            "n_events": n,
            "df": df,
            "median_car": round(float(np.median(cars)), 4),
            "min_car": round(float(np.min(cars)), 4),
            "max_car": round(float(np.max(cars)), 4),
            "positive_pct": round(sum(1 for c in cars if c > 0) / n * 100, 1),
        }

        # Grup bazlı breakdown
        if group_by and group_by in ["event_type", "sector"]:
            result["breakdown"] = self._group_breakdown(event_cars, group_by)

        # Event detayları
        result["event_details"] = event_cars

        # Wilcoxon test (non-parametrik)
        if n >= 2:
            try:
                w_stat, w_p = stats.wilcoxon(cars)
                result["wilcoxon_statistic"] = round(float(w_stat), 4)
                result["wilcoxon_p_value"] = round(float(w_p), 4)
            except Exception as e:
                logger.debug("Handled exception", error=str(e), context="cross_sectional.py:82")

        return result

    def analyze_by_type(
        self,
        event_cars: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Event type bazlı ayrı ayrı analysis.

        Returns:
            {event_type: {average_car, t_stat, p_value, n_events}}
        """
        type_groups = {}
        for e in event_cars:
            etype = e.get("event_type", "UNKNOWN")
            if etype not in type_groups:
                type_groups[etype] = []
            type_groups[etype].append(e)

        results = {}
        for etype, events in type_groups.items():
            results[etype] = self.analyze(events)

        return results

    def analyze_by_sector(
        self,
        event_cars: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Sektör bazlı ayrı ayrı analysis.

        Returns:
            {sector: {average_car, t_stat, p_value, n_events}}
        """
        sector_groups = {}
        for e in event_cars:
            sector = e.get("sector", "UNKNOWN")
            if sector not in sector_groups:
                sector_groups[sector] = []
            sector_groups[sector].append(e)

        results = {}
        for sector, events in sector_groups.items():
            results[sector] = self.analyze(events)

        return results

    def regression_analysis(
        self,
        event_cars: list[dict[str, Any]],
        features: list[str],
    ) -> dict[str, Any]:
        """CAR'ı event features'a karşı regresyon.

        CAR = β0 + β1×feature1 + β2×feature2 + ... + ε

        Args:
            event_cars: Event verileri
            features: Regresyon değişkenleri (event_cars'taki key'ler)

        Returns:
            Dict with coefficients, r_squared, p_values
        """
        if len(event_cars) < len(features) + 2:
            return {"error": "Yetersiz veri"}

        cars = np.array([e["car"] for e in event_cars])
        n = len(cars)

        # Feature matrix
        X_data = []
        for e in event_cars:
            row = [1.0]  # intercept
            for f in features:
                val = e.get(f, 0.0)
                if isinstance(val, str):
                    val = hash(val) % 100 / 100.0  # Kategorik → numerik
                row.append(float(val))
            X_data.append(row)

        X = np.array(X_data)
        y = cars

        try:
            betas, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)

            y_pred = X @ betas
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

            # p-values
            n_params = len(betas)
            if n > n_params:
                mse = ss_res / (n - n_params)
                var_betas = mse * np.linalg.inv(X.T @ X).diagonal()
                t_stats = betas / np.sqrt(np.abs(var_betas))
                p_values = [2 * (1 - stats.t.cdf(abs(t), df=n - n_params)) for t in t_stats]
            else:
                t_stats = np.zeros(n_params)
                p_values = [1.0] * n_params

            return {
                "coefficients": {f"β{i}": round(float(b), 4) for i, b in enumerate(betas)},
                "feature_names": ["intercept"] + features,
                "r_squared": round(float(r_squared), 4),
                "t_statistics": [round(float(t), 4) for t in t_stats],
                "p_values": [round(float(p), 4) for p in p_values],
                "n_obs": n,
            }
        except Exception as e:
            logger.error("cross_sectional_regression_error", error=str(e))
            return {"error": str(e)}

    def _group_breakdown(
        self, event_cars: list[dict[str, Any]], group_key: str
    ) -> dict[str, dict[str, Any]]:
        """Grup bazlı breakdown."""
        groups = {}
        for e in event_cars:
            key = e.get(group_key, "UNKNOWN")
            if key not in groups:
                groups[key] = []
            groups[key].append(e["car"])

        breakdown = {}
        for key, cars in groups.items():
            cars_arr = np.array(cars)
            n = len(cars_arr)
            mean = float(np.mean(cars_arr))
            std = float(np.std(cars_arr, ddof=1)) if n > 1 else 0.0
            t = mean / (std / np.sqrt(n)) if std > 1e-10 and n > 0 else 0.0
            p = 2 * (1 - stats.t.cdf(abs(t), df=max(n - 1, 1)))

            breakdown[key] = {
                "mean_car": round(mean, 4),
                "std_car": round(std, 4),
                "t_statistic": round(float(t), 4),
                "p_value": round(float(p), 4),
                "significant": bool(p < 0.05),
                "n_events": n,
            }

        return breakdown

    def _empty_result(self) -> dict[str, Any]:
        """Boş sonuç."""
        return {
            "average_car": 0.0,
            "std_car": 0.0,
            "std_error": 0.0,
            "t_statistic": 0.0,
            "p_value": 1.0,
            "significant": False,
            "n_events": 0,
            "df": 0,
            "median_car": 0.0,
            "min_car": 0.0,
            "max_car": 0.0,
            "positive_pct": 0.0,
            "event_details": [],
        }
