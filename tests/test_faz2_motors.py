"""
ALPHA BIST — FAZ 2 Test Suite (7 Motor)

Her motorun çıktısını doğrular.
"""

import sys
import os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_motor1_relative_strength():
    """Motor 1: Relatif Güç testleri."""
    from services.features.seven_motors import RelativeStrengthMotor

    motor = RelativeStrengthMotor()
    passed = 0
    failed = 0

    np.random.seed(42)
    stock = 100 + np.cumsum(np.random.randn(130) * 1.5)  # Daha iyi performans
    benchmark = 100 + np.cumsum(np.random.randn(130) * 1.0)

    features = motor.compute("TEST", stock, benchmark)

    # 1. vs BIST feature'ları var
    assert "rs_vs_bist_5d" in features
    assert "rs_vs_bist_20d" in features
    assert "rs_vs_bist_60d" in features
    passed += 1
    print(f"  ✓ vs BIST features: {len([k for k in features if 'vs_bist' in k])}")

    # 2. rs_ratio var
    assert "rs_ratio_5d" in features
    passed += 1
    print(f"  ✓ rs_ratio: {features.get('rs_ratio_5d', 0):.3f}")

    # 3. rs_trend var
    assert "rs_trend" in features
    passed += 1
    print(f"  ✓ rs_trend: {features.get('rs_trend', 0):.4f}")

    # 4. Peer relatif gücü
    peers = {"A": stock * 1.01, "B": stock * 0.99, "C": stock * 1.02}
    # peers should be arrays, not scalars
    peer_closes = {k: np.full(130, v) for k, v in peers.items()}
    features2 = motor.compute("TEST", stock, benchmark, peer_closes=peer_closes)
    assert "rs_vs_peers_5d" in features2
    passed += 1
    print(f"  ✓ Peer relative: {features2.get('rs_vs_peers_5d', 0):.4f}")

    return passed, failed


def test_motor2_momentum_trend():
    """Motor 2: Momentum + Trend testleri."""
    from services.features.seven_motors import MomentumTrendMotor

    motor = MomentumTrendMotor()
    passed = 0
    failed = 0

    np.random.seed(42)
    n = 130
    close = 100 + np.cumsum(np.random.randn(n) * 1.5)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    volume = np.random.randint(100000, 1000000, n).astype(float)

    features = motor.compute("TEST", close, high, low, volume)

    # 1. Trend eğimi
    assert "trend_slope_20d" in features
    assert "trend_r2_20d" in features
    passed += 1
    print(f"  ✓ Trend: slope={features.get('trend_slope_20d', 0):.4f}, R²={features.get('trend_r2_20d', 0):.3f}")

    # 2. Momentum ivmesi
    assert "roc_5d" in features
    assert "momentum_acceleration" in features
    assert "momentum_accel_trend" in features
    passed += 1
    print(f"  ✓ Momentum: roc={features.get('roc_5d', 0):.2f}%, accel={features.get('momentum_acceleration', 0):.2f}")

    # 3. Yeni yüksek/düşük
    assert "near_20d_high" in features
    assert "near_20d_low" in features
    passed += 1
    print(f"  ✓ Near high/low: high={features.get('near_20d_high', 0)}, low={features.get('near_20d_low', 0)}")

    # 4. Drawdown
    assert "drawdown_20d" in features
    passed += 1
    print(f"  ✓ Drawdown: {features.get('drawdown_20d', 0):.2f}%")

    # 5. SMA konumu
    assert "price_vs_sma20" in features
    assert "price_vs_sma50" in features
    passed += 1
    print(f"  ✓ Price vs SMA20: {features.get('price_vs_sma20', 0):.2f}%")

    return passed, failed


def test_motor3_volume():
    """Motor 3: Hacim + Mikroyapı testleri."""
    from services.features.seven_motors import VolumeMicrostructureMotor

    motor = VolumeMicrostructureMotor()
    passed = 0
    failed = 0

    np.random.seed(42)
    n = 30
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    open_ = close - np.random.rand(n) * 0.3
    high = close + np.random.rand(n)
    low = close - np.random.rand(n)
    volume = np.random.randint(100000, 1000000, n).astype(float)

    features = motor.compute("TEST", open_, close, high, low, volume)

    # 1. Volume percentile
    assert "volume_percentile" in features
    assert 0 <= features["volume_percentile"] <= 1
    passed += 1
    print(f"  ✓ Volume percentile: {features.get('volume_percentile', 0):.3f}")

    # 2. Volume up/down ratio
    assert "volume_up_down_ratio" in features
    passed += 1
    print(f"  ✓ Volume up/down: {features.get('volume_up_down_ratio', 0):.3f}")

    # 3. Tick rule
    assert "tick_rule" in features
    assert -1 <= features["tick_rule"] <= 1
    passed += 1
    print(f"  ✓ Tick rule: {features.get('tick_rule', 0):.3f}")

    # 4. VWAP deviation
    assert "vwap_deviation" in features
    passed += 1
    print(f"  ✓ VWAP deviation: {features.get('vwap_deviation', 0):.3f}%")

    # 5. Volume z-score
    assert "volume_zscore" in features
    passed += 1
    print(f"  ✓ Volume z-score: {features.get('volume_zscore', 0):.3f}")

    return passed, failed


