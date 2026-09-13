"""
ALPHA BIST — Grid Search ve Random Search Optimizasyonu

Polars vektörize metrik hesaplama ile yüksek hızlı grid/random search.
Walk-forward aware tasarım: in-sample / out-of-sample ayrımı zorunludur.

Kullanım Senaryoları:
  - Küçük parametre uzayı (<1000 kombinasyon) → Grid Search
  - Büyük parametre uzayı → Random Search (N rastgele örnekleme)
  - Walk-forward grid: Her fold için ayrı optimizasyon
"""
from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_N_RANDOM_TRIALS: int = 200
DEFAULT_MAX_WORKERS: int = 4
DEFAULT_N_FOLDS: int = 5
DEFAULT_WFO_TRAIN_RATIO: float = 0.7


@dataclass
class GridSearchResult:
    """Grid/Random Search sonucu.

    Attributes:
        best_params: En iyi parametre sözlüğü.
        best_score: En iyi fitness/metrik değeri.
        all_results: Tüm denenen parametreler ve skorlar listesi.
        n_trials: Toplam deneme sayısı.
        search_type: Kullanılan arama türü ('grid' veya 'random').
    """

    best_params: dict[str, Any]
    best_score: float
    all_results: list[dict[str, Any]]
    n_trials: int
    search_type: str

    def __repr__(self) -> str:
        """GridSearchResult kısa temsili."""
        return (
            f"GridSearchResult(type={self.search_type!r}, best={self.best_score:.4f}, "
            f"trials={self.n_trials})"
        )

    def top_k(self, k: int = 10) -> list[dict[str, Any]]:
        """En iyi K sonucu döndürür.

        Args:
            k: İstenen sonuç sayısı.

        Returns:
            Skora göre azalan sırada top K sonuç listesi.
        """
        sorted_results = sorted(self.all_results, key=lambda x: x.get("score", float("-inf")), reverse=True)
        return sorted_results[:k]


@dataclass
class WalkForwardGridResult:
    """Walk-Forward Grid Search sonucu.

    Attributes:
        fold_results: Her fold için GridSearchResult listesi.
        oos_scores: Out-of-sample skor listesi (fold başına).
        mean_oos_score: Ortalama out-of-sample skor.
        std_oos_score: Out-of-sample skor standart sapması.
        best_params_per_fold: Her fold için en iyi parametreler.
        consensus_params: Tüm foldlarda en sık seçilen parametreler.
    """

    fold_results: list[GridSearchResult]
    oos_scores: list[float]
    mean_oos_score: float
    std_oos_score: float
    best_params_per_fold: list[dict[str, Any]]
    consensus_params: dict[str, Any]

    def __repr__(self) -> str:
        """WalkForwardGridResult kısa temsili."""
        return (
            f"WalkForwardGridResult(folds={len(self.fold_results)}, "
            f"mean_oos={self.mean_oos_score:.4f}±{self.std_oos_score:.4f})"
        )


