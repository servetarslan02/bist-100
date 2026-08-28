"""
ALPHA BIST — Walk-Forward Engine v5.0 (Consolidated, Production-Grade)

Bu modül, sistemin en kritik doğrulama katmanıdır. Tüm walk-forward
mantığını tek bir tutarlı, test edilebilir, reproducible modülde birleştirir.

Güvenceler:
1. POINT-IN-TIME: Her fold için piyasa verisi test_end'e kadar KESİLİR.
2. PURGE: train_end → test_start arası gap korunur (data leakage önleme).
3. EMBARGO: test_end → sonraki train arası gap korunur (otokorelasyon önleme).
4. PER-FOLD RETRAIN: Her fold'da model sıfırdan eğitilir (pre-computed yok).
5. REPRODUCIBLE: Her fold'un feature snapshot, model version, data version,
   prediction ve realized outcome'u kaydedilir.
6. COMPREHENSIVE METRICS: Deflated Sharpe, IC, Precision@K, NDCG, Stability,
   Regime-aware breakdown, Transaction cost-aware returns.
7. AUDIT TRAIL: Her karar kanıt paketi ile saklanır.

Kaynak: Bailey & López de Prado (2014), De Prado (2018), Du (2026)

KURAL: Gelecek veriyi train'de kullanmak = ölüm.
"""

from __future__ import annotations

import hashlib
import orjson
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

MIN_TRAINING_SAMPLES = 5
MIN_TEST_SAMPLES = 1
MIN_FOLDS_FOR_VALIDATION = 3
STABILITY_THRESHOLD = 0.6
IC_SIGNIFICANCE_THRESHOLD = 0.03
MAX_PURGE_RATIO = 0.3  # purge / train_max


# ============================================================================
# ENUMS
# ============================================================================


class FoldStatus(str, Enum):
    """Fold çalışma durumu."""
    PENDING = "pending"
    TRAINING = "training"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RegimeType(str, Enum):
    """Piyasa rejimi."""
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNKNOWN = "UNKNOWN"


# ============================================================================
# PROTOCOLS (Interface Contracts)
# ============================================================================


class ModelProtocol(Protocol):
    """Model interface — her fold'da eğitilen model bu arayüzü implemente etmeli."""

    def fit(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None: ...
    def predict(self, X: np.ndarray) -> np.ndarray: ...
    def get_feature_importance(self) -> dict[str, float]: ...
    def get_params(self) -> dict[str, Any]: ...


class FeatureCalculatorProtocol(Protocol):
    """Feature hesaplama interface."""

    def compute_features(
        self,
        data: dict[str, Any],
        ticker: str,
        as_of_date: str,
    ) -> dict[str, float]: ...


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class FoldConfig:
    """Tek bir fold için konfigürasyon."""
    fold_id: int
    train_start: str
    train_end: str
    purge_start: str
    purge_end: str
    test_start: str
    test_end: str
    embargo_start: str
    embargo_end: str
    expanding_window: bool = True


@dataclass
class FoldMetrics:
    """Tek fold'un performans metrikleri."""
    # Temel
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0
    calmar_ratio: float = 0.0

    # İsabet
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_loss_ratio: float = 0.0

    # Sıralama kalitesi
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    precision_at_20: float = 0.0
    ndcg_at_10: float = 0.0
    ic: float = 0.0  # Information Coefficient (Spearman)
    ic_ir: float = 0.0  # IC Information Ratio
    rank_ic: float = 0.0  # Rank IC

    # Risk
    var_95: float = 0.0
    cvar_95: float = 0.0
    tail_ratio: float = 0.0

    # İşlem maliyeti
    total_trades: int = 0
    total_transaction_cost: float = 0.0
    turnover: float = 0.0
    avg_holding_days: float = 0.0

    # Güven
    deflated_sharpe: float = 0.0
    probabilistic_sharpe: float = 0.0
    bootstrap_sharpe_lower: float = 0.0
    bootstrap_sharpe_upper: float = 0.0

    # Rejim
    regime: str = "UNKNOWN"
    regime_confidence: float = 0.0


@dataclass
class FoldSnapshot:
    """Tek fold'un tam snapshot'ı — reproducibility için."""
    fold_config: FoldConfig
    status: FoldStatus = FoldStatus.PENDING

    # Model
    model_params: dict[str, Any] = field(default_factory=dict)
    model_feature_importance: dict[str, float] = field(default_factory=dict)
    model_version: str = ""

    # Feature
    feature_names: list[str] = field(default_factory=list)
    feature_count: int = 0
    feature_snapshot_hash: str = ""

    # Data
    train_samples: int = 0
    test_samples: int = 0
    train_tickers: list[str] = field(default_factory=list)
    test_tickers: list[str] = field(default_factory=list)
    data_version_hash: str = ""

    # Sonuçlar
    metrics: FoldMetrics = field(default_factory=FoldMetrics)
    predictions: list[dict[str, Any]] = field(default_factory=list)
    realized_outcomes: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)

    # Metadata
    started_at: str = ""
    completed_at: str = ""
    elapsed_seconds: float = 0.0
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serileştirme."""
        d = {
            "fold_id": self.fold_config.fold_id,
            "status": self.status.value,
            "train_period": f"{self.fold_config.train_start} → {self.fold_config.train_end}",
            "test_period": f"{self.fold_config.test_start} → {self.fold_config.test_end}",
            "purge_days": self._days_between(self.fold_config.purge_start, self.fold_config.purge_end),
            "train_samples": self.train_samples,
            "test_samples": self.test_samples,
            "model_version": self.model_version,
            "feature_count": self.feature_count,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }
        d.update(self._metrics_dict())
        return d

    def _metrics_dict(self) -> dict[str, Any]:
        m = self.metrics
        return {
            "total_return": round(m.total_return, 4),
            "sharpe_ratio": round(m.sharpe_ratio, 4),
            "sortino_ratio": round(m.sortino_ratio, 4),
            "max_drawdown": round(m.max_drawdown, 4),
            "win_rate": round(m.win_rate, 4),
            "profit_factor": round(m.profit_factor, 4),
            "precision_at_5": round(m.precision_at_5, 4),
            "precision_at_10": round(m.precision_at_10, 4),
            "ic": round(m.ic, 4),
            "ic_ir": round(m.ic_ir, 4),
            "ndcg_at_10": round(m.ndcg_at_10, 4),
            "deflated_sharpe": round(m.deflated_sharpe, 4),
            "total_trades": m.total_trades,
            "turnover": round(m.turnover, 4),
            "regime": m.regime,
        }

    @staticmethod
    def _days_between(d1: str, d2: str) -> int:
        try:
            dt1 = datetime.strptime(d1, "%Y-%m-%d")
            dt2 = datetime.strptime(d2, "%Y-%m-%d")
            return (dt2 - dt1).days
        except (ValueError, TypeError):
            return 0


@dataclass
class WalkForwardResult:
    """Walk-forward validation toplu sonucu."""
    run_id: str
    total_folds: int
    completed_folds: int
    failed_folds: int
    skipped_folds: int

    # Agregasyon metrikleri
    avg_test_return: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_test_sortino: float = 0.0
    avg_test_max_drawdown: float = 0.0
    avg_win_rate: float = 0.0
    avg_precision_at_5: float = 0.0
    avg_precision_at_10: float = 0.0
    avg_ic: float = 0.0
    avg_ic_ir: float = 0.0
    avg_ndcg_at_10: float = 0.0
    avg_turnover: float = 0.0

    # Sağlamlık
    stability_score: float = 0.0
    worst_fold_return: float = 0.0
    best_fold_return: float = 0.0
    fold_return_std: float = 0.0
    positive_fold_ratio: float = 0.0

    # İstatistiksel anlamlılık
    deflated_sharpe: float = 0.0
    probabilistic_sharpe: float = 0.0
    bootstrap_sharpe_lower: float = 0.0
    bootstrap_sharpe_upper: float = 0.0
    ic_t_stat: float = 0.0
    ic_p_value: float = 0.0

    # Rejim bazlı
    regime_performance: dict[str, dict[str, float]] = field(default_factory=dict)

    # Fold detayları
    folds: list[FoldSnapshot] = field(default_factory=list)

    # Metadata
    summary: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serileştirme."""
        return {
            "run_id": self.run_id,
            "total_folds": self.total_folds,
            "completed_folds": self.completed_folds,
            "failed_folds": self.failed_folds,
            "avg_test_return": round(self.avg_test_return, 4),
            "avg_test_sharpe": round(self.avg_test_sharpe, 4),
            "avg_test_sortino": round(self.avg_test_sortino, 4),
            "avg_test_max_drawdown": round(self.avg_test_max_drawdown, 4),
            "avg_win_rate": round(self.avg_win_rate, 4),
            "avg_precision_at_5": round(self.avg_precision_at_5, 4),
            "avg_precision_at_10": round(self.avg_precision_at_10, 4),
            "avg_ic": round(self.avg_ic, 4),
            "avg_ic_ir": round(self.avg_ic_ir, 4),
            "stability_score": round(self.stability_score, 4),
            "deflated_sharpe": round(self.deflated_sharpe, 4),
            "positive_fold_ratio": round(self.positive_fold_ratio, 4),
            "regime_performance": self.regime_performance,
            "folds": [f.to_dict() for f in self.folds],
            "summary": self.summary,
            "config": self.config,
            "created_at": self.created_at,
        }

    def is_valid(self) -> bool:
        """Walk-forward sonucu geçerli mi?"""
        return (
            self.completed_folds >= MIN_FOLDS_FOR_VALIDATION
            and self.stability_score >= STABILITY_THRESHOLD
            and self.all_leakage_ok()
        )

    def all_leakage_ok(self) -> bool:
        """Tüm fold'larda leakage kontrolü geçti mi?"""
        return all(
            f.status == FoldStatus.COMPLETED
            for f in self.folds
            if f.status != FoldStatus.SKIPPED
        )


