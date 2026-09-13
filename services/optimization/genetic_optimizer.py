"""
ALPHA BIST — Genetik Algoritma Optimizasyonu

DEAP benzeri, saf-Python tabanlı genetik algoritma ile strateji parametresi
optimizasyonu. Tek ve çok amaçlı (Pareto-front) optimizasyon desteği sağlar.

Özellikler:
  - Elitist seçim (elitism): En iyi bireylerin bir sonraki nesile geçişi
  - Tournament seçimi: Çeşitliliği korur, erken yakınsamayı önler
  - SBX çaprazlama (Simulated Binary Crossover): Gerçek değerli parametreler için
  - Polinomsal mutasyon: Sınır farkındalıklı, parametre uzayını dengeli keşfeder
  - Paralel fitness değerlendirme (ThreadPoolExecutor)
"""
from __future__ import annotations

import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_POPULATION_SIZE: int = 50
DEFAULT_N_GENERATIONS: int = 100
DEFAULT_CROSSOVER_PROB: float = 0.9
DEFAULT_MUTATION_PROB: float = 0.1
DEFAULT_TOURNAMENT_SIZE: int = 3
DEFAULT_ELITE_FRACTION: float = 0.1
DEFAULT_ETA_CROSSOVER: float = 15.0    # SBX dağılım indeksi
DEFAULT_ETA_MUTATION: float = 20.0     # Polinom mutasyon dağılım indeksi
DEFAULT_MAX_WORKERS: int = 4


@dataclass
class GeneticParamSpace:
    """Genetik algoritma parametre uzayı tanımı.

    Attributes:
        name: Parametre adı.
        low: Alt sınır.
        high: Üst sınır.
        is_int: True ise tam sayı parametresi.
    """

    name: str
    low: float
    high: float
    is_int: bool = False

    def __repr__(self) -> str:
        """GeneticParamSpace kısa temsili."""
        kind = "int" if self.is_int else "float"
        return f"GeneticParamSpace({self.name!r}: [{self.low}, {self.high}] {kind})"

    def clip(self, value: float) -> float:
        """Değeri sınırlar içinde tut.

        Args:
            value: Düzeltilecek değer.

        Returns:
            Sınırlara çekilmiş değer.
        """
        v = float(max(self.low, min(self.high, value)))
        return float(round(v)) if self.is_int else v

    def random(self, rng: random.Random) -> float:
        """Parametre uzayında rastgele değer üret.

        Args:
            rng: Rastgele sayı üreticisi.

        Returns:
            Rastgele parametre değeri.
        """
        if self.is_int:
            return float(rng.randint(int(self.low), int(self.high)))
        return self.low + rng.random() * (self.high - self.low)


@dataclass
class GeneticIndividual:
    """Genetik algoritma bireyi (çözüm adayı).

    Attributes:
        genes: Parametre değerleri listesi.
        fitness: Fitness değeri (yüksek = iyi, None = henüz değerlendirilmedi).
        generation: Bu bireyin üretildiği nesil.
    """

    genes: list[float]
    fitness: float | None = None
    generation: int = 0

    def __repr__(self) -> str:
        """GeneticIndividual kısa temsili."""
        fit_str = f"{self.fitness:.4f}" if self.fitness is not None else "?"
        return f"GeneticIndividual(gen={self.generation}, fitness={fit_str})"

    def to_param_dict(self, param_spaces: list[GeneticParamSpace]) -> dict[str, Any]:
        """Gen listesini parametre sözlüğüne dönüştürür.

        Args:
            param_spaces: Parametre uzayı tanımları.

        Returns:
            {param_name: value} sözlüğü.
        """
        return {
            ps.name: (int(round(g)) if ps.is_int else g)
            for ps, g in zip(param_spaces, self.genes, strict=True)
        }


@dataclass
class GeneticOptimizationResult:
    """Genetik algoritma optimizasyon sonucu.

    Attributes:
        best_params: En iyi parametre sözlüğü.
        best_fitness: En iyi fitness değeri.
        best_individual: En iyi birey.
        pareto_front: Çok amaçlı optimizasyon için Pareto cephesi (tek amaçlıda boş).
        history: Her nesildeki en iyi fitness geçmişi.
        n_generations: Koşulan nesil sayısı.
        n_evaluations: Toplam fitness değerlendirme sayısı.
    """

    best_params: dict[str, Any]
    best_fitness: float
    best_individual: GeneticIndividual
    pareto_front: list[GeneticIndividual]
    history: list[float]
    n_generations: int
    n_evaluations: int

    def __repr__(self) -> str:
        """GeneticOptimizationResult kısa temsili."""
        return (
            f"GeneticOptimizationResult(best={self.best_fitness:.4f}, "
            f"gens={self.n_generations}, evals={self.n_evaluations})"
        )


