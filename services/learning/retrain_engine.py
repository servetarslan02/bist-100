"""
ALPHA BIST — Retrain Engine v1.0

Walk-forward validated retrain orchestrator:
- Walk-forward validation zorunlu
- Deflated Sharpe correction
- Model kabul/red kararı
- Shadow mode'a geçiş tetikleme

KURAL: Walk-forward başarısızsa → retrain yapma.
"""

import numpy as np
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from services.learning.config.learning_config import learning_settings
from services.learning.utils.statistical_tests import StatisticalTests

logger = structlog.get_logger()


@dataclass
class WalkForwardMetrics:
    """Walk-forward metrikleri."""
    avg_correlation: float
    std_correlation: float
    avg_direction_accuracy: float
    std_direction_accuracy: float
    avg_sharpe: float
    deflated_sharpe: float
    total_splits: int
    passed_splits: int
    pass_rate: float


@dataclass
class RetrainResult:
    """Retrain sonucu."""
    success: bool
    version_id: str
    reason: str
    wf_metrics: Optional[WalkForwardMetrics]
    shadow_started: bool
    timestamp: str
    training_samples: int
    regime: str


class RetrainEngine:
    """Walk-forward validated retrain orchestrator."""

    def __init__(self):
        self._retrain_history: List[RetrainResult] = []
        self._last_retrain: Optional[RetrainResult] = None
        self._retrain_count: int = 0

    def validate_and_retrain(
        self,
        model_fn: Callable,
        features_map: Dict[str, np.ndarray],
        returns: Dict[str, float],
        dates: List[Any],
        regime: str = "UNKNOWN",
        feature_fn: Optional[Callable] = None,
    ) -> RetrainResult:
        """Walk-forward validation ile retrain.

        1. Walk-forward validation çalıştır
        2. Metrikleri değerlendir
        3. Deflated Sharpe hesapla
        4. Model kabul/red kararı
        5. Kabul ise → model eğit ve shadow mode'a al

        Args:
            model_fn: Model oluşturucu fonksiyon
            features_map: Feature verileri
            returns: Getiri verileri
            dates: Tarih listesi
            feature_fn: Feature çıkarma fonksiyonu

        Returns:
            RetrainResult
        """
        cfg = learning_settings.retrain
        version_id = self._generate_version_id()

        # 1. Walk-forward validation
        wf_metrics = self._run_walk_forward(
            model_fn, features_map, returns, dates, feature_fn, cfg
        )

        if wf_metrics is None:
            return RetrainResult(
                success=False, version_id="", reason="Walk-forward validation failed",
                wf_metrics=None, shadow_started=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                training_samples=0, regime=regime,
            )

        # 2. Model kabul/red kararı
        accepted, reason = self._evaluate_wf_metrics(wf_metrics, cfg)

        if not accepted:
            logger.warning("Retrain rejected", reason=reason,
                         correlation=wf_metrics.avg_correlation,
                         accuracy=wf_metrics.avg_direction_accuracy)
            return RetrainResult(
                success=False, version_id=version_id, reason=reason,
                wf_metrics=wf_metrics, shadow_started=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                training_samples=sum(len(v) for v in features_map.values()) if isinstance(next(iter(features_map.values())), np.ndarray) else 0,
                regime=regime,
            )

        # 3. Model eğit (tüm veriyle)
        try:
            model = model_fn()
            X = self._prepare_features(features_map, feature_fn)
            y = np.array([returns.get(d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d), 0) for d in dates])

            # NaN temizle
            mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
            X, y = X[mask], y[mask]

            if len(X) < cfg.min_samples:
                return RetrainResult(
                    success=False, version_id=version_id,
                    reason=f"Insufficient training data: {len(X)} < {cfg.min_samples}",
                    wf_metrics=wf_metrics, shadow_started=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    training_samples=len(X), regime=regime,
                )

            model.fit(X, y)
            self._retrain_count += 1

            result = RetrainResult(
                success=True, version_id=version_id,
                reason="Walk-forward validation passed",
                wf_metrics=wf_metrics, shadow_started=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
                training_samples=len(X), regime=regime,
            )

            self._retrain_history.append(result)
            self._last_retrain = result

            logger.info("Retrain completed",
                       version=version_id, samples=len(X),
                       wf_correlation=wf_metrics.avg_correlation,
                       wf_accuracy=wf_metrics.avg_direction_accuracy,
                       deflated_sharpe=wf_metrics.deflated_sharpe)

            return result

        except Exception as e:
            logger.error("Retrain failed", error=str(e))
            return RetrainResult(
                success=False, version_id=version_id,
                reason=f"Training error: {str(e)}",
                wf_metrics=wf_metrics, shadow_started=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                training_samples=0, regime=regime,
            )

    def get_retrain_report(self) -> Dict[str, Any]:
        """Retrain raporu."""
        if not self._last_retrain:
            return {"status": "No retrain data"}

        r = self._last_retrain
        return {
            "status": "OK",
            "last_retrain": {
                "version_id": r.version_id,
                "success": r.success,
                "reason": r.reason,
                "timestamp": r.timestamp,
                "training_samples": r.training_samples,
                "regime": r.regime,
                "shadow_started": r.shadow_started,
            },
            "wf_metrics": {
                "avg_correlation": r.wf_metrics.avg_correlation if r.wf_metrics else None,
                "avg_direction_accuracy": r.wf_metrics.avg_direction_accuracy if r.wf_metrics else None,
                "deflated_sharpe": r.wf_metrics.deflated_sharpe if r.wf_metrics else None,
                "pass_rate": r.wf_metrics.pass_rate if r.wf_metrics else None,
            } if r.wf_metrics else None,
            "total_retrains": self._retrain_count,
            "history_count": len(self._retrain_history),
        }

    # ===================== INTERNAL =====================

    def _run_walk_forward(
        self,
        model_fn: Callable,
        features_map: Dict[str, np.ndarray],
        returns: Dict[str, float],
        dates: List[Any],
        feature_fn: Optional[Callable],
        cfg: Any,
    ) -> Optional[WalkForwardMetrics]:
        """Walk-forward validation çalıştır."""
        try:
            # Tarihleri datetime'a çevir
            if dates and isinstance(dates[0], str):
                from datetime import datetime as dt
                dates = [dt.strptime(d, "%Y-%m-%d") for d in dates]

            if len(dates) < cfg.wf_train_size + cfg.wf_test_size:
                logger.warning("Insufficient data for walk-forward",
                             available=len(dates),
                             required=cfg.wf_train_size + cfg.wf_test_size)
                return None

            # Split'ler oluştur
            splits = self._generate_wf_splits(dates, cfg)
            if not splits:
                return None

            # Her split için değerlendir
            correlations = []
            accuracies = []
            sharpes = []
            passed = 0

            for i, split in enumerate(splits):
                try:
                    metrics = self._evaluate_split(
                        model_fn, features_map, returns, dates, split, feature_fn
                    )
                    if metrics:
                        correlations.append(metrics["correlation"])
                        accuracies.append(metrics["direction_accuracy"])
                        sharpes.append(metrics.get("sharpe", 0))
                        if metrics["correlation"] > cfg.wf_min_correlation:
                            passed += 1
                except Exception as e:
                    logger.debug(f"Split {i} failed", error=str(e))
                    continue

            if len(correlations) < 3:
                logger.warning("Too few successful splits", count=len(correlations))
                return None

            # Aggregate metrics
            avg_corr = float(np.mean(correlations))
            avg_acc = float(np.mean(accuracies))
            avg_sharpe = float(np.mean(sharpes))

            # Deflated Sharpe
            deflated = StatisticalTests.deflated_sharpe(
                observed_sharpe=avg_sharpe,
                n_trials=max(len(splits), 2),
                n_observations=cfg.wf_test_size,
            )

            return WalkForwardMetrics(
                avg_correlation=round(avg_corr, 4),
                std_correlation=round(float(np.std(correlations)), 4),
                avg_direction_accuracy=round(avg_acc, 2),
                std_direction_accuracy=round(float(np.std(accuracies)), 2),
                avg_sharpe=round(avg_sharpe, 4),
                deflated_sharpe=deflated,
                total_splits=len(splits),
                passed_splits=passed,
                pass_rate=round(passed / len(splits), 2) if splits else 0,
            )

        except Exception as e:
            logger.error("Walk-forward failed", error=str(e))
            return None

    def _generate_wf_splits(self, dates: List, cfg: Any) -> List[Dict]:
        """Walk-forward split'leri oluştur."""
        splits = []
        total = len(dates)
        start_idx = cfg.wf_train_size

        while start_idx + cfg.wf_test_size <= total:
            train_start = start_idx - cfg.wf_train_size
            train_end = start_idx - cfg.wf_purge_size
            test_start = start_idx
            test_end = min(start_idx + cfg.wf_test_size, total)

            if train_end > train_start and test_end > test_start:
                splits.append({
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                })

            start_idx += cfg.wf_step_size

        return splits

    def _evaluate_split(
        self,
        model_fn: Callable,
        features_map: Dict[str, np.ndarray],
        returns: Dict[str, float],
        dates: List,
        split: Dict,
        feature_fn: Optional[Callable],
    ) -> Optional[Dict[str, float]]:
        """Tek split değerlendir."""
        # Feature matrix hazırla (tüm veri)
        try:
            X_all = self._prepare_features(features_map, feature_fn)
        except Exception as e:
            return None

        # Split indeksleri
        train_start = split["train_start"]
        train_end = split["train_end"]
        test_start = split["test_start"]
        test_end = split["test_end"]

        # Sınırları kontrol et
        if train_end > len(X_all) or test_end > len(X_all):
            return None

        # Train ve test verilerini indeksle ayır
        X_train = X_all[train_start:train_end]
        X_test = X_all[test_start:test_end]

        # Getirileri hazırla
        train_dates = dates[train_start:train_end]
        test_dates = dates[test_start:test_end]
        y_train = np.array([returns.get(d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d), 0) for d in train_dates])
        y_test = np.array([returns.get(d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d), 0) for d in test_dates])

        # NaN temizle
        train_mask = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
        test_mask = np.isfinite(X_test).all(axis=1) & np.isfinite(y_test)

        X_train, y_train = X_train[train_mask], y_train[train_mask]
        X_test, y_test = X_test[test_mask], y_test[test_mask]

        if len(X_train) < 50 or len(X_test) < 5:
            return None

        # Model eğit
        model = model_fn()
        model.fit(X_train, y_train)

        # Tahmin
        predictions = model.predict(X_test)

        # Metrikler
        correlation = float(np.corrcoef(predictions, y_test)[0, 1]) if len(predictions) > 1 else 0
        if np.isnan(correlation):
            correlation = 0

        pred_dir = np.sign(predictions)
        actual_dir = np.sign(y_test)
        direction_accuracy = float(np.mean(pred_dir == actual_dir) * 100)

        sharpe = StatisticalTests.sharpe_ratio(y_test[pred_dir == actual_dir]) if np.any(pred_dir == actual_dir) else 0

        return {
            "correlation": correlation,
            "direction_accuracy": direction_accuracy,
            "sharpe": sharpe,
        }

    def _prepare_features(
        self,
        features_map: Dict[str, np.ndarray],
        feature_fn: Optional[Callable],
    ) -> np.ndarray:
        """Feature matrix hazırla."""
        if feature_fn:
            return feature_fn(features_map)

        # Dict of arrays → matrix
        arrays = []
        for name, values in features_map.items():
            if isinstance(values, np.ndarray) and values.ndim == 1:
                arrays.append(values)

        if not arrays:
            raise ValueError("No valid features found")

        # Uzunlukları eşitle
        min_len = min(len(a) for a in arrays)
        return np.column_stack([a[:min_len] for a in arrays])

    def _prepare_features_for_dates(
        self,
        features_map: Dict[str, np.ndarray],
        dates: List,
        feature_fn: Optional[Callable],
    ) -> Optional[np.ndarray]:
        """Belirli tarihler için feature matrix."""
        try:
            X = self._prepare_features(features_map, feature_fn)
            # Basit: ilk N satırı al (gerçek implementasyonda tarih bazlı filtreleme)
            return X[:len(dates)] if len(X) >= len(dates) else X
        except Exception as e:
            return None

    def _evaluate_wf_metrics(self, metrics: WalkForwardMetrics, cfg: Any) -> tuple:
        """Walk-forward metriklerini değerlendir."""
        if metrics.avg_correlation < cfg.wf_min_correlation:
            return False, f"Correlation too low: {metrics.avg_correlation} < {cfg.wf_min_correlation}"

        if metrics.avg_direction_accuracy < cfg.wf_min_direction_accuracy:
            return False, f"Direction accuracy too low: {metrics.avg_direction_accuracy} < {cfg.wf_min_direction_accuracy}"

        if metrics.pass_rate < 0.5:
            return False, f"Pass rate too low: {metrics.pass_rate} < 0.5"

        return True, "Validation passed"

    def _generate_version_id(self) -> str:
        """Versiyon ID oluştur."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        import hashlib
        random_hash = hashlib.md5(str(np.random.random()).encode()).hexdigest()[:6]
        return f"retrain_{timestamp}_{random_hash}"


# Singleton
retrain_engine = RetrainEngine()
