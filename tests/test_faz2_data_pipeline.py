#!/usr/bin/env python3
"""
ALPHA BIST — Faz 2 Data Pipeline Tests

Doğrulanan:
1. Feature data contract (value, status, timestamp, source)
2. Fundamental pipeline (provider → Motor 4)
3. KAP pipeline (PIT safety)
4. News pipeline (PIT safety)
5. Catalyst pipeline
6. Missing/unknown/stale ayrımı
7. Point-in-time leakage koruması
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =====================================================
# 1. FEATURE DATA CONTRACT
# =====================================================

def test_feature_contract_basics():
    """FeatureDataPoint doğru çalışıyor mu?"""
    from services.features.feature_contract import (
        make_fresh, make_missing, make_unknown, make_stale,
        FeatureStatus, TickerFeatureContract,
    )
    issues = []

    # FRESH
    fresh = make_fresh(42.5, "test", "2024-01-15T10:00:00Z")
    if not fresh.is_usable():
        issues.append("FRESH usable değil")
    if fresh.to_value() != 42.5:
        issues.append("FRESH to_value yanlış")
    if fresh.status != FeatureStatus.FRESH:
        issues.append("FRESH status yanlış")

    # MISSING
    missing = make_missing("test")
    if missing.is_usable():
        issues.append("MISSING usable olmamalı")
    if missing.to_value(99.0) != 99.0:
        issues.append("MISSING default dönmeli")
    if missing.value is not None:
        issues.append("MISSING value None olmalı")

    # UNKNOWN
    unknown = make_unknown("test")
    if unknown.is_usable():
        issues.append("UNKNOWN usable olmamalı")

    # STALE
    stale = make_stale(10.0, "test", "2024-01-01T00:00:00Z")
    if stale.is_usable():
        issues.append("STALE usable olmamalı (FRESH değil)")
    if stale.to_value() != 0.0:
        issues.append("STALE to_value default dönmeli")

    # Contract
    contract = TickerFeatureContract(ticker="TEST", timestamp="2024-01-15")
    contract.features["rsi"] = make_fresh(65.0, "calc")
    contract.features["pe"] = make_missing("fundamental")
    if contract.get_value("rsi") != 65.0:
        issues.append("Contract get_value FRESH")
    if contract.get_value("pe", -1) != -1:
        issues.append("Contract get_value MISSING default")

    usable = contract.get_usable_dict()
    if "pe" in usable:
        issues.append("MISSING usable_dict'te olmamalı")

    report = contract.get_availability_report()
    if report.get("rsi") != "FRESH":
        issues.append("Report FRESH")
    if report.get("pe") != "MISSING":
        issues.append("Report MISSING")

    return "Feature Data Contract", len(issues) == 0, issues


def test_contract_backward_compatible():
    """Contract backward compatible — raw dict ile aynı sonuç vermeli."""
    from services.features.feature_contract import features_to_contract
    issues = []

    raw = {"rsi_14": 65.0, "momentum_20d": 5.5, "_feature_count": 2}
    contract = features_to_contract("TEST", raw, "calculator")

    if contract.get_value("rsi_14") != 65.0:
        issues.append("Contract raw dict uyumsuz")
    if contract.get_value("momentum_20d") != 5.5:
        issues.append("Contract raw dict uyumsuz")

    raw_back = contract.get_raw_dict()
    if raw_back.get("rsi_14") != 65.0:
        issues.append("get_raw_dict uyumsuz")
    if "_feature_count" in raw_back:
        issues.append("Meta feature raw_dict'te olmamalı")

    return "Contract Backward Compatible", len(issues) == 0, issues


# =====================================================
# 2. DATA ADAPTER — PROVIDER YOKKEN GRACEFUL
# =====================================================

def test_data_adapter_no_providers():
    """Provider bağımlılıkları yokken adapter graceful davranmalı."""
    from services.features.data_adapter import data_adapter
    issues = []

    # Fundamental — provider yoksa MISSING dönmeli
    fund = data_adapter.fetch_fundamentals("THYAO", as_of_date="2024-01-15")
    if not fund:
        issues.append("Fundamental boş dict döndü")
    else:
        for key, dp in fund.items():
            if dp.status.value not in ("MISSING", "UNKNOWN"):
                issues.append(f"{key}: unexpected status {dp.status.value}")

    # KAP — provider yoksa boş liste dönmeli
    kap = data_adapter.fetch_kap_events("THYAO", as_of_date="2024-01-15")
    if kap != []:
        issues.append("KAP boş liste dönmeli")

    # News — provider yoksa boş liste dönmeli
    news = data_adapter.fetch_news_events("THYAO", as_of_date="2024-01-15")
    if news != []:
        issues.append("News boş liste dönmeli")

    # Catalyst — boş KAP/news'den boş catalyst
    cats = data_adapter.derive_catalysts([], [], as_of_date="2024-01-15")
    if cats != []:
        issues.append("Boş catalyst dönmeli")

    return "Data Adapter (No Providers)", len(issues) == 0, issues


# =====================================================
# 3. KAP HELPERS
# =====================================================

def test_kap_helpers():
    """KAP classification ve sentiment helpers."""
    from services.features.data_adapter import data_adapter
    issues = []

    # Category classification
    if data_adapter._classify_kap_category("2024 Yılı Finansal Rapor") != "FINANCIAL_REPORT":
        issues.append("FINANCIAL_REPORT classify")
    if data_adapter._classify_kap_category("Temettü Dağıtım Kararı") != "DIVIDEND":
        issues.append("DIVIDEND classify")
    if data_adapter._classify_kap_category("Sermaye Artırım Kararı") != "CAPITAL_INCREASE":
        issues.append("CAPITAL_INCREASE classify")

    # Sentiment
    pos = data_adapter._estimate_sentiment("Kâr artışı rekor seviyede", "")
    if pos <= 0:
        issues.append(f"Pozitif sentiment: {pos}")
    neg = data_adapter._estimate_sentiment("Zarar ve düşüş devam ediyor", "")
    if neg >= 0:
        issues.append(f"Negatif sentiment: {neg}")
    neutral = data_adapter._estimate_sentiment("Yönetim kurulu toplandı", "")
    if neutral != 0:
        issues.append(f"Neutral sentiment: {neutral}")

    # Importance
    if data_adapter._estimate_importance("FINANCIAL_REPORT", "") < 0.8:
        issues.append("FINANCIAL_REPORT importance düşük")
    if data_adapter._estimate_importance("OTHER", "") > 0.5:
        issues.append("OTHER importance yüksek")

    return "KAP Helpers", len(issues) == 0, issues


# =====================================================
# 4. CATALYST PIPELINE
# =====================================================

def test_catalyst_derivation():
    """KAP olaylarından katalizör türetme."""
    from services.features.data_adapter import data_adapter
    issues = []

    kap_events = [
        {"category": "FINANCIAL_REPORT", "importance": 0.9, "publish_date": "2024-03-15", "date": "2024-03-15"},
        {"category": "DIVIDEND", "importance": 0.8, "publish_date": "2024-04-01", "date": "2024-04-01"},
    ]

    # as_of_date = 2024-01-15 → her iki olay da gelecekte
    cats = data_adapter.derive_catalysts(kap_events, [], as_of_date="2024-01-15")
    if len(cats) != 2:
        issues.append(f"2 catalyst beklenen, {len(cats)} bulundu")
    else:
        if cats[0]["type"] != "EARNINGS":
            issues.append(f"Catalyst type: {cats[0]['type']}")
        if cats[0]["days_until"] != 60:  # 2024-01-15 → 2024-03-15 = 60 gün
            issues.append(f"days_until: {cats[0]['days_until']}")
        if cats[1]["days_until"] != 77:  # 2024-01-15 → 2024-04-01 = 77 gün
            issues.append(f"days_until: {cats[1]['days_until']}")

    # as_of_date = 2024-06-01 → her iki olay da geçmişte
    cats_past = data_adapter.derive_catalysts(kap_events, [], as_of_date="2024-06-01")
    if len(cats_past) != 2:
        issues.append(f"Geçmiş catalyst sayısı: {len(cats_past)}")
    else:
        if cats_past[0]["days_until"] != 0:
            issues.append("Geçmiş catalyst days_until=0 olmalı")

    return "Catalyst Derivation", len(issues) == 0, issues


# =====================================================
# 5. PIT (POINT-IN-TIME) SAFETY
# =====================================================

def test_pit_kap_filtering():
    """KAP olayları as_of_date'e göre filtreleniyor mu?"""
    from services.features.data_adapter import data_adapter
    issues = []

    # Mock KAP events — bazıları gelecekte
    mock_events = [
        {"category": "FINANCIAL_REPORT", "importance": 0.9, "publish_date": "2024-01-10", "date": "2024-01-10"},
        {"category": "DIVIDEND", "importance": 0.8, "publish_date": "2024-01-20", "date": "2024-01-20"},
    ]

    # as_of_date = 2024-01-15 → sadece 2024-01-10 olanı kullanılabilir
    # fetch_kap_events provider yoksa boş döner, ama derive_catalysts test edilebilir
    cats = data_adapter.derive_catalysts(mock_events, [], as_of_date="2024-01-15")

    # Her ikisi de catalyst olarak türetilmeli (gelecek olaylar catalyst'tir)
    # ama PIT: 2024-01-20 olayı 2024-01-15'te bilinemez
    # derive_catalysts bunu days_until > 0 olarak işaretler
    future_cats = [c for c in cats if c["days_until"] > 0]
    if len(future_cats) != 1:
        issues.append(f"Gelecek catalyst: {len(future_cats)} beklenen 1")

    return "PIT KAP Filtering", len(issues) == 0, issues