def test_motor4_fundamental():
    """Motor 4: Fundamental testleri."""
    from services.features.seven_motors import FundamentalMotor

    motor = FundamentalMotor()
    passed = 0
    failed = 0

    fund = {
        "pe_ratio": 8.5, "pb_ratio": 1.4, "ev_ebitda": 5.1,
        "free_cash_flow": 6800000, "revenue": 100000000, "market_cap": 100000000,
        "roe": 0.15, "debt_to_equity": 0.45, "current_ratio": 1.8,
        "profit_margin": 0.10,
    }
    sector_medians = {"pe_ratio": 11.0, "pb_ratio": 1.8, "ev_ebitda": 7.0}

    features = motor.compute("TEST", fund, sector_medians)

    # 1. Ham çarpanlar
    assert "raw_pe_ratio" in features
    assert "raw_roe" in features
    passed += 1
    print(f"  ✓ Raw PE: {features.get('raw_pe_ratio', 0)}, ROE: {features.get('raw_roe', 0)}")

    # 2. Sektörel normalize
    assert "sector_norm_pe_ratio" in features
    assert features["sector_norm_pe_ratio"] < 1  # P/E 8.5 / sektör 11 = 0.77
    passed += 1
    print(f"  ✓ Sector norm PE: {features.get('sector_norm_pe_ratio', 0):.3f}")

    # 3. FCF yield
    assert "fcf_yield_pct" in features
    assert features["fcf_yield_pct"] > 0
    passed += 1
    print(f"  ✓ FCF yield: {features.get('fcf_yield_pct', 0):.2f}%")

    # 4. Bilanço kalitesi
    assert "balance_sheet_quality" in features
    assert features["balance_sheet_quality"] > 50  # İyi bilanço
    passed += 1
    print(f"  ✓ Balance sheet quality: {features.get('balance_sheet_quality', 0):.0f}")

    return passed, failed


def test_motor5_kap_news():
    """Motor 5: KAP + Haber testleri."""
    from services.features.seven_motors import KAPNewsMotor

    motor = KAPNewsMotor()
    passed = 0
    failed = 0

    kap = [
        {"category": "DIVIDEND", "importance": 0.8, "sentiment": 0.7},
        {"category": "INVESTMENT", "importance": 0.6, "sentiment": 0.5},
    ]
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    recent_ts = (now - timedelta(hours=10)).isoformat()
    old_ts = (now - timedelta(hours=200)).isoformat()  # 8 gün önce
    news = [
        {"sentiment": 0.6, "importance": 0.7, "timestamp": recent_ts},
        {"sentiment": 0.3, "importance": 0.5, "timestamp": old_ts},
    ]

    features = motor.compute("TEST", kap, news)

    # 1. KAP features
    assert "kap_avg_importance" in features
    assert "kap_sentiment_avg" in features
    passed += 1
    print(f"  ✓ KAP: importance={features.get('kap_avg_importance', 0):.2f}, sentiment={features.get('kap_sentiment_avg', 0):.2f}")

    # 2. News features
    assert "news_count_24h" in features
    assert "news_sentiment_weighted" in features
    passed += 1
    print(f"  ✓ News: count={features.get('news_count_24h', 0)}, sentiment={features.get('news_sentiment_weighted', 0):.3f}")

    # 3. Sentiment momentum
    assert "sentiment_momentum" in features
    passed += 1
    print(f"  ✓ Sentiment momentum: {features.get('sentiment_momentum', 0):.3f}")

    return passed, failed


def test_motor6_catalyst():
    """Motor 6: Katalizör testleri."""
    from services.features.seven_motors import CatalystMotor

    motor = CatalystMotor()
    passed = 0
    failed = 0

    events = [
        {"type": "earnings", "importance": 0.9, "days_until": 5},
        {"type": "dividend", "importance": 0.7, "days_until": 15},
    ]

    features = motor.compute("TEST", events)

    assert features["catalyst_count"] == 2
    assert features["catalyst_importance"] == 0.9
    assert features["catalyst_days_nearest"] == 5
    passed += 1
    print(f"  ✓ Catalyst: count={features['catalyst_count']}, importance={features['catalyst_importance']}, nearest={features['catalyst_days_nearest']}d")

    # Boş olay
    features_empty = motor.compute("TEST", [])
    assert features_empty["catalyst_count"] == 0
    passed += 1
    print(f"  ✓ Empty catalyst: count={features_empty['catalyst_count']}")

    return passed, failed


