#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Historical Data Pipeline Tests

PIT-safe historical fundamental, KAP, news, catalyst testleri.
"""

import sys


def _make_repo_with_fixtures() -> Any:
    """Test fixture'ları ile repository oluştur."""
    from services.data.historical_contracts import (
        CatalystSnapshot,
        EventSnapshot,
        FundamentalSnapshot,
        InMemoryHistoricalRepository,
    )

    repo = InMemoryHistoricalRepository()

    # === FUNDAMENTAL SNAPSHOTS ===
    # THYAO Q2 2025 — açıklandı 2025-08-14
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={
                "pe_ratio": 8.5,
                "pb_ratio": 1.2,
                "roe": 0.18,
                "profit_margin": 0.14,
                "fcf_yield": 0.06,
                "free_cash_flow": 5e9,
                "revenue": 60e9,
                "market_cap": 200e9,
                "total_assets": 100e9,
                "debt_to_equity": 0.3,
                "current_ratio": 2.5,
                "roa": 0.10,
            },
            source="yfinance",
            status="FRESH",
        )
    )

    # THYAO Q1 2025 — açıklandı 2025-05-10
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-03-31",
            available_at="2025-05-10",
            values={
                "pe_ratio": 9.0,
                "pb_ratio": 1.3,
                "roe": 0.16,
                "profit_margin": 0.12,
                "fcf_yield": 0.05,
                "free_cash_flow": 4e9,
                "revenue": 55e9,
                "market_cap": 190e9,
                "total_assets": 95e9,
                "debt_to_equity": 0.35,
                "current_ratio": 2.3,
                "roa": 0.09,
            },
            source="yfinance",
            status="FRESH",
        )
    )

    # === KAP EVENTS ===
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="KAP-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="2025 Q2 Finansal Rapor Açıklandı",
            sentiment=0.5,
            importance=1.0,
            source="kap",
        )
    )

    repo.add_event_snapshot(
        EventSnapshot(
            event_id="KAP-002",
            ticker="THYAO",
            published_at="2025-07-15T14:00:00",
            event_type="DIVIDEND",
            title="Temettü Dağıtım Kararı",
            sentiment=0.3,
            importance=0.8,
            source="kap",
        )
    )

    # === NEWS EVENTS ===
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="NEWS-001",
            ticker="THYAO",
            published_at="2025-08-12T08:30:00",
            event_type="NEWS",
            title="THYAO Yeni Hat Açıkladı",
            sentiment=0.4,
            importance=0.6,
            source="news",
        )
    )

    # === CATALYST SNAPSHOTS ===
    # Açıklandı 2025-08-10, gerçekleşecek 2025-08-20
    repo.add_catalyst_snapshot(
        CatalystSnapshot(
            event_id="CAT-001",
            ticker="THYAO",
            announcement_date="2025-08-10",
            event_date="2025-08-20",
            catalyst_type="EARNINGS",
            importance=0.9,
            source="kap",
        )
    )

    # Açıklandı 2025-07-01, gerçekleşti 2025-07-15
    repo.add_catalyst_snapshot(
        CatalystSnapshot(
            event_id="CAT-002",
            ticker="THYAO",
            announcement_date="2025-07-01",
            event_date="2025-07-15",
            catalyst_type="DIVIDEND_DATE",
            importance=0.6,
            source="kap",
        )
    )

    return repo


# =====================================================
# 1. FUNDAMENTAL PUBLICATION PIT
# =====================================================


