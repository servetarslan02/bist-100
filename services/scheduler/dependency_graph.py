"""
ALPHA BIST — Pipeline DAG (Yönlendirilmiş Asiklik Graf) Bağımlılık Yöneticisi

Pipeline aşamalarını DAG olarak modelleyen, topolojik sıralama ile doğru
çalıştırma düzenini belirleyen ve döngü tespiti yapan bağımlılık yönetim sistemi.

Özellikler:
  - Topolojik sıralama (Kahn algoritması, O(V+E))
  - Döngü tespiti (DFS tabanlı, hata ile bildirilir)
  - Paralel çalıştırılabilir aşama grubu tespiti (katman analizi)
  - Kritik yol hesaplama (en uzun bağımlılık zinciri)
  - DOT formatında görselleştirme
  - Thread-safe graf değişikliği
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DependencyNode:
    """DAG düğümü — tek bir pipeline aşaması.

    Attributes:
        name: Benzersiz düğüm adı.
        description: İnsan okunabilir açıklama.
        timeout_seconds: Maksimum çalışma süresi (0 = limitsiz).
        retries: Maksimum yeniden deneme sayısı.
        metadata: Ek bağlam bilgisi.
    """

    name: str
    description: str = ""
    timeout_seconds: float = 0.0
    retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """DependencyNode kısa temsili."""
        return f"DependencyNode({self.name!r}, timeout={self.timeout_seconds}s)"

    def __hash__(self) -> int:
        """Hash metodu (ad üzerinden)."""
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        """Eşitlik karşılaştırması."""
        if not isinstance(other, DependencyNode):
            return NotImplemented
        return self.name == other.name


@dataclass
class CriticalPathResult:
    """Kritik yol analizi sonucu.

    Attributes:
        path: Kritik yoldaki düğüm adları.
        total_timeout: Yoldaki toplam timeout süresi.
        bottleneck: Kritik yolun en uzun adımı.
    """

    path: list[str]
    total_timeout: float
    bottleneck: str

    def __repr__(self) -> str:
        """CriticalPathResult kısa temsili."""
        return (
            f"CriticalPathResult(path={self.path}, "
            f"total={self.total_timeout:.1f}s, bottleneck={self.bottleneck!r})"
        )


class CycleDetectedError(Exception):
    """DAG'da döngü tespit edildiğinde fırlatılır."""


