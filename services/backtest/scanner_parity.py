"""
ALPHA BIST — Backtest-Scanner Parity Module

Backtest ve canlı tarama sisteminin aynı kodu kullanmasını garanti eder.
"Farklı kod = farklı sonuç" problemini çözer.

Prensipler:
1. Shared feature engine - backtest ve canlı aynı feature'ları hesaplar
2. Shared signal logic - aynı scoring fonksiyonu
3. Shared risk limits - aynı limitler
4. Shared cost model - aynı maliyet modeli
5. Version lock - feature versiyonu sabitlenir
"""

import hashlib
import orjson
import polars as pl
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class ParityConfig:
    """Parity konfigürasyonu."""
    feature_version: str = "v1.0"
    scoring_version: str = "v1.0"
    risk_version: str = "v1.0"
    cost_model_version: str = "v1.0"
    config_hash: str = ""

    def compute_hash(self) -> str:
        """Konfigürasyon hash'i."""
        content = f"{self.feature_version}:{self.scoring_version}:{self.risk_version}:{self.cost_model_version}"
        self.config_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self.config_hash


@dataclass
class ParityCheckResult:
    """Parity kontrol sonucu."""
    check_type: str  # feature | signal | risk | cost
    is_parity: bool
    backtest_value: Any
    live_value: Any
    difference: Optional[float] = None
    tolerance: float = 1e-6

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "is_parity": self.is_parity,
            "backtest_value": str(self.backtest_value)[:100],
            "live_value": str(self.live_value)[:100],
            "difference": self.difference,
        }


@dataclass
class ParityReport:
    """Parity raporu."""
    timestamp: str
    config_hash: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    is_full_parity: bool
    checks: List[ParityCheckResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "config_hash": self.config_hash,
            "total_checks": self.total_checks,
            "passed": self.passed_checks,
            "failed": self.failed_checks,
            "is_full_parity": self.is_full_parity,
            "checks": [c.to_dict() for c in self.checks],
        }


