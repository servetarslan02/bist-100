"""
ALPHA BIST — Learning System Faz 6 Test Suite (Model Registry)

Model versioning testing:
- Register (yeni model kaydetme)
- Status transitions (CANDIDATE → SHADOW → CHAMPION → RETIRED)
- Promote to champion
- Promote to shadow
- Rollback
- Version listing
- Performance history
- Auto-cleanup
- Edge cases (duplicate, not found)
"""

import sys
import os



def test_register():
    """Model kayıt."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    record = r.register("m1", "v1", {"sharpe": 1.5}, ["feat_a"], {"n": 100}, {"samples": 1000})

    assert record.model_id == "m1"
    assert record.version == "v1"
    assert record.status == "CANDIDATE"
    assert record.metrics["sharpe"] == 1.5
    print("✅ Register")


def test_register_with_regime():
    """Regime ile kayıt."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    record = r.register("m1", "v1", {}, [], {}, {}, regime="BULL")

    assert record.regime == "BULL"
    print("✅ Register with regime")


def test_register_with_status():
    """Özel status ile kayıt."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    record = r.register("m1", "v1", {}, [], {}, {}, status="SHADOW")

    assert record.status == "SHADOW"
    print("✅ Register with status")


def test_register_multiple():
    """Birden fazla model kayıt."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.register("m2", "v2", {}, [], {}, {})
    r.register("m3", "v3", {}, [], {}, {})

    assert len(r._records) == 3
    print("✅ Register multiple")


def test_promote_to_champion():
    """Champion yapma."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.promote_to_champion("v1")

    champion = r.get_champion()
    assert champion is not None
    assert champion.version == "v1"
    assert champion.status == "CHAMPION"
    print("✅ Promote to champion")


def test_promote_to_champion_retires_old():
    """Yeni champion eski champion'ı retired yapmalı."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.promote_to_champion("v1")
    r.register("m2", "v2", {}, [], {}, {})
    r.promote_to_champion("v2")

    v1 = r.get_version("v1")
    v2 = r.get_version("v2")

    assert v1.status == "RETIRED"
    assert v1.retired_at is not None
    assert v2.status == "CHAMPION"
    print("✅ Promote retires old champion")


def test_promote_to_shadow():
    """Shadow yapma."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.promote_to_shadow("v1")

    v1 = r.get_version("v1")
    assert v1.status == "SHADOW"
    print("✅ Promote to shadow")


def test_rollback():
    """Rollback."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.promote_to_champion("v1")
    r.register("m2", "v2", {}, [], {}, {})
    r.promote_to_champion("v2")

    result = r.rollback("v1")
    assert result is True

    v1 = r.get_version("v1")
    assert v1.status == "CHAMPION"
    assert v1.retired_at is None
    print("✅ Rollback")


def test_rollback_not_found():
    """Olmayan versiyona rollback."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})

    result = r.rollback("v999")
    assert result is False
    print("✅ Rollback not found")


def test_rollback_only_retired():
    """Sadece retired modellere rollback yapılmalı."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {}, status="CANDIDATE")

    result = r.rollback("v1")
    assert result is False  # CANDIDATE → rollback yapılamaz
    print("✅ Rollback only retired")


def test_get_version():
    """Versiyon getirme."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {"sharpe": 1.5}, ["feat_a"], {"n": 100}, {"samples": 1000})

    v = r.get_version("v1")
    assert v is not None
    assert v.model_id == "m1"
    assert v.metrics["sharpe"] == 1.5
    print("✅ Get version")


def test_get_version_not_found():
    """Olmayan versiyon."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    v = r.get_version("v999")
    assert v is None
    print("✅ Get version not found")


def test_get_all_versions():
    """Tüm versiyonlar."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.register("m2", "v2", {}, [], {}, {})

    versions = r.get_all_versions()
    assert len(versions) == 2
    assert versions[0]["version"] == "v1"
    assert versions[1]["version"] == "v2"
    print("✅ Get all versions")


def test_get_champion_regime():
    """Regime-specific champion."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {}, regime="BULL")
    r.promote_to_champion("v1", regime="BULL")
    r.register("m2", "v2", {}, [], {}, {}, regime="BEAR")
    r.promote_to_champion("v2", regime="BEAR")

    bull = r.get_champion("BULL")
    bear = r.get_champion("BEAR")

    assert bull.version == "v1"
    assert bear.version == "v2"
    print("✅ Get champion regime")


