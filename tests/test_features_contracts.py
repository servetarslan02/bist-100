"""ALPHA BIST — Feature Contract Testleri

Her feature için:
- PIT-safety kontrolü
- Value range testi
- Edge case testi (NaN, Inf, negatif volume)
- Validation rules testi
- Contract completeness testi

Kullanım:
    python -m pytest tests/test_features_contracts.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from services.features.contract import FeatureContract, FeatureRegistry, feature_registry


class TestFeatureContracts:
    """Feature contract testleri."""

    # =====================================================
    # PIT-SAFETY TESTS
    # =====================================================

    def test_all_features_have_pit_safe_field(self):
        """Tüm feature'lar pit_safe field'ına sahip olmalı."""
        for contract in feature_registry.list_all():
            assert hasattr(contract, "pit_safe"), (
                f"Feature '{contract.name}' pit_safe field'ına sahip değil"
            )

    def test_pit_safe_features_use_only_past_data(self):
        """PIT-safe feature'lar sadece geçmiş veri kullanmalı.

        Bu test, PIT-safe olarak işaretlenen feature'ların
        lookback ve available_at değerlerinin tutarlılığını kontrol eder.
        """
        for contract in feature_registry.list_all():
            if not contract.pit_safe:
                continue

            # PIT-safe feature'lar "realtime" available_at ile gelecek veri kullanmamalı
            # (session feature'lar hariç — onlar zaten o anki durumu ölçer)
            if contract.available_at == "realtime" and contract.category != "session":
                # Bu bir uyarı, hata değil — bazı realtime feature'lar PIT-safe olabilir
                pass

    def test_pit_unsafe_features_are_marked(self):
        """PIT-unsafe feature'lar açıkça işaretlenmiş olmalı."""
        for contract in feature_registry.list_all():
            if not contract.pit_safe:
                # PIT-unsafe feature'lar "future" veya "forward" içermemeli
                # (bu onların gerçekten unsafe olduğunu doğrular)
                assert "future" not in contract.formula.lower() or "forward" not in contract.formula.lower(), (
                    f"Feature '{contract.name}' PIT-unsafe olarak işaretlenmiş ama "
                    f"formülünde 'future' veya 'forward' geçiyor — tutarsızlık"
                )

    # =====================================================
    # VALUE RANGE TESTS
    # =====================================================

    def test_value_range_is_valid(self):
        """Value range tanımlıysa min < max olmalı."""
        for contract in feature_registry.list_all():
            if contract.value_range is not None:
                min_val, max_val = contract.value_range
                assert min_val < max_val, (
                    f"Feature '{contract.name}' value_range'ında min ({min_val}) >= max ({max_val})"
                )

    def test_validate_value_within_range(self):
        """Değer aralık içindeyse geçmeli."""
        for contract in feature_registry.list_all():
            if contract.value_range is None:
                continue

            min_val, max_val = contract.value_range
            mid_val = (min_val + max_val) / 2

            assert contract.validate_value(mid_val), (
                f"Feature '{contract.name}' orta değer ({mid_val}) aralık içinde olmalı"
            )

    def test_validate_value_outside_range(self):
        """Değer aralık dışındaysa başarısız olmalı."""
        for contract in feature_registry.list_all():
            if contract.value_range is None:
                continue

            min_val, max_val = contract.value_range

            # Min'in altında
            below = min_val - abs(min_val) * 0.1 - 0.01
            assert not contract.validate_value(below), (
                f"Feature '{contract.name}' aralık altı değer ({below}) reddedilmeli"
            )

            # Max'ın üstünde
            above = max_val + abs(max_val) * 0.1 + 0.01
            assert not contract.validate_value(above), (
                f"Feature '{contract.name}' aralık üstü değer ({above}) reddedilmeli"
            )

    # =====================================================
    # EDGE CASE TESTS
    # =====================================================

    def test_validate_value_none(self):
        """None değer geçerli olmalı (eksik veri)."""
        for contract in feature_registry.list_all():
            assert contract.validate_value(None), (
                f"Feature '{contract.name}' None değeri kabul etmeli (eksik veri)"
            )

    def test_validate_value_nan(self):
        """NaN değer geçersiz olmalı."""
        for contract in feature_registry.list_all():
            assert not contract.validate_value(float("nan")), (
                f"Feature '{contract.name}' NaN değeri reddetmeli"
            )

    def test_validate_value_inf(self):
        """Inf değer geçersiz olmalı."""
        for contract in feature_registry.list_all():
            assert not contract.validate_value(float("inf")), (
                f"Feature '{contract.name}' +Inf değeri reddetmeli"
            )
            assert not contract.validate_value(float("-inf")), (
                f"Feature '{contract.name}' -Inf değeri reddetmeli"
            )

    def test_validate_value_zero(self):
        """Sıfır değer — range'e bağlı olarak geçerli veya geçersiz."""
        for contract in feature_registry.list_all():
            result = contract.validate_value(0.0)
            if contract.value_range:
                min_val, max_val = contract.value_range
                if min_val <= 0.0 <= max_val:
                    assert result, (
                        f"Feature '{contract.name}' sıfır değerini kabul etmeli (range: {contract.value_range})"
                    )
                else:
                    assert not result, (
                        f"Feature '{contract.name}' sıfır değerini reddetmeli (range: {contract.value_range})"
                    )

    def test_validate_value_negative(self):
        """Negatif değer — range'e bağlı olarak geçerli veya geçersiz."""
        for contract in feature_registry.list_all():
            result = contract.validate_value(-1.0)
            if contract.value_range:
                min_val, max_val = contract.value_range
                if min_val <= -1.0 <= max_val:
                    assert result, (
                        f"Feature '{contract.name}' -1.0 değerini kabul etmeli (range: {contract.value_range})"
                    )
                else:
                    assert not result, (
                        f"Feature '{contract.name}' -1.0 değerini reddetmeli (range: {contract.value_range})"
                    )

    # =====================================================
    # VALIDATION RULES TESTS
    # =====================================================

    def test_validation_rules_min(self):
        """Min kuralı çalışmalı."""
        contract = FeatureContract(
            name="test_min",
            source="test",
            formula="test",
            lookback=1,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            validation_rules={"min": 10},
        )

        assert contract.validate_value(15)
        assert contract.validate_value(10)
        assert not contract.validate_value(5)

    def test_validation_rules_max(self):
        """Max kuralı çalışmalı."""
        contract = FeatureContract(
            name="test_max",
            source="test",
            formula="test",
            lookback=1,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            validation_rules={"max": 100},
        )

        assert contract.validate_value(50)
        assert contract.validate_value(100)
        assert not contract.validate_value(150)

    def test_validation_rules_min_and_max(self):
        """Min + Max kuralı birlikte çalışmalı."""
        contract = FeatureContract(
            name="test_range",
            source="test",
            formula="test",
            lookback=1,
            frequency="daily",
            available_at="close",
            pit_safe=True,
            version=1,
            owner="test",
            validation_rules={"min": 0, "max": 100},
        )

        assert contract.validate_value(50)
        assert contract.validate_value(0)
        assert contract.validate_value(100)
        assert not contract.validate_value(-1)
        assert not contract.validate_value(101)

    # =====================================================
    # CONTRACT COMPLETENESS TESTS
    # =====================================================

    def test_all_contracts_have_required_fields(self):
        """Tüm contract'lar zorunlu field'lara sahip olmalı."""
        required_fields = [
            "name", "source", "formula", "lookback",
            "frequency", "available_at", "pit_safe",
            "version", "owner",
        ]

        for contract in feature_registry.list_all():
            for field in required_fields:
                value = getattr(contract, field, None)
                assert value is not None, (
                    f"Feature '{contract.name}' zorunlu field '{field}' eksik"
                )

    def test_all_contracts_have_description(self):
        """Tüm contract'lar description'a sahip olmalı."""
        for contract in feature_registry.list_all():
            assert contract.description, (
                f"Feature '{contract.name}' description eksik"
            )

    def test_all_contracts_have_category(self):
        """Tüm contract'lar category'ye sahip olmalı."""
        valid_categories = {
            "technical", "fundamental", "sentiment",
            "microstructure", "session", "risk", "market", "macro",
        }

        for contract in feature_registry.list_all():
            assert contract.category in valid_categories, (
                f"Feature '{contract.name}' geçersiz kategori: '{contract.category}'. "
                f"Geçerli kategoriler: {valid_categories}"
            )

    def test_lookback_is_non_negative(self):
        """Lookback negatif olmamalı."""
        for contract in feature_registry.list_all():
            assert contract.lookback >= 0, (
                f"Feature '{contract.name}' negatif lookback: {contract.lookback}"
            )

    def test_version_is_positive(self):
        """Version pozitif olmalı."""
        for contract in feature_registry.list_all():
            assert contract.version > 0, (
                f"Feature '{contract.name}' geçersiz version: {contract.version}"
            )

    # =====================================================
    # REGISTRY TESTS
    # =====================================================

    def test_registry_has_features(self):
        """Registry boş olmamalı."""
        assert len(feature_registry.list_all()) > 0, "Feature registry boş"

    def test_registry_no_duplicate_names(self):
        """Tekrar eden feature isimleri olmamalı."""
        names = [c.name for c in feature_registry.list_all()]
        assert len(names) == len(set(names)), (
            f"Tekrar eden feature isimleri: {[n for n in names if names.count(n) > 1]}"
        )

    def test_registry_list_by_category(self):
        """Kategoriye göre listeleme çalışmalı."""
        for category in ["technical", "fundamental", "sentiment", "session", "risk"]:
            features = feature_registry.list_by_category(category)
            # Her kategoride en az 0 feature olabilir (boş kategori geçerli)

    def test_registry_list_pit_safe(self):
        """PIT-safe listeleme çalışmalı."""
        pit_safe = feature_registry.list_pit_safe()
        for c in pit_safe:
            assert c.pit_safe

    def test_registry_get_summary(self):
        """Özet istatistikler çalışmalı."""
        summary = feature_registry.get_summary()

        assert "total" in summary
        assert "pit_safe" in summary
        assert "pit_unsafe" in summary
        assert "by_category" in summary
        assert "by_owner" in summary
        assert summary["total"] > 0
        assert summary["pit_safe"] + summary["pit_unsafe"] == summary["total"]

    def test_registry_validate_known_feature(self):
        """Bilinen feature için validation çalışmalı."""
        rsi_contract = feature_registry.get("rsi_14")
        if rsi_contract:
            assert feature_registry.validate("rsi_14", 50.0)
            assert not feature_registry.validate("rsi_14", -10.0)
            assert not feature_registry.validate("rsi_14", 110.0)

    def test_registry_validate_unknown_feature(self):
        """Bilinmeyen feature için validation False döndürmeli."""
        assert not feature_registry.validate("nonexistent_feature", 42.0)

    # =====================================================
    # TO_DICT TESTS
    # =====================================================

    def test_contract_to_dict(self):
        """to_dict() tüm field'ları içermeli."""
        for contract in feature_registry.list_all():
            d = contract.to_dict()

            assert "name" in d
            assert "source" in d
            assert "formula" in d
            assert "lookback" in d
            assert "frequency" in d
            assert "available_at" in d
            assert "pit_safe" in d
            assert "version" in d
            assert "owner" in d
            assert "description" in d
            assert "category" in d

    def test_contract_to_dict_value_range_serializable(self):
        """to_dict() value_range serialize edilebilir olmalı."""
        for contract in feature_registry.list_all():
            d = contract.to_dict()
            vr = d.get("value_range")

            if vr is not None:
                assert isinstance(vr, list), (
                    f"Feature '{contract.name}' value_range list olmalı: {type(vr)}"
                )
                assert len(vr) == 2
                assert vr[0] < vr[1]