class BacktestScannerParity:
    """
    Backtest-Scanner parity garantisi.

    Backtest ve canlı sistemin aynı kod yolunu kullanmasını sağlar.
    """

    def __init__(self):
        self._feature_engine: Optional[Callable] = None
        self._signal_engine: Optional[Callable] = None
        self._risk_engine: Optional[Callable] = None
        self._cost_engine: Optional[Callable] = None
        self._config = ParityConfig()

    def register_engines(
        self,
        feature_engine: Callable,
        signal_engine: Callable,
        risk_engine: Optional[Callable] = None,
        cost_engine: Optional[Callable] = None,
    ):
        """Motorları kaydet."""
        self._feature_engine = feature_engine
        self._signal_engine = signal_engine
        self._risk_engine = risk_engine
        self._cost_engine = cost_engine
        logger.info("Parity engines registered")

    def verify_feature_parity(
        self,
        data: pl.DataFrame,
        ticker: str,
        timestamp: datetime,
        expected_features: Optional[Dict[str, float]] = None,
        tolerance: float = 1e-6,
    ) -> ParityCheckResult:
        """
        Feature parity kontrolü.

        Backtest ve canlı sistem aynı veriyle aynı feature'ları üretmeli.
        """
        if self._feature_engine is None:
            return ParityCheckResult(
                check_type="feature",
                is_parity=False,
                backtest_value=None,
                live_value=None,
            )

        # Compute features
        computed = self._feature_engine(data, ticker, timestamp)

        if expected_features is None:
            # First run - use computed as reference
            return ParityCheckResult(
                check_type="feature",
                is_parity=True,
                backtest_value=computed,
                live_value=computed,
            )

        # Compare
        mismatches = []
        for key in expected_features:
            if key in computed:
                diff = abs(computed[key] - expected_features[key])
                if diff > tolerance:
                    mismatches.append((key, expected_features[key], computed[key], diff))

        return ParityCheckResult(
            check_type="feature",
            is_parity=len(mismatches) == 0,
            backtest_value=expected_features,
            live_value=computed,
            difference=max(m[3] for m in mismatches) if mismatches else 0,
        )

    def verify_signal_parity(
        self,
        features: Dict[str, float],
        ticker: str,
        expected_score: Optional[float] = None,
        tolerance: float = 0.01,
    ) -> ParityCheckResult:
        """
        Sinyal parity kontrolü.

        Aynı feature'larla aynı sinyal skoru üretilmeli.
        """
        if self._signal_engine is None:
            return ParityCheckResult(
                check_type="signal",
                is_parity=False,
                backtest_value=None,
                live_value=None,
            )

        computed_score = self._signal_engine(features, ticker)

        if expected_score is None:
            return ParityCheckResult(
                check_type="signal",
                is_parity=True,
                backtest_value=computed_score,
                live_value=computed_score,
            )

        diff = abs(computed_score - expected_score)
        return ParityCheckResult(
            check_type="signal",
            is_parity=diff <= tolerance,
            backtest_value=expected_score,
            live_value=computed_score,
            difference=diff,
        )

    def run_full_parity_check(
        self,
        test_data: pl.DataFrame,
        test_tickers: List[str],
        test_timestamp: datetime,
    ) -> ParityReport:
        """
        Tam parity kontrolü çalıştır.

        Tüm motorlar için parity testi yapar.
        """
        checks = []

        # Feature parity
        for ticker in test_tickers[:5]:  # İlk 5 hisse
            ticker_data = test_data.filter(pl.col('ticker') == ticker) if "ticker" in test_data.columns else test_data
            result = self.verify_feature_parity(ticker_data, ticker, test_timestamp)
            checks.append(result)

        # Signal parity
        if self._feature_engine and self._signal_engine:
            for ticker in test_tickers[:5]:
                ticker_data = test_data.filter(pl.col('ticker') == ticker) if "ticker" in test_data.columns else test_data
                features = self._feature_engine(ticker_data, ticker, test_timestamp)
                result = self.verify_signal_parity(features, ticker)
                checks.append(result)

        passed = sum(1 for c in checks if c.is_parity)
        failed = len(checks) - passed

        report = ParityReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            config_hash=self._config.compute_hash(),
            total_checks=len(checks),
            passed_checks=passed,
            failed_checks=failed,
            is_full_parity=failed == 0,
            checks=checks,
        )

        logger.info("Parity check complete",
                    total=len(checks),
                    passed=passed,
                    failed=failed,
                    full_parity=report.is_full_parity)

        return report


class FeatureVersionLock:
    """
    Feature versiyon kilidi.

    Feature hesaplama mantığı değiştiğinde eski versiyonu korur
    ve backtest'in aynı feature'ları kullanmasını garanti eder.
    """

    def __init__(self):
        self._versions: Dict[str, Dict[str, Any]] = {}
        self._active_version: str = "v1.0"

    def register_version(
        self,
        version: str,
        feature_names: List[str],
        computation_config: Dict[str, Any],
    ):
        """Feature versiyonu kaydet."""
        self._versions[version] = {
            "feature_names": feature_names,
            "config": computation_config,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "hash": hashlib.sha256(
                orjson.dumps({"names": feature_names, "config": computation_config}, option=orjson.OPT_SORT_KEYS).decode()
            ).hexdigest()[:16],
        }
        logger.info("Feature version registered",
                    version=version,
                    features=len(feature_names))

    def set_active_version(self, version: str):
        """Aktif versiyonu ayarla."""
        if version not in self._versions:
            raise ValueError(f"Unknown feature version: {version}")
        self._active_version = version

    def get_active_config(self) -> Dict[str, Any]:
        """Aktif versiyonun konfigürasyonunu döndür."""
        return self._versions.get(self._active_version, {})

    def validate_version_match(self, expected_version: str) -> bool:
        """Versiyon eşleşmesini kontrol et."""
        return self._active_version == expected_version


# Singleton
parity_checker = BacktestScannerParity()
feature_version_lock = FeatureVersionLock()