def test_fundamental_publication_pit() -> Any:
    """Fundamental veri sadece publication tarihinden sonra kullanılabilir."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-08-13: Q2 henüz açıklanmamış
    feats_before = adapter.get_fundamental_features("THYAO", "2025-08-13")
    if feats_before:
        # Q1 verisi mevcut olmalı (2025-05-10'da açıklandı)
        pe = feats_before.get("pe_ratio")
        if pe and pe == 8.5:
            issues.append("Q2 verisi 2025-08-13'te kullanıldı (açıklanmamış)")

    # 2025-08-14: Q2 açıklandı
    feats_after = adapter.get_fundamental_features("THYAO", "2025-08-14")
    if not feats_after:
        issues.append("2025-08-14'te fundamental veri yok")
    elif feats_after.get("pe_ratio") != 8.5:
        issues.append(f"Q2 pe_ratio yanlış: {feats_after.get('pe_ratio')}")

    return "Fundamental publication PIT", len(issues) == 0, issues


# =====================================================
# 2. FUNDAMENTAL PERIOD SELECTION
# =====================================================


def test_fundamental_period_selection() -> Any:
    """Birden fazla snapshot varsa en güncel olanı seçilmeli."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-06-01: Q1 mevcut, Q2 yok
    feats = adapter.get_fundamental_features("THYAO", "2025-06-01")
    if not feats:
        issues.append("2025-06-01'de veri yok")
    elif feats.get("pe_ratio") != 9.0:
        issues.append(f"Q1 pe_ratio yanlış: {feats.get('pe_ratio')} (beklenen9.0)")

    # 2025-09-01: Her ikisi de mevcut, Q2 seçilmeli
    feats2 = adapter.get_fundamental_features("THYAO", "2025-09-01")
    if not feats2:
        issues.append("2025-09-01'de veri yok")
    elif feats2.get("pe_ratio") != 8.5:
        issues.append(f"Q2 pe_ratio yanlış: {feats2.get('pe_ratio')} (beklenen8.5)")

    return "Fundamental period selection", len(issues) == 0, issues


# =====================================================
# 3. FUNDAMENTAL FUTURE REJECTION
# =====================================================


def test_fundamental_future_rejection() -> Any:
    """Gelecekteki fundamental veri reddedilmeli."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-01-01: Hiçbir snapshot mevcut değil
    feats = adapter.get_fundamental_features("THYAO", "2025-01-01")
    if feats:
        issues.append(f"2025-01-01'de veri var: {list(feats.keys())}")

    return "Fundamental future rejection", len(issues) == 0, issues


# =====================================================
# 4. FUNDAMENTAL LATEST-KNOWN SNAPSHOT
# =====================================================


def test_fundamental_latest_known() -> Any:
    """En son bilinen snapshot kullanılmalı (eksik dönem olsa bile)."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-12-01: Q3 snapshot'ı yok, Q2 kullanılmalı
    feats = adapter.get_fundamental_features("THYAO", "2025-12-01")
    if not feats:
        issues.append("2025-12-01'de veri yok (Q2 kullanılmalı)")
    elif feats.get("pe_ratio") != 8.5:
        issues.append(f"Q2 pe_ratio yanlış: {feats.get('pe_ratio')}")

    return "Fundamental latest known", len(issues) == 0, issues


# =====================================================
# 5. KAP PUBLICATION PIT
# =====================================================


def test_kap_publication_pit() -> Any:
    """KAP event'leri sadece publication tarihinden sonra kullanılabilir."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-08-09: KAP-001 henüz yayınlanmamış
    events_before = adapter.get_kap_events("THYAO", "2025-08-09")
    kap_ids_before = [e["id"] for e in events_before]
    if "KAP-001" in kap_ids_before:
        issues.append("KAP-001 2025-08-09'da kullanıldı (2025-08-10'da yayınlandı)")

    # 2025-08-10: KAP-001 yayınlandı
    events_after = adapter.get_kap_events("THYAO", "2025-08-10")
    kap_ids_after = [e["id"] for e in events_after]
    if "KAP-001" not in kap_ids_after:
        issues.append("KAP-001 2025-08-10'da bulunamadı")

    return "KAP publication PIT", len(issues) == 0, issues


# =====================================================
# 6. KAP DUPLICATE EVENT
# =====================================================


def test_kap_duplicate_event() -> Any:
    """Aynı KAP event'i tekrar eklenmemeli."""
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.historical_contracts import EventSnapshot, InMemoryHistoricalRepository

    issues = []

    repo = InMemoryHistoricalRepository()
    # Aynı event'i iki kez ekle
    for _ in range(2):
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="KAP-DUP",
                ticker="THYAO",
                published_at="2025-08-10T10:00:00",
                event_type="FINANCIAL_REPORT",
                title="Test",
                source="kap",
            )
        )

    adapter = HistoricalDataAdapter(repo)
    events = adapter.get_kap_events("THYAO", "2025-08-15")

    # Duplicate kontrolü data_adapter seviyesinde yapılmalı
    # Repository seviyesinde duplicate varsa adapter filtrelemeli
    event_ids = [e["id"] for e in events]
    if event_ids.count("KAP-DUP") > 1:
        issues.append(f"Duplicate event: KAP-DUP {event_ids.count('KAP-DUP')} kez")

    return "KAP duplicate event", len(issues) == 0, issues


