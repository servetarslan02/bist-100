#!/usr/bin/env python3
"""
ALPHA BIST — Provider Integration Tests

Gerçek provider entegrasyon testleri — unit testlerden ayrı katman.

Bu testler:
- Network erişimi gerektirir
- Provider yoksa otomatik skip edilir
- Unit testleri ASLA etkilemez

Kapsam:
1. Fundamental → Motor 4 (yfinance)
2. KAP → Motor 5 (kap.org.tr API)
3. News → Motor 5 (RSS feeds)
4. Catalyst → Motor 6
5. PIT filtreleme gerçek veri üzerinde
6. Availability timestamp doğrulama
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import structlog
logger = structlog.get_logger()


# =====================================================
# PROVIDER ERİŞİM KONTROL
# =====================================================

def _check_yfinance():
    """yfinance erişilebilir mi?"""
    try:
        import yfinance as yf
        t = yf.Ticker("GARAN.IS")
        info = t.info
        return info is not None and "regularMarketPrice" in info
    except Exception:
        return False


def _check_kap_api():
    """KAP API erişilebilir mi?"""
    try:
        import socket
        socket.setdefaulttimeout(5)
        s = socket.create_connection(("www.kap.org.tr", 443), timeout=5)
        s.close()
        return True
    except Exception:
        return False


def _check_rss_feeds():
    """RSS feed'leri erişilebilir mi?"""
    try:
        import socket
        socket.setdefaulttimeout(5)
        s = socket.create_connection(("www.bloomberght.com", 443), timeout=5)
        s.close()
        return True
    except Exception:
        return False


# =====================================================
# 1. FUNDAMENTAL → MOTOR 4
# =====================================================

def test_fundamental_real_data():
    """Gerçek yfinance verisi ile fundamental pipeline."""
    if not _check_yfinance():
        return "Fundamental (Real)", None, ["yfinance erişilebilir değil — SKIP"]

    from services.features.data_adapter import data_adapter
    from services.features.seven_motors import FundamentalMotor
    issues = []

    # Gerçek veri çek
    fund_features = data_adapter.fetch_fundamentals("GARAN")
    usable = {k: v for k, v in fund_features.items() if v.is_usable()}

    if not usable:
        issues.append("GARAN fundamental verisi boş (usable yok)")
        return "Fundamental (Real)", False, issues

    # Motor 4'e besle
    motor = FundamentalMotor()
    raw = {k: v.to_value() for k, v in fund_features.items() if v.is_usable()}
    motor_features = motor.compute("GARAN", raw)

    if not motor_features:
        issues.append("Motor 4 feature üretmedi (gerçek veriyle)")
    else:
        if "raw_pe_ratio" not in motor_features and "pe_ratio" in raw:
            issues.append("raw_pe_ratio üretilmedi")
        if "balance_sheet_quality" not in motor_features:
            issues.append("balance_sheet_quality üretilmedi")

    # PIT kontrolü: gelecek tarihte veri bloklanmalı
    future_fund = data_adapter.fetch_fundamentals("GARAN", as_of_date="2020-01-01")
    future_usable = [v for v in future_fund.values() if v.is_usable()]
    # 2020 tarihindeki veri STALE veya MISSING olmalı (veri 2024+ tarihli)
    stale_count = sum(1 for v in future_fund.values()
                      if v.status.value in ("STALE", "MISSING", "UNKNOWN"))
    if stale_count < len(future_fund) * 0.5:
        issues.append(f"PIT: gelecek tarihte çok fazla usable veri ({stale_count}/{len(future_fund)} stale/missing)")

    return "Fundamental (Real)", len(issues) == 0, issues


# =====================================================
# 2. KAP → MOTOR 5
# =====================================================

def test_kap_real_data():
    """Gerçek KAP API verisi ile KAP pipeline."""
    if not _check_kap_api():
        return "KAP (Real)", None, ["KAP API erişilebilir değil — SKIP"]

    from services.features.data_adapter import data_adapter
    issues = []

    data_adapter.reset_duplicates()

    # Gerçek KAP verisi çek (son 30 gün)
    kap_events = data_adapter.fetch_kap_events("GARAN", as_of_date="2026-08-17", limit=10)

    # KAP API erişilebilir ama veri dönmeyebilir (API yapısı değişmiş olabilir)
    # Bu durumda test skip sayılır
    if kap_events is None:
        return "KAP (Real)", None, ["KAP API yanıt vermedi — SKIP"]

    # Zorunlu alan kontrolü
    for event in kap_events:
        if not event.get("title"):
            issues.append(f"KAP event title eksik: {event}")
        if not event.get("publish_date"):
            issues.append(f"KAP event publish_date eksik: {event}")
        if event.get("ticker") and event["ticker"].upper() != "GARAN":
            issues.append(f"KAP event yanlış ticker: {event['ticker']} (beklenen GARAN)")

    # Duplicate kontrolü
    event_ids = [e.get("title", "") + ":" + e.get("publish_date", "") for e in kap_events]
    if len(event_ids) != len(set(event_ids)):
        issues.append("KAP duplicate event tespit edildi")

    return "KAP (Real)", len(issues) == 0, issues


# =====================================================
# 3. NEWS → MOTOR 5
# =====================================================

