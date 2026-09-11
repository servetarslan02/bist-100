"""ALPHA BIST — Feature Lineage Tracker v1.0

Feature lineage tracking — raw data'dan feature'a, feature'dan model'e kadar tam izleme:
- Raw data → feature dönüşüm zinciri
- Feature dependency graph
- Lineage sorgulama (bu feature hangi raw data'dan türedi?)
- Mermaid formatında dependency graph üretimi
- Lineage history tracking
- Persistence desteği (DuckDB/JSON)

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

    # Persistence
    feature_lineage.save_to_json("lineage.json")
    feature_lineage.load_from_json("lineage.json")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

_MAX_CHAIN_DEPTH: int = 10


# ---------------------------------------------------------------------------
# Veri sınıfları
# ---------------------------------------------------------------------------


@dataclass
class LineageNode:
    """Lineage graph düğümü.

    Args:
        name: Düğüm adı (örn: "close_price", "rsi_14")
        node_type: Düğüm tipi (raw, feature, model, target)
        description: İnsan tarafından okunabilir açıklama
        version: Versiyon numarası
        created_at: Oluşturulma zamanı (ISO 8601)
    """

    name: str
    node_type: str
    description: str = ""
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __repr__(self) -> str:
        """LineageNode kısa temsili.

        Returns:
            Düğüm adı ve tipi.
        """
        return f"LineageNode({self.name!r}, type={self.node_type!r})"


@dataclass
class LineageEdge:
    """Lineage graph kenarı.

    Args:
        source: Kaynak düğüm adı
        target: Hedef düğüm adı
        transformation: Dönüşüm açıklaması
    """

    source: str
    target: str
    transformation: str = ""

    def __repr__(self) -> str:
        """LineageEdge kısa temsili.

        Returns:
            Kaynak → hedef dönüşüm bilgisi.
        """
        return f"LineageEdge({self.source!r} → {self.target!r})"


@dataclass
class FeatureLineageRecord:
    """Tek feature'ın lineage kaydı.

    Args:
        feature_name: Feature adı
        raw_sources: Ham veri kaynakları
        intermediate_features: Ara feature'lar (bağımlı feature'lar)
        transformations: Dönüşüm adımları
        computed_by: Hangi modül hesapladı
        version: Feature version
        description: Açıklama
        created_at: Oluşturulma zamanı (ISO 8601)
    """

    feature_name: str
    raw_sources: list[str]
    intermediate_features: list[str]
    transformations: list[str]
    computed_by: str
    version: int = 1
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __repr__(self) -> str:
        """FeatureLineageRecord kısa temsili.

        Returns:
            Feature adı, kaynak sayısı ve dönüşüm sayısı.
        """
        return (
            f"FeatureLineageRecord({self.feature_name!r}, "
            f"sources={len(self.raw_sources)}, transforms={len(self.transformations)})"
        )


@dataclass
class LineageGraph:
    """Tam lineage graph.

    Args:
        nodes: Düğüm listesi
        edges: Kenar listesi
        mermaid: Mermaid formatında graph
        timestamp: Oluşturulma zamanı (ISO 8601)
    """

    nodes: list[LineageNode]
    edges: list[LineageEdge]
    mermaid: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __repr__(self) -> str:
        """LineageGraph kısa temsili.

        Returns:
            Düğüm ve kenar sayıları.
        """
        return f"LineageGraph(nodes={len(self.nodes)}, edges={len(self.edges)})"


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------


class FeatureLineageTracker:
    """Feature lineage tracking motoru.

    Raw data'dan feature'a, feature'dan model'e kadar tam izleme sağlar.
    Thread-safe değildir — tek thread tarafından kullanılmalıdır.

    Özellikler:
        - Raw data → feature dönüşüm zinciri kaydı
        - Feature dependency graph oluşturma
        - Lineage sorgulama ve izleme
        - Mermaid formatında graph üretimi
        - Version-aware lineage tracking
        - JSON persistence desteği
    """

    def __init__(self) -> None:
        """Feature lineage tracker başlatıcısı.

        Boş kayıt havuzları ve raw kaynak kümesi oluşturur.

        Returns:
            None.

        Raises:
            Yok.
        """
        self._records: dict[str, FeatureLineageRecord] = {}
        self._raw_sources: set[str] = set()
        self._history: list[dict[str, Any]] = []

    def __repr__(self) -> str:
        """FeatureLineageTracker kısa temsili.

        Returns:
            Kayıtlı feature ve raw kaynak sayıları.
        """
        return (
            f"FeatureLineageTracker(features={len(self._records)}, "
            f"raw_sources={len(self._raw_sources)})"
        )

    # ------------------------------------------------------------------
    # Dış API
    # ------------------------------------------------------------------

    def record(
        self,
        feature_name: str,
        raw_sources: list[str],
        transformations: list[str],
        computed_by: str = "unknown",
        intermediate_features: list[str] | None = None,
        version: int = 1,
        description: str = "",
    ) -> bool:
        """Feature lineage kaydeder.

        Aynı isimle kayıt varsa üzerine yazar ve eski kaydı history'ye ekler.

        Args:
            feature_name: Feature adı (örn: "rsi_14").
            raw_sources: Ham veri kaynakları (örn: ["close_price", "volume"]).
            transformations: Dönüşüm adımları (örn: ["log_return", "rsi_calculation"]).
            computed_by: Hangi modül hesapladı (örn: "feature-engine").
            intermediate_features: Ara feature'lar (bağımlı feature'lar).
            version: Feature version numarası.
            description: Feature açıklaması.

        Returns:
            True ise yeni kayıt, False ise mevcut kayıt güncellendi.

        Raises:
            ValueError: feature_name boş ise.
        """
        if not feature_name:
            raise ValueError("feature_name boş olamaz")

        is_new = feature_name not in self._records

        # Eski kaydı history'ye ekle
        if not is_new:
            old_record = self._records[feature_name]
            self._history.append({
                "action": "update",
                "feature_name": feature_name,
                "old_version": old_record.version,
                "new_version": version,
                "timestamp": datetime.now(UTC).isoformat(),
            })

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

        logger.info(
            "lineage_recorded",
            feature=feature_name,
            raw_sources=len(raw_sources),
            transformations=len(transformations),
            computed_by=computed_by,
            is_new=is_new,
        )

        return is_new

    def get_lineage(self, feature_name: str) -> FeatureLineageRecord | None:
        """Feature lineage kaydını döndürür.

        Args:
            feature_name: Feature adı.

        Returns:
            FeatureLineageRecord veya None (kayıt yoksa).
        """
        return self._records.get(feature_name)

    def has_feature(self, feature_name: str) -> bool:
        """Feature'ın kayıtlı olup olmadığını kontrol eder.

        Args:
            feature_name: Feature adı.

        Returns:
            True ise kayıtlı, False ise değil.
        """
        return feature_name in self._records

    def remove_feature(self, feature_name: str) -> bool:
        """Feature lineage kaydını siler.

        Args:
            feature_name: Feature adı.

        Returns:
            True ise silindi, False ise bulunamadı.
        """
        if feature_name not in self._records:
            return False

        old_record = self._records.pop(feature_name)
        self._history.append({
            "action": "delete",
            "feature_name": feature_name,
            "version": old_record.version,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        logger.info("lineage_removed", feature=feature_name)
        return True

    def get_raw_sources(self, feature_name: str) -> list[str]:
        """Feature'ın tüm raw kaynaklarını recursive olarak döndürür.

        Args:
            feature_name: Feature adı.

        Returns:
            Sıralanmış raw kaynak listesi. Feature bulunamazsa boş liste döner.
        """
        record = self._records.get(feature_name)
        if record is None:
            return []

        all_sources: set[str] = set(record.raw_sources)
        for intermediate in record.intermediate_features:
            all_sources.update(self.get_raw_sources(intermediate))

        return sorted(all_sources)

    def get_dependents(self, feature_name: str) -> list[str]:
        """Bu feature'a bağımlı feature'ları döndürür.

        Args:
            feature_name: Feature adı.

        Returns:
            Bağımlı feature isimleri listesi.
        """
        dependents: list[str] = []
        for name, record in self._records.items():
            if feature_name in record.raw_sources or feature_name in record.intermediate_features:
                dependents.append(name)
        return sorted(dependents)

    def get_all_features(self) -> list[str]:
        """Tüm kayıtlı feature isimlerini döndürür.

        Returns:
            Sıralanmış feature isimleri listesi.
        """
        return sorted(self._records.keys())

    def get_all_raw_sources(self) -> list[str]:
        """Tüm raw kaynak isimlerini döndürür.

        Returns:
            Sıralanmış raw kaynak isimleri listesi.
        """
        return sorted(self._raw_sources)

    def get_history(self, feature_name: str | None = None) -> list[dict[str, Any]]:
        """Lineage geçmişini döndürür.

        Args:
            feature_name: Belirli bir feature için geçmiş. None ise tüm geçmiş.

        Returns:
            Geçmiş kayıtları listesi.
        """
        if feature_name is not None:
            return [h for h in self._history if h.get("feature_name") == feature_name]
        return list(self._history)

    def get_transformation_count(self, feature_name: str) -> int:
        """Feature'ın toplam transformation sayısını döndürür (recursive).

        Args:
            feature_name: Feature adı.

        Returns:
            Toplam transformation sayısı. Feature bulunamazsa 0 döner.
        """
        record = self._records.get(feature_name)
        if record is None:
            return 0

        count = len(record.transformations)
        for intermediate in record.intermediate_features:
            count += self.get_transformation_count(intermediate)
        return count

    # ------------------------------------------------------------------
    # Graph & Rapor
    # ------------------------------------------------------------------

    def generate_dependency_graph(self) -> LineageGraph:
        """Tam dependency graph oluşturur.

        Tüm feature'lar ve raw kaynakları için düğüm ve kenar listesi,
        ayrıca Mermaid formatında graph üretir.

        Returns:
            LineageGraph: nodes, edges ve mermaid formatında graph.
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
                nodes.append(
                    LineageNode(
                        name=name,
                        node_type="feature",
                        description=record.description,
                        version=record.version,
                    )
                )
                seen_nodes.add(name)

            for raw in record.raw_sources:
                edges.append(
                    LineageEdge(
                        source=raw,
                        target=name,
                        transformation=record.transformations[0] if record.transformations else "",
                    )
                )

            for intermediate in record.intermediate_features:
                edges.append(
                    LineageEdge(
                        source=intermediate,
                        target=name,
                        transformation="composition",
                    )
                )

        mermaid = self._generate_mermaid(nodes, edges)

        return LineageGraph(nodes=nodes, edges=edges, mermaid=mermaid)

    def trace_to_raw(self, feature_name: str) -> dict[str, Any]:
        """Feature'dan raw data'ya kadar tam izleme sağlar.

        Args:
            feature_name: Feature adı.

        Returns:
            Feature, raw kaynakları, transformation zinciri ve derinlik bilgisi.
        """
        record = self._records.get(feature_name)
        if record is None:
            return {"feature": feature_name, "raw_sources": [], "transformation_chain": [], "depth": 0}

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
        """Lineage özetini döndürür.

        Returns:
            Toplam feature/raw kaynak sayısı, computed_by dağılımı,
            ortalama transformation sayısı ve feature listesi.
        """
        return {
            "total_features": len(self._records),
            "total_raw_sources": len(self._raw_sources),
            "raw_sources": sorted(self._raw_sources),
            "features": sorted(self._records.keys()),
            "features_by_computed_by": self._group_by_computed_by(),
            "avg_transformations": self._avg_transformations(),
            "history_length": len(self._history),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_to_json(self, path: str | Path) -> None:
        """Lineage kayıtlarını JSON dosyasına kaydeder.

        Args:
            path: JSON dosya yolu.

        Returns:
            None.

        Raises:
            OSError: Dosya yazma hatası.
        """
        data = {
            "records": {
                name: {
                    "feature_name": r.feature_name,
                    "raw_sources": r.raw_sources,
                    "intermediate_features": r.intermediate_features,
                    "transformations": r.transformations,
                    "computed_by": r.computed_by,
                    "version": r.version,
                    "description": r.description,
                    "created_at": r.created_at,
                }
                for name, r in self._records.items()
            },
            "history": self._history,
            "exported_at": datetime.now(UTC).isoformat(),
        }

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("lineage_saved", path=str(path), records=len(self._records))

    def load_from_json(self, path: str | Path) -> int:
        """Lineage kayıtlarını JSON dosyasından yükler.

        Mevcut kayıtların üzerine yazar.

        Args:
            path: JSON dosya yolu.

        Returns:
            Yüklenen kayıt sayısı.

        Raises:
            FileNotFoundError: Dosya bulunamazsa.
            json.JSONDecodeError: JSON formatı geçersizse.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Lineage dosyası bulunamadı: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))

        records_data = data.get("records", {})
        for name, r in records_data.items():
            self._records[name] = FeatureLineageRecord(
                feature_name=r["feature_name"],
                raw_sources=r["raw_sources"],
                intermediate_features=r.get("intermediate_features", []),
                transformations=r["transformations"],
                computed_by=r.get("computed_by", "unknown"),
                version=r.get("version", 1),
                description=r.get("description", ""),
                created_at=r.get("created_at", datetime.now(UTC).isoformat()),
            )
            self._raw_sources.update(r["raw_sources"])

        self._history.extend(data.get("history", []))

        logger.info("lineage_loaded", path=str(path), records=len(records_data))
        return len(records_data)

    # ------------------------------------------------------------------
    # İç yardımcı metodlar
    # ------------------------------------------------------------------

    def _build_chain(self, feature_name: str, chain: list[str], depth: int) -> None:
        """Recursive transformation chain oluşturur.

        Sonsuz döngü koruması: _MAX_CHAIN_DEPTH derinliğinde durur.

        Args:
            feature_name: Feature adı.
            chain: Transformation zinciri listesi (in-place güncellenir).
            depth: Mevcut derinlik.

        Returns:
            None.
        """
        if depth > _MAX_CHAIN_DEPTH:
            logger.warning(
                "chain_depth_limit_reached",
                feature=feature_name,
                depth=depth,
                max_depth=_MAX_CHAIN_DEPTH,
            )
            return

        record = self._records.get(feature_name)
        if record is None:
            return

        for transform in record.transformations:
            chain.append(f"{feature_name}: {transform}")

        for intermediate in record.intermediate_features:
            self._build_chain(intermediate, chain, depth + 1)

    def _group_by_computed_by(self) -> dict[str, int]:
        """Computed_by'a göre feature sayısını döndürür.

        Returns:
            computed_by → feature sayısı sözlüğü.
        """
        groups: dict[str, int] = {}
        for record in self._records.values():
            groups[record.computed_by] = groups.get(record.computed_by, 0) + 1
        return groups

    def _avg_transformations(self) -> float:
        """Ortalama transformation sayısını döndürür.

        Returns:
            Ortalama transformation sayısı. Kayıt yoksa 0.0.
        """
        if not self._records:
            return 0.0
        total = sum(len(r.transformations) for r in self._records.values())
        return round(total / len(self._records), 2)

    def _generate_mermaid(self, nodes: list[LineageNode], edges: list[LineageEdge]) -> str:
        """Mermaid formatında graph üretir.

        Args:
            nodes: Düğüm listesi.
            edges: Kenar listesi.

        Returns:
            Mermaid formatında graph metni.
        """
        lines: list[str] = ["graph TD"]

        for node in nodes:
            safe_name = node.name.replace(".", "_").replace("-", "_")
            if node.node_type == "raw":
                lines.append(f'    {safe_name}["📦 {node.name}"]')
            elif node.node_type == "feature":
                lines.append(f'    {safe_name}["🔧 {node.name}"]')
            elif node.node_type == "model":
                lines.append(f'    {safe_name}["🤖 {node.name}"]')
            else:
                lines.append(f'    {safe_name}["📊 {node.name}"]')

        for edge in edges:
            safe_source = edge.source.replace(".", "_").replace("-", "_")
            safe_target = edge.target.replace(".", "_").replace("-", "_")
            if edge.transformation:
                lines.append(f"    {safe_source} -->|{edge.transformation}| {safe_target}")
            else:
                lines.append(f"    {safe_source} --> {safe_target}")

        return "\n".join(lines)


__all__: list[str] = ["LineageNode", "LineageEdge", "FeatureLineageRecord", "LineageGraph", "FeatureLineageTracker", "feature_lineage"]

# Singleton
feature_lineage = FeatureLineageTracker()
