"""ALPHA BIST — Feature Lineage Tracker v1.0

Feature lineage tracking — raw data'dan feature'a, feature'dan model'e kadar tam izleme:
- Raw data → feature dönüşüm zinciri
- Feature dependency graph
- Lineage sorgulama (bu feature hangi raw data'dan türedi?)
- Mermaid formatında dependency graph üretimi
- Lineage history tracking

Kullanım:
    from services.features.lineage import feature_lineage

    # Lineage kaydet
    feature_lineage.record(
        feature_name="rsi_14",
        raw_sources=["close_price"],
        transformations=["log_return", "rs_calculation", "rsi_formula"],
        computed_by="feature-engine",
    )

    # Lineage sorgula
    lineage = feature_lineage.get_lineage("rsi_14")

    # Dependency graph üret
    graph = feature_lineage.generate_dependency_graph()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class LineageNode:
    """Lineage graph düğümü."""

    name: str
    node_type: str  # "raw", "feature", "model", "target"
    description: str = ""
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LineageEdge:
    """Lineage graph kenarı."""

    source: str  # Kaynak düğüm adı
    target: str  # Hedef düğüm adı
    transformation: str = ""  # Dönüşüm açıklaması


@dataclass
class FeatureLineageRecord:
    """Tek feature'ın lineage kaydı."""

    feature_name: str
    raw_sources: list[str]
    intermediate_features: list[str]  # Bağımlı feature'lar
    transformations: list[str]
    computed_by: str  # Hangi modül hesapladı
    version: int = 1
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LineageGraph:
    """Tam lineage graph."""

    nodes: list[LineageNode]
    edges: list[LineageEdge]
    mermaid: str  # Mermaid formatında graph
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FeatureLineageTracker:
    """Feature lineage tracking motoru.

    Özellikler:
    - Raw data → feature dönüşüm zinciri kaydı
    - Feature dependency graph oluşturma
    - Lineage sorgulama
    - Mermaid formatında graph üretimi
    - Version-aware lineage tracking
    """

    def __init__(self):
        self._records: dict[str, FeatureLineageRecord] = {}
        self._raw_sources: set[str] = set()
        self._history: list[dict[str, Any]] = []

    def record(
        self,
        feature_name: str,
        raw_sources: list[str],
        transformations: list[str],
        computed_by: str = "unknown",
        intermediate_features: list[str] | None = None,
        version: int = 1,
        description: str = "",
    ) -> None:
        """Feature lineage kaydet.

        Args:
            feature_name: Feature adı
            raw_sources: Ham veri kaynakları (ör: ["close_price", "volume"])
            transformations: Dönüşüm adımları (ör: ["log_return", "rsi_calculation"])
            computed_by: Hangi modül hesapladı
            intermediate_features: Ara feature'lar (bağımlı feature'lar)
            version: Feature version
            description: Açıklama
        """
        record = FeatureLineageRecord(
            feature_name=feature_name,
            raw_sources=raw_sources,
            intermediate_features=intermediate_features or [],
            transformations=transformations,
            computed_by=computed_by,
            version=version,
            description=description,
        )

        self._records[feature_name] = record
        self._raw_sources.update(raw_sources)

        logger.debug(
            "lineage_recorded",
            feature=feature_name,
            raw_sources=raw_sources,
            computed_by=computed_by,
        )

    def get_lineage(self, feature_name: str) -> FeatureLineageRecord | None:
        """Feature lineage kaydını döndür.

        Args:
            feature_name: Feature adı

        Returns:
            FeatureLineageRecord veya None
        """
        return self._records.get(feature_name)

    def get_raw_sources(self, feature_name: str) -> list[str]:
        """Feature'ın raw kaynaklarını döndür.

        Args:
            feature_name: Feature adı

        Returns:
            Raw kaynak listesi
        """
        record = self._records.get(feature_name)
        if record is None:
            return []

        # Recursive olarak tüm raw kaynakları topla
        all_sources: set[str] = set(record.raw_sources)

        for intermediate in record.intermediate_features:
            intermediate_sources = self.get_raw_sources(intermediate)
            all_sources.update(intermediate_sources)

        return sorted(all_sources)

    def get_dependents(self, feature_name: str) -> list[str]:
        """Bu feature'a bağımlı feature'ları döndür.

        Args:
            feature_name: Feature adı

        Returns:
            Bağımlı feature isimleri
        """
        dependents: list[str] = []
        for name, record in self._records.items():
            if feature_name in record.raw_sources or feature_name in record.intermediate_features:
                dependents.append(name)
        return sorted(dependents)

    def get_all_features(self) -> list[str]:
        """Tüm kayıtlı feature isimlerini döndür."""
        return sorted(self._records.keys())

    def get_all_raw_sources(self) -> list[str]:
        """Tüm raw kaynak isimlerini döndür."""
        return sorted(self._raw_sources)

    def generate_dependency_graph(self) -> LineageGraph:
        """Tam dependency graph oluştur.

        Returns:
            LineageGraph (nodes, edges, mermaid formatında)
        """
        nodes: list[LineageNode] = []
        edges: list[LineageEdge] = []
        seen_nodes: set[str] = set()

        # Raw source düğümleri
        for raw in self._raw_sources:
            if raw not in seen_nodes:
                nodes.append(LineageNode(name=raw, node_type="raw"))
                seen_nodes.add(raw)

        # Feature düğümleri ve kenarları
        for name, record in self._records.items():
            if name not in seen_nodes:
                nodes.append(LineageNode(
                    name=name,
                    node_type="feature",
                    description=record.description,
                    version=record.version,
                ))
                seen_nodes.add(name)

            # Raw source kenarları
            for raw in record.raw_sources:
                edges.append(LineageEdge(
                    source=raw,
                    target=name,
                    transformation=record.transformations[0] if record.transformations else "",
                ))

            # Intermediate feature kenarları
            for intermediate in record.intermediate_features:
                edges.append(LineageEdge(
                    source=intermediate,
                    target=name,
                    transformation="composition",
                ))

        # Mermaid formatı
        mermaid = self._generate_mermaid(nodes, edges)

        return LineageGraph(
            nodes=nodes,
            edges=edges,
            mermaid=mermaid,
        )

    def trace_to_raw(self, feature_name: str) -> dict[str, Any]:
        """Feature'dan raw data'ya kadar tam izleme.

        Args:
            feature_name: Feature adı

        Returns:
            {feature, raw_sources, transformation_chain, depth}
        """
        record = self._records.get(feature_name)
        if record is None:
            return {"feature": feature_name, "raw_sources": [], "transformation_chain": [], "depth": 0}

        # Recursive transformation chain
        chain: list[str] = []
        self._build_chain(feature_name, chain, depth=0)

        return {
            "feature": feature_name,
            "raw_sources": self.get_raw_sources(feature_name),
            "transformation_chain": chain,
            "depth": len(chain),
            "computed_by": record.computed_by,
            "version": record.version,
        }

    def get_lineage_summary(self) -> dict[str, Any]:
        """Lineage özeti."""
        return {
            "total_features": len(self._records),
            "total_raw_sources": len(self._raw_sources),
            "raw_sources": sorted(self._raw_sources),
            "features_by_computed_by": self._group_by_computed_by(),
            "avg_transformations": self._avg_transformations(),
        }

    def _build_chain(self, feature_name: str, chain: list[str], depth: int) -> None:
        """Recursive transformation chain oluştur."""
        if depth > 10:  # Sonsuz döngü koruması
            return

        record = self._records.get(feature_name)
        if record is None:
            return

        for transform in record.transformations:
            chain.append(f"{feature_name}: {transform}")

        for intermediate in record.intermediate_features:
            self._build_chain(intermediate, chain, depth + 1)

    def _group_by_computed_by(self) -> dict[str, int]:
        """Computed_by'a göre feature sayısı."""
        groups: dict[str, int] = {}
        for record in self._records.values():
            groups[record.computed_by] = groups.get(record.computed_by, 0) + 1
        return groups

    def _avg_transformations(self) -> float:
        """Ortal transformation sayısı."""
        if not self._records:
            return 0.0
        total = sum(len(r.transformations) for r in self._records.values())
        return round(total / len(self._records), 2)

    def _generate_mermaid(self, nodes: list[LineageNode], edges: list[LineageEdge]) -> str:
        """Mermaid formatında graph üret."""
        lines: list[str] = ["graph TD"]

        # Düğüm tanımları
        for node in nodes:
            safe_name = node.name.replace(".", "_").replace("-", "_")
            if node.node_type == "raw":
                lines.append(f"    {safe_name}[\"📦 {node.name}\"]")
            elif node.node_type == "feature":
                lines.append(f"    {safe_name}[\"🔧 {node.name}\"]")
            elif node.node_type == "model":
                lines.append(f"    {safe_name}[\"🤖 {node.name}\"]")
            else:
                lines.append(f"    {safe_name}[\"📊 {node.name}\"]")

        # Kenar tanımları
        for edge in edges:
            safe_source = edge.source.replace(".", "_").replace("-", "_")
            safe_target = edge.target.replace(".", "_").replace("-", "_")
            if edge.transformation:
                lines.append(f"    {safe_source} -->|{edge.transformation}| {safe_target}")
            else:
                lines.append(f"    {safe_source} --> {safe_target}")

        return "\n".join(lines)


# Singleton
feature_lineage = FeatureLineageTracker()
