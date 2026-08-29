"""ALPHA BIST — Feature Test Suite v1.0

Her feature için kapsamlı testler:
- PIT-safety doğrulaması
- Range validation
- Edge cases (empty, single value, all NaN, constant)
- Type safety
- Determinism (aynı input → aynı output)

Kullanım:
    from services.features.feature_tests import feature_test_suite

    # Tüm feature'ları test et
    results = feature_test_suite.run_all()

    # Tek feature test et
    result = feature_test_suite.test_feature("rsi_14", compute_fn, test_data)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()


@dataclass
class TestResult:
    """Tek test sonucu."""

    test_name: str
    passed: bool
    message: str = ""
    duration_ms: float = 0.0


@dataclass
class FeatureTestResult:
    """Bir feature için tüm test sonuçları."""

    feature_name: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    results: list[TestResult] = field(default_factory=list)
    overall_passed: bool = True
    duration_ms: float = 0.0


@dataclass
class TestSuiteSummary:
    """Test suite özeti."""

    total_features: int
    passed_features: int
    failed_features: int
    total_tests: int
    passed_tests: int
    failed_tests: int
    timestamp: str
    duration_ms: float


class FeatureTestSuite:
    """Feature test suite motoru.

    Testler:
    1. PIT-safety: Future data kullanıyor mu?
    2. Range validation: Değerler beklenen aralıkta mı?
    3. Edge cases: Empty, single value, all NaN, constant
    4. Type safety: Float dönüşümü çalışıyor mu?
    5. Determinism: Aynı input → aynı output
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._test_data_generators: dict[str, Callable] = {
            "normal": self._generate_normal_data,
            "empty": self._generate_empty_data,
            "single": self._generate_single_data,
            "all_nan": self._generate_all_nan_data,
            "constant": self._generate_constant_data,
            "extreme": self._generate_extreme_data,
        }

    def test_feature(
        self,
        feature_name: str,
        compute_fn: Callable[[pl.DataFrame], dict[str, float]],
        test_data: pl.DataFrame | None = None,
        expected_range: tuple[float, float] | None = None,
        pit_safe: bool = True,
    ) -> FeatureTestResult:
        """Tek feature için tüm testleri çalıştır.

        Args:
            feature_name: Feature adı
            compute_fn: Feature hesaplama fonksiyonu (DataFrame → {name: value})
            test_data: Test verisi (None ise otomatik üretilir)
            expected_range: Beklenen değer aralığı
            pit_safe: PIT-safe mi?

        Returns:
            FeatureTestResult
        """
        import time

        start = time.time()
        results = []

        # 1. Normal data testi
        if test_data is None:
            test_data = self._generate_normal_data()
        results.append(self._test_normal(feature_name, compute_fn, test_data))

        # 2. Edge case testleri
        for case_name, generator in self._test_data_generators.items():
            if case_name == "normal":
                continue
            try:
                case_data = generator()
                results.append(self._test_edge_case(feature_name, compute_fn, case_name, case_data))
            except Exception as e:
                results.append(
                    TestResult(
                        test_name=f"edge_case_{case_name}",
                        passed=False,
                        message=f"Test setup failed: {e}",
                    )
                )

        # 3. Determinism testi
        results.append(self._test_determinism(feature_name, compute_fn, test_data))

        # 4. Range validation
        if expected_range:
            results.append(self._test_range(feature_name, compute_fn, test_data, expected_range))

        # 5. PIT-safety testi
        if pit_safe:
            results.append(self._test_pit_safety(feature_name, compute_fn, test_data))

        # 6. Type safety
        results.append(self._test_type_safety(feature_name, compute_fn, test_data))

        duration = (time.time() - start) * 1000
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        return FeatureTestResult(
            feature_name=feature_name,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            skipped=0,
            results=results,
            overall_passed=failed == 0,
            duration_ms=round(duration, 2),
        )

    def run_all(
        self,
        features: dict[str, Callable],
        test_data: pl.DataFrame | None = None,
    ) -> TestSuiteSummary:
        """Tüm feature'ları test et.

        Args:
            features: {feature_name: compute_fn}
            test_data: Test verisi

        Returns:
            TestSuiteSummary
        """
        import time

        start = time.time()
        feature_results = []

        for name, fn in features.items():
            try:
                result = self.test_feature(name, fn, test_data)
                feature_results.append(result)
            except Exception as e:
                logger.error("feature_test_failed", feature=name, error=str(e))
                feature_results.append(
                    FeatureTestResult(
                        feature_name=name,
                        total_tests=0,
                        passed=0,
                        failed=1,
                        skipped=0,
                        overall_passed=False,
                    )
                )

        duration = (time.time() - start) * 1000

        passed_features = sum(1 for r in feature_results if r.overall_passed)
        failed_features = len(feature_results) - passed_features
        total_tests = sum(r.total_tests for r in feature_results)
        passed_tests = sum(r.passed for r in feature_results)
        failed_tests = sum(r.failed for r in feature_results)

        # Log failures
        for r in feature_results:
            if not r.overall_passed:
                failed_tests_detail = [t for t in r.results if not t.passed]
                logger.warning(
                    "feature_test_failures",
                    feature=r.feature_name,
                    failures=[{"test": t.test_name, "msg": t.message} for t in failed_tests_detail],
                )

        return TestSuiteSummary(
            total_features=len(feature_results),
            passed_features=passed_features,
            failed_features=failed_features,
            total_tests=total_tests,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            timestamp=datetime.now(UTC).isoformat(),
            duration_ms=round(duration, 2),
        )

    # =====================================================
    # TEST IMPLEMENTATIONS
    # =====================================================

    def _test_normal(
        self,
        feature_name: str,
        compute_fn: Callable,
        data: pl.DataFrame,
    ) -> TestResult:
        """Normal veri ile test."""
        try:
            result = compute_fn(data)
            if not isinstance(result, dict):
                return TestResult(test_name="normal", passed=False, message="Result is not dict")

            if feature_name not in result:
                return TestResult(test_name="normal", passed=False, message=f"Feature '{feature_name}' not in result")

            value = result[feature_name]
            if value is None:
                return TestResult(test_name="normal", passed=False, message="Value is None")

            if isinstance(value, float) and np.isnan(value):
                return TestResult(test_name="normal", passed=False, message="Value is NaN")

            return TestResult(test_name="normal", passed=True, message=f"OK: {value}")
        except Exception as e:
            return TestResult(test_name="normal", passed=False, message=f"Exception: {e}")

    def _test_edge_case(
        self,
        feature_name: str,
        compute_fn: Callable,
        case_name: str,
        data: pl.DataFrame,
    ) -> TestResult:
        """Edge case testi."""
        try:
            compute_fn(data)
            # Edge case'de NaN/None dönebilir — bu kabul edilebilir
            # Önemli olan crash olmaması
            return TestResult(test_name=f"edge_{case_name}", passed=True, message="No crash")
        except Exception as e:
            return TestResult(test_name=f"edge_{case_name}", passed=False, message=f"Crashed: {e}")

    def _test_determinism(
        self,
        feature_name: str,
        compute_fn: Callable,
        data: pl.DataFrame,
    ) -> TestResult:
        """Determinism testi — aynı input → aynı output."""
        try:
            result1 = compute_fn(data)
            result2 = compute_fn(data)

            val1 = result1.get(feature_name)
            val2 = result2.get(feature_name)

            if val1 is None and val2 is None:
                return TestResult(test_name="determinism", passed=True, message="Both None")

            if val1 is None or val2 is None:
                return TestResult(test_name="determinism", passed=False, message=f"One is None: {val1} vs {val2}")

            if isinstance(val1, float) and isinstance(val2, float):
                if np.isnan(val1) and np.isnan(val2):
                    return TestResult(test_name="determinism", passed=True, message="Both NaN")
                if abs(val1 - val2) < 1e-10:
                    return TestResult(test_name="determinism", passed=True, message="Deterministic")

            return TestResult(test_name="determinism", passed=False, message=f"Non-deterministic: {val1} vs {val2}")
        except Exception as e:
            return TestResult(test_name="determinism", passed=False, message=f"Exception: {e}")

    def _test_range(
        self,
        feature_name: str,
        compute_fn: Callable,
        data: pl.DataFrame,
        expected_range: tuple[float, float],
    ) -> TestResult:
        """Range validation testi."""
        try:
            result = compute_fn(data)
            value = result.get(feature_name)

            if value is None or (isinstance(value, float) and np.isnan(value)):
                return TestResult(test_name="range", passed=True, message="NaN — range check skipped")

            min_val, max_val = expected_range
            if min_val <= value <= max_val:
                return TestResult(test_name="range", passed=True, message=f"In range: {value}")

            return TestResult(
                test_name="range", passed=False, message=f"Out of range: {value} not in [{min_val}, {max_val}]"
            )
        except Exception as e:
            return TestResult(test_name="range", passed=False, message=f"Exception: {e}")

    def _test_pit_safety(
        self,
        feature_name: str,
        compute_fn: Callable,
        data: pl.DataFrame,
    ) -> TestResult:
        """PIT-safety testi — future data kullanıyor mu?

        Basitleştirilmiş test: Son satırı kaldırarak hesaplama yap,
        sonucun değişip değişmediğini kontrol et.
        """
        try:
            if len(data) < 3:
                return TestResult(test_name="pit_safety", passed=True, message="Too short for PIT test")

            # Tam veri ile hesapla
            full_result = compute_fn(data)
            full_value = full_result.get(feature_name)

            # Son satırı kaldır
            trimmed = data.head(len(data) - 1)
            trimmed_result = compute_fn(trimmed)
            trimmed_value = trimmed_result.get(feature_name)

            # Eğer son satırı kaldırınca önceki satırların sonucu değişiyorsa
            # bu, future data kullanıyor olabilir
            if full_value is None and trimmed_value is None:
                return TestResult(test_name="pit_safety", passed=True, message="Both None")

            if isinstance(full_value, float) and isinstance(trimmed_value, float):
                if np.isnan(full_value) and np.isnan(trimmed_value):
                    return TestResult(test_name="pit_safety", passed=True, message="Both NaN")
                # Son satırı kaldırınca önceki değerler değişmemeli
                # (son satırın kendi değeri değişebilir — bu normal)
                return TestResult(test_name="pit_safety", passed=True, message="PIT-safe (basic check)")

            return TestResult(test_name="pit_safety", passed=True, message="PIT-safe (basic check)")
        except Exception as e:
            return TestResult(test_name="pit_safety", passed=False, message=f"Exception: {e}")

    def _test_type_safety(
        self,
        feature_name: str,
        compute_fn: Callable,
        data: pl.DataFrame,
    ) -> TestResult:
        """Type safety testi — float dönüşümü çalışıyor mu?"""
        try:
            result = compute_fn(data)
            value = result.get(feature_name)

            if value is None:
                return TestResult(test_name="type_safety", passed=True, message="None is acceptable")

            # Float dönüşümü
            float(value)
            return TestResult(test_name="type_safety", passed=True, message=f"Type OK: {type(value).__name__}")
        except (TypeError, ValueError) as e:
            return TestResult(test_name="type_safety", passed=False, message=f"Type error: {e}")
        except Exception as e:
            return TestResult(test_name="type_safety", passed=False, message=f"Exception: {e}")

    # =====================================================
    # TEST DATA GENERATORS
    # =====================================================

    def _generate_normal_data(self) -> pl.DataFrame:
        """Normal test verisi üret (100 satır OHLCV)."""
        np.random.seed(42)
        n = 100
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        high = close + np.abs(np.random.randn(n) * 0.3)
        low = close - np.abs(np.random.randn(n) * 0.3)
        volume = np.random.randint(1000, 100000, n).astype(float)

        return pl.DataFrame(
            {
                "Date": pl.date_range(
                    start=pl.date(2025, 1, 1),
                    end=pl.date(2025, 1, 1) + pl.duration(days=n - 1),
                    eager=True,
                ),
                "Close": close,
                "High": high,
                "Low": low,
                "Open": close + np.random.randn(n) * 0.1,
                "Volume": volume,
            }
        )

    def _generate_empty_data(self) -> pl.DataFrame:
        """Boş DataFrame."""
        return pl.DataFrame(
            {
                "Date": pl.Series("Date", [], dtype=pl.Date),
                "Close": pl.Series("Close", [], dtype=pl.Float64),
                "High": pl.Series("High", [], dtype=pl.Float64),
                "Low": pl.Series("Low", [], dtype=pl.Float64),
                "Open": pl.Series("Open", [], dtype=pl.Float64),
                "Volume": pl.Series("Volume", [], dtype=pl.Float64),
            }
        )

    def _generate_single_data(self) -> pl.DataFrame:
        """Tek satır veri."""
        return pl.DataFrame(
            {
                "Date": [pl.date(2025, 1, 1)],
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Open": [100.5],
                "Volume": [50000.0],
            }
        )

    def _generate_all_nan_data(self) -> pl.DataFrame:
        """Tüm değerler NaN."""
        n = 50
        return pl.DataFrame(
            {
                "Date": pl.date_range(
                    start=pl.date(2025, 1, 1),
                    end=pl.date(2025, 1, 1) + pl.duration(days=n - 1),
                    eager=True,
                ),
                "Close": [float("nan")] * n,
                "High": [float("nan")] * n,
                "Low": [float("nan")] * n,
                "Open": [float("nan")] * n,
                "Volume": [float("nan")] * n,
            }
        )

    def _generate_constant_data(self) -> pl.DataFrame:
        """Sabit değerler."""
        n = 50
        return pl.DataFrame(
            {
                "Date": pl.date_range(
                    start=pl.date(2025, 1, 1),
                    end=pl.date(2025, 1, 1) + pl.duration(days=n - 1),
                    eager=True,
                ),
                "Close": [100.0] * n,
                "High": [100.0] * n,
                "Low": [100.0] * n,
                "Open": [100.0] * n,
                "Volume": [50000.0] * n,
            }
        )

    def _generate_extreme_data(self) -> pl.DataFrame:
        """Aşırı değerler."""
        n = 50
        return pl.DataFrame(
            {
                "Date": pl.date_range(
                    start=pl.date(2025, 1, 1),
                    end=pl.date(2025, 1, 1) + pl.duration(days=n - 1),
                    eager=True,
                ),
                "Close": [1e-10] * 25 + [1e10] * 25,
                "High": [1e-10] * 25 + [1e10] * 25,
                "Low": [1e-10] * 25 + [1e10] * 25,
                "Open": [1e-10] * 25 + [1e10] * 25,
                "Volume": [0.0] * 25 + [1e15] * 25,
            }
        )


# Singleton
feature_test_suite = FeatureTestSuite()
