"""
ALPHA BIST — FAZ 2 Test Suite

Fundamental Features, Macro Features, Sentiment Features, Feature Store testleri.

Kullanım:
  python3 tests/test_phase2.py
"""

import sys
import os


def test_fundamental_features():
    """Fundamental Feature Engine testleri."""
    from services.features.fundamental import fundamental_feature_engine

    passed = 0
    failed = 0

    # Test verisi
    fund = {
        "price": 305.25,
        "pe_ratio": 8.5,
        "forward_pe": 7.2,
        "pb_ratio": 1.4,
        "ev_ebitda": 5.1,
        "fcf_yield": 0.068,
        "dividend_yield": 0.032,
        "gross_margin": 0.25,
        "ebitda_margin": 0.18,
        "operating_margin": 0.12,
        "profit_margin": 0.10,
        "roe": 0.15,
        "roa": 0.08,
        "revenue_growth": 0.205,
        "earnings_growth": 0.15,
        "debt_to_equity": 0.45,
        "current_ratio": 1.8,
        "total_debt": 5000000,
        "total_cash": 2000000,
        "ebitda": 10000000,
        "free_cash_flow": 6800000,
        "operating_cash_flow": 8500000,
        "revenue": 100000000,
        "net_income": 10000000,
        "total_equity": 50000000,
        "market_cap": 100000000,
    }

    # 1. Valuation features
    features = fundamental_feature_engine.compute_valuation_features(fund)
    assert features.get("pe_ratio") == 8.5, f"P/E: {features.get('pe_ratio')}"
    assert features.get("pb_ratio") == 1.4, f"P/B: {features.get('pb_ratio')}"
    assert features.get("ev_ebitda") == 5.1, f"EV/EBITDA: {features.get('ev_ebitda')}"
    assert abs(features.get("fcf_yield", 0) - 6.8) < 0.1, f"FCF Yield: {features.get('fcf_yield')}"
    assert abs(features.get("dividend_yield", 0) - 3.2) < 0.1, f"Div Yield: {features.get('dividend_yield')}"
    passed += 1
    print("  ✓ Valuation features")

    # 2. Profitability features
    features = fundamental_feature_engine.compute_profitability_features(fund)
    assert abs(features.get("roe", 0) - 15.0) < 0.1, f"ROE: {features.get('roe')}"
    assert abs(features.get("profit_margin", 0) - 10.0) < 0.1, f"Margin: {features.get('profit_margin')}"
    passed += 1
    print("  ✓ Profitability features")

    # 3. Growth features
    features = fundamental_feature_engine.compute_growth_features(fund)
    assert abs(features.get("revenue_growth_pct", 0) - 20.5) < 0.1, f"Rev Growth: {features.get('revenue_growth_pct')}"
    passed += 1
    print("  ✓ Growth features")

    # 4. Balance sheet features
    features = fundamental_feature_engine.compute_balance_sheet_features(fund)
    assert features.get("debt_to_equity") == 0.45, f"D/E: {features.get('debt_to_equity')}"
    assert features.get("current_ratio") == 1.8, f"CR: {features.get('current_ratio')}"
    assert features.get("net_debt") == 3000000, f"Net Debt: {features.get('net_debt')}"
    passed += 1
    print("  ✓ Balance sheet features")

    # 5. Cash flow features
    features = fundamental_feature_engine.compute_cash_flow_features(fund)
    assert features.get("free_cash_flow") == 6800000, f"FCF: {features.get('free_cash_flow')}"
    assert abs(features.get("fcf_margin", 0) - 6.8) < 0.1, f"FCF Margin: {features.get('fcf_margin')}"
    passed += 1
    print("  ✓ Cash flow features")

    # 6. Quality features
    features = fundamental_feature_engine.compute_quality_features(fund)
    assert features.get("growth_quality_score", 0) > 50, f"Quality: {features.get('growth_quality_score')}"
    passed += 1
    print("  ✓ Quality features")

    # 7. Trend features
    quarterly = [
        {"period": "2025-06-30", "total_revenue": 80000000, "net_income": 7000000},
        {"period": "2025-09-30", "total_revenue": 85000000, "net_income": 8000000},
        {"period": "2025-12-31", "total_revenue": 90000000, "net_income": 9000000},
        {"period": "2026-03-31", "total_revenue": 100000000, "net_income": 10000000},
    ]
    features = fundamental_feature_engine.compute_trend_features(quarterly)
    assert features.get("revenue_trend") == 1.0, f"Trend: {features.get('revenue_trend')}"
    assert features.get("quarterly_revenue_growth", 0) > 0, f"Q Growth: {features.get('quarterly_revenue_growth')}"
    passed += 1
    print("  ✓ Trend features")

    # 8. All features combined
    all_features = fundamental_feature_engine.compute_all_fundamental_features(fund)
    assert len(all_features) >= 15, f"Too few features: {len(all_features)}"
    passed += 1
    print(f"  ✓ All fundamental features ({len(all_features)} feature)")

    # 9. Empty fundamentals
    empty_features = fundamental_feature_engine.compute_all_fundamental_features({})
    assert isinstance(empty_features, dict)
    passed += 1
    print("  ✓ Empty fundamentals handled")

    return passed, failed


