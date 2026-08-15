"""
ALPHA BIST — Bölüm 1 & 2 Enhancement Tests

PIT Store, Cross-Source Reconciliation, Streaming Anomaly Detection testleri.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_pit_store():
    """Point-in-Time Store testleri."""
    from services.core.pit_store import PointInTimeStore
    from datetime import datetime, timezone, timedelta

    store = PointInTimeStore()
    passed = 0
    failed = 0

    now = datetime.now(timezone.utc)
    day1 = now - timedelta(days=10)
    day2 = now - timedelta(days=5)
    day3 = now

    # 1. Insert ve get_as_of
    store.insert("THYAO", "pe_ratio", 8.5, day1, "yfinance")
    store.insert("THYAO", "pe_ratio", 9.0, day2, "yfinance")  # Düzeltme

    # day1'de bilinen değer
    val = store.get_as_of("THYAO", "pe_ratio", day1 + timedelta(hours=1))
    assert val == 8.5, f"Expected 8.5, got {val}"

    # day2'de bilinen değer (düzeltilmiş)
    val = store.get_as_of("THYAO", "pe_ratio", day2 + timedelta(hours=1))
    assert val == 9.0, f"Expected 9.0, got {val}"

    # day1'den önce bilinmiyor
    val = store.get_as_of("THYAO", "pe_ratio", day1 - timedelta(days=1))
    assert val is None

    passed += 1
    print("  ✓ PIT Store: insert, get_as_of, revision")

    # 2. Latest
    latest = store.get_latest("THYAO", "pe_ratio")
    assert latest == 9.0
    passed += 1
    print("  ✓ PIT Store: get_latest")

    # 3. History
    history = store.get_history("THYAO", "pe_ratio")
    assert len(history) == 2
    assert history[0]["revision"] == 0
    assert history[1]["revision"] == 1
    passed += 1
    print(f"  ✓ PIT Store: history ({len(history)} revisions)")

    # 4. Bulk insert
    store.bulk_insert("ASELS", {"price": 38.5, "volume": 500000}, day1, "yfinance")
    assert store.get_latest("ASELS", "price") == 38.5
    passed += 1
    print("  ✓ PIT Store: bulk_insert")

    # 5. Stats
    stats = store.get_stats()
    assert stats["tickers"] >= 2
    passed += 1
    print(f"  ✓ PIT Store: stats ({stats})")

    return passed, failed


def test_cross_source_reconciliation():
    """Cross-Source Reconciliation testleri."""
    from services.core.reconciliation import cross_source_reconciliation, CrossSourceReconciliation

    rec = CrossSourceReconciliation()
    passed = 0
    failed = 0

    # 1. Tutarlı kaynaklar
    result = rec.reconcile_price({"yfinance": 305.25, "matriks": 305.30, "kap": 305.20})
    assert result.is_consistent
    assert result.quality_score > 80
    assert not result.anomaly_detected
    passed += 1
    print(f"  ✓ Consistent: value={result.value}, quality={result.quality_score}")

    # 2. Uyuşmazlık var
    result2 = rec.reconcile_price({"yfinance": 305.25, "matriks": 320.00})
    assert result2.discrepancy_pct > 2
    assert not result2.is_consistent
    passed += 1
    print(f"  ✓ Discrepancy: {result2.discrepancy_pct}%, consistent={result2.is_consistent}")

    # 3. Anomali tespiti (çok farklı)
    result3 = rec.reconcile_price({"yfinance": 305.25, "matriks": 305.30, "kap": 400.00})
    # 3 kaynakta anomaly detection çalışmalı
    assert result3.discrepancy_pct > 20  # Büyük fark
    passed += 1
    print(f"  ✓ Anomaly: discrepancy={result3.discrepancy_pct:.1f}%, quality={result3.quality_score}")

    # 4. Tek kaynak
    result4 = rec.reconcile_price({"yfinance": 305.25})
    assert result4.confidence < 0.8  # Tek kaynak düşük güven
    passed += 1
    print(f"  ✓ Single source: confidence={result4.confidence}")

    # 5. En güvenilir kaynak seçimi
    result5 = rec.reconcile_price({"social_media": 300.0, "bloomberg": 305.0, "yfinance": 305.25})
    assert result5.source in ["bloomberg", "yfinance"]  # Bloomberg daha güvenilir
    passed += 1
    print(f"  ✓ Best source: {result5.source}")

    # 6. Price jump detection
    is_jump, change = rec.detect_price_jump("TEST", 120, 100, 0.25)
    assert abs(change - 20.0) < 0.1
    passed += 1
    print(f"  ✓ Price jump: {change:.1f}%")

    return passed, failed


def test_streaming_anomaly():
    """Streaming Anomaly Detector testleri."""
    from services.core.streaming_anomaly import StreamingAnomalyDetector

    detector = StreamingAnomalyDetector(window_size=50)
    passed = 0
    failed = 0

    # 1. Normal fiyat — anomali yok
    for i in range(20):
        detector.check_price("TEST", 100 + i * 0.1, 100 + (i-1) * 0.1)
    result = detector.check_price("TEST", 102.0, 101.9)
    assert not result.is_anomaly
    passed += 1
    print(f"  ✓ Normal price: anomaly={result.is_anomaly}")

    # 2. Ani sıçrama — anomali
    result = detector.check_price("TEST", 150.0, 102.0, volatility=0.25)
    assert result.is_anomaly
    assert result.severity in ["HIGH", "CRITICAL"]
    passed += 1
    print(f"  ✓ Price jump: anomaly={result.is_anomaly}, severity={result.severity}")

    # 3. Hacim anomalisi
    for i in range(20):
        detector.check_volume("TEST", 100000)
    result = detector.check_volume("TEST", 5000000)
    assert result.is_anomaly
    passed += 1
    print(f"  ✓ Volume anomaly: zscore={result.zscore}")

    # 4. Spread anomalisi
    result = detector.check_spread("TEST", 100.0, 106.0)
    assert result.is_anomaly  # %6 spread
    passed += 1
    print(f"  ✓ Spread anomaly: {result.details}")

    # 5. Tüm kontroller
    results = detector.check_all("TEST", 200.0, 102.0, 5000000, 99.0, 101.0)
    assert len(results) >= 2
    anomalies = [r for r in results if r.is_anomaly]
    assert len(anomalies) > 0  # Fiyat ve hacim anomalisi olmalı
    passed += 1
    print(f"  ✓ All checks: {len(anomalies)} anomalies")

    return passed, failed


def main():
    print("=" * 60)
    print("  Bölüm 1 & 2 — Enhancement Tests")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("PIT Store", test_pit_store),
        ("Cross-Source Reconciliation", test_cross_source_reconciliation),
        ("Streaming Anomaly", test_streaming_anomaly),
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