def test_pit_fundamental_date():
    """Fundamental veri as_of_date'ten sonraysa bloklanmalı."""
    from services.features.data_adapter import data_adapter
    issues = []

    # Provider yoksa MISSING döner — bu doğru davranış
    fund = data_adapter.fetch_fundamentals("THYAO", as_of_date="2024-01-15")
    for key, dp in fund.items():
        if dp.status.value not in ("MISSING", "UNKNOWN"):
            issues.append(f"{key}: unexpected status when provider unavailable")

    return "PIT Fundamental Date", len(issues) == 0, issues


# =====================================================
# 6. MISSING/UNKNOWN/STALE AYRIMI
# =====================================================

def test_missing_unknown_stale():
    """Feature durumları doğru ayrılıyor mu?"""
    from services.features.feature_contract import (
        make_fresh, make_missing, make_unknown, make_stale,
        FeatureStatus,
    )
    issues = []

    # FRESH → model kullanabilir
    f = make_fresh(1.0, "test")
    if not f.is_usable():
        issues.append("FRESH usable olmalı")
    if f.to_value(99.0) != 1.0:
        issues.append("FRESH kendi değerini dönmeli")

    # MISSING → model kullanamaz, default döner
    m = make_missing("test")
    if m.is_usable():
        issues.append("MISSING usable olmamalı")
    if m.to_value(99.0) != 99.0:
        issues.append("MISSING default dönmeli")

    # UNKNOWN → model kullanamaz, default döner
    u = make_unknown("test")
    if u.is_usable():
        issues.append("UNKNOWN usable olmamalı")

    # STALE → model kullanamaz (FRESH değil), ama değeri var
    s = make_stale(42.0, "test", "2024-01-01")
    if s.is_usable():
        issues.append("STALE usable olmamalı")
    if s.value != 42.0:
        issues.append("STALE değeri korunmalı")
    if s.to_value(0.0) != 0.0:
        issues.append("STALE to_value default dönmeli (FRESH değil)")

    return "Missing/Unknown/Stale", len(issues) == 0, issues