def test_news_real_data():
    """Gerçek RSS verisi ile news pipeline."""
    if not _check_rss_feeds():
        return "News (Real)", None, ["RSS feed'ler erişilebilir değil — SKIP"]

    from services.features.data_adapter import data_adapter
    issues = []

    data_adapter.reset_duplicates()

    # Gerçek haber verisi çek
    news_events = data_adapter.fetch_news_events("GARAN", as_of_date="2026-08-17", limit=10)

    if news_events is None:
        return "News (Real)", None, ["News provider yanıt vermedi — SKIP"]

    # Zorunlu alan kontrolü
    for event in news_events:
        if not event.get("title"):
            issues.append(f"News event title eksik")
        if not event.get("ticker"):
            issues.append(f"News event ticker eksik: {event.get('title', '')[:30]}")

    # Duplicate kontrolü
    titles = [e.get("title", "") for e in news_events]
    if len(titles) != len(set(titles)):
        issues.append("Duplicate news event tespit edildi")

    return "News (Real)", len(issues) == 0, issues


# =====================================================
# 4. CATALYST → MOTOR 6
# =====================================================

def test_catalyst_real_data():
    """Gerçek KAP/haber verisinden katalizör türetme."""
    if not _check_kap_api():
        return "Catalyst (Real)", None, ["KAP API erişilebilir değil — SKIP"]

    from services.features.data_adapter import data_adapter
    issues = []

    data_adapter.reset_duplicates()

    kap_events = data_adapter.fetch_kap_events("GARAN", as_of_date="2026-08-17", limit=10)
    news_events = data_adapter.fetch_news_events("GARAN", as_of_date="2026-08-17", limit=5)

    if kap_events is None:
        return "Catalyst (Real)", None, ["KAP verisi alınamadı — SKIP"]

    catalysts = data_adapter.derive_catalysts(
        kap_events or [], news_events or [], as_of_date="2026-08-17"
    )

    # Katalizör yapısı kontrolü
    for cat in catalysts:
        if "type" not in cat:
            issues.append(f"Catalyst type eksik: {cat}")
        if "importance" not in cat:
            issues.append(f"Catalyst importance eksik: {cat}")
        if cat.get("importance", 0) < 0 or cat.get("importance", 0) > 1:
            issues.append(f"Catalyst importance geçersiz: {cat.get('importance')}")

    return "Catalyst (Real)", len(issues) == 0, issues


# =====================================================
# 5. PIT FİLTRELEME (GERÇEK VERİ)
# =====================================================

def test_pit_real_data():
    """PIT filtreleme gerçek veri üzerinde."""
    if not _check_yfinance():
        return "PIT (Real)", None, ["yfinance erişilebilir değil — SKIP"]

    from services.features.data_adapter import data_adapter
    from services.features.feature_contract import FeatureStatus
    issues = []

    # Bugünkü veri → FRESH/STALE/UNKNOWN olmalı
    today = data_adapter.fetch_fundamentals("GARAN")
    today_usable = sum(1 for v in today.values() if v.status == FeatureStatus.FRESH)

    # 2020 tarihi → verilerin çoğu STALE/MISSING olmalı
    past = data_adapter.fetch_fundamentals("GARAN", as_of_date="2020-01-01")
    past_missing = sum(1 for v in past.values()
                       if v.status in (FeatureStatus.MISSING, FeatureStatus.UNKNOWN, FeatureStatus.STALE))

    if past_missing < len(past) * 0.5:
        issues.append(f"PIT filtreleme yetersiz: 2020 tarihinde {past_missing}/{len(past)} missing/stale")

    return "PIT (Real)", len(issues) == 0, issues


# =====================================================
# 6. AVAILABILITY TIMESTAMP
# =====================================================

def test_availability_timestamp():
    """Veri timestamp'leri doğru mu?"""
    if not _check_yfinance():
        return "Timestamp (Real)", None, ["yfinance erişilebilir değil — SKIP"]

    from services.features.data_adapter import data_adapter
    from datetime import datetime, timezone
    issues = []

    fund = data_adapter.fetch_fundamentals("GARAN")

    for key, dp in fund.items():
        if dp.status.value == "FRESH" and dp.availability_ts:
            try:
                ts = datetime.fromisoformat(dp.availability_ts.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if ts > now:
                    issues.append(f"{key}: availability_ts gelecekte: {dp.availability_ts}")
            except ValueError:
                issues.append(f"{key}: availability_ts parse edilemedi: {dp.availability_ts}")

    return "Timestamp (Real)", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

def run_all():
    print("=" * 60)
    print("  Provider Integration Tests")
    print("  (Network erişimi gerektirir)")
    print("=" * 60)

    tests = [
        test_fundamental_real_data,
        test_kap_real_data,
        test_news_real_data,
        test_catalyst_real_data,
        test_pit_real_data,
        test_availability_timestamp,
    ]

    passed = failed = skipped = 0
    all_issues = []

    for test_func in tests:
        try:
            result = test_func()
            if len(result) == 3:
                name, ok, issues = result
            else:
                name, ok, issues = test_func.__name__, False, ["Unknown result format"]
        except Exception as e:
            name, ok, issues = test_func.__name__, False, [f"Exception: {e}"]
            import traceback
            traceback.print_exc()

        if ok is None:
            icon = "⏭️"
            skipped += 1
        elif ok:
            icon = "✅"
            passed += 1
        else:
            icon = "❌"
            failed += 1

        print(f"{icon} {name}")
        for i in issues:
            print(f"   {'⏭️' if ok is None else '❌'} {i}")
            if ok is not None:
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {passed} geçti, {failed} başarısız, {skipped} atlandı")
    if all_issues:
        print(f"\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"    {i}. {issue}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