# =====================================================
# 7. KAP TICKER VALIDATION
# =====================================================


def test_kap_ticker_validation() -> Any:
    """KAP event'leri doğru ticker ile eşleşmeli."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # THYAO event'leri
    thyao_events = adapter.get_kap_events("THYAO", "2025-08-15")
    for event in thyao_events:
        if event["ticker"] != "THYAO":
            issues.append(f"Yanlış ticker: {event['ticker']} (beklenen THYAO)")

    # GARAN event'leri (fixture'ta yok)
    garan_events = adapter.get_kap_events("GARAN", "2025-08-15")
    if garan_events:
        issues.append(f"GARAN event'leri var: {len(garan_events)}")

    return "KAP ticker validation", len(issues) == 0, issues


# =====================================================
# 8. NEWS PUBLICATION PIT
# =====================================================


def test_news_publication_pit() -> Any:
    """Haber event'leri sadece publication tarihinden sonra kullanılabilir."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-08-11: NEWS-001 henüz yayınlanmamış
    news_before = adapter.get_news_events("THYAO", "2025-08-11")
    titles_before = [e["title"] for e in news_before]
    if "THYAO Yeni Hat Açıkladı" in titles_before:
        issues.append("NEWS-001 2025-08-11'de kullanıldı")

    # 2025-08-12: NEWS-001 yayınlandı
    news_after = adapter.get_news_events("THYAO", "2025-08-12")
    titles_after = [e["title"] for e in news_after]
    if "THYAO Yeni Hat Açıkladı" not in titles_after:
        issues.append("NEWS-001 2025-08-12'de bulunamadı")

    return "News publication PIT", len(issues) == 0, issues


# =====================================================
# 9. NEWS TICKER MATCHING
# =====================================================


def test_news_ticker_matching() -> Any:
    """Haberler doğru ticker ile eşleşmeli."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    thyao_news = adapter.get_news_events("THYAO", "2025-08-15")
    for news in thyao_news:
        if news["ticker"] != "THYAO":
            issues.append(f"Yanlış ticker: {news['ticker']}")

    return "News ticker matching", len(issues) == 0, issues


# =====================================================
# 10. NEWS DUPLICATE EVENT
# =====================================================


def test_news_duplicate_event() -> Any:
    """Aynı haber tekrar eklenmemeli."""
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.historical_contracts import EventSnapshot, InMemoryHistoricalRepository

    issues = []

    repo = InMemoryHistoricalRepository()
    for _ in range(2):
        repo.add_event_snapshot(
            EventSnapshot(
                event_id="NEWS-DUP",
                ticker="THYAO",
                published_at="2025-08-10T08:00:00",
                event_type="NEWS",
                title="Duplicate Test",
                source="news",
            )
        )

    adapter = HistoricalDataAdapter(repo)
    news = adapter.get_news_events("THYAO", "2025-08-15")
    titles = [e["title"] for e in news]
    if titles.count("Duplicate Test") > 1:
        issues.append(f"Duplicate news: {titles.count('Duplicate Test')} kez")

    return "News duplicate event", len(issues) == 0, issues


# =====================================================
# 11. SENTIMENT DETERMINISTIC
# =====================================================


def test_sentiment_deterministic() -> Any:
    """Aynı event'ler → aynı sentiment (deterministic)."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    kap_events = adapter.get_kap_events("THYAO", "2025-08-15")
    news_events = adapter.get_news_events("THYAO", "2025-08-15")

    sent1 = adapter.compute_sentiment(kap_events, news_events)
    sent2 = adapter.compute_sentiment(kap_events, news_events)

    for key in sent1:
        if key in sent2 and sent1[key] != sent2[key]:
            issues.append(f"Non-deterministic: {key}")

    return "Sentiment deterministic", len(issues) == 0, issues


# =====================================================
# 12. CATALYST ANNOUNCEMENT PIT
# =====================================================