def test_macro_features():
    """Macro Feature Engine testleri."""
    from services.features.macro import MacroFeatureEngine

    engine = MacroFeatureEngine()
    passed = 0
    failed = 0

    # 1. Currency features
    features = engine.compute_currency_features(47.88, 55.38)
    assert features.get("usdtry_level") == 47.88, f"USD/TRY: {features.get('usdtry_level')}"
    assert features.get("eurtry_level") == 55.38, f"EUR/TRY: {features.get('eurtry_level')}"
    passed += 1
    print("  ✓ Currency features")

    # 2. VIX features (history yokken sadece level)
    features = engine.compute_vix_features(14.25)
    assert features.get("vix_level") == 14.25, f"VIX: {features.get('vix_level')}"
    # Regime için history gerekli
    for _ in range(30):
        engine.update_history("vix", 15.0)
    features = engine.compute_vix_features(14.25)
    assert features.get("vix_regime") == 0.0, f"VIX regime: {features.get('vix_regime')}"  # COMPLACENT
    passed += 1
    print("  ✓ VIX features")

    # 3. Commodity features
    features = engine.compute_commodity_features(4437.3, 82.4)
    assert features.get("gold_price") == 4437.3, f"Gold: {features.get('gold_price')}"
    assert features.get("oil_price") == 82.4, f"Oil: {features.get('oil_price')}"
    passed += 1
    print("  ✓ Commodity features")

    # 4. Global features
    features = engine.compute_global_features(7785.76, 26729.16)
    assert features.get("sp500_level") == 7785.76, f"S&P: {features.get('sp500_level')}"
    passed += 1
    print("  ✓ Global features")

    # 5. All macro features
    macro_data = {
        "USD/TRY": {"price": 47.88},
        "EUR/TRY": {"price": 55.38},
        "Gold": {"price": 4437.3},
        "Oil": {"price": 82.4},
        "VIX": {"price": 14.25},
        "S&P500": {"price": 7785.76},
        "Nasdaq": {"price": 26729.16},
    }
    all_features = engine.compute_all_macro_features(macro_data)
    assert len(all_features) >= 8, f"Too few features: {len(all_features)}"
    passed += 1
    print(f"  ✓ All macro features ({len(all_features)} feature)")

    # 6. History + z-score
    for _ in range(30):
        engine.update_history("usdtry", 45.0)
    engine.update_history("usdtry", 50.0)
    features = engine.compute_currency_features(50.0)
    assert "usdtry_zscore" in features, "Z-score missing"
    passed += 1
    print("  ✓ History + z-score")

    return passed, failed


def test_sentiment_features():
    """Sentiment Feature Engine testleri."""
    from services.features.sentiment import SentimentFeatureEngine
    from datetime import datetime, timezone, timedelta

    engine = SentimentFeatureEngine()
    passed = 0
    failed = 0

    # 1. Empty state
    features = engine.compute_all_sentiment_features("THYAO")
    assert features.get("news_sentiment") == 0.0
    assert features.get("kap_sentiment") == 0.0
    assert features.get("social_sentiment") == 0.0
    passed += 1
    print("  ✓ Empty state")

    # 2. News events
    now = datetime.now(timezone.utc).isoformat()
    engine.add_news_event("THYAO", {"sentiment": 0.8, "importance": 0.7, "credibility": 0.9, "timestamp": now})
    engine.add_news_event("THYAO", {"sentiment": 0.6, "importance": 0.5, "credibility": 0.8, "timestamp": now})
    features = engine.compute_news_features("THYAO")
    assert features.get("news_sentiment", 0) > 0, f"News sentiment: {features.get('news_sentiment')}"
    assert features.get("news_count_24h") == 2
    passed += 1
    print("  ✓ News features")

    # 3. KAP events
    engine.add_kap_event("THYAO", {"sentiment": 0.9, "importance": 0.9, "is_price_sensitive": True, "timestamp": now})
    features = engine.compute_kap_features("THYAO")
    assert features.get("kap_sentiment", 0) > 0
    assert features.get("kap_price_sensitive_count") == 1
    passed += 1
    print("  ✓ KAP features")

    # 4. Social events
    engine.add_social_event("THYAO", {"sentiment": 0.5, "engagement_score": 10, "timestamp": now})
    engine.add_social_event("THYAO", {"sentiment": 0.3, "engagement_score": 5, "timestamp": now})
    features = engine.compute_social_features("THYAO")
    assert features.get("social_sentiment", 0) > 0
    assert features.get("social_volume_24h") == 2
    passed += 1
    print("  ✓ Social features")

    # 5. Composite sentiment
    features = engine.compute_all_sentiment_features("THYAO")
    assert "composite_sentiment" in features
    assert features.get("composite_sentiment", 0) > 0
    passed += 1
    print("  ✓ Composite sentiment")

    # 6. Manipulation detection
    for _ in range(20):
        engine.add_social_event("SUSPECT", {"sentiment": 0.99, "engagement_score": 1, "timestamp": now})
    features = engine.compute_social_features("SUSPECT")
    assert features.get("social_manipulation_score", 0) > 0, f"Manipulation: {features.get('social_manipulation_score')}"
    passed += 1
    print("  ✓ Manipulation detection")

    return passed, failed


