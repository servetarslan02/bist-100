"""
ALPHA BIST — Learning System Faz 4 Test Suite (Feature Importance Tracker)

SHAP-based feature importance testing:
- Tracking fonksiyonu
- Trend analizi (artan/azalan/stabil)
- Regime-specific importance
- Feature selection önerileri
- Raporlama
- Edge cases (boş veri, tek kayıt, çok rejim)
"""

import sys
from datetime import UTC, datetime, timedelta

import numpy as np


def _make_tracker_with_data(n_records=30, n_features=5):
    """Test verisiyle tracker oluştur."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    np.random.seed(42)

    for i in range(n_records):
        date = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
        for j in range(n_features):
            tracker._history.append(
                type('Record', (), {
                    'date': date,
                    'feature': f'feat_{j}',
                    'importance': 0.1 + j * 0.05 + np.random.randn() * 0.01,
                    'regime': 'BULL' if i % 2 == 0 else 'BEAR',
                    'model_version': 'v1',
                })()
            )
    return tracker


# ===================== INIT =====================

def test_tracker_init():
    """Tracker başlatılıyor mu?"""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    assert len(tracker._history) == 0
    assert len(tracker._last_importance) == 0
    print("✅ Tracker init")


def test_tracker_singleton():
    """Singleton doğru mu?"""
    from services.learning.feature_tracker import feature_importance_tracker
    assert feature_importance_tracker is not None
    print("✅ Tracker singleton")


# ===================== TRENDS =====================

def test_trends_empty():
    """Boş tracker trends boş döndürmeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    trends = tracker.get_trends()
    assert isinstance(trends, dict)
    assert len(trends) == 0
    print("✅ Trends empty")


def test_trends_with_data():
    """Veri ile trends doğru mu?"""
    tracker = _make_tracker_with_data(n_records=30, n_features=5)
    trends = tracker.get_trends(top_n=3)

    assert len(trends) > 0
    for _name, trend in trends.items():
        assert hasattr(trend, 'avg_importance')
        assert hasattr(trend, 'trend')
        assert trend.trend in ["increasing", "decreasing", "stable"]
    print(f"✅ Trends with data: {len(trends)} features")


def test_trends_top_n():
    """Top N çalışıyor mu?"""
    tracker = _make_tracker_with_data(n_records=20, n_features=10)

    trends_5 = tracker.get_trends(top_n=5)
    trends_3 = tracker.get_trends(top_n=3)

    assert len(trends_5) <= 5
    assert len(trends_3) <= 3
    assert len(trends_3) <= len(trends_5)
    print(f"✅ Trends top_n: 5→{len(trends_5)}, 3→{len(trends_3)}")


def test_trends_ordering():
    """Trends importance'a göre sıralı mı?"""
    tracker = _make_tracker_with_data(n_records=20, n_features=5)
    trends = tracker.get_trends(top_n=5)

    importances = [t.avg_importance for t in trends.values()]
    assert importances == sorted(importances, reverse=True)
    print("✅ Trends ordering: correct")


def test_trends_increasing():
    """Artan trend tespit edilmeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    # Artan importance verisi ekle
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=19-i)).strftime("%Y-%m-%d")
        tracker._history.append(
            type('Record', (), {
                'date': date, 'feature': 'rising_feat',
                'importance': 0.01 + i * 0.01,  # Artan
                'regime': 'BULL', 'model_version': 'v1',
            })()
        )

    trends = tracker.get_trends(top_n=1)
    assert 'rising_feat' in trends
    assert trends['rising_feat'].trend == "increasing"
    print(f"✅ Trends increasing: {trends['rising_feat'].trend}")


def test_trends_decreasing():
    """Azalan trend tespit edilmeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=19-i)).strftime("%Y-%m-%d")
        tracker._history.append(
            type('Record', (), {
                'date': date, 'feature': 'falling_feat',
                'importance': 0.5 - i * 0.02,  # Azalan
                'regime': 'BULL', 'model_version': 'v1',
            })()
        )

    trends = tracker.get_trends(top_n=1)
    assert 'falling_feat' in trends
    assert trends['falling_feat'].trend == "decreasing"
    print(f"✅ Trends decreasing: {trends['falling_feat'].trend}")


def test_trends_window_days():
    """Window days filtresi çalışıyor mu?"""
    tracker = _make_tracker_with_data(n_records=60, n_features=3)

    trends_short = tracker.get_trends(top_n=10, window_days=10)
    trends_long = tracker.get_trends(top_n=10, window_days=60)

    # Kısa pencerede daha az veri → daha az feature
    assert len(trends_short) <= len(trends_long)
    print(f"✅ Trends window: short={len(trends_short)}, long={len(trends_long)}")


# ===================== REGIME IMPORTANCE =====================

def test_regime_importance():
    """Regime-specific importance doğru mu?"""
    tracker = _make_tracker_with_data(n_records=30, n_features=3)

    bull_imp = tracker.get_regime_importance("BULL")
    bear_imp = tracker.get_regime_importance("BEAR")

    assert len(bull_imp) > 0
    assert len(bear_imp) > 0
    for _name, val in bull_imp.items():
        assert isinstance(val, float)
        assert val >= 0
    print(f"✅ Regime importance: BULL={len(bull_imp)}, BEAR={len(bear_imp)}")