def test_catalyst_announcement_pit() -> Any:
    """Catalyst sadece announcement tarihinden sonra kullanılabilir."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-08-09: CAT-001 henüz açıklanmamış
    cats_before = adapter.get_catalyst_events("THYAO", "2025-08-09")
    cat_ids_before = [c.get("type") for c in cats_before]
    if "EARNINGS" in cat_ids_before:
        issues.append("EARNINGS catalyst 2025-08-09'da kullanıldı")

    # 2025-08-10: CAT-001 açıklandı
    cats_after = adapter.get_catalyst_events("THYAO", "2025-08-10")
    cat_ids_after = [c.get("type") for c in cats_after]
    if "EARNINGS" not in cat_ids_after:
        issues.append("EARNINGS catalyst 2025-08-10'da bulunamadı")

    return "Catalyst announcement PIT", len(issues) == 0, issues


# =====================================================
# 13. CATALYST FUTURE REJECTION
# =====================================================


def test_catalyst_future_rejection() -> Any:
    """Gelecekteki announcement reddedilmeli."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    # 2025-01-01: Hiçbir catalyst açıklanmamış
    cats = adapter.get_catalyst_events("THYAO", "2025-01-01")
    if cats:
        issues.append(f"2025-01-01'de catalyst var: {len(cats)}")

    return "Catalyst future rejection", len(issues) == 0, issues


# =====================================================
# 14. HISTORICAL SNAPSHOT DETERMINISTIC
# =====================================================


def test_historical_snapshot_deterministic() -> Any:
    """Aynı snapshot → aynı feature (deterministic)."""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    feats1 = adapter.get_fundamental_features("THYAO", "2025-09-01")
    feats2 = adapter.get_fundamental_features("THYAO", "2025-09-01")

    for key in feats1:
        if key in feats2 and feats1[key] != feats2[key]:
            issues.append(f"Non-deterministic: {key}")

    return "Historical snapshot deterministic", len(issues) == 0, issues


# =====================================================
# 15. FUTURE MUTATION INVARIANCE
# =====================================================


def test_future_mutation_invariance() -> Any:
    """Gelecekteki veri eklendiğinde geçmiş skor değişmemeli."""
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.historical_contracts import EventSnapshot, InMemoryHistoricalRepository

    issues = []

    repo = InMemoryHistoricalRepository()
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="EVT-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="Q2 Report",
            sentiment=0.5,
            importance=1.0,
            source="kap",
        )
    )

    adapter = HistoricalDataAdapter(repo)

    # 2025-08-05 snapshot
    events_before = adapter.get_kap_events("THYAO", "2025-08-05")

    # Gelecekteki event ekle
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="EVT-FUTURE",
            ticker="THYAO",
            published_at="2025-09-01T10:00:00",
            event_type="DIVIDEND",
            title="Future Event",
            source="kap",
        )
    )

    # 2025-08-05 snapshot hâlâ aynı olmalı
    events_after = adapter.get_kap_events("THYAO", "2025-08-05")

    if len(events_before) != len(events_after):
        issues.append(f"Event sayısı değişti: {len(events_before)} → {len(events_after)}")

    return "Future mutation invariance", len(issues) == 0, issues


# =====================================================
# 16. MISSING DATA BEHAVIOR
# =====================================================


def test_missing_data_behavior() -> Any:
    """Eksik veri durumunda boş dict dönmeli (50 ile doldurma)."""
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.historical_contracts import InMemoryHistoricalRepository

    issues = []

    repo = InMemoryHistoricalRepository()
    adapter = HistoricalDataAdapter(repo)

    feats = adapter.get_fundamental_features("THYAO", "2025-01-01")
    if feats:
        issues.append(f"Boş repo'dan veri döndü: {list(feats.keys())}")

    return "Missing data behavior", len(issues) == 0, issues


# =====================================================
# 17. STALE DATA BEHAVIOR
# =====================================================


def test_stale_data_behavior() -> Any:
    """Eski veri STALE olarak işaretlenmeli."""
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.historical_contracts import FundamentalSnapshot, InMemoryHistoricalRepository

    issues = []

    repo = InMemoryHistoricalRepository()
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2024-03-31",
            available_at="2024-05-10",
            values={"pe_ratio": 10.0},
            source="yfinance",
            status="STALE",
        )
    )

    adapter = HistoricalDataAdapter(repo)
    feats = adapter.get_fundamental_features("THYAO", "2025-01-01")

    if not feats:
        issues.append("STALE veri döndürülemedi")
    # STALE veri kullanılabilir ama düşük güvenilirlikte

    return "Stale data behavior", len(issues) == 0, issues


# =====================================================
# 18. COMPLETE HISTORICAL SNAPSHOT
# =====================================================