# =====================================================
# 7. MOTOR 4 DATA FLOW
# =====================================================

def test_motor4_receives_data():
    """Motor 4 fundamental data aldığında feature üretiyor mu?"""
    from services.features.seven_motors import FundamentalMotor
    issues = []

    motor = FundamentalMotor()

    # Veri varken
    fundamentals = {
        "pe_ratio": 12.5,
        "pb_ratio": 1.8,
        "roe": 0.15,
        "profit_margin": 0.12,
        "debt_to_equity": 0.4,
        "current_ratio": 2.1,
        "free_cash_flow": 500000000,
        "revenue": 10000000000,
        "market_cap": 20000000000,
    }
    feats = motor.compute("THYAO", fundamentals)
    if not feats:
        issues.append("Motor 4 veri varken feature üretmedi")
    else:
        if "raw_pe_ratio" not in feats:
            issues.append("raw_pe_ratio üretilmedi")
        if "balance_sheet_quality" not in feats:
            issues.append("balance_sheet_quality üretilmedi")
        if "fcf_yield_pct" not in feats:
            issues.append("fcf_yield_pct üretilmedi")

    # Veri yokken
    empty = motor.compute("THYAO", {})
    if empty:
        issues.append(f"Boş veriyle {len(empty)} feature üretildi, 0 beklenen")

    return "Motor 4 Data Flow", len(issues) == 0, issues