def test_feature_store():
    """Feature Store testleri."""
    from services.features.store import feature_store

    passed = 0
    failed = 0

    # Temizle
    feature_store.clear()

    # 1. Set and get
    feature_store.set("THYAO", {"rsi_14": 64.2, "momentum_20d": 5.3}, version="v1")
    rsi = feature_store.get("THYAO", "rsi_14")
    assert rsi == 64.2, f"RSI: {rsi}"
    passed += 1
    print("  ✓ Set and get")

    # 2. Get all
    features = feature_store.get_all("THYAO")
    assert "rsi_14" in features
    assert "momentum_20d" in features
    passed += 1
    print("  ✓ Get all")

    # 3. Versioning
    feature_store.set("THYAO", {"rsi_14": 65.0, "new_feature": 42.0}, version="v2")
    rsi_v1 = feature_store.get("THYAO", "rsi_14", version="v1")
    rsi_v2 = feature_store.get("THYAO", "rsi_14", version="v2")
    assert rsi_v1 == 64.2, f"V1 RSI: {rsi_v1}"
    assert rsi_v2 == 65.0, f"V2 RSI: {rsi_v2}"
    passed += 1
    print("  ✓ Versioning")

    # 4. Latest version
    rsi_latest = feature_store.get("THYAO", "rsi_14", version="latest")
    assert rsi_latest == 65.0, f"Latest RSI: {rsi_latest}"
    passed += 1
    print("  ✓ Latest version")

    # 5. Metadata
    meta = feature_store.get_metadata("THYAO")
    assert meta is not None
    assert meta.get("feature_count") > 0
    passed += 1
    print("  ✓ Metadata")

    # 6. History
    history = feature_store.get_history("THYAO")
    assert len(history) >= 2
    passed += 1
    print("  ✓ History")

    # 7. Feature hash
    hash1 = feature_store.get_feature_hash("THYAO")
    assert len(hash1) == 16
    passed += 1
    print("  ✓ Feature hash")

    # 8. Register version
    feature_store.register_version("technical", "v1", "RSI(14), SMA(20), MACD(12,26,9)")
    feature_store.register_version("technical", "v2", "RSI(14) Wilder, SMA(20), MACD(12,26,9)")
    versions = feature_store.get_version_info("technical")
    assert "v1" in versions
    assert "v2" in versions
    passed += 1
    print("  ✓ Version registration")

    # 9. Stats
    stats = feature_store.get_stats()
    assert stats.get("total_tickers") >= 1
    assert stats.get("total_features") >= 3
    passed += 1
    print("  ✓ Stats")

    # 10. Clear
    feature_store.clear("THYAO")
    features = feature_store.get_all("THYAO")
    assert len(features) == 0
    passed += 1
    print("  ✓ Clear")

    return passed, failed


def test_technical_features_integration():
    """Teknik feature'lar + feature store entegrasyon testi."""
    from services.features.calculator import feature_calculator
    from services.features.store import feature_store
    from services.ingestion.providers.yfinance_provider import yfinance_provider

    passed = 0
    failed = 0

    # 1. OHLCV çek → feature hesapla → store'a kaydet
    df = yfinance_provider.fetch_ohlcv("THYAO", period="60d")
    if df is not None and len(df) >= 20:
        features = feature_calculator.compute_all_features(df)
        assert len(features) > 30, f"Too few features: {len(features)}"

        # Store'a kaydet
        feature_store.set("THYAO", features, version="v1", source="calculator")

        # Store'dan oku
        stored_features = feature_store.get_all("THYAO")
        assert stored_features.get("rsi_14") == features.get("rsi_14")

        passed += 1
        print("  ✓ OHLCV → Feature → Store → Read")
    else:
        failed += 1
        print("  ✗ OHLCV fetch failed")

    # 2. Fundamental + teknik birleştirme
    from services.features.fundamental import fundamental_feature_engine
    from services.ingestion.providers.fundamental_provider import fundamental_provider

    fund = fundamental_provider.fetch_fundamentals("THYAO")
    if fund:
        fund_features = fundamental_feature_engine.compute_all_fundamental_features(fund)
        assert len(fund_features) >= 10

        # Teknik + fundamental birleştir
        combined = {}
        combined.update(feature_store.get_all("THYAO"))
        combined.update(fund_features)

        assert "rsi_14" in combined
        assert "pe_ratio" in combined or "pb_ratio" in combined

        feature_store.set("THYAO", combined, version="v2", source="combined")
        passed += 1
        print(f"  ✓ Teknik + Fundamental birleştirme ({len(combined)} feature)")
    else:
        failed += 1
        print("  ✗ Fundamental fetch failed")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 2 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Fundamental Features", test_fundamental_features),
        ("Macro Features", test_macro_features),
        ("Sentiment Features", test_sentiment_features),
        ("Feature Store", test_feature_store),
        ("Technical + Store Integration", test_technical_features_integration),
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
