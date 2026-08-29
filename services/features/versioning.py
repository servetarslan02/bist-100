"""ALPHA BIST — Feature Version Manager v1.0

Feature version yönetimi:
- Feature tanımı değişirse otomatik version artırma
- Version history tracking
- Eski version ile uyumluluk kontrolü
- Version diff (iki version arasındaki fark)
- Version rollback

Kullanım:
    from services.features.versioning import feature_version_manager

    # Feature kaydet (otomatik version)
    feature_version_manager.register(contract)

    # Version history
    history = feature_version_manager.get_version_history("rsi_14")

    # Uyumluluk kontrolü
    compat = feature_version_manager.check_compatibility("rsi_14", old_version=1, new_version=2)

    # Rollback
    feature_version_manager.rollback("rsi_14", target_version=1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class VersionSnapshot:
    """Feature version anlık görüntüsü."""

    feature_name: str
    version: int
    source: str
    formula: str
    lookback: int
    frequency: str
    available_at: str
    pit_safe: bool
    value_range: tuple[float, float] | None
    validation_rules: dict[str, Any]
    dependencies: list[str]
    category: str
    description: str
    changed_fields: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    created_by: str = "system"


@dataclass
class VersionDiff:
    """İki version arasındaki fark."""

    feature_name: str
    old_version: int
    new_version: int
    changed_fields: list[str]
    field_changes: dict[str, dict[str, Any]]  # field → {old, new}
    is_compatible: bool
    compatibility_notes: list[str]


@dataclass
class CompatibilityReport:
    """Version uyumluluk raporu."""

    feature_name: str
    old_version: int
    new_version: int
    is_compatible: bool
    breaking_changes: list[str]
    warnings: list[str]
    notes: list[str]


class FeatureVersionManager:
    """Feature version yönetimi motoru.

    Özellikler:
    - Otomatik version artırma (değişiklik tespiti)
    - Version history tracking
    - Uyumluluk kontrolü (breaking change detection)
    - Version diff
    - Version rollback
    """

    def __init__(self):
        """Otomatik eklendi."""
        self._versions: dict[str, list[VersionSnapshot]] = {}  # feature_name → [versions]
        self._current: dict[str, VersionSnapshot] = {}  # feature_name → current version
        self._history: list[dict[str, Any]] = []

    def register(self, contract: Any) -> int:
        """Feature contract'ı kaydet. Değişiklik varsa version artır.

        Args:
            contract: FeatureContract instance

        Returns:
            Kaydedilen version numarası
        """
        name = contract.name

        # Mevcut version'ı kontrol et
        current = self._current.get(name)

        if current is None:
            # İlk kayıt
            snapshot = self._contract_to_snapshot(contract, version=1)
            self._versions[name] = [snapshot]
            self._current[name] = snapshot
            self._record_history("register", name, 1)
            logger.debug("feature_version_registered", feature=name, version=1)
            return 1

        # Değişiklik kontrolü
        changed_fields = self._detect_changes(current, contract)

        if not changed_fields:
            # Değişiklik yok — mevcut version'ı koru
            return current.version

        # Version artır
        new_version = current.version + 1
        snapshot = self._contract_to_snapshot(contract, version=new_version)
        snapshot.changed_fields = changed_fields

        self._versions[name].append(snapshot)
        self._current[name] = snapshot

        self._record_history("update", name, new_version, changed_fields)

        logger.info(
            "feature_version_updated",
            feature=name,
            old_version=current.version,
            new_version=new_version,
            changed_fields=changed_fields,
        )

        return new_version

    def get_current_version(self, feature_name: str) -> VersionSnapshot | None:
        """Feature'ın mevcut version'ını döndür."""
        return self._current.get(feature_name)

    def get_version_history(self, feature_name: str) -> list[VersionSnapshot]:
        """Feature'ın tüm version geçmişini döndür."""
        return self._versions.get(feature_name, [])

    def get_version(self, feature_name: str, version: int) -> VersionSnapshot | None:
        """Belirli bir version'ı döndür."""
        versions = self._versions.get(feature_name, [])
        for v in versions:
            if v.version == version:
                return v
        return None

    def diff(self, feature_name: str, old_version: int, new_version: int) -> VersionDiff | None:
        """İki version arasındaki farkı hesapla.

        Args:
            feature_name: Feature adı
            old_version: Eski version numarası
            new_version: Yeni version numarası

        Returns:
            VersionDiff veya None
        """
        old = self.get_version(feature_name, old_version)
        new = self.get_version(feature_name, new_version)

        if old is None or new is None:
            return None

        changed_fields: list[str] = []
        field_changes: dict[str, dict[str, Any]] = {}

        fields_to_compare = [
            "source",
            "formula",
            "lookback",
            "frequency",
            "available_at",
            "pit_safe",
            "value_range",
            "validation_rules",
            "dependencies",
            "category",
            "description",
        ]

        for f in fields_to_compare:
            old_val = getattr(old, f, None)
            new_val = getattr(new, f, None)

            if old_val != new_val:
                changed_fields.append(f)
                field_changes[f] = {"old": old_val, "new": new_val}

        # Uyumluluk kontrolü
        is_compatible = self._check_backward_compatibility(changed_fields)

        return VersionDiff(
            feature_name=feature_name,
            old_version=old_version,
            new_version=new_version,
            changed_fields=changed_fields,
            field_changes=field_changes,
            is_compatible=is_compatible,
            compatibility_notes=self._get_compatibility_notes(changed_fields),
        )

    def check_compatibility(
        self,
        feature_name: str,
        old_version: int,
        new_version: int,
    ) -> CompatibilityReport:
        """Version uyumluluğunu kontrol et.

        Args:
            feature_name: Feature adı
            old_version: Eski version
            new_version: Yeni version

        Returns:
            CompatibilityReport
        """
        version_diff = self.diff(feature_name, old_version, new_version)

        if version_diff is None:
            return CompatibilityReport(
                feature_name=feature_name,
                old_version=old_version,
                new_version=new_version,
                is_compatible=False,
                breaking_changes=["Version not found"],
                warnings=[],
                notes=[],
            )

        breaking_changes: list[str] = []
        warnings: list[str] = []
        notes: list[str] = []

        for field_name in version_diff.changed_fields:
            change = version_diff.field_changes[field_name]

            if field_name == "formula":
                breaking_changes.append(f"Formula changed: {change['old']} → {change['new']}")
            elif field_name == "lookback":
                old_lb = change["old"]
                new_lb = change["new"]
                if new_lb > old_lb:
                    warnings.append(f"Lookback increased: {old_lb} → {new_lb} (more data needed)")
                else:
                    notes.append(f"Lookback decreased: {old_lb} → {new_lb}")
            elif field_name == "value_range":
                breaking_changes.append(f"Value range changed: {change['old']} → {change['new']}")
            elif field_name == "pit_safe":
                if change["old"] and not change["new"]:
                    breaking_changes.append("PIT-safety removed — CRITICAL")
                elif not change["old"] and change["new"]:
                    notes.append("PIT-safety added — improvement")
            elif field_name == "dependencies":
                warnings.append(f"Dependencies changed: {change['old']} → {change['new']}")
            else:
                notes.append(f"{field_name} changed")

        is_compatible = len(breaking_changes) == 0

        return CompatibilityReport(
            feature_name=feature_name,
            old_version=old_version,
            new_version=new_version,
            is_compatible=is_compatible,
            breaking_changes=breaking_changes,
            warnings=warnings,
            notes=notes,
        )

    def rollback(self, feature_name: str, target_version: int) -> bool:
        """Belirli bir version'a geri dön.

        Args:
            feature_name: Feature adı
            target_version: Hedef version numarası

        Returns:
            Başarılı mı?
        """
        versions = self._versions.get(feature_name, [])
        target = None

        for v in versions:
            if v.version == target_version:
                target = v
                break

        if target is None:
            logger.error("rollback_version_not_found", feature=feature_name, version=target_version)
            return False

        self._current[feature_name] = target
        self._record_history("rollback", feature_name, target_version)

        logger.info("feature_version_rollback", feature=feature_name, version=target_version)
        return True

    def get_all_features(self) -> list[str]:
        """Tüm version'lanmış feature isimlerini döndür."""
        return sorted(self._versions.keys())

    def get_summary(self) -> dict[str, Any]:
        """Version yönetimi özeti."""
        total_versions = sum(len(v) for v in self._versions.values())
        return {
            "total_features": len(self._versions),
            "total_versions": total_versions,
            "avg_versions_per_feature": round(total_versions / max(len(self._versions), 1), 2),
            "features_with_multiple_versions": sum(1 for v in self._versions.values() if len(v) > 1),
        }

    def _contract_to_snapshot(self, contract: Any, version: int) -> VersionSnapshot:
        """Contract'tan snapshot oluştur."""
        return VersionSnapshot(
            feature_name=contract.name,
            version=version,
            source=contract.source,
            formula=contract.formula,
            lookback=contract.lookback,
            frequency=contract.frequency,
            available_at=contract.available_at,
            pit_safe=contract.pit_safe,
            value_range=contract.value_range,
            validation_rules=dict(contract.validation_rules) if contract.validation_rules else {},
            dependencies=list(contract.dependencies) if contract.dependencies else [],
            category=contract.category,
            description=contract.description,
        )

    def _detect_changes(self, current: VersionSnapshot, contract: Any) -> list[str]:
        """Değişiklik tespiti."""
        changed: list[str] = []

        comparisons = [
            ("source", current.source, contract.source),
            ("formula", current.formula, contract.formula),
            ("lookback", current.lookback, contract.lookback),
            ("frequency", current.frequency, contract.frequency),
            ("available_at", current.available_at, contract.available_at),
            ("pit_safe", current.pit_safe, contract.pit_safe),
            ("value_range", current.value_range, contract.value_range),
            ("validation_rules", current.validation_rules, contract.validation_rules),
            ("dependencies", current.dependencies, contract.dependencies),
            ("category", current.category, contract.category),
            ("description", current.description, contract.description),
        ]

        for field_name, old_val, new_val in comparisons:
            if old_val != new_val:
                changed.append(field_name)

        return changed

    def _check_backward_compatibility(self, changed_fields: list[str]) -> bool:
        """Geriye dönük uyumluluk kontrolü."""
        breaking_fields = {"formula", "value_range", "pit_safe"}
        return not any(f in breaking_fields for f in changed_fields)

    def _get_compatibility_notes(self, changed_fields: list[str]) -> list[str]:
        """Uyumluluk notları."""
        notes: list[str] = []
        for f in changed_fields:
            if f == "formula":
                notes.append("Formula değişikliği — model retrain gerekebilir")
            elif f == "lookback":
                notes.append("Lookback değişikliği — veri pipeline güncelleme gerekebilir")
            elif f == "pit_safe":
                notes.append("PIT-safety değişikliği — veri sızıntısı riski kontrol edilmeli")
            elif f == "value_range":
                notes.append("Value range değişikliği — validation güncellenmeli")
        return notes

    def _record_history(
        self,
        action: str,
        feature_name: str,
        version: int,
        details: list[str] | None = None,
    ) -> None:
        """History kaydet."""
        self._history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "feature": feature_name,
                "version": version,
                "details": details or [],
            }
        )
        if len(self._history) > 1000:
            self._history = self._history[-1000:]


# Singleton
feature_version_manager = FeatureVersionManager()