class DependencyGraph:
    """Pipeline bağımlılık grafı (thread-safe DAG implementasyonu).

    Kahn algoritması ile topolojik sıralama ve DFS tabanlı döngü tespiti
    gerçekleştirir. Paralel çalıştırma için bağımsız aşama gruplarını (katmanları)
    tespit eder.
    """

    def __init__(self, name: str = "pipeline") -> None:
        """DependencyGraph başlatıcı.

        Args:
            name: Grafın adı (loglama için).
        """
        self.name = name
        self._nodes: dict[str, DependencyNode] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # upstream → downstream
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """DependencyGraph kısa temsili."""
        return (
            f"DependencyGraph({self.name!r}, "
            f"nodes={len(self._nodes)}, edges={self._edge_count()})"
        )

    def _edge_count(self) -> int:
        """Toplam kenar sayısı."""
        return sum(len(v) for v in self._edges.values())

    def add_node(self, node: DependencyNode) -> None:
        """Grafikya düğüm ekler.

        Args:
            node: Eklenecek düğüm.

        Raises:
            ValueError: Aynı adlı düğüm zaten varsa.
        """
        with self._lock:
            if node.name in self._nodes:
                raise ValueError(f"Düğüm zaten mevcut: {node.name!r}")
            self._nodes[node.name] = node
            logger.debug("Düğüm eklendi.", graph=self.name, node=node.name)

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Bağımlılık kenarı ekler (from_node → to_node: to_node, from_node'a bağlıdır).

        Args:
            from_node: Önce çalışması gereken düğüm adı.
            to_node: Bağımlı düğüm adı (from_node tamamlandıktan sonra çalışır).

        Raises:
            KeyError: Düğüm bulunamazsa.
            CycleDetectedError: Kenar döngüye yol açıyorsa.
        """
        with self._lock:
            if from_node not in self._nodes:
                raise KeyError(f"Düğüm bulunamadı: {from_node!r}")
            if to_node not in self._nodes:
                raise KeyError(f"Düğüm bulunamadı: {to_node!r}")
            self._edges[from_node].add(to_node)
            # Döngü kontrolü
            if self._has_cycle():
                self._edges[from_node].discard(to_node)
                raise CycleDetectedError(
                    f"Kenar {from_node!r} -> {to_node!r} donguye yol açıyor."
                )
            logger.debug("Kenar eklendi.", graph=self.name, frm=from_node, to=to_node)

    def _has_cycle(self) -> bool:
        """DFS tabanlı döngü tespiti.

        Returns:
            True ise döngü var, False ise DAG geçerli.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in self._nodes}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for neighbor in self._edges.get(node, set()):
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False

        return any(color[n] == WHITE and dfs(n) for n in self._nodes)

    def topological_sort(self) -> list[str]:
        """Kahn algoritması ile topolojik sıralama.

        Returns:
            Topolojik sıralanmış düğüm adları listesi.

        Raises:
            CycleDetectedError: Graf döngü içeriyorsa.
        """
        with self._lock:
            in_degree: dict[str, int] = {n: 0 for n in self._nodes}
            for src, dsts in self._edges.items():
                for dst in dsts:
                    in_degree[dst] = in_degree.get(dst, 0) + 1

            queue: deque[str] = deque(
                sorted(n for n, d in in_degree.items() if d == 0)
            )
            result: list[str] = []

            while queue:
                node = queue.popleft()
                result.append(node)
                for neighbor in sorted(self._edges.get(node, set())):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            if len(result) != len(self._nodes):
                raise CycleDetectedError(
                    f"Topolojik sıralama başarısız: Graf döngü içeriyor. "
                    f"İşlenemeyen: {set(self._nodes) - set(result)}"
                )

            logger.info(
                "Topolojik sıralama tamamlandı.",
                graph=self.name,
                order=result,
            )
            return result

    def execution_layers(self) -> list[list[str]]:
        """Paralel çalıştırılabilir aşama katmanlarını belirler.

        Aynı katmandaki düğümlerin birbirinden bağımsız olduğu (paralel çalışabilir)
        katman listesi döndürür.

        Returns:
            Her elemanda paralel çalışabilecek düğüm adlarını içeren katman listesi.

        Raises:
            CycleDetectedError: Graf döngü içeriyorsa.
        """
        with self._lock:
            in_degree: dict[str, int] = {n: 0 for n in self._nodes}
            for src, dsts in self._edges.items():
                for dst in dsts:
                    in_degree[dst] = in_degree.get(dst, 0) + 1

            layers: list[list[str]] = []
            remaining = set(self._nodes.keys())

            while remaining:
                # Tüm bağımlılıkları tamamlanan düğümler
                layer = sorted(n for n in remaining if in_degree[n] == 0)
                if not layer:
                    raise CycleDetectedError(
                        f"Katman analizi başarısız: Kalan düğümler döngü içeriyor: {remaining}"
                    )
                layers.append(layer)
                for node in layer:
                    remaining.discard(node)
                    for neighbor in self._edges.get(node, set()):
                        in_degree[neighbor] -= 1

            logger.info(
                "Katman analizi tamamlandı.",
                graph=self.name,
                layer_count=len(layers),
                layer_sizes=[len(l) for l in layers],
            )
            return layers

    def critical_path(self) -> CriticalPathResult:
        """Kritik yolu hesaplar (en uzun bağımlılık zinciri).

        Zaman bazlı: Her düğümün `timeout_seconds` değeri kullanılır.
        Timeout 0 olan düğümler 1.0 saniye olarak sayılır.

        Returns:
            Kritik yol ve toplam süre.

        Raises:
            CycleDetectedError: Graf döngü içeriyorsa.
            ValueError: Graf boşsa.
        """
        with self._lock:
            if not self._nodes:
                raise ValueError("Graf boş, kritik yol hesaplanamaz.")

            topo = self.topological_sort()
            # Dinamik programlama: dist[node] = o noktaya kadar maksimum süre
            dist: dict[str, float] = {n: 0.0 for n in topo}
            prev: dict[str, str | None] = {n: None for n in topo}

            for node in topo:
                node_cost = max(self._nodes[node].timeout_seconds, 1.0)
                dist[node] = dist.get(node, 0.0) + node_cost
                for neighbor in self._edges.get(node, set()):
                    candidate = dist[node] + max(self._nodes[neighbor].timeout_seconds, 1.0)
                    if candidate > dist.get(neighbor, 0.0):
                        dist[neighbor] = candidate
                        prev[neighbor] = node

            # En uzun yolun sonu
            end_node = max(dist, key=lambda n: dist[n])
            # Yolu geri iz sürerek bul
            path: list[str] = []
            current: str | None = end_node
            while current is not None:
                path.append(current)
                current = prev.get(current)
            path.reverse()

            bottleneck = max(path, key=lambda n: self._nodes[n].timeout_seconds)

            return CriticalPathResult(
                path=path,
                total_timeout=dist[end_node],
                bottleneck=bottleneck,
            )

    def upstream(self, node_name: str) -> set[str]:
        """Belirtilen düğümün tüm yukarı akış bağımlılıklarını döndürür.

        Args:
            node_name: Hedef düğüm adı.

        Returns:
            Yukarı akış düğüm adları kümesi.
        """
        with self._lock:
            # Kenarları ters yönde al
            rev: dict[str, set[str]] = defaultdict(set)
            for src, dsts in self._edges.items():
                for dst in dsts:
                    rev[dst].add(src)

            visited: set[str] = set()
            queue: deque[str] = deque([node_name])
            while queue:
                current = queue.popleft()
                for dep in rev.get(current, set()):
                    if dep not in visited:
                        visited.add(dep)
                        queue.append(dep)
            visited.discard(node_name)
            return visited

    def downstream(self, node_name: str) -> set[str]:
        """Belirtilen düğümün tüm aşağı akış bağımlılarını döndürür.

        Args:
            node_name: Kaynak düğüm adı.

        Returns:
            Aşağı akış düğüm adları kümesi.
        """
        with self._lock:
            visited: set[str] = set()
            queue: deque[str] = deque([node_name])
            while queue:
                current = queue.popleft()
                for dep in self._edges.get(current, set()):
                    if dep not in visited:
                        visited.add(dep)
                        queue.append(dep)
            visited.discard(node_name)
            return visited

    def to_dot(self) -> str:
        """Grafı DOT formatında döndürür (Graphviz görselleştirme).

        Returns:
            DOT formatında string.
        """
        with self._lock:
            lines = [f'digraph "{self.name}" {{', "  rankdir=LR;"]
            for name, node in self._nodes.items():
                label = name
                if node.description:
                    label = f"{name}\\n({node.description})"
                lines.append(f'  "{name}" [label="{label}"];')
            for src, dsts in self._edges.items():
                for dst in sorted(dsts):
                    lines.append(f'  "{src}" -> "{dst}";')
            lines.append("}")
            return "\n".join(lines)

    @property
    def node_names(self) -> list[str]:
        """Tüm düğüm adları.

        Returns:
            Düğüm adları listesi.
        """
        with self._lock:
            return list(self._nodes.keys())

    @property
    def node_count(self) -> int:
        """Toplam düğüm sayısı."""
        with self._lock:
            return len(self._nodes)