def test_motor7_why_falling():
    """Motor 7: Neden Düşüyor testleri."""
    from services.features.seven_motors import WhyFallingMotor

    motor = WhyFallingMotor()
    passed = 0
    failed = 0

    # 1. Düşüş yok
    features = motor.compute("TEST", 2.0, 1.0, 1.5, 1.0, 0.0, 0.0)
    assert features["why_falling"] == 0.0
    passed += 1
    print(f"  ✓ No fall: why_falling={features['why_falling']}")

    # 2. Market selloff
    features = motor.compute("TEST", -8.0, -5.0, -3.0, 1.0, 0.0, 0.0)
    assert features["fall_market_selloff"] == 1.0
    assert features["falling_is_temporary"] == 1.0  # Market genel düşüş
    passed += 1
    print(f"  ✓ Market selloff: temporary={features['falling_is_temporary']}")

    # 3. Company-specific
    features = motor.compute("TEST", -10.0, 1.0, 1.0, 1.0, -0.3, 0.0)
    assert features["fall_company_specific"] == 1.0
    assert features["falling_is_temporary"] == 0.0  # Company-specific = kalıcı
    passed += 1
    print(f"  ✓ Company specific: temporary={features['falling_is_temporary']}")

    # 4. Liquidity event
    features = motor.compute("TEST", -12.0, -2.0, -3.0, 3.5, -0.5, 0.0)
    assert features["fall_liquidity_event"] == 1.0
    passed += 1
    print(f"  ✓ Liquidity event: {features['fall_liquidity_event']}")

    return passed, failed


def test_seven_motor_integration():
    """7 Motor entegrasyon testi."""
    from services.features.seven_motors import seven_motor_engine

    passed = 0
    failed = 0

    np.random.seed(42)
    n = 130
    close = 100 + np.cumsum(np.random.randn(n) * 1.5)
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    open_ = close - np.random.rand(n) * 0.5
    volume = np.random.randint(100000, 1000000, n).astype(float)
    benchmark = 100 + np.cumsum(np.random.randn(n) * 1.0)

    features = seven_motor_engine.compute_all(
        ticker="TEST",
        close=close, open_=open_, high=high, low=low, volume=volume,
        benchmark_close=benchmark,
        fundamentals={"pe_ratio": 8.5, "roe": 0.15, "free_cash_flow": 6800000, "revenue": 100e6, "market_cap": 100e6},
        market_regime="BULL",
    )

    # 1. Motor 1 çıktıları
    assert any("rs_vs_bist" in k for k in features)
    passed += 1
    print(f"  ✓ Motor 1 (Relatif Güç): {len([k for k in features if 'rs_' in k])} features")

    # 2. Motor 2 çıktıları
    assert "trend_slope_20d" in features
    assert "momentum_acceleration" in features
    passed += 1
    print(f"  ✓ Motor 2 (Momentum+Trend): {len([k for k in features if 'trend' in k or 'momentum' in k or 'roc' in k])} features")

    # 3. Motor 3 çıktıları
    assert "tick_rule" in features
    assert "volume_percentile" in features
    passed += 1
    print(f"  ✓ Motor 3 (Hacim+Mikroyapı): {len([k for k in features if 'volume' in k or 'tick' in k or 'vwap' in k])} features")

    # 4. Motor 4 çıktıları
    assert "raw_pe_ratio" in features
    passed += 1
    print(f"  ✓ Motor 4 (Fundamental): {len([k for k in features if 'raw_' in k or 'sector_norm' in k or 'fcf' in k])} features")

    # 5. Motor 6 çıktıları (boş olay)
    assert "catalyst_count" in features
    passed += 1
    print(f"  ✓ Motor 6 (Katalizör): count={features.get('catalyst_count', 0)}")

    # 6. Motor 7 çıktıları
    assert "why_falling" in features
    passed += 1
    print(f"  ✓ Motor 7 (Neden Düşüyor): {features.get('why_falling', 0)}")

    # 7. Toplam feature sayısı
    assert len(features) >= 30
    passed += 1
    print(f"  ✓ Toplam feature: {len(features)}")

    # 8. Regime bilgisi
    assert features.get("regime") == "BULL"
    passed += 1
    print(f"  ✓ Regime: {features.get('regime')}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 2 — 7 Motor Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Motor 1: Relatif Güç", test_motor1_relative_strength),
        ("Motor 2: Momentum+Trend", test_motor2_momentum_trend),
        ("Motor 3: Hacim+Mikroyapı", test_motor3_volume),
        ("Motor 4: Fundamental", test_motor4_fundamental),
        ("Motor 5: KAP+Haber", test_motor5_kap_news),
        ("Motor 6: Katalizör", test_motor6_catalyst),
        ("Motor 7: Neden Düşüyor", test_motor7_why_falling),
        ("7 Motor Entegrasyon", test_seven_motor_integration),
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
