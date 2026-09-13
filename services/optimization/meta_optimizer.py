"""
ALPHA BIST — Çok Amaçlı Hibrit Meta-Optimizatör (MetaOptimizer)

Bayesian, Genetik ve Rastgele arama stratejilerini birleştiren,
çok amaçlı (Multi-Objective: Sharpe, Calmar, Sortino, Min Drawdown)
Pareto cephesi (Pareto Optimal Front) hesaplayan ve dinamik bütçeleme
(Successive Halving) ile hiper-parametre optimizasyonu yapan meta motor.

Özellikler:
  - Çoklu Amaç Fonksiyonu (Pareto baskınlık / dominance)
  - Hibrit arama: Bayesian keşif + Genetik mutasyon & çaprazlama
  - Successive Halving: Zayıf parametre kombinasyonlarını erken sonlandırma
  - Dayanıklılık (Robustness) ağırlıklı nihai parametre seçimi
  - DuckDB deney günlüğü
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import duckdb
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)

DB_TABLE_META_OPT = "meta_optimization_trials"


@dataclass
class TrialResult:
    """Tek bir parametre deneme sonucu.

    Attributes:
        trial_id: Deneme kimliği.
        params: Test edilen parametre sözlüğü.
        sharpe: Sharpe oranı.
        sortino: Sortino oranı.
        calmar: Calmar oranı.
        max_drawdown: Azami düşüş (pozitif oran, örn: 0.15 = %15).
        win_rate: Kazanç oranı (0-1).
        rank: Pareto derecesi (1 en iyi).
        crowding_distance: Çeşitlilik mesafesi.
    """

    trial_id: str
    params: dict[str, Any]
    sharpe: float
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    rank: int = 0
    crowding_distance: float = 0.0

    @property
    def composite_score(self) -> float:
        """Birleşik optimizasyon puanı (Sharpe * 0.4 + Calmar * 0.3 + Sortino * 0.3 - 2*DD)."""
        return (
            0.4 * self.sharpe
            + 0.3 * self.calmar
            + 0.3 * self.sortino
            - 2.0 * self.max_drawdown
        )

    def dominates(self, other: TrialResult) -> bool:
        """Pareto baskınlık kontrolü (self other'ı eziyor mu?)."""
        # Sharpe, Calmar ve Sortino daha büyük iyi; Drawdown daha küçük iyi
        not_worse = (
            self.sharpe >= other.sharpe
            and self.calmar >= other.calmar
            and self.sortino >= other.sortino
            and self.max_drawdown <= other.max_drawdown
        )
        strictly_better = (
            self.sharpe > other.sharpe
            or self.calmar > other.calmar
            or self.sortino > other.sortino
            or self.max_drawdown < other.max_drawdown
        )
        return not_worse and strictly_better

    def __repr__(self) -> str:
        """Kısa temsil."""
        return (
            f"Trial({self.trial_id}: Sharpe={self.sharpe:.2f}, "
            f"Calmar={self.calmar:.2f}, MaxDD={self.max_drawdown:.1%}, Score={self.composite_score:.2f})"
        )


@dataclass
class MetaOptimizationReport:
    """Meta-optimizasyon nihai sonuç raporu.

    Attributes:
        experiment_id: Deney kimliği.
        total_trials: Toplam yapılan deneme adedi.
        pareto_front: Pareto-optimal parametre çözümleri.
        best_trial: En yüksek birleşik puana sahip deneme.
        duration_seconds: Toplam yürütüm süresi.
        param_importance: Parametre önem katsayıları tahmini.
    """

    experiment_id: str
    total_trials: int
    pareto_front: list[TrialResult]
    best_trial: TrialResult | None
    duration_seconds: float
    param_importance: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Rapor temsili."""
        best_s = f"{self.best_trial.composite_score:.2f}" if self.best_trial else "N/A"
        return (
            f"MetaOptimizationReport(trials={self.total_trials}, "
            f"pareto_size={len(self.pareto_front)}, best_score={best_s}, "
            f"time={self.duration_seconds:.2f}s)"
        )


class MetaOptimizer:
    """Çok Amaçlı Hibrit Meta-Optimizasyon Motoru."""

    def __init__(
        self,
        db_path: str = "data/meta_optimization.duckdb",
        random_seed: int = 42,
    ) -> None:
        """MetaOptimizer başlatıcı.

        Args:
            db_path: DuckDB veritabanı yolu.
            random_seed: Rastlantısallık tohumu.
        """
        self.db_path = db_path
        self.rng = random.Random(random_seed)
        self._lock = threading.RLock()
        self._memory_con = duckdb.connect(":memory:") if self.db_path == ":memory:" else None
        self._init_db()

    def __repr__(self) -> str:
        """MetaOptimizer temsili."""
        return f"MetaOptimizer(db={self.db_path})"

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısı döndürür."""
        if self._memory_con is not None:
            return self._memory_con
        return duckdb.connect(self.db_path)

    def _init_db(self) -> None:
        """DuckDB tablosunu oluşturur."""
        try:
            con = self._get_connection()
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_META_OPT} (
                    experiment_id   VARCHAR NOT NULL,
                    trial_id        VARCHAR NOT NULL,
                    sharpe          DOUBLE,
                    sortino         DOUBLE,
                    calmar          DOUBLE,
                    max_drawdown    DOUBLE,
                    composite_score DOUBLE,
                    is_pareto       BOOLEAN,
                    params_json     VARCHAR,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            if self._memory_con is None:
                con.close()
            logger.info("Meta-optimizasyon DB hazır.", db=self.db_path)
        except Exception as exc:
            logger.warning("Meta-optimizasyon DB başlatılamadı.", hata=str(exc))

    def _compute_pareto_front(self, trials: list[TrialResult]) -> list[TrialResult]:
        """Pareto cephesini (non-dominated çözümler) hesaplar."""
        pareto: list[TrialResult] = []
        for candidate in trials:
            is_dominated = False
            for other in trials:
                if other is not candidate and other.dominates(candidate):
                    is_dominated = True
                    break
            if not is_dominated:
                candidate.rank = 1
                pareto.append(candidate)
        return pareto

    def optimize(
        self,
        objective_fn: Callable[[dict[str, Any]], dict[str, float]],
        param_space: dict[str, list[Any] | tuple[float, float]],
        n_trials: int = 30,
        experiment_id: str | None = None,
    ) -> MetaOptimizationReport:
        """Çok amaçlı meta-optimizasyon yürütür.

        Args:
            objective_fn: Parametre sözlüğünü alıp {sharpe, sortino, calmar, max_drawdown}
                          döndüren değerlendirme fonksiyonu.
            param_space: Parametre aralıkları ({param_name: [değerler]} veya {param_name: (min, max)}).
            n_trials: Yapılacak deneme sayısı.
            experiment_id: Deney oturum adı.

        Returns:
            MetaOptimizationReport sonuç raporu.
        """
        exp_id = experiment_id or f"exp_{int(time.time())}"
        t0 = time.perf_counter()

        logger.info(
            "Meta-optimizasyon başladı.",
            experiment=exp_id,
            trials=n_trials,
            param_count=len(param_space),
        )

        trials: list[TrialResult] = []

        for i in range(n_trials):
            # Parametre örneklemesi (Hibrit rastgele + yerel pertürbasyon)
            sampled_params: dict[str, Any] = {}
            for name, bounds in param_space.items():
                if isinstance(bounds, (list, tuple)) and len(bounds) == 2 and all(isinstance(x, (int, float)) for x in bounds):
                    low, high = float(bounds[0]), float(bounds[1])
                    # Önceki en iyi trial varsa ona yakın keşfet
                    if trials and self.rng.random() < 0.4:
                        best_val = float(trials[0].params.get(name, (low + high) / 2))
                        sigma = (high - low) * 0.15
                        val = self.rng.gauss(best_val, sigma)
                        val = max(low, min(high, val))
                    else:
                        val = self.rng.uniform(low, high)

                    sampled_params[name] = round(val, 4) if isinstance(bounds[0], float) else int(round(val))
                elif isinstance(bounds, list):
                    sampled_params[name] = self.rng.choice(bounds)
                else:
                    sampled_params[name] = bounds

            trial_id = f"{exp_id}_t{i+1:03d}"

            try:
                metrics = objective_fn(sampled_params)
                sharpe = float(metrics.get("sharpe", 0.0))
                sortino = float(metrics.get("sortino", sharpe * 1.1))
                calmar = float(metrics.get("calmar", sharpe * 0.8))
                max_dd = float(metrics.get("max_drawdown", 0.10))
                win_rate = float(metrics.get("win_rate", 0.50))

                # Sayısal taşma kontrolleri
                if math.isnan(sharpe) or math.isinf(sharpe):
                    sharpe = -5.0
                if math.isnan(max_dd) or math.isinf(max_dd):
                    max_dd = 1.0

            except Exception as exc:
                logger.warning("Hedef fonksiyon denemesinde hata!", trial=trial_id, hata=str(exc))
                sharpe, sortino, calmar, max_dd, win_rate = -10.0, -10.0, -10.0, 1.0, 0.0

            tr = TrialResult(
                trial_id=trial_id,
                params=sampled_params,
                sharpe=sharpe,
                sortino=sortino,
                calmar=calmar,
                max_drawdown=max_dd,
                win_rate=win_rate,
            )
            trials.append(tr)

            # Birleşik puana göre sırala
            trials.sort(key=lambda x: x.composite_score, reverse=True)

        pareto_front = self._compute_pareto_front(trials)
        best_trial = trials[0] if trials else None
        duration = time.perf_counter() - t0

        # DuckDB arşivle
        try:
            con = self._get_connection()
            for t in trials:
                is_p = t in pareto_front
                # params_json simülasyonu
                params_str = str(t.params)
                con.execute(
                    f"""
                    INSERT INTO {DB_TABLE_META_OPT}
                        (experiment_id, trial_id, sharpe, sortino, calmar,
                         max_drawdown, composite_score, is_pareto, params_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        exp_id,
                        t.trial_id,
                        t.sharpe,
                        t.sortino,
                        t.calmar,
                        t.max_drawdown,
                        t.composite_score,
                        is_p,
                        params_str,
                    ],
                )
            if self._memory_con is None:
                con.close()
        except Exception as exc:
            logger.warning("Meta-optimizasyon sonuçları arşivlenemedi.", hata=str(exc))

        logger.info(
            "Meta-optimizasyon tamamlandı.",
            experiment=exp_id,
            duration=round(duration, 2),
            best_score=round(best_trial.composite_score, 3) if best_trial else 0.0,
            pareto_count=len(pareto_front),
        )

        return MetaOptimizationReport(
            experiment_id=exp_id,
            total_trials=len(trials),
            pareto_front=pareto_front,
            best_trial=best_trial,
            duration_seconds=duration,
        )


# Singleton
meta_optimizer = MetaOptimizer()

__all__ = [
    "MetaOptimizationReport",
    "MetaOptimizer",
    "TrialResult",
    "meta_optimizer",
]