def build_alpha_bist_dag() -> DependencyGraph:
    """ALPHA BIST standart günlük pipeline DAG'ı oluşturur.

    Returns:
        Konfigüre edilmiş DependencyGraph nesnesi.
    """
    dag = DependencyGraph(name="alpha_bist_daily")

    # Veri toplama katmanı
    nodes = [
        DependencyNode("market_data_fetch", "Piyasa verisi çek", timeout_seconds=60.0, retries=3),
        DependencyNode("macro_data_fetch", "Makro veri çek", timeout_seconds=30.0, retries=2),
        DependencyNode("news_fetch", "Haber çek", timeout_seconds=20.0, retries=2),
        # Feature hesaplama
        DependencyNode("feature_engineering", "Feature hesapla", timeout_seconds=120.0, retries=1),
        DependencyNode("macro_features", "Makro feature", timeout_seconds=60.0, retries=1),
        DependencyNode("sentiment_features", "Duygu feature", timeout_seconds=30.0, retries=1),
        # Etiketleme
        DependencyNode("labeling", "Triple barrier etiketleme", timeout_seconds=60.0, retries=1),
        # Model
        DependencyNode("model_inference", "Model tahmini", timeout_seconds=90.0, retries=2),
        # Risk
        DependencyNode("risk_assessment", "Risk değerlendirme", timeout_seconds=30.0, retries=2),
        # Karar ve sipariş
        DependencyNode("signal_generation", "Sinyal üret", timeout_seconds=30.0, retries=1),
        DependencyNode("order_management", "Emir yönetimi", timeout_seconds=30.0, retries=2),
        # Raporlama
        DependencyNode("daily_report", "Günlük rapor", timeout_seconds=30.0, retries=1),
    ]

    for node in nodes:
        dag.add_node(node)

    # Bağımlılıklar
    edges = [
        ("market_data_fetch", "feature_engineering"),
        ("market_data_fetch", "labeling"),
        ("macro_data_fetch", "macro_features"),
        ("news_fetch", "sentiment_features"),
        ("feature_engineering", "model_inference"),
        ("macro_features", "model_inference"),
        ("sentiment_features", "model_inference"),
        ("labeling", "model_inference"),
        ("model_inference", "risk_assessment"),
        ("risk_assessment", "signal_generation"),
        ("signal_generation", "order_management"),
        ("order_management", "daily_report"),
    ]

    for frm, to in edges:
        dag.add_edge(frm, to)

    logger.info(
        "ALPHA BIST pipeline DAG oluşturuldu.",
        nodes=dag.node_count,
        edges=dag._edge_count(),
    )
    return dag


__all__: list[str] = [
    "CriticalPathResult",
    "CycleDetectedError",
    "DependencyGraph",
    "DependencyNode",
    "build_alpha_bist_dag",
]