def test_add_performance_record():
    """Performans kaydı ekleme."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})

    r.add_performance_record("v1", {"sharpe": 1.5, "win_rate": 0.6})
    r.add_performance_record("v1", {"sharpe": 1.3, "win_rate": 0.58})

    v = r.get_version("v1")
    assert len(v.performance_history) == 2
    assert v.performance_history[0]["sharpe"] == 1.5
    print("✅ Add performance record")


def test_add_performance_record_not_found():
    """Olmayan versiyona performans kaydı."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    # Hata vermemeli, sessizce geçmeli
    r.add_performance_record("v999", {"sharpe": 1.5})
    print("✅ Add performance record not found → silent")


def test_report():
    """Rapor doğru mu?"""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    r.register("m1", "v1", {}, [], {}, {})
    r.promote_to_champion("v1")
    r.register("m2", "v2", {}, [], {}, {})
    r.promote_to_shadow("v2")
    r.register("m3", "v3", {}, [], {}, {})

    report = r.get_report()
    assert report["total_versions"] == 3
    assert report["champions"] == 1
    assert report["shadows"] == 1
    print(f"✅ Report: {report}")


def test_report_empty():
    """Boş rapor."""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    report = r.get_report()
    assert report["total_versions"] == 0
    assert report["champions"] == 0
    print("✅ Report empty")


def test_cleanup_old_versions():
    """Eski versiyonlar temizleniyor mu?"""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    # 25 retired model oluştur (max_versions=20)
    for i in range(25):
        r.register(f"m{i}", f"v{i}", {}, [], {}, {}, status="RETIRED")

    # Champion ekle (korunmalı)
    r.register("champ", "v_champ", {}, [], {}, {}, status="CHAMPION")

    # Cleanup tetikle
    r._cleanup_old_versions()

    # Champion + son 20 retired kalmalı
    retired = [rec for rec in r._records if rec.status == "RETIRED"]
    assert len(retired) <= 20
    print(f"✅ Cleanup: {len(retired)} retired (max 20)")


def test_created_at():
    """created_at doğru mu?"""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    record = r.register("m1", "v1", {}, [], {}, {})

    assert record.created_at is not None
    assert "T" in record.created_at  # ISO format
    print(f"✅ Created at: {record.created_at}")


def test_features_stored():
    """Features doğru saklanıyor mu?"""
    from services.learning.model_registry import ModelRegistry

    r = ModelRegistry()
    features = ["rsi_14", "momentum_20d", "volume_zscore"]
    record = r.register("m1", "v1", {}, features, {}, {})

    assert record.features == features
    print(f"✅ Features stored: {record.features}")


# ===================== MAIN =====================

def run_all_tests():
    tests = [
        test_register,
        test_register_with_regime,
        test_register_with_status,
        test_register_multiple,
        test_promote_to_champion,
        test_promote_to_champion_retires_old,
        test_promote_to_shadow,
        test_rollback,
        test_rollback_not_found,
        test_rollback_only_retired,
        test_get_version,
        test_get_version_not_found,
        test_get_all_versions,
        test_get_champion_regime,
        test_add_performance_record,
        test_add_performance_record_not_found,
        test_report,
        test_report_empty,
        test_cleanup_old_versions,
        test_created_at,
        test_features_stored,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            print(f"❌ {test.__name__}: {e}")

    print(f"\n{'='*60}")
    print(f"📊 FAZ 6 TEST SONUÇLARI (Model Registry)")
    print(f"{'='*60}")
    print(f"✅ Geçen: {passed}")
    print(f"❌ Başarısız: {failed}")
    print(f"📈 Toplam: {passed + failed}")

    if errors:
        print(f"\n🔍 Hatalar:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
