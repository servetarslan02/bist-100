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

# Varsayılan sabitler
MIN_EVENTS_FOR_TTEST: int = 2
SIGNIFICANCE_LEVEL: float = 0.05
MIN_EVENTS_FOR_REGRESSION: int = 3  # intercept + en az1feature +1veri
STD_ERROR_THRESHOLD: float = 1e-10
DEFAULT_CAR_VALUE: float = 0.0
DEFAULT_P_VALUE: float = 1.0
DEFAULT_R_SQUARED: float = 0.0
ROUND_DECIMALS: int = 4
ROUND_DECIMALS_STDERR: int = 6


def _encode_categorical(value: str) -> float:
    """Kategorik değeri deterministik numerik değere dönüştürür.

    Args:
        value: Kategorik string değer

    Returns:
        0.0-1.0 arası deterministik numerik değer
    """
    return float(abs(hash(value)) % 100) / 100.0


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

        Raises:
            ValueError: event_cars içinde "car" key eksikse veya NaN/Inf varsa
        """
        if not event_cars:
            logger.warning("cross_sectional_empty_input")
            return self._empty_result()

        # "car" key kontrolü
        for i, e in enumerate(event_cars):
            if "car" not in e:
                logger.error("cross_sectional_missing_car_key", index=i, keys=list(e.keys()))
                raise ValueError(f"event_cars[{i}] içinde 'car' key eksik. Mevcut key'ler: {list(e.keys())}")

        cars = [e["car"] for e in event_cars]

        # NaN/Inf kontrolü
        for i, c in enumerate(cars):
            if isinstance(c, float) and (np.isnan(c) or np.isinf(c)):
                logger.error("cross_sectional_nan_inf_car", index=i, value=c)
                raise ValueError(f"event_cars[{i}] car değeri geçersiz: {c}")

        n = len(cars)

        # Genel istatistikler
        mean_car = float(np.mean(cars))
        if n >= MIN_EVENTS_FOR_TTEST:
            std_car = float(np.std(cars, ddof=1))
            std_error = std_car / np.sqrt(n)
            t_stat = mean_car / std_error if std_error > STD_ERROR_THRESHOLD else DEFAULT_CAR_VALUE
            df = n - 1
            p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=df))
        else:
            std_car = DEFAULT_CAR_VALUE
            std_error = DEFAULT_CAR_VALUE
            t_stat = DEFAULT_CAR_VALUE
            df = 0
            p_value = DEFAULT_P_VALUE

        result: dict[str, Any] = {
            "average_car": round(mean_car, ROUND_DECIMALS),
            "std_car": round(std_car, ROUND_DECIMALS),
            "std_error": round(std_error, ROUND_DECIMALS_STDERR),
            "t_statistic": round(float(t_stat), ROUND_DECIMALS),
            "p_value": round(float(p_value), ROUND_DECIMALS),
            "significant": bool(p_value < SIGNIFICANCE_LEVEL),
            "n_events": n,
            "df": df,
            "median_car": round(float(np.median(cars)), ROUND_DECIMALS),
            "min_car": round(float(np.min(cars)), ROUND_DECIMALS),
            "max_car": round(float(np.max(cars)), ROUND_DECIMALS),
            "positive_pct": round(sum(1 for c in cars if c > 0) / n * 100, 1),
        }

        # Grup bazlı breakdown
        if group_by and group_by in ["event_type", "sector"]:
            result["breakdown"] = self._group_breakdown(event_cars, group_by)

        # Event detayları
        result["event_details"] = event_cars

        # Wilcoxon test (non-parametrik)
        if n >= MIN_EVENTS_FOR_TTEST:
            try:
                w_stat, w_p = stats.wilcoxon(cars)
                result["wilcoxon_statistic"] = round(float(w_stat), ROUND_DECIMALS)
                result["wilcoxon_p_value"] = round(float(w_p), ROUND_DECIMALS)
            except ValueError as e:
                # Wilcoxon tüm değerler aynıysa hata verir — bu beklenen bir durum
                logger.warning("wilcoxon_test_skipped", reason=str(e))

        return result

    def analyze_by_type(
        self,
        event_cars: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Event type bazlı ayrı ayrı analysis.

        Args:
            event_cars: Event verileri listesi

        Returns:
            {event_type: {average_car, t_stat, p_value, n_events}}

        Raises:
            ValueError: event_cars içinde "car" key eksikse
        """
        type_groups: dict[str, list[dict[str, Any]]] = {}
        for e in event_cars:
            etype = e.get("event_type", "UNKNOWN")
            if etype not in type_groups:
                type_groups[etype] = []
            type_groups[etype].append(e)

        results: dict[str, dict[str, Any]] = {}
        for etype, events in type_groups.items():
            results[etype] = self.analyze(events)

        return results

    def analyze_by_sector(
        self,
        event_cars: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Sektör bazlı ayrı ayrı analysis.

        Args:
            event_cars: Event verileri listesi

        Returns:
            {sector: {average_car, t_stat, p_value, n_events}}

        Raises:
            ValueError: event_cars içinde "car" key eksikse
        """
        sector_groups: dict[str, list[dict[str, Any]]] = {}
        for e in event_cars:
            sector = e.get("sector", "UNKNOWN")
            if sector not in sector_groups:
                sector_groups[sector] = []
            sector_groups[sector].append(e)

        results: dict[str, dict[str, Any]] = {}
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

        Raises:
            ValueError: Yetersiz veri veya singular matrix durumunda
            ValueError: event_cars içinde "car" key eksikse
        """
        min_required = len(features) + MIN_EVENTS_FOR_REGRESSION
        if len(event_cars) < min_required:
            logger.error(
                "cross_sectional_regression_insufficient",
                n_events=len(event_cars),
                min_required=min_required,
            )
            raise ValueError(
                f"Regresyon için yetersiz veri: {len(event_cars)} event, "
                f"en az {min_required} gerekli ({len(features)} feature + {MIN_EVENTS_FOR_REGRESSION})"
            )

        # "car" key kontrolü
        for i, e in enumerate(event_cars):
            if "car" not in e:
                logger.error("cross_sectional_regression_missing_car", index=i)
                raise ValueError(f"event_cars[{i}] içinde 'car' key eksik.")

        cars = np.array([e["car"] for e in event_cars])
        n = len(cars)

        # Feature matrix
        X_data: list[list[float]] = []
        for e in event_cars:
            row: list[float] = [1.0]  # intercept
            for f in features:
                val = e.get(f, 0.0)
                if isinstance(val, str):
                    val = _encode_categorical(val)
                row.append(float(val))
            X_data.append(row)

        X = np.array(X_data)
        y = cars

        # Singüler matris kontrolü
        try:
            betas, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError as e:
            logger.error("cross_sectional_regression_linalg_error", error=str(e))
            raise ValueError(f"Regresyon hesaplama hatası (singüler matris): {e}") from e

        y_pred = X @ betas
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > STD_ERROR_THRESHOLD else DEFAULT_R_SQUARED

        # p-values
        n_params = len(betas)
        if n > n_params:
            mse = ss_res / (n - n_params)
            try:
                var_betas = mse * np.linalg.inv(X.T @ X).diagonal()
            except np.linalg.LinAlgError as e:
                logger.error("cross_sectional_regression_inv_error", error=str(e))
                raise ValueError(f"Regresyon matris tersi hesaplama hatası: {e}") from e

            # Sıfır veya negatif varyans kontrolü
            t_stats_arr = np.zeros(n_params)
            p_values_arr = np.ones(n_params)
            for i in range(n_params):
                if var_betas[i] > STD_ERROR_THRESHOLD:
                    t_stats_arr[i] = betas[i] / np.sqrt(var_betas[i])
                    p_values_arr[i] = 2 * (1 - stats.t.cdf(abs(t_stats_arr[i]), df=n - n_params))
                else:
                    logger.warning("cross_sectional_regression_zero_variance", param_index=i)

            t_stats = t_stats_arr
            p_values = p_values_arr
        else:
            t_stats = np.zeros(n_params)
            p_values = np.ones(n_params)

        return {
            "coefficients": {f"β{i}": round(float(b), ROUND_DECIMALS) for i, b in enumerate(betas)},
            "feature_names": ["intercept"] + features,
            "r_squared": round(float(r_squared), ROUND_DECIMALS),
            "t_statistics": [round(float(t), ROUND_DECIMALS) for t in t_stats],
            "p_values": [round(float(p), ROUND_DECIMALS) for p in p_values],
            "n_obs": n,
        }

    def _group_breakdown(
        self, event_cars: list[dict[str, Any]], group_key: str
    ) -> dict[str, dict[str, Any]]:
        """Grup bazlı breakdown hesapla.

        Args:
            event_cars: Event verileri listesi
            group_key: Gruplama yapılacak key ("event_type" veya "sector")

        Returns:
            {group_key_value: {mean_car, std_car, t_statistic, p_value, significant, n_events}}
        """
        groups: dict[str, list[float]] = {}
        for e in event_cars:
            key = e.get(group_key, "UNKNOWN")
            if key not in groups:
                groups[key] = []
            groups[key].append(e["car"])

        breakdown: dict[str, dict[str, Any]] = {}
        for key, cars in groups.items():
            cars_arr = np.array(cars)
            n = len(cars_arr)
            mean = float(np.mean(cars_arr))
            std = float(np.std(cars_arr, ddof=1)) if n > MIN_EVENTS_FOR_TTEST else DEFAULT_CAR_VALUE
            if std > STD_ERROR_THRESHOLD and n > 0:
                t = mean / (std / np.sqrt(n))
            else:
                t = DEFAULT_CAR_VALUE
            df = max(n - 1, 1)
            p = 2 * (1 - stats.t.cdf(abs(t), df=df))

            breakdown[key] = {
                "mean_car": round(mean, ROUND_DECIMALS),
                "std_car": round(std, ROUND_DECIMALS),
                "t_statistic": round(float(t), ROUND_DECIMALS),
                "p_value": round(float(p), ROUND_DECIMALS),
                "significant": bool(p < SIGNIFICANCE_LEVEL),
                "n_events": n,
            }

        return breakdown

    def _empty_result(self) -> dict[str, Any]:
        """Boş analiz sonucu döndürür.

        Returns:
            Varsayılan boş sonuç sözlüğü
        """
        return {
            "average_car": DEFAULT_CAR_VALUE,
            "std_car": DEFAULT_CAR_VALUE,
            "std_error": DEFAULT_CAR_VALUE,
            "t_statistic": DEFAULT_CAR_VALUE,
            "p_value": DEFAULT_P_VALUE,
            "significant": False,
            "n_events": 0,
            "df": 0,
            "median_car": DEFAULT_CAR_VALUE,
            "min_car": DEFAULT_CAR_VALUE,
            "max_car": DEFAULT_CAR_VALUE,
            "positive_pct": DEFAULT_CAR_VALUE,
            "event_details": [],
        }