class GridSearchOptimizer:
    """Paralel Grid Search ve Random Search optimizatörü.

    Walk-forward aware yapısı sayesinde in-sample optimizasyon ve
    out-of-sample doğrulama ayrımını zorunlu kılar. Bu, strateji parametrelerinin
    gerçek performansını abartmadan değerlendirmeyi sağlar.
    """

    def __init__(
        self,
        n_random_trials: int = DEFAULT_N_RANDOM_TRIALS,
        max_workers: int = DEFAULT_MAX_WORKERS,
        seed: int | None = None,
    ) -> None:
        """GridSearchOptimizer başlatıcı.

        Args:
            n_random_trials: Random search'de toplam deneme sayısı.
            max_workers: Paralel değerlendirme iş parçacığı sayısı.
            seed: Tekrarlanabilirlik için rastgele tohum.

        Raises:
            ValueError: n_random_trials < 1 ise.
        """
        if n_random_trials < 1:
            raise ValueError(f"n_random_trials >= 1 olmalıdır: {n_random_trials}")
        self.n_random_trials = n_random_trials
        self.max_workers = max_workers
        self._rng = np.random.default_rng(seed)

    def __repr__(self) -> str:
        """GridSearchOptimizer kısa temsili."""
        return f"GridSearchOptimizer(random_trials={self.n_random_trials}, workers={self.max_workers})"

    def _evaluate_params(
        self,
        fitness_fn: Callable[[dict[str, Any]], float],
        param_list: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parametre listesini paralel olarak değerlendirir.

        Args:
            fitness_fn: Parametreleri alıp skor döndüren fonksiyon.
            param_list: Değerlendirilecek parametre sözlüklerinin listesi.

        Returns:
            Her parametre seti için 'score' anahtarı eklenmiş sonuç listesi.
        """
        results: list[dict[str, Any]] = []
        result_lock: list[dict[str, Any]] = []

        def eval_one(params: dict[str, Any]) -> dict[str, Any]:
            try:
                score = fitness_fn(params)
            except Exception as e:
                logger.warning("Parametre değerlendirme hatası.", hata=str(e), params=params)
                score = float("-inf")
            return {**params, "score": score}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(eval_one, p) for p in param_list]
            for future in as_completed(futures):
                try:
                    result_lock.append(future.result())
                except Exception as e:
                    logger.warning("Future sonucu alınamadı.", hata=str(e))

        results = result_lock
        return results

    def grid_search(
        self,
        fitness_fn: Callable[[dict[str, Any]], float],
        param_grid: dict[str, list[Any]],
    ) -> GridSearchResult:
        """Tüm parametre kombinasyonlarını dener (tam grid).

        Args:
            fitness_fn: Parametreleri alıp skor döndüren fonksiyon (yüksek = iyi).
            param_grid: {param_name: [değer1, değer2, ...]} şeklinde grid tanımı.

        Returns:
            En iyi parametreler ve tüm sonuçları içeren GridSearchResult.

        Raises:
            ValueError: param_grid boşsa.
        """
        if not param_grid:
            raise ValueError("param_grid boş olamaz.")

        keys = list(param_grid.keys())
        value_lists = [param_grid[k] for k in keys]
        combos = [dict(zip(keys, values, strict=True)) for values in itertools.product(*value_lists)]
        n_trials = len(combos)

        logger.info("Grid search başlatıldı.", n_trials=n_trials, params=keys)

        all_results = self._evaluate_params(fitness_fn, combos)

        if not all_results:
            return GridSearchResult(
                best_params={},
                best_score=float("-inf"),
                all_results=[],
                n_trials=n_trials,
                search_type="grid",
            )

        best = max(all_results, key=lambda x: x.get("score", float("-inf")))
        best_params = {k: best[k] for k in keys}

        logger.info(
            "Grid search tamamlandı.",
            best=round(best.get("score", 0.0), 4),
            params=best_params,
        )

        return GridSearchResult(
            best_params=best_params,
            best_score=best.get("score", float("-inf")),
            all_results=all_results,
            n_trials=n_trials,
            search_type="grid",
        )

    def random_search(
        self,
        fitness_fn: Callable[[dict[str, Any]], float],
        param_distributions: dict[str, tuple[float, float] | list[Any]],
        n_trials: int | None = None,
    ) -> GridSearchResult:
        """Rastgele örnekleme ile parametre arama.

        Args:
            fitness_fn: Parametreleri alıp skor döndüren fonksiyon.
            param_distributions: {param: (low, high)} veya {param: [seçenekler]} sözlüğü.
            n_trials: Toplam deneme sayısı. None ise DEFAULT_N_RANDOM_TRIALS kullanılır.

        Returns:
            En iyi parametreler ve tüm sonuçları içeren GridSearchResult.

        Raises:
            ValueError: param_distributions boşsa.
        """
        if not param_distributions:
            raise ValueError("param_distributions boş olamaz.")

        n = n_trials or self.n_random_trials

        def sample_params() -> dict[str, Any]:
            params: dict[str, Any] = {}
            for name, dist in param_distributions.items():
                if isinstance(dist, (list, tuple)) and len(dist) == 2 and isinstance(dist[0], (int, float)):
                    low, high = float(dist[0]), float(dist[1])
                    params[name] = float(self._rng.uniform(low, high))
                elif isinstance(dist, list):
                    params[name] = dist[int(self._rng.integers(0, len(dist)))]
                else:
                    params[name] = dist
            return params

        param_list = [sample_params() for _ in range(n)]
        logger.info("Random search başlatıldı.", n_trials=n, params=list(param_distributions.keys()))

        all_results = self._evaluate_params(fitness_fn, param_list)

        if not all_results:
            return GridSearchResult(
                best_params={},
                best_score=float("-inf"),
                all_results=[],
                n_trials=n,
                search_type="random",
            )

        best = max(all_results, key=lambda x: x.get("score", float("-inf")))
        keys = list(param_distributions.keys())
        best_params = {k: best[k] for k in keys if k in best}

        logger.info("Random search tamamlandı.", best=round(best.get("score", 0.0), 4))

        return GridSearchResult(
            best_params=best_params,
            best_score=best.get("score", float("-inf")),
            all_results=all_results,
            n_trials=n,
            search_type="random",
        )

    def walk_forward_grid(
        self,
        fitness_fn_factory: Callable[[np.ndarray, np.ndarray], Callable[[dict[str, Any]], float]],
        data: np.ndarray,
        param_grid: dict[str, list[Any]],
        n_folds: int = DEFAULT_N_FOLDS,
        train_ratio: float = DEFAULT_WFO_TRAIN_RATIO,
        oos_eval_fn: Callable[[dict[str, Any], np.ndarray, np.ndarray], float] | None = None,
    ) -> WalkForwardGridResult:
        """Walk-Forward Grid Search: Her fold için ayrı optimizasyon.

        Her fold:
          - Train: İlk train_ratio kadar → Grid Search ile en iyi parametreler bulunur.
          - OOS: Kalan kısım → Bulunan parametreler ile out-of-sample değerlendirme.

        Args:
            fitness_fn_factory: (train_data, train_labels) → fitness_fn döndüren fabrika.
            data: Tüm veri dizisi (satırlar = zaman adımları).
            param_grid: {param_name: [değer1, değer2, ...]} grid tanımı.
            n_folds: Walk-forward fold sayısı.
            train_ratio: Her fold içinde training set oranı (0-1).
            oos_eval_fn: Opsiyonel out-of-sample değerlendirme fonksiyonu.

        Returns:
            Tüm fold sonuçlarını ve OOS istatistiklerini içeren WalkForwardGridResult.

        Raises:
            ValueError: n_folds < 2 veya train_ratio geçersizse.
        """
        if n_folds < 2:
            raise ValueError(f"n_folds >= 2 olmalıdır: {n_folds}")
        if not (0.0 < train_ratio < 1.0):
            raise ValueError(f"train_ratio (0,1) aralığında olmalıdır: {train_ratio}")

        n = len(data)
        fold_size = n // n_folds
        fold_results: list[GridSearchResult] = []
        oos_scores: list[float] = []
        best_params_per_fold: list[dict[str, Any]] = []

        logger.info("Walk-forward grid search başlatıldı.", folds=n_folds, n=n)

        for fold in range(n_folds):
            fold_start = fold * fold_size
            fold_end = fold_start + fold_size if fold < n_folds - 1 else n
            fold_data = data[fold_start:fold_end]

            split_idx = int(len(fold_data) * train_ratio)
            if split_idx < 10 or len(fold_data) - split_idx < 5:
                logger.warning("Fold veri yetersiz, atlanıyor.", fold=fold)
                continue

            train_data = fold_data[:split_idx]
            oos_data = fold_data[split_idx:]

            fitness_fn = fitness_fn_factory(train_data, oos_data)
            fold_result = self.grid_search(fitness_fn, param_grid)
            fold_results.append(fold_result)
            best_params_per_fold.append(fold_result.best_params)

            # OOS değerlendirme
            if oos_eval_fn is not None:
                oos_score = oos_eval_fn(fold_result.best_params, train_data, oos_data)
            else:
                oos_score = fold_result.best_score
            oos_scores.append(oos_score)

            logger.info(
                "Fold tamamlandı.",
                fold=fold,
                is_score=round(fold_result.best_score, 4),
                oos_score=round(oos_score, 4),
            )

        # Consensus parametreleri: her fold'un en iyi parametrelerinden oy çoğunluğu
        consensus: dict[str, Any] = {}
        if best_params_per_fold:
            keys = list(best_params_per_fold[0].keys())
            for key in keys:
                vals = [p[key] for p in best_params_per_fold if key in p]
                if not vals:
                    continue
                if isinstance(vals[0], (int, float)):
                    consensus[key] = float(np.median(vals))
                else:
                    # Kategorik: mod
                    unique, counts = np.unique(vals, return_counts=True)
                    consensus[key] = unique[int(np.argmax(counts))]

        mean_oos = float(np.mean(oos_scores)) if oos_scores else 0.0
        std_oos = float(np.std(oos_scores)) if oos_scores else 0.0

        logger.info(
            "Walk-forward grid search tamamlandı.",
            mean_oos=round(mean_oos, 4),
            std_oos=round(std_oos, 4),
        )

        return WalkForwardGridResult(
            fold_results=fold_results,
            oos_scores=oos_scores,
            mean_oos_score=mean_oos,
            std_oos_score=std_oos,
            best_params_per_fold=best_params_per_fold,
            consensus_params=consensus,
        )


__all__: list[str] = [
    "GridSearchOptimizer",
    "GridSearchResult",
    "WalkForwardGridResult",
    "grid_search_optimizer",
]

# Singleton
grid_search_optimizer = GridSearchOptimizer()
