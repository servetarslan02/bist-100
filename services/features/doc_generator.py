"""ALPHA BIST — Feature Documentation Generator v1.0

Feature contract'tan otomatik dokümantasyon üretimi:
- Markdown formatında feature catalog
- Feature dependency graph (Mermaid)
- Feature summary statistics
- Per-category ve per-owner raporlar

Kullanım:
    from services.features.doc_generator import feature_doc_generator

    # Tam katalog üret
    markdown = feature_doc_generator.generate_catalog()

    # Dependency graph
    mermaid = feature_doc_generator.generate_dependency_graph()

    # Özet rapor
    summary = feature_doc_generator.generate_summary_report()
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class FeatureDocGenerator:
    """Feature dokümantasyon üretici.

    Özellikler:
    - Markdown feature catalog
    - Mermaid dependency graph
    - Per-category raporlar
    - Per-owner raporlar
    - Summary statistics
    """

    def __init__(self):
        """Otomatik eklendi."""
        pass

    def generate_catalog(
        self,
        contracts: list[Any] | None = None,
        registry: Any | None = None,
    ) -> str:
        """Tüm feature'lar için Markdown katalog üret.

        Args:
            contracts: FeatureContract listesi (None = registry'den al)
            registry: FeatureRegistry instance (None = singleton kullan)

        Returns:
            Markdown formatında katalog
        """
        if contracts is None:
            from .contract import feature_registry

            contracts = feature_registry.list_all()

        lines: list[str] = [
            "# ALPHA BIST — Feature Catalog",
            "",
            f"> Oluşturulma: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            f"> Toplam Feature: {len(contracts)}",
            "",
            "---",
            "",
        ]

        # Kategoriye göre grupla
        by_category: dict[str, list[Any]] = {}
        for c in contracts:
            cat = getattr(c, "category", "other")
            by_category.setdefault(cat, []).append(c)

        for category in sorted(by_category.keys()):
            features = by_category[category]
            lines.append(f"## {category.upper()}")
            lines.append("")

            for c in sorted(features, key=lambda x: x.name):
                pit_icon = "✅" if c.pit_safe else "⚠️"
                lines.append(f"### `{c.name}`")
                lines.append("")
                lines.append("| Alan | Değer |")
                lines.append("|------|-------|")
                lines.append(f"| **Açıklama** | {c.description} |")
                lines.append(f"| **Kaynak** | {c.source} |")
                lines.append(f"| **Formül** | `{c.formula}` |")
                lines.append(f"| **Lookback** | {c.lookback} gün |")
                lines.append(f"| **Frekans** | {c.frequency} |")
                lines.append(f"| **Kullanılabilirlik** | {c.available_at} |")
                lines.append(f"| **PIT-Safe** | {pit_icon} {'Evet' if c.pit_safe else 'Hayır'} |")
                lines.append(f"| **Version** | v{c.version} |")
                lines.append(f"| **Owner** | {c.owner} |")
                lines.append(f"| **Kategori** | {c.category} |")

                if c.value_range:
                    lines.append(f"| **Değer Aralığı** | [{c.value_range[0]}, {c.value_range[1]}] |")

                if c.validation_rules:
                    rules_str = ", ".join(f"{k}={v}" for k, v in c.validation_rules.items())
                    lines.append(f"| **Validasyon Kuralları** | {rules_str} |")

                if c.dependencies:
                    deps_str = ", ".join(f"`{d}`" for d in c.dependencies)
                    lines.append(f"| **Bağımlılıklar** | {deps_str} |")

                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def generate_dependency_graph(
        self,
        contracts: list[Any] | None = None,
    ) -> str:
        """Feature dependency graph üret (Mermaid formatında).

        Args:
            contracts: FeatureContract listesi

        Returns:
            Mermaid formatında graph
        """
        if contracts is None:
            from .contract import feature_registry

            contracts = feature_registry.list_all()

        lines: list[str] = ["graph TD"]
        seen_nodes: set[str] = set()

        for c in contracts:
            safe_name = c.name.replace(".", "_").replace("-", "_")

            if safe_name not in seen_nodes:
                icon = self._get_category_icon(c.category)
                lines.append(f'    {safe_name}["{icon} {c.name}"]')
                seen_nodes.add(safe_name)

            for dep in c.dependencies:
                safe_dep = dep.replace(".", "_").replace("-", "_")
                if safe_dep not in seen_nodes:
                    lines.append(f'    {safe_dep}["📦 {dep}"]')
                    seen_nodes.add(safe_dep)
                lines.append(f"    {safe_dep} --> {safe_name}")

        return "\n".join(lines)

    def generate_summary_report(
        self,
        contracts: list[Any] | None = None,
    ) -> str:
        """Özet rapor üret (Markdown).

        Args:
            contracts: FeatureContract listesi

        Returns:
            Markdown formatında özet rapor
        """
        if contracts is None:
            from .contract import feature_registry

            contracts = feature_registry.list_all()

        total = len(contracts)
        pit_safe = sum(1 for c in contracts if c.pit_safe)
        pit_unsafe = total - pit_safe

        # Kategori dağılımı
        by_category: dict[str, int] = {}
        for c in contracts:
            cat = getattr(c, "category", "other")
            by_category[cat] = by_category.get(cat, 0) + 1

        # Owner dağılımı
        by_owner: dict[str, int] = {}
        for c in contracts:
            by_owner[c.owner] = by_owner.get(c.owner, 0) + 1

        # Frekans dağılımı
        by_frequency: dict[str, int] = {}
        for c in contracts:
            by_frequency[c.frequency] = by_frequency.get(c.frequency, 0) + 1

        # Lookback istatistikleri
        lookbacks = [c.lookback for c in contracts]
        avg_lookback = sum(lookbacks) / len(lookbacks) if lookbacks else 0
        max_lookback = max(lookbacks) if lookbacks else 0

        lines: list[str] = [
            "# ALPHA BIST — Feature Summary Report",
            "",
            f"> Oluşturulma: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Genel İstatistikler",
            "",
            "| Metrik | Değer |",
            "|--------|-------|",
            f"| Toplam Feature | {total} |",
            f"| PIT-Safe | {pit_safe} ({pit_safe / max(total, 1) * 100:.0f}%) |",
            f"| PIT-Unsafe | {pit_unsafe} ({pit_unsafe / max(total, 1) * 100:.0f}%) |",
            f"| Ortalama Lookback | {avg_lookback:.1f} gün |",
            f"| Maksimum Lookback | {max_lookback} gün |",
            "",
            "## Kategori Dağılımı",
            "",
            "| Kategori | Sayı | Oran |",
            "|----------|------|------|",
        ]

        for cat in sorted(by_category.keys(), key=lambda x: by_category[x], reverse=True):
            count = by_category[cat]
            ratio = count / total * 100
            lines.append(f"| {cat} | {count} | {ratio:.0f}% |")

        lines.extend(
            [
                "",
                "## Owner Dağılımı",
                "",
                "| Owner | Sayı | Oran |",
                "|-------|------|------|",
            ]
        )

        for owner in sorted(by_owner.keys(), key=lambda x: by_owner[x], reverse=True):
            count = by_owner[owner]
            ratio = count / total * 100
            lines.append(f"| {owner} | {count} | {ratio:.0f}% |")

        lines.extend(
            [
                "",
                "## Frekans Dağılımı",
                "",
                "| Frekans | Sayı | Oran |",
                "|---------|------|------|",
            ]
        )

        for freq in sorted(by_frequency.keys(), key=lambda x: by_frequency[x], reverse=True):
            count = by_frequency[freq]
            ratio = count / total * 100
            lines.append(f"| {freq} | {count} | {ratio:.0f}% |")

        lines.extend(
            [
                "",
                "---",
                "",
                "*Bu rapor FeatureDocGenerator tarafından otomatik oluşturulmuştur.*",
            ]
        )

        return "\n".join(lines)

    def generate_feature_card(self, contract: Any) -> str:
        """Tek feature için kart formatında dokümantasyon.

        Args:
            contract: FeatureContract instance

        Returns:
            Markdown formatında feature kartı
        """
        pit_icon = "✅" if contract.pit_safe else "⚠️"

        lines: list[str] = [
            f"# {contract.name}",
            "",
            f"> {contract.description}",
            "",
            "## Metadata",
            "",
            f"- **Kaynak:** {contract.source}",
            f"- **Formül:** `{contract.formula}`",
            f"- **Lookback:** {contract.lookback} gün",
            f"- **Frekans:** {contract.frequency}",
            f"- **Kullanılabilirlik:** {contract.available_at}",
            f"- **PIT-Safe:** {pit_icon} {'Evet' if contract.pit_safe else 'Hayır'}",
            f"- **Version:** v{contract.version}",
            f"- **Owner:** {contract.owner}",
            f"- **Kategori:** {contract.category}",
        ]

        if contract.value_range:
            lines.append(f"- **Değer Aralığı:** [{contract.value_range[0]}, {contract.value_range[1]}]")

        if contract.validation_rules:
            lines.append("- **Validasyon Kuralları:**")
            for k, v in contract.validation_rules.items():
                lines.append(f"  - {k}: {v}")

        if contract.dependencies:
            lines.append("- **Bağımlılıklar:**")
            for dep in contract.dependencies:
                lines.append(f"  - `{dep}`")

        return "\n".join(lines)

    def _get_category_icon(self, category: str) -> str:
        """Kategori için icon döndür."""
        icons = {
            "technical": "📈",
            "fundamental": "📊",
            "sentiment": "💬",
            "microstructure": "🔬",
            "session": "⏰",
            "risk": "⚠️",
            "market": "🏛️",
            "macro": "🌍",
        }
        return icons.get(category, "📦")


# Singleton
feature_doc_generator = FeatureDocGenerator()
