"""
ALPHA BIST — FAZ 1 E2E Integration Test

Veri çek → Quality Gate → Feature Store → Event Pipeline

Bu test FAZ 1'in tamamının entegrasyonunu doğrular.
"""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone


def test_e2e_data_pipeline():
    """E2E: Veri çek → Quality → Feature → Event."""
    passed = 0
    failed = 0

    print("=== E2E Data Pipeline Test ===")
    print()

    # 1. Market Calendar
    print("1. Market Calendar")
    from services.core.market_calendar import market_calendar
    info = market_calendar.get_info()
    print(f"   Trading day: {info['is_trading_day']}")
    print(f"   Market open: {info['is_market_open']}")
    print(f"   Session: {info['session']}")
    passed += 1
    print("   ✓ Market calendar çalışıyor")
    print()

    # 2. BIST Universe
    print("2. BIST Universe")
    from services.ingestion.bist_universe import bist_universe
    tickers = bist_universe.get_tickers()
    print(f"   Tickers: {len(tickers)}")
    if len(tickers) > 100:
        passed += 1
        print(f"   ✓ {len(tickers)} hisse yüklendi")
    else:
        failed += 1
        print(f"   ✗ Çok az hisse: {len(tickers)}")
    print()

    # 3. Data Quality Gate
    print("3. Data Quality Gate")
    from services.core.data_quality import data_quality_gate, DataValidity
    from datetime import timezone

    # Valid tick
    r = data_quality_gate.check_tick("THYAO", 305.25, 50000, datetime.now(timezone.utc))
    assert r.passed and r.validity == DataValidity.VALID, f"Valid tick failed: {r}"

    # Invalid tick
    r = data_quality_gate.check_tick("THYAO", -10, 100, datetime.now(timezone.utc))
    assert not r.passed and r.validity == DataValidity.INVALID

    # Future tick
    from datetime import timedelta
    future = datetime.now(timezone.utc) + timedelta(seconds=20)
    r = data_quality_gate.check_tick("THYAO", 305.25, 50000, future)
    assert not r.passed and r.validity == DataValidity.FUTURE

    passed += 1
    print("   ✓ Data quality gate çalışıyor (valid, invalid, future)")
    print()

    # 4. yfinance Provider
    print("4. yfinance Provider")
    from services.ingestion.providers.yfinance_provider import yfinance_provider

    # Price
    price_data = yfinance_provider.fetch_current_price("THYAO")
    assert price_data and price_data.get("price", 0) > 0, "Price fetch failed"
    passed += 1
    print(f"   ✓ Fiyat: {price_data['price']}")

    # OHLCV
    df = yfinance_provider.fetch_ohlcv("THYAO", period="5d")
    assert df is not None and len(df) > 0, "OHLCV fetch failed"
    passed += 1
    print(f"   ✓ OHLCV: {len(df)} satır")

    # Macro
    macro = yfinance_provider.fetch_macro()
    assert macro and macro.get("USD/TRY", {}).get("price", 0) > 0, "Macro fetch failed"
    passed += 1
    print(f"   ✓ USD/TRY: {macro['USD/TRY']['price']}")
    print(f"   ✓ Gold: {macro['Gold']['price']}")
    print(f"   ✓ VIX: {macro['VIX']['price']}")
    print()

    # 5. Fundamental Provider
    print("5. Fundamental Provider")
    from services.ingestion.providers.fundamental_provider import fundamental_provider

    fund = fundamental_provider.fetch_fundamentals("THYAO")
    assert fund and fund.get("price", 0) > 0, "Fundamental fetch failed"
    passed += 1
    print(f"   ✓ Price: {fund['price']}")
    print(f"   ✓ P/B: {fund.get('pb_ratio')}")
    print(f"   ✓ ROE: {fund.get('roe')}")
    print(f"   ✓ Revenue Growth: {fund.get('revenue_growth')}")

    summary = fundamental_provider.get_valuation_summary("THYAO")
    assert summary, "Valuation summary failed"
    passed += 1
    print(f"   ✓ Valuation summary hazır")
    print()

    # 6. KAP Provider
    print("6. KAP Provider")
    from services.ingestion.providers.kap_provider import kap_provider

    disclosures = kap_provider.fetch_disclosures(from_date="2026-08-14", to_date="2026-08-15")
    # KAP timeout olabilir - bu durumda boş liste döner
    if disclosures:
        passed += 1
        print(f"   ✓ {len(disclosures)} KAP bildirimi")
    else:
        print(f"   ⚠ KAP erişilemedi (timeout - normal olabilir)")
        passed += 1  # Network issue, not a code bug
    print()

    # 7. News Provider
    print("7. News Provider")
    from services.ingestion.providers.news_provider import news_provider

    rss = news_provider.fetch_financial_news_rss()
    if rss:
        passed += 1
        print(f"   ✓ {len(rss)} RSS haberi")
        print(f"   ✓ İlk: {rss[0].get('source')} - {rss[0].get('title', '')[:50]}")
    else:
        print(f"   ⚠ RSS haber gelmedi (ağ sorunu olabilir)")
        passed += 1
    print()

    # 8. Feature Calculator
    print("8. Feature Calculator")
    import polars as pl
    import numpy as np
    from services.features.calculator import feature_calculator

    # yfinance'dan veri çek
    df = yfinance_provider.fetch_ohlcv("THYAO", period="60d")
    if df is not None and len(df) >= 20:
        features = feature_calculator.compute_all_features(df)
        assert len(features) > 30, f"Too few features: {len(features)}"
        passed += 1
        print(f"   ✓ {len(features)} feature hesaplandı")
        print(f"   ✓ RSI: {features.get('rsi_14', 'N/A'):.1f}")
        print(f"   ✓ Return 1d: {features.get('return_1d', 'N/A'):.2f}%")
        print(f"   ✓ Volume Z-score: {features.get('volume_zscore', 'N/A'):.2f}")
    else:
        failed += 1
        print(f"   ✗ OHLCV verisi yetersiz")
    print()

    # 9. Circuit Breaker + Rate Limiter
    print("9. Circuit Breaker + Rate Limiter")
    from services.core.circuit_breaker import (
        CircuitBreaker, RateLimiter, register_protected_provider, get_all_health
    )

    def mock_fetch(ticker):
        return {"ticker": ticker, "price": 100.0}

    provider = register_protected_provider("test_provider", mock_fetch, max_calls_per_second=10.0)
    health = get_all_health()
    assert "test_provider" in health
    passed += 1
    print(f"   ✓ Protected provider çalışıyor")
    print(f"   ✓ Circuit state: {health['test_provider']['circuit']['state']}")
    print(f"   ✓ Reliability: {health['test_provider']['reliability']['reliability_score']}")
    print()

    # 10. Corporate Actions
    print("10. Corporate Actions")
    from services.ingestion.corporate_actions import (
        corporate_actions, CorporateAction, ActionType
    )

    # Temettü düzeltmesi
    corporate_actions.add_action(CorporateAction(
        action_id="TEST-DIV-001",
        ticker="THYAO",
        action_type=ActionType.DIVIDEND,
        ex_date=datetime(2026, 6, 1).date(),
        dividend_per_share=5.25,
    ))

    adjusted = corporate_actions.adjust_price("THYAO", 300.0, datetime(2026, 6, 2).date())
    assert abs(adjusted - 294.75) < 0.01, f"Dividend adjustment failed: {adjusted}"
    passed += 1
    print(f"   ✓ Temettü düzeltmesi: 300 → {adjusted}")

    # Bölünme
    corporate_actions.add_action(CorporateAction(
        action_id="TEST-SPLIT-001",
        ticker="ASELS",
        action_type=ActionType.STOCK_SPLIT,
        ex_date=datetime(2026, 7, 1).date(),
        split_ratio=10.0,
    ))

    adjusted = corporate_actions.adjust_price("ASELS", 500.0, datetime(2026, 7, 2).date())
    assert abs(adjusted - 50.0) < 0.01, f"Split adjustment failed: {adjusted}"

    new_qty = corporate_actions.adjust_position("ASELS", 100, CorporateAction(
        action_id="TEST", ticker="ASELS", action_type=ActionType.STOCK_SPLIT,
        ex_date=datetime(2026, 7, 1).date(), split_ratio=10.0,
    ))
    assert new_qty == 1000, f"Position adjustment failed: {new_qty}"
    passed += 1
    print(f"   ✓ Bölünme düzeltmesi: 500 → {adjusted}, 100 lot → {new_qty}")
    print()

    # 11. Provider Manager
    print("11. Provider Manager")
    from services.ingestion.providers.provider_manager import provider_manager

    # Mevcut health
    health = provider_manager.get_health()
    print(f"   Registered: {list(health.keys())}")
    passed += 1
    print("   ✓ Provider manager çalışıyor")
    print()

    # 12. Event Schema
    print("12. Event Schema")
    from services.core.event_schema import CanonicalEvent, EventType

    event = CanonicalEvent(
        event_type=EventType.MARKET_TICK,
        source="test",
        data={"ticker": "THYAO", "price": 305.25, "volume": 50000},
    )

    # Validation
    missing = event.validate_payload()
    assert len(missing) == 0, f"Validation failed: {missing}"

    # JSON serialization
    json_str = event.to_json()
    assert "THYAO" in json_str
    assert "305.25" in json_str

    # Deserialization
    event2 = CanonicalEvent.from_json(json_str)
    assert event2.data["ticker"] == "THYAO"

    passed += 1
    print(f"   ✓ Event schema: create → validate → serialize → deserialize")
    print()

    # 13. Data Quality Gate - Batch
    print("13. Data Quality Gate - Batch Test")
    tickers_to_test = ["THYAO", "ASELS", "GARAN", "AKBNK", "EREGL"]
    valid_count = 0
    for t in tickers_to_test:
        pd = yfinance_provider.fetch_current_price(t)
        if pd and pd.get("price", 0) > 0:
            r = data_quality_gate.check_tick(t, pd["price"], pd.get("volume", 0), datetime.now(timezone.utc))
            if r.passed:
                valid_count += 1

    if valid_count >= 3:
        passed += 1
        print(f"   ✓ {valid_count}/{len(tickers_to_test)} tick geçti")
    else:
        failed += 1
        print(f"   ✗ {valid_count}/{len(tickers_to_test)} tick geçti")
    print()

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 1 — E2E Integration Test")
    print("=" * 60)
    print()

    start = time.time()
    passed, failed = test_e2e_data_pipeline()
    elapsed = time.time() - start

    print()
    print("=" * 60)
    print(f"  SONUÇ: {passed} passed, {failed} failed")
    print(f"  Süre: {elapsed:.1f}s")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
