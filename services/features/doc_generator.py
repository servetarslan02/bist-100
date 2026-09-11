"""ALPHA BIST — Feature Dokümantasyon Üretici v1.0

Feature contract tanımlarından otomatik dokümantasyon üretimi sağlar.
Çıktı formatları: Markdown katalog, Mermaid bağımlılık grafiği,
özet istatistik raporu ve tekil feature kartları.

Modül, feature_registry singleton'ı ile entegre çalışır.
Registry boşsa boş rapor döndürür, hata fırlatmaz.

Kullanım:
    from services.features.doc_generator import feature_doc_generator

    # Tam katalog üret
    markdown = feature_doc_generator.generate_catalog()

    # Dependency graph
    mermaid = feature_doc_generator.generate_dependency_graph()

    # Özet rapor
    summary = feature_doc_generator.generate_summary_report()

    # Tekil feature kartı
    card = feature_doc_generator.generate_feature_card(contract)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORY: str = "other"
_DEFAULT_OWNER: str = "unknown"
_DEFAULT_FREQUENCY: str = "unknown"
_DEFAULT_ICON: str = "📦"

_CATEGORY_ICONS: dict[str, str] = {
    "technical": "📈",
    "fundamental": "📊",
    "sentiment": "💬",
    "microstructure": "🔬",
    "session": "⏰",
    "risk": "⚠️",
    "market": "🏛️",
    "macro": "🌍",
    "momentum": "🚀",
    "volume": "📦",
    "volatility": "🌊",
    "quality": "✅",
    "liquidity": "💧",
}


# ---------------------------------------------------------------------------
# Yardımcı veri sınıfı
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CategoryStats:
    """Kategori bazlı istatistik tutucusu.

    Args:
        name: Kategori adı
        count: Bu kategorideki feature sayısı
        ratio: Toplam feature sayısına oranı (yüzde)
    """

    name: str
    count: int
    ratio: float

    def __repr__(self) -> str:
        """Sınıfın kısa temsilini döndürür.

        Returns:
            _CategoryStats alanlarını içeren okunabilir metin.
        """
        return f"_CategoryStats(name={self.name!r}, count={self.count}, ratio={self.ratio:.1f}%)"


# ---------------------------------------------------------------------------
# Özet istatistik veri yapısı
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SummaryStats:
    """Özet rapor istatistik veri yapısı.

    Args:
        total: Toplam feature sayısı
        pit_safe: PIT-safe feature sayısı
        pit_unsafe: PIT-unsafe feature sayısı
        avg_lookback: Ortalama lookback süresi (gün)
        max_lookback: Maksimum lookback süresi (gün)
        categories: Kategori bazlı istatistik listesi
        owners: Owner bazlı istatistik listesi
        frequencies: Frekans bazlı istatistik listesi
    """

    total: int
    pit_safe: int
    pit_unsafe: int
    avg_lookback: float
    max_lookback: int
    categories: list[_CategoryStats]
    owners: list[_CategoryStats]
    frequencies: list[_CategoryStats]

    def __repr__(self) -> str:
        """Özet istatistiklerin kısa temsilini döndürür.

        Returns:
            _SummaryStats alanlarını içeren okunabilir metin.
        """
        return (
            f"_SummaryStats(total={self.total}, pit_safe={self.pit_safe}, "
            f"pit_unsafe={self.pit_unsafe}, avg_lookback={self.avg_lookback:.1f}, "
            f"max_lookback={self.max_lookback})"
        )


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------


class FeatureDocGenerator:
    """Feature dokümantasyon üretici sınıfı.

    Feature contract listesinden Markdown katalog, Mermaid bağımlılık grafiği,
    özet istatistik raporu ve tekil feature kartları üretir.

    Sınıf, modül sonundaki ``feature_doc_generator`` singleton örneği üzerinden kullanılır.
    Durum tutmaz (stateless), thread-safe'dir.

    Özellikler:
        - Markdown feature catalog üretimi
        - Mermaid dependency graph üretimi
        - Per-category ve per-owner raporlar
        - Özet istatistikler
    """

    def __init__(self) -> None:
        """FeatureDocGenerator başlatıcısı.

        Ek bir yapılandırma gerektirmez. Stateless olarak tasarlanmıştır.
        Modül sonundaki singleton örneği (`feature_doc_generator`) üzerinden kullanılır.

        Returns:
            None.

        Raises:
            Yok — başlatma hatası oluşmaz.
        """
        self._logger = structlog.get_logger().bind(component="doc_generator")

    def __repr__(self) -> str:
        """Sınıfın kısa temsilini döndürür.

        Returns:
            Sınıf adını ve boş parantez içeren metin.
        """
        return "FeatureDocGenerator()"

    # ------------------------------------------------------------------
    # Dış API
    # ------------------------------------------------------------------

    def generate_catalog(
        self,
        contracts: list[Any] | None = None,
        registry: Any | None = None,
    ) -> str:
        """Tüm feature'lar için Markdown katalog üretir.

        Her feature için ad, açıklama, kaynak, formül, lookback, frekans,
        PIT-safe durumu ve bağımlılıkları içeren tablo formatında katalog oluşturur.
        Feature'lar kategoriye göre gruplanır ve alfabetik sıralanır.

        Args:
            contracts: FeatureContract listesi. None ise registry singleton'dan alınır.
            registry: FeatureRegistry instance. Geriye uyumluluk için korunur,
                      None ise singleton kullanılır.

        Returns:
            Markdown formatında tam katalog metni.

        Raises:
            RuntimeError: Registry erişiminde hata oluşursa.
        """
        contracts = self._resolve_contracts(contracts, registry)

        if not contracts:
            logger.info("catalog_empty", reason="no_contracts")
            return "# ALPHA BIST — Feature Catalog\n\n> Henüz feature tanımlı değil.\n"

        by_category = self._group_by_category(contracts)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        sections: list[str] = [
            "# ALPHA BIST — Feature Catalog",
            "",
            f"> Oluşturulma: {now}",
            f"> Toplam Feature: {len(contracts)}",
            "",
            "---",
            "",
        ]

        for category in sorted(by_category.keys()):
            features = by_category[category]
            sections.append(f"## {category.upper()}")
            sections.append("")
            sections.extend(self._render_feature_table(features))
            sections.append("---")
            sections.append("")

        logger.info(
            "catalog_generated",
            total=len(contracts),
            categories=len(by_category),
        )
        return "\n".join(sections)

    def generate_dependency_graph(
        self,
        contracts: list[Any] | None = None,
        registry: Any | None = None,
    ) -> str:
        """Feature dependency graph üretir (Mermaid formatında).

        Feature'lar arası bağımlılık ilişkilerini Mermaid diagram syntax'ında
        üretir. Her feature düğümü kategori ikonu ile etiketlenir.

        Args:
            contracts: FeatureContract listesi. None ise registry'den alınır.
            registry: FeatureRegistry instance. Geriye uyumluluk için korunur.

        Returns:
            Mermaid formatında graph metni.

        Raises:
            RuntimeError: Registry erişiminde hata oluşursa.
        """
        contracts = self._resolve_contracts(contracts, registry)

        if not contracts:
            return "graph TD\n    empty[\"Henüz feature yok\"]"

        lines: list[str] = ["graph TD"]
        seen_nodes: set[str] = set()

        for c in contracts:
            name = getattr(c, "name", None)
            if not name:
                logger.warning("contract_missing_name", contract=repr(c))
                continue

            safe_name = name.replace(".", "_").replace("-", "_")

            if safe_name not in seen_nodes:
                icon = _CATEGORY_ICONS.get(getattr(c, "category", _DEFAULT_CATEGORY), _DEFAULT_ICON)
                lines.append(f'    {safe_name}["{icon} {name}"]')
                seen_nodes.add(safe_name)

            for dep in getattr(c, "dependencies", []):
                safe_dep = dep.replace(".", "_").replace("-", "_")
                if safe_dep not in seen_nodes:
                    lines.append(f'    {safe_dep}["{_DEFAULT_ICON} {dep}"]')
                    seen_nodes.add(safe_dep)
                lines.append(f"    {safe_dep} --> {safe_name}")

        logger.info("dependency_graph_generated", nodes=len(seen_nodes))
        return "\n".join(lines)

    def generate_summary_report(
        self,
        contracts: list[Any] | None = None,
        registry: Any | None = None,
    ) -> str:
        """Özet istatistik raporu üretir (Markdown).

        PIT-safe dağılımı, kategori dağılımı, owner dağılımı, frekans dağılımı
        ve lookback istatistiklerini içeren kapsamlı özet rapor oluşturur.

        Args:
            contracts: FeatureContract listesi. None ise registry'den alınır.
            registry: FeatureRegistry instance. Geriye uyumluluk için korunur.

        Returns:
            Markdown formatında özet rapor metni.

        Raises:
            RuntimeError: Registry erişiminde hata oluşursa.
        """
        contracts = self._resolve_contracts(contracts, registry)

        if not contracts:
            return (
                "# ALPHA BIST — Feature Summary Report\n\n"
                "> Henüz feature tanımlı değil.\n"
            )

        stats = self._compute_stats(contracts)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        sections: list[str] = [
            "# ALPHA BIST — Feature Summary Report",
            "",
            f"> Oluşturulma: {now}",
            "",
            *self._render_general_stats(stats),
            "",
            *self._render_distribution_table("Kategori Dağılımı", stats.categories),
            "",
            *self._render_distribution_table("Owner Dağılımı", stats.owners),
            "",
            *self._render_distribution_table("Frekans Dağılımı", stats.frequencies),
            "",
            "---",
            "",
            "*Bu rapor FeatureDocGenerator tarafından otomatik oluşturulmuştur.*",
        ]

        logger.info(
            "summary_report_generated",
            total=stats.total,
            pit_safe=stats.pit_safe,
        )
        return "\n".join(sections)

    def generate_feature_card(self, contract: Any) -> str:
        """Tek feature için kart formatında dokümantasyon üretir.

        Feature'ın tüm metadata'sını okunabilir Markdown kartı formatında döndürür.

        Args:
            contract: FeatureContract instance.

        Returns:
            Markdown formatında feature kartı metni.

        Raises:
            AttributeError: contract.name erişilemezse (zorunlu alan).
        """
        name = getattr(contract, "name", None)
        if not name:
            logger.error("feature_card_no_name", contract=repr(contract))
            raise AttributeError("FeatureContract.name zorunlu alandır, None geldi.")

        pit_safe = getattr(contract, "pit_safe", False)
        pit_icon = "✅" if pit_safe else "⚠️"

        sections: list[str] = [
            f"# {name}",
            "",
            f"> {getattr(contract, 'description', '-')}",
            "",
            "## Metadata",
            "",
            f"- **Kaynak:** {getattr(contract, 'source', '-')}",
            f"- **Formül:** `{getattr(contract, 'formula', '-')}`",
            f"- **Lookback:** {getattr(contract, 'lookback', 0)} gün",
            f"- **Frekans:** {getattr(contract, 'frequency', '-')}",
            f"- **Kullanılabilirlik:** {getattr(contract, 'available_at', '-')}",
            f"- **PIT-Safe:** {pit_icon} {'Evet' if pit_safe else 'Hayır'}",
            f"- **Version:** v{getattr(contract, 'version', '?')}",
            f"- **Owner:** {getattr(contract, 'owner', '-')}",
            f"- **Kategori:** {getattr(contract, 'category', _DEFAULT_CATEGORY)}",
        ]

        value_range = getattr(contract, "value_range", None)
        if value_range and len(value_range) >= 2:
            sections.append(f"- **Değer Aralığı:** [{value_range[0]}, {value_range[1]}]")

        validation_rules = getattr(contract, "validation_rules", None)
        if validation_rules:
            sections.append("- **Validasyon Kuralları:**")
            for k, v in validation_rules.items():
                sections.append(f"  - {k}: {v}")

        dependencies = getattr(contract, "dependencies", None)
        if dependencies:
            sections.append("- **Bağımlılıklar:**")
            for dep in dependencies:
                sections.append(f"  - `{dep}`")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # İç yardımcı metodlar
    # ------------------------------------------------------------------

    def _resolve_contracts(
        self,
        contracts: list[Any] | None,
        registry: Any | None,
    ) -> list[Any]:
        """Contract listesini çözümler — dışarıdan geldiyse onu kullanır, yoksa registry'den alır.

        Args:
            contracts: Dışarıdan verilen contract listesi veya None.
            registry: FeatureRegistry instance veya None.

        Returns:
            FeatureContract listesi.

        Raises:
            RuntimeError: Registry erişiminde hata oluşursa.
        """
        if contracts is not None:
            return list(contracts)

        try:
            from .contract import feature_registry

            resolved = feature_registry.list_all()
            logger.debug("contracts_resolved_from_registry", count=len(resolved))
            return resolved
        except Exception as exc:
            logger.error("registry_access_failed", error=str(exc))
            raise RuntimeError(
                f"Feature registry erişimi başarısız: {exc}"
            ) from exc

    def _group_by_category(self, contracts: list[Any]) -> dict[str, list[Any]]:
        """Contract listesini kategoriye göre gruplar.

        Args:
            contracts: FeatureContract listesi.

        Returns:
            Kategori adı → contract listesi sözlüğü.
        """
        by_category: dict[str, list[Any]] = {}
        for c in contracts:
            cat = getattr(c, "category", _DEFAULT_CATEGORY)
            by_category.setdefault(cat, []).append(c)
        return by_category

    def _render_feature_table(self, features: list[Any]) -> list[str]:
        """Bir kategorideki feature'ları Markdown tablosu olarak render eder.

        Args:
            features: Aynı kategorideki FeatureContract listesi.

        Returns:
            Markdown tablo satırları.
        """
        rows: list[str] = []
        for c in sorted(features, key=lambda x: getattr(x, "name", "")):
            name = getattr(c, "name", "unknown")
            pit_safe = getattr(c, "pit_safe", False)
            pit_icon = "✅" if pit_safe else "⚠️"

            rows.append(f"### `{name}`")
            rows.append("")
            rows.append("| Alan | Değer |")
            rows.append("|------|-------|")
            rows.append(f"| **Açıklama** | {getattr(c, 'description', '-')} |")
            rows.append(f"| **Kaynak** | {getattr(c, 'source', '-')} |")
            rows.append(f"| **Formül** | `{getattr(c, 'formula', '-')}` |")
            rows.append(f"| **Lookback** | {getattr(c, 'lookback', 0)} gün |")
            rows.append(f"| **Frekans** | {getattr(c, 'frequency', '-')} |")
            rows.append(f"| **Kullanılabilirlik** | {getattr(c, 'available_at', '-')} |")
            rows.append(f"| **PIT-Safe** | {pit_icon} {'Evet' if pit_safe else 'Hayır'} |")
            rows.append(f"| **Version** | v{getattr(c, 'version', '?')} |")
            rows.append(f"| **Owner** | {getattr(c, 'owner', '-')} |")
            rows.append(f"| **Kategori** | {getattr(c, 'category', _DEFAULT_CATEGORY)} |")

            value_range = getattr(c, "value_range", None)
            if value_range and len(value_range) >= 2:
                rows.append(f"| **Değer Aralığı** | [{value_range[0]}, {value_range[1]}] |")

            validation_rules = getattr(c, "validation_rules", None)
            if validation_rules:
                rules_str = ", ".join(f"{k}={v}" for k, v in validation_rules.items())
                rows.append(f"| **Validasyon Kuralları** | {rules_str} |")

            dependencies = getattr(c, "dependencies", None)
            if dependencies:
                deps_str = ", ".join(f"`{d}`" for d in dependencies)
                rows.append(f"| **Bağımlılıklar** | {deps_str} |")

            rows.append("")

        return rows

    def _compute_stats(self, contracts: list[Any]) -> _SummaryStats:
        """Contract listesinden özet istatistikleri hesaplar.

        Tek geçişte tüm istatistikleri toplar — performans optimizasyonu.

        Args:
            contracts: FeatureContract listesi.

        Returns:
            _SummaryStats veri yapısı.
        """
        total = len(contracts)
        pit_safe = 0
        lookback_sum = 0
        max_lookback = 0

        cat_counts: dict[str, int] = {}
        owner_counts: dict[str, int] = {}
        freq_counts: dict[str, int] = {}

        for c in contracts:
            # PIT-safe sayacı
            if getattr(c, "pit_safe", False):
                pit_safe += 1

            # Lookback istatistikleri
            lb = getattr(c, "lookback", 0)
            lookback_sum += lb
            if lb > max_lookback:
                max_lookback = lb

            # Kategori/owner/frekans dağılımı (tek geçiş)
            cat = getattr(c, "category", _DEFAULT_CATEGORY)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

            owner = getattr(c, "owner", _DEFAULT_OWNER)
            owner_counts[owner] = owner_counts.get(owner, 0) + 1

            freq = getattr(c, "frequency", _DEFAULT_FREQUENCY)
            freq_counts[freq] = freq_counts.get(freq, 0) + 1

        safe_total = max(total, 1)
        avg_lookback = lookback_sum / safe_total

        return _SummaryStats(
            total=total,
            pit_safe=pit_safe,
            pit_unsafe=total - pit_safe,
            avg_lookback=avg_lookback,
            max_lookback=max_lookback,
            categories=sorted(
                [_CategoryStats(k, v, v / safe_total * 100) for k, v in cat_counts.items()],
                key=lambda s: s.count,
                reverse=True,
            ),
            owners=sorted(
                [_CategoryStats(k, v, v / safe_total * 100) for k, v in owner_counts.items()],
                key=lambda s: s.count,
                reverse=True,
            ),
            frequencies=sorted(
                [_CategoryStats(k, v, v / safe_total * 100) for k, v in freq_counts.items()],
                key=lambda s: s.count,
                reverse=True,
            ),
        )

    def _render_general_stats(self, stats: _SummaryStats) -> list[str]:
        """Genel istatistik tablosunu render eder.

        Args:
            stats: _SummaryStats veri yapısı.

        Returns:
            Markdown tablo satırları.
        """
        safe_total = max(stats.total, 1)
        return [
            "## Genel İstatistikler",
            "",
            "| Metrik | Değer |",
            "|--------|-------|",
            f"| Toplam Feature | {stats.total} |",
            f"| PIT-Safe | {stats.pit_safe} ({stats.pit_safe / safe_total * 100:.0f}%) |",
            f"| PIT-Unsafe | {stats.pit_unsafe} ({stats.pit_unsafe / safe_total * 100:.0f}%) |",
            f"| Ortalama Lookback | {stats.avg_lookback:.1f} gün |",
            f"| Maksimum Lookback | {stats.max_lookback} gün |",
        ]

    def _render_distribution_table(
        self,
        title: str,
        items: list[_CategoryStats],
    ) -> list[str]:
        """Dağılım tablosunu render eder.

        Args:
            title: Tablo başlığı.
            items: _CategoryStats listesi.

        Returns:
            Markdown tablo satırları.
        """
        rows: list[str] = [
            f"## {title}",
            "",
            "| Adet | Sayı | Oran |",
            "|------|------|------|",
        ]
        for item in items:
            rows.append(f"| {item.name} | {item.count} | {item.ratio:.0f}% |")
        return rows


__all__: list[str] = ["FeatureDocGenerator", "feature_doc_generator"]

# Singleton
feature_doc_generator = FeatureDocGenerator()
