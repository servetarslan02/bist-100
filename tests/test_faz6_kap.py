"""
ALPHA BIST — FAZ 6 Test Suite (KAP Extractor & Sector Chain)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_kap_extractor():
    """KAP Extractor testleri."""
    from services.intelligence.kap_extractor import kap_extractor

    passed = 0
    failed = 0

    # 1. Temettü sınıflandırma
    result = kap_extractor.extract("THYAO", "KAP-001", "Şirketimiz 2026 yılı kar payı dağıtımı hakkında")
    assert result.event_type == "DIVIDEND"
    assert result.financial_impact > 0
    passed += 1
    print(f"  ✓ Temettü: type={result.event_type}, impact={result.financial_impact:.2f}")

    # 2. Yatırım sınıflandırma
    result = kap_extractor.extract("ASELS", "KAP-002", "Yeni yatırım kararı: 500 milyon TL kapasite artışı")
    assert result.event_type == "INVESTMENT"
    assert result.financial_impact > 0
    passed += 1
    print(f"  ✓ Yatırım: type={result.event_type}, impact={result.financial_impact:.2f}")

    # 3. Sözleşme
    result = kap_extractor.extract("TUPRS", "KAP-003", "Yeni petrol sözleşmesi imzalandı")
    assert result.event_type == "CONTRACT"
    passed += 1
    print(f"  ✓ Sözleşme: type={result.event_type}, impact={result.financial_impact:.2f}")

    # 4. Dava
    result = kap_extractor.extract("GARAN", "KAP-004", "Banka aleyhine açılan dava sonuçlandı")
    assert result.event_type == "LEGAL"
    assert result.financial_impact < 0
    passed += 1
    print(f"  ✓ Dava: type={result.event_type}, impact={result.financial_impact:.2f}")

    # 5. Beklenmediklik
    result = kap_extractor.extract("THYAO", "KAP-005", "Sürpriz kar payı dağıtımı açıklandı")
    assert result.surprise_score > 0.5
    passed += 1
    print(f"  ✓ Beklenmediklik: surprise={result.surprise_score:.2f}")

    # 6. Belirsizlik
    result = kap_extractor.extract("AKBNK", "KAP-006", "Belirsiz piyasa koşulları nedeniyle tahmini sonuçlar")
    assert result.uncertainty > 0.5
    passed += 1
    print(f"  ✓ Belirsizlik: uncertainty={result.uncertainty:.2f}")

    # 7. Sektör tespiti
    result = kap_extractor.extract("TUPRS", "KAP-007", "Petrol rafineri kapasite artışı yatırımı")
    assert "ENERGY" in result.affected_sectors
    passed += 1
    print(f"  ✓ Sektör: {result.affected_sectors}")

    # 8. Bilinmeyen olay
    result = kap_extractor.extract("TEST", "KAP-008", "Genel kurul toplantısı yapılacak")
    assert result.event_type == "UNKNOWN"
    passed += 1
    print(f"  ✓ Bilinmeyen: type={result.event_type}")

    return passed, failed


def test_sector_chain():
    """Sektör Zincirleme Etki testleri."""
    from services.intelligence.kap_extractor import sector_chain

    passed = 0
    failed = 0

    # 1. Enerji → Havacılık (negatif)
    impacts = sector_chain.compute_chain_impact("ENERGY", 1.0)  # Petrol yükseldi
    aviation_impact = next((i for i in impacts if i["target_sector"] == "AVIATION"), None)
    assert aviation_impact is not None
    assert aviation_impact["impact"] < 0  # Havacılık negatif etkilenir
    passed += 1
    print(f"  ✓ Enerji→Havacılık: {aviation_impact['impact']:.2f} ({aviation_impact['reason']})")

    # 2. Banka → İnşaat (negatif)
    impacts = sector_chain.compute_chain_impact("BANK", 1.0)  # Faiz arttı
    constr_impact = next((i for i in impacts if i["target_sector"] == "CONSTR"), None)
    assert constr_impact is not None
    assert constr_impact["impact"] < 0
    passed += 1
    print(f"  ✓ Banka→İnşaat: {constr_impact['impact']:.2f} ({constr_impact['reason']})")

    # 3. Bilinmeyen sektör
    impacts = sector_chain.compute_chain_impact("UNKNOWN", 1.0)
    assert len(impacts) == 0
    passed += 1
    print(f"  ✓ Bilinmeyen sektör: {len(impacts)} etki")

    # 4. Negatif yön
    impacts = sector_chain.compute_chain_impact("ENERGY", -1.0)  # Petrol düştü
    aviation_impact = next((i for i in impacts if i["target_sector"] == "AVIATION"), None)
    assert aviation_impact["impact"] > 0  # Petrol düşünce havacılık pozitif
    passed += 1
    print(f"  ✓ Negatif yön: Enerji→Havacılık={aviation_impact['impact']:.2f}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 6 — KAP Extractor & Sector Chain Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("KAP Extractor", test_kap_extractor),
        ("Sector Chain Impact", test_sector_chain),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