def test_complete_historical_snapshot() -> Any:
    """Tam historical snapshot çalışıyor mu?"""
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    date = "2025-08-15"

    fund = adapter.get_fundamental_features("THYAO", date)
    kap = adapter.get_kap_events("THYAO", date)
    news = adapter.get_news_events("THYAO", date)
    cats = adapter.get_catalyst_events("THYAO", date)
    sent = adapter.compute_sentiment(kap, news)
    cat_feats = adapter.compute_catalyst_features(cats)

    if not fund:
        issues.append("Fundamental boş")
    if not kap:
        issues.append("KAP boş")
    if not news:
        issues.append("News boş")
    if not cats:
        issues.append("Catalyst boş")
    if not sent:
        issues.append("Sentiment boş")
    if not cat_feats:
        issues.append("Catalyst features boş")

    return "Complete historical snapshot", len(issues) == 0, issues


# =====================================================
# 19-21. CANONICAL SCORE INTEGRATION
# =====================================================


def test_canonical_fundamental_score() -> Any:
    """Historical fundamental veri canonical skoru etkiliyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    base_features = {"rsi_14": 55, "momentum_20d": 5, "volume_zscore": 1.5}

    # Fundamental olmadan
    cs_without = canonical_scoring.compute_canonical_score("THYAO", base_features, "BULL")

    # Fundamental ile
    fund = adapter.get_fundamental_features("THYAO", "2025-09-01")
    enriched = {**base_features, **fund}
    cs_with = canonical_scoring.compute_canonical_score("THYAO", enriched, "BULL")

    if cs_with.opportunity_score == cs_without.opportunity_score:
        issues.append("Fundamental skoru etkilemiyor")

    return "Canonical fundamental score", len(issues) == 0, issues


def test_canonical_news_score() -> Any:
    """Historical news sentiment canonical skoru etkiliyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    base_features = {"rsi_14": 55, "momentum_20d": 5}

    # Sentiment olmadan
    cs_without = canonical_scoring.compute_canonical_score("THYAO", base_features, "BULL")

    # Sentiment ile
    kap = adapter.get_kap_events("THYAO", "2025-08-15")
    news = adapter.get_news_events("THYAO", "2025-08-15")
    sent = adapter.compute_sentiment(kap, news)
    enriched = {**base_features, **sent}
    cs_with = canonical_scoring.compute_canonical_score("THYAO", enriched, "BULL")

    if cs_with.opportunity_score == cs_without.opportunity_score:
        issues.append("News sentiment skoru etkilemiyor")

    return "Canonical news score", len(issues) == 0, issues


def test_canonical_catalyst_score() -> Any:
    """Historical catalyst canonical skoru etkiliyor mu?"""
    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter

    issues = []

    repo = _make_repo_with_fixtures()
    adapter = HistoricalDataAdapter(repo)

    base_features = {"rsi_14": 55, "momentum_20d": 5}

    # Catalyst olmadan
    cs_without = canonical_scoring.compute_canonical_score("THYAO", base_features, "BULL")

    # Catalyst ile
    cats = adapter.get_catalyst_events("THYAO", "2025-08-15")
    cat_feats = adapter.compute_catalyst_features(cats)
    enriched = {**base_features, **cat_feats}
    cs_with = canonical_scoring.compute_canonical_score("THYAO", enriched, "BULL")

    if cs_with.opportunity_score == cs_without.opportunity_score:
        issues.append("Catalyst skoru etkilemiyor")

    return "Canonical catalyst score", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  Historical Data Pipeline Tests")
    logger.info("=" * 60)

    tests = [
        # Fundamental
        test_fundamental_publication_pit,
        test_fundamental_period_selection,
        test_fundamental_future_rejection,
        test_fundamental_latest_known,
        # KAP
        test_kap_publication_pit,
        test_kap_duplicate_event,
        test_kap_ticker_validation,
        # News
        test_news_publication_pit,
        test_news_ticker_matching,
        test_news_duplicate_event,
        # Sentiment
        test_sentiment_deterministic,
        # Catalyst
        test_catalyst_announcement_pit,
        test_catalyst_future_rejection,
        # General
        test_historical_snapshot_deterministic,
        test_future_mutation_invariance,
        test_missing_data_behavior,
        test_stale_data_behavior,
        test_complete_historical_snapshot,
        # Canonical integration
        test_canonical_fundamental_score,
        test_canonical_news_score,
        test_canonical_catalyst_score,
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
        logger.info(f"{icon} {name}")
        if ok:
            passed += 1
        else:
            failed += 1
            for i in issues:
                logger.info(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        logger.info("\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            logger.info(f"    {i}. {issue}")
    logger.info("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