def test_regime_importance_empty():
    """Olmayan rejim boş döndürmeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    result = tracker.get_regime_importance("UNKNOWN")
    assert len(result) == 0
    print("✅ Regime importance empty")


def test_regime_importance_different():
    """Farklı rejimler farklı importance vermeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    np.random.seed(42)

    # BULL: feat_0 önemli
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'feat_0', 'importance': 0.8,
            'regime': 'BULL', 'model_version': 'v1',
        })())
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'feat_1', 'importance': 0.2,
            'regime': 'BULL', 'model_version': 'v1',
        })())

    # BEAR: feat_1 önemli
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'feat_0', 'importance': 0.2,
            'regime': 'BEAR', 'model_version': 'v1',
        })())
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'feat_1', 'importance': 0.8,
            'regime': 'BEAR', 'model_version': 'v1',
        })())

    bull = tracker.get_regime_importance("BULL")
    bear = tracker.get_regime_importance("BEAR")

    assert bull['feat_0'] > bull['feat_1']  # BULL'da feat_0 daha önemli
    assert bear['feat_1'] > bear['feat_0']  # BEAR'da feat_1 daha önemli
    print(f"✅ Regime importance different: BULL feat_0={bull['feat_0']:.2f}, BEAR feat_1={bear['feat_1']:.2f}")


# ===================== FEATURE SELECTION =====================

def test_feature_selection_empty():
    """Boş tracker feature selection boş döndürmeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    suggestions = tracker.suggest_feature_selection()
    assert isinstance(suggestions, list)
    assert len(suggestions) == 0
    print("✅ Feature selection empty")


def test_feature_selection_low_importance():
    """Düşük importance'lı feature'lar önerilmeli."""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=19-i)).strftime("%Y-%m-%d")
        # Düşük importance + azalan trend
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'low_feat',
            'importance': 0.0001 - i * 0.000005,
            'regime': 'BULL', 'model_version': 'v1',
        })())
        # Yüksek importance
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'high_feat',
            'importance': 0.5,
            'regime': 'BULL', 'model_version': 'v1',
        })())

    suggestions = tracker.suggest_feature_selection(min_importance=0.001)
    assert 'low_feat' in suggestions
    assert 'high_feat' not in suggestions
    print(f"✅ Feature selection: {suggestions}")


def test_feature_selection_custom_threshold():
    """Custom threshold çalışıyor mu?"""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=19-i)).strftime("%Y-%m-%d")
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'med_feat',
            'importance': 0.01 - i * 0.0005,
            'regime': 'BULL', 'model_version': 'v1',
        })())

    # Yüksek threshold → çıkarılmalı
    suggestions_high = tracker.suggest_feature_selection(min_importance=0.05)
    assert 'med_feat' in suggestions_high

    # Düşük threshold → çıkarılmamalı
    suggestions_low = tracker.suggest_feature_selection(min_importance=0.0001)
    assert 'med_feat' not in suggestions_low
    print("✅ Feature selection custom threshold")


# ===================== REPORT =====================

def test_report_empty():
    """Boş rapor doğru mu?"""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    report = tracker.get_report()

    assert report["status"] == "OK"
    assert report["total_records"] == 0
    assert report["unique_features"] == 0
    print("✅ Report empty")


def test_report_with_data():
    """Veri ile rapor doğru mu?"""
    tracker = _make_tracker_with_data(n_records=20, n_features=5)
    report = tracker.get_report()

    assert report["status"] == "OK"
    assert report["total_records"] > 0
    assert report["unique_features"] == 5
    assert "top_features" in report
    print(f"✅ Report: {report['total_records']} records, {report['unique_features']} features")


def test_report_top_features():
    """Top features raporda doğru mu?"""
    tracker = _make_tracker_with_data(n_records=20, n_features=5)
    report = tracker.get_report()

    top = report["top_features"]
    assert len(top) > 0
    for _name, info in top.items():
        assert "importance" in info
        assert "trend" in info
    print(f"✅ Report top features: {len(top)} features")


# ===================== VOLATILITY =====================

def test_trend_volatility():
    """Volatility hesaplanıyor mu?"""
    from services.learning.feature_tracker import FeatureImportanceTracker

    tracker = FeatureImportanceTracker()
    np.random.seed(42)

    # Stabil feature
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=19-i)).strftime("%Y-%m-%d")
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'stable_feat',
            'importance': 0.5 + np.random.randn() * 0.001,  # Çok düşük volatility
            'regime': 'BULL', 'model_version': 'v1',
        })())

    # Volatil feature
    for i in range(20):
        date = (datetime.now(UTC) - timedelta(days=19-i)).strftime("%Y-%m-%d")
        tracker._history.append(type('Record', (), {
            'date': date, 'feature': 'volatile_feat',
            'importance': 0.5 + np.random.randn() * 0.2,  # Yüksek volatility
            'regime': 'BULL', 'model_version': 'v1',
        })())

    trends = tracker.get_trends(top_n=2)
    assert trends['stable_feat'].volatility < trends['volatile_feat'].volatility
    print(f"✅ Volatility: stable={trends['stable_feat'].volatility:.4f}, volatile={trends['volatile_feat'].volatility:.4f}")


# ===================== MAIN =====================

def run_all_tests():
    tests = [
        test_tracker_init,
        test_tracker_singleton,
        test_trends_empty,
        test_trends_with_data,
        test_trends_top_n,
        test_trends_ordering,
        test_trends_increasing,
        test_trends_decreasing,
        test_trends_window_days,
        test_regime_importance,
        test_regime_importance_empty,
        test_regime_importance_different,
        test_feature_selection_empty,
        test_feature_selection_low_importance,
        test_feature_selection_custom_threshold,
        test_report_empty,
        test_report_with_data,
        test_report_top_features,
        test_trend_volatility,
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
    print("📊 FAZ 4 TEST SONUÇLARI (Feature Importance Tracker)")
    print(f"{'='*60}")
    print(f"✅ Geçen: {passed}")
    print(f"❌ Başarısız: {failed}")
    print(f"📈 Toplam: {passed + failed}")

    if errors:
        print("\n🔍 Hatalar:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