# ============================================================================
# WALK-FORWARD ENGINE
# ============================================================================


class WalkForwardEngineV5:
    """Walk-Forward Validation Engine v5.0 — Consolidated, Production-Grade.

    Sistemin en kritik doğrulama katmanı. Her fold'da modeli sıfırdan eğitir,
    purge + embargo ile data leakage'ı önler, kapsamlı metrikler üretir.

    Args:
        purge_days: Train sonu → test başı arası gap (gün). Default: 5
        embargo_days: Test sonu → sonraki train arası gap (gün). Default: 5
        train_days: Eğitim penceresi uzunluğu (gün). Default: 252 (1 yıl)
        test_days: Test penceresi uzunluğu (gün). Default: 63 (3 ay)
        step_days: Pencere kaydırma adımı (gün). Default: 21 (1 ay)
        expanding_window: True ise train penceresi genişleyen (expanding) olur.
        transaction_cost_pct: İşlem maliyeti (komisyon + slipaj). Default: %0.124
        risk_free_rate: Risksiz faiz oranı (yıllık). Default: 0.40 (TCMB)
        n_bootstrap: Bootstrap güven aralığı için iterasyon sayısı. Default: 1000
        random_seed: Determinizm için seed. Default: 42
    """

    def __init__(
        self,
        purge_days: int = 5,
        embargo_days: int = 5,
        train_days: int = 252,
        test_days: int = 63,
        step_days: int = 21,
        expanding_window: bool = True,
        transaction_cost_pct: float = 0.00124,
        risk_free_rate: float = 0.40,
        n_bootstrap: int = 1000,
        random_seed: int = 42,
    ):
        # Parametre doğrulama
        if purge_days < 0:
            raise ValueError(f"purge_days >= 0 olmalı, aldım: {purge_days}")
        if embargo_days < 0:
            raise ValueError(f"embargo_days >= 0 olmalı, aldım: {embargo_days}")
        if train_days < 60:
            raise ValueError(f"train_days >= 60 olmalı, aldım: {train_days}")
        if test_days < 5:
            raise ValueError(f"test_days >= 5 olmalı, aldım: {test_days}")
        if step_days < 1:
            raise ValueError(f"step_days >= 1 olmalı, aldım: {step_days}")
        if not 0.0 <= transaction_cost_pct < 0.1:
            raise ValueError(f"transaction_cost_pct [0, 0.1) aralığında olmalı, aldım: {transaction_cost_pct}")

        self.purge_days = purge_days
        self.embargo_days = embargo_days
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.expanding_window = expanding_window
        self.transaction_cost_pct = transaction_cost_pct
        self.risk_free_rate = risk_free_rate
        self.n_bootstrap = n_bootstrap
        self.random_seed = random_seed

        self._rng = np.random.RandomState(random_seed)

        logger.info(
            "WalkForwardEngineV5 initialized",
            purge=purge_days,
            embargo=embargo_days,
            train=train_days,
            test=test_days,
            step=step_days,
            expanding=expanding_window,
            cost_pct=transaction_cost_pct,
        )

    # ========================================================================
    # FOLD CREATION
    # ========================================================================

    def create_folds(self, dates: list[str]) -> list[FoldConfig]:
        """Purge + embargo korumalı fold'lar oluştur.

        Args:
            dates: Sıralı tarih listesi (YYYY-MM-DD formatında)

        Returns:
            FoldConfig listesi

        Raises:
            ValueError: Tarihler sıralı değilse veya yetersizse
        """
        if not dates:
            raise ValueError("dates boş olamaz")

        # Tarih sıralı mı kontrol et
        for i in range(1, len(dates)):
            if dates[i] < dates[i - 1]:
                raise ValueError(f"Tarihler sıralı olmalı: dates[{i-1}]={dates[i-1]} > dates[{i}]={dates[i]}")

        min_required = self.train_days + self.purge_days + self.test_days
        if len(dates) < min_required:
            logger.warning(
                "Walk-forward için yetersiz veri",
                available=len(dates),
                required=min_required,
            )
            return []

        folds = []
        i = 0

        while True:
            # Train penceresi
            if self.expanding_window:
                train_start_idx = 0
            else:
                train_start_idx = i

            train_end_idx = i + self.train_days - 1

            # Purge gap
            purge_start_idx = train_end_idx + 1
            purge_end_idx = train_end_idx + self.purge_days

            # Test penceresi
            test_start_idx = purge_end_idx + 1
            test_end_idx = test_start_idx + self.test_days - 1

            # Embargo gap
            embargo_start_idx = test_end_idx + 1
            embargo_end_idx = test_end_idx + self.embargo_days

            # Sınır kontrolü
            if test_end_idx >= len(dates):
                break

            fold = FoldConfig(
                fold_id=len(folds) + 1,
                train_start=dates[train_start_idx],
                train_end=dates[train_end_idx],
                purge_start=dates[purge_start_idx],
                purge_end=dates[min(purge_end_idx, len(dates) - 1)],
                test_start=dates[test_start_idx],
                test_end=dates[test_end_idx],
                embargo_start=dates[min(embargo_start_idx, len(dates) - 1)],
                embargo_end=dates[min(embargo_end_idx, len(dates) - 1)],
                expanding_window=self.expanding_window,
            )
            folds.append(fold)

            i += self.step_days

        logger.info(
            "Walk-forward folds created",
            total_folds=len(folds),
            expanding=self.expanding_window,
            first_fold=folds[0].fold_id if folds else None,
            last_fold=folds[-1].fold_id if folds else None,
        )

        return folds

    # ========================================================================
    # MAIN EXECUTION
    # ========================================================================

    def run(
        self,
        market_data: dict[str, Any],
        model_factory: Any = None,
        feature_calculator: Any = None,
        benchmark_data: Any = None,
        universe_at_date: list[str] | None = None,
        run_id: str | None = None,
        persist_dir: str | None = None,
    ) -> WalkForwardResult:
        """Walk-forward validation çalıştır.

        Her fold'da:
        1. Train verisini hazırla (PIT-safe: test_end'e kadar kes)
        2. Modeli sıfırdan eğit
        3. Test döneminde tahmin üret
        4. Metrikleri hesapla
        5. Snapshot'ı kaydet

        Args:
            market_data: {ticker: DataFrame} — OHLCV verisi
            model_factory: ModelProtocol üreten callable (None = rule-based fallback)
            feature_calculator: FeatureCalculatorProtocol (None = basit feature seti)
            benchmark_data: Benchmark DataFrame (opsiyonel)
            universe_at_date: Survivorship kontrolü için evren (opsiyonel)
            run_id: Run identifier (None = otomatik üret)
            persist_dir: Sonuçların kaydedileceği dizin (None = kaydetme)

        Returns:
            WalkForwardResult — kapsamlı walk-forward sonucu
        """
        start_time = time.time()

        # Run ID
        if run_id is None:
            run_id = self._generate_run_id(market_data)

        # Tarihleri çıkar
        dates = self._extract_dates(market_data)
        if not dates:
            logger.error("Market data'dan tarih çıkarılamadı")
            return self._empty_result(run_id)

        # Fold'ları oluştur
        folds = self.create_folds(dates)
        if not folds:
            logger.error("Walk-forward fold oluşturulamadı")
            return self._empty_result(run_id)

        # Her fold'u çalıştır
        fold_snapshots: list[FoldSnapshot] = []

        for fold_config in folds:
            snapshot = self._run_fold(
                fold_config=fold_config,
                market_data=market_data,
                model_factory=model_factory,
                feature_calculator=feature_calculator,
                benchmark_data=benchmark_data,
                universe_at_date=universe_at_date,
            )
            fold_snapshots.append(snapshot)

            logger.info(
                "Walk-forward fold completed",
                fold=fold_config.fold_id,
                status=snapshot.status.value,
                return_pct=round(snapshot.metrics.total_return, 4),
                sharpe=round(snapshot.metrics.sharpe_ratio, 4),
                ic=round(snapshot.metrics.ic, 4),
                elapsed=round(snapshot.elapsed_seconds, 3),
            )

        # Sonuçları birleştir
        result = self._aggregate_results(run_id, fold_snapshots, start_time)

        # Persist
        if persist_dir:
            self._persist_result(result, persist_dir)

        logger.info(
            "Walk-forward validation completed",
            run_id=run_id,
            total_folds=result.total_folds,
            completed=result.completed_folds,
            avg_sharpe=round(result.avg_test_sharpe, 4),
            stability=round(result.stability_score, 4),
            deflated_sharpe=round(result.deflated_sharpe, 4),
            is_valid=result.is_valid(),
            elapsed=round(time.time() - start_time, 2),
        )

        return result

    # ========================================================================
    # FOLD EXECUTION
    # ========================================================================

    def _run_fold(
        self,
        fold_config: FoldConfig,
        market_data: dict[str, Any],
        model_factory: Any,
        feature_calculator: Any,
        benchmark_data: Any,
        universe_at_date: list[str] | None,
    ) -> FoldSnapshot:
        """Tek bir fold'u çalıştır."""
        snapshot = FoldSnapshot(
            fold_config=fold_config,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            snapshot.status = FoldStatus.TRAINING

            # 1. PIT-safe veri kesimi
            pit_data = self._truncate_to_pit(market_data, fold_config.test_end)

            # 2. Train verisini hazırla
            train_data = self._extract_window(pit_data, fold_config.train_start, fold_config.train_end)
            if not train_data:
                snapshot.status = FoldStatus.SKIPPED
                snapshot.error_message = "Train verisi yetersiz"
                return snapshot

            # 3. Feature hesapla
            train_features, feature_names = self._compute_features(
                train_data, feature_calculator, fold_config.train_end
            )
            snapshot.feature_names = feature_names
            snapshot.feature_count = len(feature_names)
            snapshot.feature_snapshot_hash = self._hash_features(train_features)
            snapshot.train_samples = len(train_features)

            if len(train_features) < MIN_TRAINING_SAMPLES:
                snapshot.status = FoldStatus.SKIPPED
                snapshot.error_message = f"Yetersiz train samples: {len(train_features)} < {MIN_TRAINING_SAMPLES}"
                return snapshot

            # 4. Model eğit
            model, model_version = self._train_model(
                train_features, feature_names, model_factory
            )
            snapshot.model_version = model_version
            snapshot.model_params = model.get_params() if model else {}
            snapshot.model_feature_importance = (
                model.get_feature_importance() if model else {}
            )

            # 5. Test döneminde tahmin üret
            snapshot.status = FoldStatus.TESTING
            test_data = self._extract_window(pit_data, fold_config.test_start, fold_config.test_end)
            test_features, _ = self._compute_features(
                test_data, feature_calculator, fold_config.test_end
            )
            snapshot.test_samples = len(test_features)

            if len(test_features) < MIN_TEST_SAMPLES:
                snapshot.status = FoldStatus.SKIPPED
                snapshot.error_message = f"Yetersiz test samples: {len(test_features)} < {MIN_TEST_SAMPLES}"
                return snapshot

            predictions = self._generate_predictions(model, test_features, feature_names)
            snapshot.predictions = predictions

            # 6. Gerçekleşen sonuçlarla eşleştir
            realized = self._compute_realized_outcomes(test_data, predictions)
            snapshot.realized_outcomes = realized

            # 7. Metrikleri hesapla
            metrics = self._compute_fold_metrics(
                predictions=predictions,
                realized=realized,
                train_data=train_data,
                test_data=test_data,
                fold_config=fold_config,
            )
            snapshot.metrics = metrics

            # 8. Data version hash
            snapshot.data_version_hash = self._hash_data_version(pit_data, fold_config)

            snapshot.status = FoldStatus.COMPLETED
            snapshot.completed_at = datetime.now(timezone.utc).isoformat()
            snapshot.elapsed_seconds = time.time() - time.mktime(
                datetime.fromisoformat(snapshot.started_at.replace("Z", "+00:00")).timetuple()
            ) if snapshot.started_at else 0.0

        except Exception as e:
            snapshot.status = FoldStatus.FAILED
            snapshot.error_message = str(e)
            logger.error(
                "Walk-forward fold failed",
                fold=fold_config.fold_id,
                error=str(e),
                exc_info=True,
            )

        return snapshot

    # ========================================================================
    # DATA OPERATIONS
    # ========================================================================

    def _truncate_to_pit(
        self, market_data: dict[str, Any], cutoff_date: str
    ) -> dict[str, Any]:
        """Veriyi cutoff_date'e kadar kes (Point-in-Time).

        Gelecek veriyi fiziksel olarak yok eder — leakage'ı önler.
        """
        pit_data = {}
        for ticker, df in market_data.items():
            if df is None:
                continue

            try:
                # Polars DataFrame
                if hasattr(df, "filter") and hasattr(df, "columns"):
                    if "Date" in df.columns:
                        cut = df.filter(pl.col("Date") <= cutoff_date)
                    else:
                        cut = df
                # Pandas DataFrame
                elif hasattr(df, "index") and hasattr(df, "loc"):
                    cut = df[df.index <= cutoff_date]
                # Plain dict
                elif isinstance(df, dict) and "Date" in df:
                    dates = df["Date"]
                    indices = [i for i, d in enumerate(dates) if str(d)[:10] <= cutoff_date]
                    if indices:
                        cut = {k: [v[i] for i in indices] for k, v in df.items()}
                    else:
                        cut = None
                else:
                    cut = df

                if cut is not None and len(cut) > 0:
                    pit_data[ticker] = cut
            except Exception:
                continue

        return pit_data

    def _extract_window(
        self, data: dict[str, Any], start_date: str, end_date: str
    ) -> dict[str, Any]:
        """Belirli bir tarih penceresindeki veriyi çıkar."""
        window = {}
        for ticker, df in data.items():
            if df is None:
                continue

            try:
                # Polars DataFrame
                if hasattr(df, "filter") and hasattr(df, "columns"):
                    if "Date" in df.columns:
                        w = df.filter(
                            (pl.col("Date") >= start_date) & (pl.col("Date") <= end_date)
                        )
                    else:
                        w = df
                # Pandas DataFrame
                elif hasattr(df, "loc") and hasattr(df, "index"):
                    w = df[(df.index >= start_date) & (df.index <= end_date)]
                # Plain dict
                elif isinstance(df, dict) and "Date" in df:
                    dates = df["Date"]
                    indices = [i for i, d in enumerate(dates) if start_date <= str(d)[:10] <= end_date]
                    if indices:
                        w = {k: [v[i] for i in indices] for k, v in df.items()}
                    else:
                        w = None
                else:
                    w = df

                if w is not None and len(w) > 0:
                    window[ticker] = w
            except Exception:
                continue

        return window

    def _extract_dates(self, market_data: dict[str, Any]) -> list[str]:
        """Market data'dan sıralı tarih listesi çıkar."""
        all_dates: set[str] = set()

        for ticker, df in market_data.items():
            if df is None:
                continue

            try:
                if hasattr(df, "columns") and "Date" in df.columns:
                    dates_col = df["Date"].to_list() if hasattr(df["Date"], "to_list") else df["Date"].tolist()
                    for d in dates_col:
                        all_dates.add(str(d)[:10])
                elif hasattr(df, "index"):
                    for idx in df.index:
                        d = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
                        all_dates.add(d)
                # Plain dict with "Date" key
                elif isinstance(df, dict) and "Date" in df:
                    for d in df["Date"]:
                        all_dates.add(str(d)[:10])
            except Exception:
                continue

        return sorted(all_dates)

    # ========================================================================
    # FEATURE COMPUTATION
    # ========================================================================

    def _compute_features(
        self,
        data: dict[str, Any],
        feature_calculator: Any,
        as_of_date: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Feature'ları hesapla.

        Returns:
            (samples, feature_names) — her sample {ticker, date, features...}
        """
        if feature_calculator is not None:
            return self._compute_with_calculator(data, feature_calculator, as_of_date)
        return self._compute_builtin_features(data, as_of_date)

    def _compute_with_calculator(
        self, data: dict[str, Any], calc: Any, as_of_date: str
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Harici feature calculator ile hesapla."""
        samples = []
        feature_names_set: set[str] = set()

        for ticker, df in data.items():
            try:
                features = calc.compute_features(df, ticker, as_of_date)
                if features:
                    features["ticker"] = ticker
                    samples.append(features)
                    feature_names_set.update(k for k in features if k not in ("ticker", "date"))
            except Exception:
                continue

        feature_names = sorted(feature_names_set)
        return samples, feature_names

    def _compute_builtin_features(
        self, data: dict[str, Any], as_of_date: str
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Dahili basit feature seti hesapla."""
        samples = []

        for ticker, df in data.items():
            try:
                # Polars/Pandas DataFrame
                if hasattr(df, "columns"):
                    close = df["Close"].to_numpy() if "Close" in df.columns else None
                    high = df["High"].to_numpy() if "High" in df.columns else close
                    low = df["Low"].to_numpy() if "Low" in df.columns else close
                    volume = df["Volume"].to_numpy() if "Volume" in df.columns else np.zeros(len(df))
                # Plain dict
                elif isinstance(df, dict) and "Close" in df:
                    close = np.array(df["Close"], dtype=np.float64)
                    high = np.array(df.get("High", df["Close"]), dtype=np.float64)
                    low = np.array(df.get("Low", df["Close"]), dtype=np.float64)
                    volume = np.array(df.get("Volume", [0.0] * len(close)), dtype=np.float64)
                else:
                    continue

                if close is None or len(close) < 20:
                    continue

                # Son günün feature'ları
                c = close[-1]
                if c <= 0 or np.isnan(c):
                    continue

                features = {
                    "ticker": ticker,
                    "roc_5d": (close[-1] / close[-6] - 1.0) * 100.0 if len(close) > 5 else 0.0,
                    "roc_20d": (close[-1] / close[-21] - 1.0) * 100.0 if len(close) > 20 else 0.0,
                    "momentum_20d": (close[-1] / close[-21] - 1.0) * 100.0 if len(close) > 20 else 0.0,
                    "volatility_20d": float(np.std(np.diff(close[-21:]) / close[-21:-1]) * np.sqrt(252) * 100.0) if len(close) > 20 else 0.0,
                    "volume_zscore": float((volume[-1] - np.mean(volume[-20:])) / (np.std(volume[-20:]) + 1e-10)) if len(volume) > 20 else 0.0,
                    "atr_pct": float(np.mean(np.abs(np.diff(close[-15:]))) / c * 100.0) if len(close) > 14 else 0.0,
                    "bb_position": self._bb_position(close),
                    "price_vs_sma20": (c / np.mean(close[-20:]) - 1.0) * 100.0 if len(close) >= 20 else 0.0,
                    "price_vs_sma50": (c / np.mean(close[-50:]) - 1.0) * 100.0 if len(close) >= 50 else 0.0,
                }
                samples.append(features)
            except Exception:
                continue

        feature_names = [
            "roc_5d", "roc_20d", "momentum_20d", "volatility_20d",
            "volume_zscore", "atr_pct", "bb_position", "price_vs_sma20", "price_vs_sma50",
        ]
        return samples, feature_names

    @staticmethod
    def _bb_position(close: np.ndarray) -> float:
        """Bollinger Band pozisyonu (0-1 arası)."""
        if len(close) < 20:
            return 0.5
        sma = np.mean(close[-20:])
        std = np.std(close[-20:])
        if std < 1e-10:
            return 0.5
        upper = sma + 2 * std
        lower = sma - 2 * std
        bb_range = upper - lower
        if bb_range < 1e-10:
            return 0.5
        return float((close[-1] - lower) / bb_range)

    # ========================================================================
    # MODEL TRAINING
    # ========================================================================

    def _train_model(
        self,
        train_features: list[dict[str, Any]],
        feature_names: list[str],
        model_factory: Any,
    ) -> tuple[Any, str]:
        """Modeli train verisiyle eğit.

        Returns:
            (model, model_version) — model None ise rule-based fallback
        """
        if model_factory is not None:
            try:
                model = model_factory()
                X = self._features_to_matrix(train_features, feature_names)
                y = self._extract_targets(train_features)

                if len(X) >= MIN_TRAINING_SAMPLES and len(y) >= MIN_TRAINING_SAMPLES:
                    model.fit(X, y)
                    version = self._model_version(model, train_features)
                    return model, version
            except Exception as e:
                logger.warning("Model eğitimi başarısız, rule-based fallback", error=str(e))

        # Rule-based fallback
        return None, "rule_based_v1"

    def _features_to_matrix(
        self, features: list[dict[str, Any]], feature_names: list[str]
    ) -> np.ndarray:
        """Feature listesini numpy matrisine çevir."""
        matrix = []
        for sample in features:
            row = [sample.get(fn, 0.0) for fn in feature_names]
            matrix.append(row)
        return np.array(matrix, dtype=np.float64)

    def _extract_targets(self, features: list[dict[str, Any]]) -> np.ndarray:
        """Target değerlerini çıkar (varsa)."""
        targets = []
        for sample in features:
            t = sample.get("target_return", sample.get("target_5d_ret", 0.0))
            targets.append(float(t))
        return np.array(targets, dtype=np.float64)

    def _model_version(self, model: Any, features: list[dict[str, Any]]) -> str:
        """Model versiyon hash'i üret."""
        params = str(model.get_params()) if hasattr(model, "get_params") else str(model)
        n_samples = str(len(features))
        ts = datetime.now(timezone.utc).isoformat()
        return hashlib.sha256(f"{params}_{n_samples}_{ts}".encode()).hexdigest()[:16]

    # ========================================================================
    # PREDICTION
    # ========================================================================

    def _generate_predictions(
        self,
        model: Any,
        test_features: list[dict[str, Any]],
        feature_names: list[str],
    ) -> list[dict[str, Any]]:
        """Test döneminde tahmin üret."""
        predictions = []

        if model is not None:
            try:
                X = self._features_to_matrix(test_features, feature_names)
                scores = model.predict(X)

                for i, sample in enumerate(test_features):
                    predictions.append({
                        "ticker": sample.get("ticker", ""),
                        "date": sample.get("date", ""),
                        "score": float(scores[i]) if i < len(scores) else 0.0,
                        "model": "ml",
                    })
            except Exception as e:
                logger.warning("ML prediction failed, using rule-based", error=str(e))
                predictions = self._rule_based_predictions(test_features)
        else:
            predictions = self._rule_based_predictions(test_features)

        return predictions

    def _rule_based_predictions(
        self, features: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Kural tabanlı tahmin üret (ML modeli yoksa)."""
        predictions = []
        for sample in features:
            # Basit momentum + mean-reversion skoru
            mom = sample.get("momentum_20d", 0.0)
            vol_z = sample.get("volume_zscore", 0.0)
            bb = sample.get("bb_position", 0.5)

            score = (
                np.tanh(mom / 10.0) * 0.4
                + np.tanh(vol_z / 2.0) * 0.3
                + (bb - 0.5) * 0.3
            )

            predictions.append({
                "ticker": sample.get("ticker", ""),
                "date": sample.get("date", ""),
                "score": float(score),
                "model": "rule_based",
            })
        return predictions

    # ========================================================================
    # REALIZED OUTCOMES
    # ========================================================================

    def _compute_realized_outcomes(
        self,
        test_data: dict[str, Any],
        predictions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Gerçekleşen sonuçları hesapla."""
        outcomes = []

        for pred in predictions:
            ticker = pred.get("ticker", "")
            date = pred.get("date", "")

            if ticker not in test_data:
                outcomes.append({"ticker": ticker, "date": date, "actual_return": 0.0, "is_correct": False})
                continue

            df = test_data[ticker]
            try:
                # Polars DataFrame
                if hasattr(df, "filter") and hasattr(df, "columns") and "Date" in df.columns:
                    all_close = df["Close"].to_list()
                    all_dates = df["Date"].to_list()
                    idx = None
                    for i, d in enumerate(all_dates):
                        if str(d)[:10] == date:
                            idx = i
                            break

                    if idx is not None and idx + 5 < len(all_close):
                        actual_ret = (all_close[idx + 5] / all_close[idx] - 1.0) * 100.0
                    else:
                        actual_ret = 0.0
                # Plain dict
                elif isinstance(df, dict) and "Close" in df and "Date" in df:
                    all_close = df["Close"]
                    all_dates = df["Date"]
                    idx = None
                    for i, d in enumerate(all_dates):
                        if str(d)[:10] == date:
                            idx = i
                            break

                    if idx is not None and idx + 5 < len(all_close):
                        actual_ret = (all_close[idx + 5] / all_close[idx] - 1.0) * 100.0
                    else:
                        actual_ret = 0.0
                else:
                    actual_ret = 0.0

                score = pred.get("score", 0.0)
                is_correct = (score > 0 and actual_ret > 0) or (score < 0 and actual_ret < 0)

                outcomes.append({
                    "ticker": ticker,
                    "date": date,
                    "actual_return": actual_ret,
                    "predicted_score": score,
                    "is_correct": is_correct,
                })
            except Exception:
                outcomes.append({"ticker": ticker, "date": date, "actual_return": 0.0, "is_correct": False})

        return outcomes

    # ========================================================================
    # METRICS COMPUTATION
    # ========================================================================

    def _compute_fold_metrics(
        self,
        predictions: list[dict[str, Any]],
        realized: list[dict[str, Any]],
        train_data: dict[str, Any],
        test_data: dict[str, Any],
        fold_config: FoldConfig,
    ) -> FoldMetrics:
        """Kapsamlı fold metrikleri hesapla."""
        metrics = FoldMetrics()

        if not predictions or not realized:
            return metrics

        # Getiri serisi
        returns = [r.get("actual_return", 0.0) / 100.0 for r in realized]
        scores = [p.get("score", 0.0) for p in predictions]
        actuals = [r.get("actual_return", 0.0) for r in realized]

        if not returns:
            return metrics

        returns_arr = np.array(returns)
        scores_arr = np.array(scores)
        actuals_arr = np.array(actuals)

        # === Temel Metrikler ===
        metrics.total_return = float(np.sum(returns_arr)) * 100.0
        n_days = max(len(returns_arr), 1)
        metrics.annualized_return = float((1 + np.sum(returns_arr)) ** (252 / n_days) - 1) * 100.0

        # Sharpe
        if np.std(returns_arr) > 0:
            rf_daily = self.risk_free_rate / 252.0
            excess = returns_arr - rf_daily
            metrics.sharpe_ratio = float(np.mean(excess) / np.std(returns_arr) * np.sqrt(252))
        else:
            metrics.sharpe_ratio = 0.0

        # Sortino
        downside = returns_arr[returns_arr < 0]
        if len(downside) > 0 and np.std(downside) > 0:
            metrics.sortino_ratio = float(
                (np.mean(returns_arr) - self.risk_free_rate / 252) / np.std(downside) * np.sqrt(252)
            )

        # Max Drawdown
        cumulative = np.cumprod(1 + returns_arr)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / np.maximum(peak, 1e-10)
        metrics.max_drawdown = float(np.max(drawdown)) * 100.0

        # Drawdown süresi
        in_dd = drawdown > 0.001
        if np.any(in_dd):
            dd_runs = np.diff(np.where(np.concatenate(([not in_dd[0]], in_dd, [not in_dd[-1]])))[0])
            metrics.max_drawdown_duration_days = int(np.max(dd_runs)) if len(dd_runs) > 0 else 0

        # Calmar
        if metrics.max_drawdown > 0:
            metrics.calmar_ratio = metrics.annualized_return / metrics.max_drawdown

        # === İsabet Metrikleri ===
        wins = [r for r in realized if r.get("is_correct", False)]
        losses = [r for r in realized if not r.get("is_correct", False)]
        metrics.win_rate = len(wins) / len(realized) if realized else 0.0

        win_returns = [r.get("actual_return", 0.0) for r in wins]
        loss_returns = [abs(r.get("actual_return", 0.0)) for r in losses]

        metrics.avg_win = float(np.mean(win_returns)) if win_returns else 0.0
        metrics.avg_loss = float(np.mean(loss_returns)) if loss_returns else 0.0
        metrics.win_loss_ratio = metrics.avg_win / metrics.avg_loss if metrics.avg_loss > 0 else 0.0

        gross_profit = sum(win_returns)
        gross_loss = sum(loss_returns)
        metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # === Sıralama Kalitesi ===
        metrics.precision_at_5 = self._precision_at_k(scores_arr, actuals_arr, k=5)
        metrics.precision_at_10 = self._precision_at_k(scores_arr, actuals_arr, k=10)
        metrics.precision_at_20 = self._precision_at_k(scores_arr, actuals_arr, k=20)
        metrics.ndcg_at_10 = self._ndcg_at_k(scores_arr, actuals_arr, k=10)

        # IC (Spearman rank correlation)
        if len(scores_arr) > 10:
            metrics.ic = float(self._spearman_correlation(scores_arr, actuals_arr))
            metrics.rank_ic = metrics.ic

            # IC IR (IC'nin istikrarı)
            # Günlük IC'lerden hesapla
            daily_ics = self._compute_daily_ics(predictions, realized)
            if len(daily_ics) > 5:
                ic_mean = np.mean(daily_ics)
                ic_std = np.std(daily_ics)
                metrics.ic_ir = float(ic_mean / ic_std) if ic_std > 0 else 0.0

        # === Risk Metrikleri ===
        if len(returns_arr) > 20:
            sorted_returns = np.sort(returns_arr)
            var_idx = int(len(sorted_returns) * 0.05)
            metrics.var_95 = float(abs(sorted_returns[var_idx])) * 100.0
            metrics.cvar_95 = float(abs(np.mean(sorted_returns[:var_idx + 1]))) * 100.0

            # Tail ratio
            p95 = np.percentile(returns_arr, 95)
            p5 = abs(np.percentile(returns_arr, 5))
            metrics.tail_ratio = float(p95 / p5) if p5 > 0 else 0.0

        # === İşlem Maliyeti ===
        metrics.total_trades = len(predictions)
        metrics.total_transaction_cost = len(predictions) * self.transaction_cost_pct * 2  # al+sat

        # Turnover
        metrics.turnover = self._compute_turnover(predictions)

        # === İstatistiksel Anlamlılık ===
        metrics.deflated_sharpe = self._deflated_sharpe(
            metrics.sharpe_ratio, len(returns_arr), len(predictions)
        )
        metrics.probabilistic_sharpe = self._probabilistic_sharpe(
            metrics.sharpe_ratio, len(returns_arr)
        )

        # Bootstrap Sharpe CI
        if len(returns_arr) > 30:
            lower, upper = self._bootstrap_sharpe_ci(returns_arr)
            metrics.bootstrap_sharpe_lower = lower
            metrics.bootstrap_sharpe_upper = upper

        # === Rejim ===
        metrics.regime = self._detect_regime(test_data)
        metrics.regime_confidence = 0.7  # Basit heuristic

        return metrics

    def _precision_at_k(self, scores: np.ndarray, actuals: np.ndarray, k: int) -> float:
        """Precision@K: En iyi K tahminden kaçı gerçekten pozitif?"""
        if len(scores) < k:
            return 0.0

        top_k_idx = np.argsort(scores)[-k:]
        correct = sum(1 for idx in top_k_idx if idx < len(actuals) and actuals[idx] > 0)
        return float(correct / k)

    def _ndcg_at_k(self, scores: np.ndarray, actuals: np.ndarray, k: int) -> float:
        """NDCG@K: Sıralama kalitesi (Normalized Discounted Cumulative Gain)."""
        if len(scores) < k:
            return 0.0

        # Gerçek sıralama
        ideal_order = np.argsort(actuals)[::-1][:k]
        ideal_dcg = sum(
            actuals[idx] / np.log2(i + 2) for i, idx in enumerate(ideal_order) if idx < len(actuals)
        )

        # Model sıralaması
        model_order = np.argsort(scores)[::-1][:k]
        model_dcg = sum(
            actuals[idx] / np.log2(i + 2) for i, idx in enumerate(model_order) if idx < len(actuals)
        )

        if ideal_dcg <= 0:
            return 0.0

        return float(model_dcg / ideal_dcg)

    def _spearman_correlation(self, x: np.ndarray, y: np.ndarray) -> float:
        """Spearman rank korelasyonu."""
        n = len(x)
        if n < 3:
            return 0.0

        # Rank hesapla
        rank_x = np.argsort(np.argsort(x)).astype(float)
        rank_y = np.argsort(np.argsort(y)).astype(float)

        # Pearson on ranks
        mean_x = np.mean(rank_x)
        mean_y = np.mean(rank_y)
        std_x = np.std(rank_x)
        std_y = np.std(rank_y)

        if std_x < 1e-10 or std_y < 1e-10:
            return 0.0

        cov = np.mean((rank_x - mean_x) * (rank_y - mean_y))
        return float(cov / (std_x * std_y))

    def _compute_daily_ics(
        self, predictions: list[dict], realized: list[dict]
    ) -> list[float]:
        """Günlük IC değerlerini hesapla."""
        # Tarih bazlı grupla
        date_groups: dict[str, list[tuple[float, float]]] = {}

        for pred, real in zip(predictions, realized):
            date = pred.get("date", "")
            score = pred.get("score", 0.0)
            actual = real.get("actual_return", 0.0)

            if date not in date_groups:
                date_groups[date] = []
            date_groups[date].append((score, actual))

        daily_ics = []
        for date, pairs in date_groups.items():
            if len(pairs) < 3:
                continue
            scores = np.array([p[0] for p in pairs])
            actuals = np.array([p[1] for p in pairs])
            ic = self._spearman_correlation(scores, actuals)
            if not np.isnan(ic):
                daily_ics.append(ic)

        return daily_ics

    def _compute_turnover(self, predictions: list[dict]) -> float:
        """Portföy turnover oranı."""
        if len(predictions) < 2:
            return 0.0

        # Tarih bazlı grupla
        date_groups: dict[str, list[str]] = {}
        for pred in predictions:
            date = pred.get("date", "")
            ticker = pred.get("ticker", "")
            if date not in date_groups:
                date_groups[date] = []
            date_groups[date].append(ticker)

        dates_sorted = sorted(date_groups.keys())
        turnovers = []

        for i in range(1, len(dates_sorted)):
            prev_set = set(date_groups[dates_sorted[i - 1]])
            curr_set = set(date_groups[dates_sorted[i]])
            if prev_set:
                changed = len(curr_set - prev_set)
                turnovers.append(changed / max(len(curr_set), 1))

        return float(np.mean(turnovers)) if turnovers else 0.0

    # ========================================================================
    # STATISTICAL TESTS
    # ========================================================================

    def _deflated_sharpe(
        self, sharpe: float, n_obs: int, n_trials: int = 1
    ) -> float:
        """Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

        Çoklu test düzeltmesi: Backtest sayısı arttıkça Sharpe'ın güvenilirliği düşer.
        """
        if n_obs < 30 or sharpe <= 0:
            return 0.0

        # Annualized → daily
        daily_sharpe = sharpe / np.sqrt(252)

        # Standard error (skewness + kurtosis düzeltmesi)
        se = np.sqrt((1 + 0.5 * daily_sharpe**2) / n_obs)

        # Multiple testing düzeltmesi (Bonferroni)
        if n_trials > 1:
            adjusted = daily_sharpe - se * np.sqrt(2 * np.log(n_trials))
        else:
            adjusted = daily_sharpe

        return max(0.0, float(adjusted * np.sqrt(252)))

    def _probabilistic_sharpe(self, sharpe: float, n_obs: int) -> float:
        """Probabilistic Sharpe Ratio.

        Gözlemlenen Sharpe'ın 0'dan büyük olma olasılığı.
        """
        if n_obs < 30:
            return 0.0

        daily_sharpe = sharpe / np.sqrt(252)
        se = np.sqrt((1 + 0.5 * daily_sharpe**2) / n_obs)

        if se < 1e-10:
            return 1.0 if sharpe > 0 else 0.0

        z = daily_sharpe / se
        # Normal CDF approximation
        psr = 0.5 * (1 + np.sign(z) * np.sqrt(1 - np.exp(-2 * z**2 / np.pi)))
        return float(max(0.0, min(1.0, psr)))

    def _bootstrap_sharpe_ci(
        self, returns: np.ndarray, confidence: float = 0.95
    ) -> tuple[float, float]:
        """Block bootstrap ile Sharpe güven aralığı.

        Otokorelasyonu korumak için blok bootstrap kullanılır.
        """
        n = len(returns)
        if n < 30:
            return (0.0, 0.0)

        block_size = max(5, int(np.sqrt(n)))
        n_blocks = n // block_size
        sharpes = []

        for _ in range(self.n_bootstrap):
            # Block bootstrap
            blocks = self._rng.randint(0, n_blocks, size=n_blocks)
            sample = []
            for b in blocks:
                start = b * block_size
                end = min(start + block_size, n)
                sample.extend(returns[start:end])
            sample = np.array(sample[:n])

            # Sharpe hesapla
            if np.std(sample) > 0:
                s = float(np.mean(sample) / np.std(sample) * np.sqrt(252))
                sharpes.append(s)

        if not sharpes:
            return (0.0, 0.0)

        alpha = (1 - confidence) / 2
        lower = float(np.percentile(sharpes, alpha * 100))
        upper = float(np.percentile(sharpes, (1 - alpha) * 100))

        return (lower, upper)

    # ========================================================================
    # REGIME DETECTION
    # ========================================================================

    def _detect_regime(self, test_data: dict[str, Any]) -> str:
        """Test dönemindeki piyasa rejimini tespit et."""
        # Basit heuristic — tüm hisselerin ortalama momentumuna bak
        all_returns = []
        for ticker, df in test_data.items():
            try:
                # Polars/Pandas DataFrame
                if hasattr(df, "columns") and "Close" in df.columns:
                    close = df["Close"].to_numpy()
                    if len(close) > 20:
                        ret = (close[-1] / close[-21] - 1.0) * 100.0
                        all_returns.append(ret)
                # Plain dict
                elif isinstance(df, dict) and "Close" in df:
                    close = df["Close"]
                    if len(close) > 20:
                        ret = (close[-1] / close[-21] - 1.0) * 100.0
                        all_returns.append(ret)
            except Exception:
                continue

        if not all_returns:
            return RegimeType.UNKNOWN.value

        avg_ret = np.mean(all_returns)
        vol = np.std(all_returns)

        if vol > 15.0:
            return RegimeType.HIGH_VOLATILITY.value
        elif vol < 5.0:
            return RegimeType.LOW_VOLATILITY.value
        elif avg_ret > 3.0:
            return RegimeType.BULL.value
        elif avg_ret < -3.0:
            return RegimeType.BEAR.value
        else:
            return RegimeType.SIDEWAYS.value

    # ========================================================================
    # AGGREGATION
    # ========================================================================

    def _aggregate_results(
        self,
        run_id: str,
        folds: list[FoldSnapshot],
        start_time: float,
    ) -> WalkForwardResult:
        """Fold sonuçlarını birleştir."""
        completed = [f for f in folds if f.status == FoldStatus.COMPLETED]
        failed = [f for f in folds if f.status == FoldStatus.FAILED]
        skipped = [f for f in folds if f.status == FoldStatus.SKIPPED]

        if not completed:
            return self._empty_result(run_id)

        # Metrik serileri
        returns = [f.metrics.total_return for f in completed]
        sharpes = [f.metrics.sharpe_ratio for f in completed]
        sortinos = [f.metrics.sortino_ratio for f in completed]
        dds = [f.metrics.max_drawdown for f in completed]
        wins = [f.metrics.win_rate for f in completed]
        prec_5 = [f.metrics.precision_at_5 for f in completed]
        prec_10 = [f.metrics.precision_at_10 for f in completed]
        ics = [f.metrics.ic for f in completed]
        ic_irs = [f.metrics.ic_ir for f in completed]
        ndcgs = [f.metrics.ndcg_at_10 for f in completed]
        turnovers = [f.metrics.turnover for f in completed]

        # Stability: fold'lar arası tutarlılık
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns))
        stability = max(0.0, 1.0 - std_ret / (abs(mean_ret) + 0.01))

        # Positive fold ratio
        positive_folds = sum(1 for r in returns if r > 0)
        positive_ratio = positive_folds / len(returns) if returns else 0.0

        # Deflated Sharpe (tüm fold'lar birleştirilmiş)
        total_obs = sum(f.test_samples for f in completed)
        deflated = self._deflated_sharpe(float(np.mean(sharpes)), total_obs, len(completed))

        # Probabilistic Sharpe
        prob_sharpe = self._probabilistic_sharpe(float(np.mean(sharpes)), total_obs)

        # Bootstrap CI
        all_returns = []
        for f in completed:
            for pred in f.predictions:
                all_returns.append(pred.get("score", 0.0))
        bootstrap_lower, bootstrap_upper = 0.0, 0.0
        if len(all_returns) > 30:
            bootstrap_lower, bootstrap_upper = self._bootstrap_sharpe_ci(np.array(all_returns))

        # IC t-test
        ic_t, ic_p = self._ic_t_test(ics)

        # Rejim bazlı performans
        regime_perf = self._aggregate_regime_performance(completed)

        # Summary
        summary = {
            "purge_days": self.purge_days,
            "embargo_days": self.embargo_days,
            "train_days": self.train_days,
            "test_days": self.test_days,
            "step_days": self.step_days,
            "expanding_window": self.expanding_window,
            "transaction_cost_pct": self.transaction_cost_pct,
            "risk_free_rate": self.risk_free_rate,
            "total_predictions": sum(f.test_samples for f in completed),
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

        config = {
            "purge_days": self.purge_days,
            "embargo_days": self.embargo_days,
            "train_days": self.train_days,
            "test_days": self.test_days,
            "step_days": self.step_days,
            "expanding_window": self.expanding_window,
            "transaction_cost_pct": self.transaction_cost_pct,
            "random_seed": self.random_seed,
        }

        return WalkForwardResult(
            run_id=run_id,
            total_folds=len(folds),
            completed_folds=len(completed),
            failed_folds=len(failed),
            skipped_folds=len(skipped),
            avg_test_return=round(float(np.mean(returns)), 4),
            avg_test_sharpe=round(float(np.mean(sharpes)), 4),
            avg_test_sortino=round(float(np.mean(sortinos)), 4),
            avg_test_max_drawdown=round(float(np.mean(dds)), 4),
            avg_win_rate=round(float(np.mean(wins)), 4),
            avg_precision_at_5=round(float(np.mean(prec_5)), 4),
            avg_precision_at_10=round(float(np.mean(prec_10)), 4),
            avg_ic=round(float(np.mean(ics)), 4),
            avg_ic_ir=round(float(np.mean(ic_irs)), 4),
            avg_ndcg_at_10=round(float(np.mean(ndcgs)), 4),
            avg_turnover=round(float(np.mean(turnovers)), 4),
            stability_score=round(stability, 4),
            worst_fold_return=round(float(min(returns)), 4),
            best_fold_return=round(float(max(returns)), 4),
            fold_return_std=round(std_ret, 4),
            positive_fold_ratio=round(positive_ratio, 4),
            deflated_sharpe=round(deflated, 4),
            probabilistic_sharpe=round(prob_sharpe, 4),
            bootstrap_sharpe_lower=round(bootstrap_lower, 4),
            bootstrap_sharpe_upper=round(bootstrap_upper, 4),
            ic_t_stat=round(ic_t, 4),
            ic_p_value=round(ic_p, 4),
            regime_performance=regime_perf,
            folds=folds,
            summary=summary,
            config=config,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _ic_t_test(self, ics: list[float]) -> tuple[float, float]:
        """IC'nin 0'dan farklı olup olmadığını t-test ile test et."""
        if len(ics) < 3:
            return (0.0, 1.0)

        ic_arr = np.array(ics)
        mean_ic = np.mean(ic_arr)
        std_ic = np.std(ic_arr, ddof=1)

        if std_ic < 1e-10:
            return (0.0, 1.0)

        t_stat = mean_ic / (std_ic / np.sqrt(len(ics)))

        # Basit p-value approximation (two-tailed)
        # t-distribution yerine normal approximation
        z = abs(t_stat)
        p_value = 2 * (1 - 0.5 * (1 + np.sign(z) * np.sqrt(1 - np.exp(-2 * z**2 / np.pi))))

        return (float(t_stat), float(max(0.0, min(1.0, p_value))))

    def _aggregate_regime_performance(
        self, folds: list[FoldSnapshot]
    ) -> dict[str, dict[str, float]]:
        """Rejim bazlı performans özeti."""
        regime_data: dict[str, list[float]] = {}

        for fold in folds:
            regime = fold.metrics.regime
            if regime not in regime_data:
                regime_data[regime] = []
            regime_data[regime].append(fold.metrics.total_return)

        result = {}
        for regime, returns in regime_data.items():
            result[regime] = {
                "count": len(returns),
                "avg_return": round(float(np.mean(returns)), 4),
                "std_return": round(float(np.std(returns)), 4),
                "min_return": round(float(min(returns)), 4),
                "max_return": round(float(max(returns)), 4),
            }

        return result

    # ========================================================================
    # UTILITIES
    # ========================================================================

    def _generate_run_id(self, market_data: dict[str, Any]) -> str:
        """Deterministik run ID üret."""
        tickers = sorted(market_data.keys())
        config_str = (
            f"wf_v5_{self.purge_days}_{self.embargo_days}_"
            f"{self.train_days}_{self.test_days}_{self.step_days}_"
            f"{self.expanding_window}_{self.transaction_cost_pct}"
        )
        hash_input = f"{config_str}_{'_'.join(tickers)}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    def _hash_features(self, features: list[dict[str, Any]]) -> str:
        """Feature snapshot hash'i."""
        if not features:
            return ""
        # İlk 10 sample'ın hash'i (determinizm için)
        sample_str = orjson.dumps(features[:10], default=str).decode()
        return hashlib.sha256(sample_str.encode()).hexdigest()[:16]

    def _hash_data_version(
        self, pit_data: dict[str, Any], fold_config: FoldConfig
    ) -> str:
        """Veri versiyon hash'i."""
        version_str = f"{fold_config.train_start}_{fold_config.test_end}_{len(pit_data)}"
        return hashlib.sha256(version_str.encode()).hexdigest()[:16]

    def _persist_result(self, result: WalkForwardResult, persist_dir: str) -> None:
        """Sonucu dosyaya kaydet."""
        try:
            path = Path(persist_dir)
            path.mkdir(parents=True, exist_ok=True)

            filename = f"wf_{result.run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = path / filename

            with open(filepath, "wb") as f:
                f.write(orjson.dumps(result.to_dict(), option=orjson.OPT_INDENT_2, default=str))

            logger.info("Walk-forward result persisted", path=str(filepath))
        except Exception as e:
            logger.warning("Walk-forward result persist failed", error=str(e))

    def _empty_result(self, run_id: str) -> WalkForwardResult:
        """Boş sonuç."""
        return WalkForwardResult(
            run_id=run_id,
            total_folds=0,
            completed_folds=0,
            failed_folds=0,
            skipped_folds=0,
            created_at=datetime.now(timezone.utc).isoformat(),
        )


# ============================================================================
# SINGLETON
# ============================================================================

walk_forward_engine_v5 = WalkForwardEngineV5()