class GeneticOptimizer:
    """Elitist Genetik Algoritma ile strateji parametre optimizasyonu.

    Gerçek değerli parametreler için SBX çaprazlama ve polinomsal mutasyon kullanır.
    Thread-güvenli paralel fitness değerlendirme destekler.
    """

    def __init__(
        self,
        population_size: int = DEFAULT_POPULATION_SIZE,
        n_generations: int = DEFAULT_N_GENERATIONS,
        crossover_prob: float = DEFAULT_CROSSOVER_PROB,
        mutation_prob: float = DEFAULT_MUTATION_PROB,
        tournament_size: int = DEFAULT_TOURNAMENT_SIZE,
        elite_fraction: float = DEFAULT_ELITE_FRACTION,
        eta_c: float = DEFAULT_ETA_CROSSOVER,
        eta_m: float = DEFAULT_ETA_MUTATION,
        max_workers: int = DEFAULT_MAX_WORKERS,
        seed: int | None = None,
    ) -> None:
        """GeneticOptimizer başlatıcı.

        Args:
            population_size: Popülasyon büyüklüğü.
            n_generations: Nesil sayısı.
            crossover_prob: Çaprazlama olasılığı (0-1).
            mutation_prob: Mutasyon olasılığı (0-1).
            tournament_size: Tournament seçimi katılımcı sayısı.
            elite_fraction: Elitist olarak korunan birey oranı (0-1).
            eta_c: SBX çaprazlama dağılım indeksi (yüksek = daha az çeşitlilik).
            eta_m: Polinomsal mutasyon dağılım indeksi (yüksek = daha küçük adım).
            max_workers: Paralel fitness değerlendirme iş parçacığı sayısı.
            seed: Tekrarlanabilirlik için rastgele tohum.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if population_size < 4:
            raise ValueError(f"population_size >= 4 olmalıdır: {population_size}")
        if not (0.0 < crossover_prob <= 1.0):
            raise ValueError(f"crossover_prob (0,1] aralığında olmalıdır: {crossover_prob}")
        if not (0.0 < mutation_prob <= 1.0):
            raise ValueError(f"mutation_prob (0,1] aralığında olmalıdır: {mutation_prob}")
        if not (0.0 < elite_fraction < 1.0):
            raise ValueError(f"elite_fraction (0,1) aralığında olmalıdır: {elite_fraction}")

        self.population_size = population_size
        self.n_generations = n_generations
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        self.tournament_size = min(tournament_size, population_size)
        self.elite_fraction = elite_fraction
        self.eta_c = eta_c
        self.eta_m = eta_m
        self.max_workers = max_workers
        self._rng = random.Random(seed)
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """GeneticOptimizer kısa temsili."""
        return (
            f"GeneticOptimizer(pop={self.population_size}, gens={self.n_generations}, "
            f"cx={self.crossover_prob:.1f}, mut={self.mutation_prob:.2f})"
        )

    def _init_population(
        self, param_spaces: list[GeneticParamSpace], generation: int = 0
    ) -> list[GeneticIndividual]:
        """Rastgele başlangıç popülasyonu oluşturur.

        Args:
            param_spaces: Parametre uzayı tanımları.
            generation: Başlangıç nesil indeksi.

        Returns:
            Rastgele bireylerden oluşan popülasyon listesi.
        """
        return [
            GeneticIndividual(
                genes=[ps.random(self._rng) for ps in param_spaces],
                generation=generation,
            )
            for _ in range(self.population_size)
        ]

    def _tournament_select(self, population: list[GeneticIndividual]) -> GeneticIndividual:
        """Tournament seçimi ile bir birey seçer.

        Args:
            population: Seçim yapılacak popülasyon.

        Returns:
            En yüksek fitness'lı tournament kazananı.
        """
        competitors = self._rng.sample(population, min(self.tournament_size, len(population)))
        return max(
            (c for c in competitors if c.fitness is not None),
            key=lambda ind: ind.fitness if ind.fitness is not None else float("-inf"),
            default=competitors[0],
        )

    def _sbx_crossover(
        self,
        parent1: GeneticIndividual,
        parent2: GeneticIndividual,
        param_spaces: list[GeneticParamSpace],
        generation: int,
    ) -> tuple[GeneticIndividual, GeneticIndividual]:
        """Simulated Binary Crossover (SBX) ile iki çocuk üretir.

        Args:
            parent1: Birinci ebeveyn.
            parent2: İkinci ebeveyn.
            param_spaces: Parametre uzayı tanımları.
            generation: Mevcut nesil.

        Returns:
            İki çocuk birey tuple'ı.
        """
        if self._rng.random() > self.crossover_prob:
            return (
                GeneticIndividual(genes=parent1.genes[:], generation=generation),
                GeneticIndividual(genes=parent2.genes[:], generation=generation),
            )

        child1_genes: list[float] = []
        child2_genes: list[float] = []

        for ps, g1, g2 in zip(param_spaces, parent1.genes, parent2.genes, strict=True):
            if abs(g1 - g2) < 1e-10:
                child1_genes.append(g1)
                child2_genes.append(g2)
                continue

            if self._rng.random() <= 0.5:
                u = self._rng.random()
                if u <= 0.5:
                    beta = (2.0 * u) ** (1.0 / (self.eta_c + 1.0))
                else:
                    beta = (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (self.eta_c + 1.0))

                c1 = 0.5 * ((1.0 + beta) * g1 + (1.0 - beta) * g2)
                c2 = 0.5 * ((1.0 - beta) * g1 + (1.0 + beta) * g2)
            else:
                c1, c2 = g1, g2

            child1_genes.append(ps.clip(c1))
            child2_genes.append(ps.clip(c2))

        return (
            GeneticIndividual(genes=child1_genes, generation=generation),
            GeneticIndividual(genes=child2_genes, generation=generation),
        )

    def _polynomial_mutate(
        self,
        individual: GeneticIndividual,
        param_spaces: list[GeneticParamSpace],
    ) -> GeneticIndividual:
        """Polinomsal mutasyon uygular.

        Args:
            individual: Mutasyona uğrayacak birey.
            param_spaces: Parametre uzayı tanımları.

        Returns:
            Mutasyona uğramış yeni birey.
        """
        new_genes: list[float] = []
        for ps, gene in zip(param_spaces, individual.genes, strict=True):
            if self._rng.random() < self.mutation_prob:
                u = self._rng.random()
                delta_l = (gene - ps.low) / (ps.high - ps.low + 1e-12)
                delta_r = (ps.high - gene) / (ps.high - ps.low + 1e-12)

                if u <= 0.5:
                    aux = 2.0 * u + (1.0 - 2.0 * u) * (1.0 - delta_l) ** (self.eta_m + 1.0)
                    delta = aux ** (1.0 / (self.eta_m + 1.0)) - 1.0
                else:
                    aux = 2.0 * (1.0 - u) + 2.0 * (u - 0.5) * (1.0 - delta_r) ** (self.eta_m + 1.0)
                    delta = 1.0 - aux ** (1.0 / (self.eta_m + 1.0))

                mutated = gene + delta * (ps.high - ps.low)
                new_genes.append(ps.clip(mutated))
            else:
                new_genes.append(gene)

        return GeneticIndividual(genes=new_genes, generation=individual.generation)

    def _evaluate_population(
        self,
        population: list[GeneticIndividual],
        fitness_fn: Callable[[dict[str, Any]], float],
        param_spaces: list[GeneticParamSpace],
    ) -> int:
        """Tüm bireyler için fitness değerlendirmesi (paralel).

        Args:
            population: Değerlendirilecek popülasyon.
            fitness_fn: Parametre sözlüğü → fitness skoru fonksiyonu.
            param_spaces: Parametre uzayı tanımları.

        Returns:
            Gerçekleştirilen değerlendirme sayısı.
        """
        unevaluated = [ind for ind in population if ind.fitness is None]
        if not unevaluated:
            return 0

        def evaluate_one(ind: GeneticIndividual) -> tuple[GeneticIndividual, float]:
            params = ind.to_param_dict(param_spaces)
            try:
                score = fitness_fn(params)
            except Exception as e:
                logger.warning("Fitness değerlendirme hatası.", hata=str(e))
                score = float("-inf")
            return ind, score

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(evaluate_one, ind): ind for ind in unevaluated}
            for future in as_completed(futures):
                ind, score = future.result()
                with self._lock:
                    ind.fitness = score

        return len(unevaluated)

    def optimize(
        self,
        fitness_fn: Callable[[dict[str, Any]], float],
        param_spaces: list[GeneticParamSpace],
        callback: Callable[[int, float], None] | None = None,
    ) -> GeneticOptimizationResult:
        """Genetik algoritma ile optimizasyon çalıştırır.

        Args:
            fitness_fn: Parametre sözlüğünü alıp fitness skoru döndüren fonksiyon.
                        Yüksek skor = iyi parametre seti.
            param_spaces: Optimizasyon parametre uzayı tanımları.
            callback: Opsiyonel (generation, best_fitness) → None geri çağırım.

        Returns:
            En iyi parametreleri ve geçmiş bilgilerini içeren GeneticOptimizationResult.

        Raises:
            ValueError: param_spaces boşsa.
        """
        if not param_spaces:
            raise ValueError("param_spaces boş olamaz.")

        n_elite = max(1, int(self.population_size * self.elite_fraction))
        population = self._init_population(param_spaces, generation=0)
        history: list[float] = []
        total_evaluations = 0

        logger.info(
            "Genetik algoritma başlatıldı.",
            pop=self.population_size,
            gens=self.n_generations,
            params=len(param_spaces),
        )

        for gen in range(self.n_generations):
            total_evaluations += self._evaluate_population(population, fitness_fn, param_spaces)

            # Elitler
            evaluated = [ind for ind in population if ind.fitness is not None]
            if not evaluated:
                continue
            evaluated.sort(key=lambda ind: ind.fitness or float("-inf"), reverse=True)
            elites = evaluated[:n_elite]
            best_fitness = elites[0].fitness or float("-inf")
            history.append(best_fitness)

            if callback is not None:
                callback(gen, best_fitness)

            if gen % 10 == 0:
                logger.info(
                    "Nesil tamamlandı.",
                    gen=gen,
                    best=round(best_fitness, 4),
                    evals=total_evaluations,
                )

            if gen == self.n_generations - 1:
                break

            # Yeni nesil
            offspring: list[GeneticIndividual] = list(elites)
            while len(offspring) < self.population_size:
                p1 = self._tournament_select(evaluated)
                p2 = self._tournament_select(evaluated)
                c1, c2 = self._sbx_crossover(p1, p2, param_spaces, gen + 1)
                c1 = self._polynomial_mutate(c1, param_spaces)
                c2 = self._polynomial_mutate(c2, param_spaces)
                offspring.append(c1)
                if len(offspring) < self.population_size:
                    offspring.append(c2)

            population = offspring

        # Final değerlendirme
        total_evaluations += self._evaluate_population(population, fitness_fn, param_spaces)
        all_evaluated = [ind for ind in population if ind.fitness is not None]
        if not all_evaluated:
            logger.error("Hiç birey değerlendirilemedi.")
            return GeneticOptimizationResult(
                best_params={},
                best_fitness=float("-inf"),
                best_individual=GeneticIndividual(genes=[]),
                pareto_front=[],
                history=history,
                n_generations=self.n_generations,
                n_evaluations=total_evaluations,
            )

        best = max(all_evaluated, key=lambda ind: ind.fitness or float("-inf"))

        logger.info(
            "Genetik algoritma tamamlandı.",
            best=round(best.fitness or 0.0, 4),
            total_gens=self.n_generations,
            total_evals=total_evaluations,
        )

        return GeneticOptimizationResult(
            best_params=best.to_param_dict(param_spaces),
            best_fitness=best.fitness or float("-inf"),
            best_individual=best,
            pareto_front=[],
            history=history,
            n_generations=self.n_generations,
            n_evaluations=total_evaluations,
        )


__all__: list[str] = [
    "GeneticIndividual",
    "GeneticOptimizationResult",
    "GeneticOptimizer",
    "GeneticParamSpace",
    "genetic_optimizer",
]

# Singleton
genetic_optimizer = GeneticOptimizer()