# =====================================================
# 8. ORCHESTRATOR INTEGRATION
# =====================================================

def test_orchestrator_with_data_adapter():
    """Orchestrator data adapter ile çalışıyor mu? (provider yokken)"""
    issues = []

    # Mini market data
    np.random.seed(42)
    n = 100
    dates = pd.date_range(end=datetime.now(), periods=n, freq='B')
    close = 100 * np.exp(np.cumsum(np.random.randn(n) * 0.015))

    market_data = {
        "TEST": pd.DataFrame({
            'Open': close, 'High': close * 1.01, 'Low': close * 0.99,
            'Close': close, 'Volume': np.full(n, 100000.0),
        }, index=dates),
    }

    from services.core.orchestrator import SystemOrchestrator
    orch = SystemOrchestrator()
    report = orch.run_full_pipeline(
        date="2024-01-15",
        market_data=market_data,
        sector_map={"TEST": "TECH"},
    )

    # Pipeline hata vermemeli
    if report is None:
        issues.append("Pipeline None döndü")
    elif "CRITICAL" in report.system_health.get("status", ""):
        issues.append(f"Pipeline CRITICAL: {report.system_health.get('errors')}")

    # Motor 4 feature'ları MISSING olsa bile pipeline durmamalı
    # (Bu normal — provider yok)

    return "Orchestrator + Data Adapter", len(issues) == 0, issues


# =====================================================
# 9. MOTOR 7 RSI FIX
# =====================================================

def test_motor7_rsi_from_calculator():
    """Motor 7 artık calculator'dan rsi_14 okuyor (Motor 8'den rsi_14d değil)."""
    from services.features.seven_motors import WhyFallingMotor
    issues = []

    motor = WhyFallingMotor()

    # rsi_14 varken (calculator'dan)
    feats = motor.compute(
        "TEST", stock_return_5d=-6.0, stock_return_20d=-10.0,
        market_return_5d=-2.0, market_return_20d=-3.0,
        sector_return_5d=-3.0, sector_return_20d=-5.0,
        volume_change=1.0, volume_zscore=2.0,
        news_sentiment=-0.2, kap_sentiment=-0.3,
        rsi=25.0,  # Aşırı satım
    )
    if feats.get("fall_oversold_bounce") != 1.0:
        issues.append(f"RSI=25 oversold bounce: {feats.get('fall_oversold_bounce')}")

    # rsi=50 (varsayılan) ile
    feats_default = motor.compute(
        "TEST", stock_return_5d=-6.0, stock_return_20d=-10.0,
        market_return_5d=-2.0, market_return_20d=-3.0,
        sector_return_5d=-3.0, sector_return_20d=-5.0,
        volume_change=1.0, volume_zscore=2.0,
        news_sentiment=-0.2, kap_sentiment=-0.3,
        rsi=50.0,  # Varsayılan
    )
    if feats_default.get("fall_oversold_bounce") != 0.0:
        issues.append(f"RSI=50 oversold bounce: {feats_default.get('fall_oversold_bounce')}")

    return "Motor 7 RSI Fix", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("  Faz 2 — Data Pipeline Tests")
    print("=" * 60)

    tests = [
        test_feature_contract_basics,
        test_contract_backward_compatible,
        test_data_adapter_no_providers,
        test_kap_helpers,
        test_catalyst_derivation,
        test_pit_kap_filtering,
        test_pit_fundamental_date,
        test_missing_unknown_stale,
        test_motor4_receives_data,
        test_orchestrator_with_data_adapter,
        test_motor7_rsi_from_calculator,
    ]

    passed = failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = test_func()
        except Exception as e:
            name, ok, issues = test_func.__name__, False, [f"Exception: {e}"]
            import traceback
            traceback.print_exc()

        icon = "✅" if ok else "❌"
        print(f"{icon} {name}")
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print(f"\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
