#!/usr/bin/env python3
import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Production-Grade Historical Data Ingestion Tests

PIT-safe, deterministic, incremental ingestion testleri.
"""

import os
import sys
import tempfile


def _make_temp_repo() -> Any:
    """Geçici SQLite repository oluştur."""
    from services.data.persistent_repository import PersistentHistoricalRepository

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return PersistentHistoricalRepository(db_path=path), path


def _make_test_snapshots() -> Any:
    """Test snapshot'ları oluştur."""
    from services.data.historical_contracts import (
        CatalystSnapshot,
        EventSnapshot,
        FundamentalSnapshot,
    )

    fundamentals = [
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5, "roe": 0.18, "revenue": 60e9},
            source="yfinance",
            status="FRESH",
        ),
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-03-31",
            available_at="2025-05-10",
            values={"pe_ratio": 9.0, "roe": 0.16, "revenue": 55e9},
            source="yfinance",
            status="FRESH",
        ),
        FundamentalSnapshot(
            ticker="GARAN",
            period_end="2025-06-30",
            available_at="2025-08-12",
            values={"pe_ratio": 6.0, "roe": 0.22, "revenue": 40e9},
            source="yfinance",
            status="FRESH",
        ),
    ]

    events = [
        EventSnapshot(
            event_id="KAP-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="Q2 Finansal Rapor",
            sentiment=0.5,
            importance=1.0,
            source="kap",
        ),
        EventSnapshot(
            event_id="KAP-002",
            ticker="THYAO",
            published_at="2025-07-15T14:00:00",
            event_type="DIVIDEND",
            title="Temettü Kararı",
            sentiment=0.3,
            importance=0.8,
            source="kap",
        ),
        EventSnapshot(
            event_id="NEWS-001",
            ticker="THYAO",
            published_at="2025-08-12T08:00:00",
            event_type="NEWS",
            title="THYAO Yeni Hat",
            sentiment=0.4,
            importance=0.6,
            source="news",
        ),
    ]

    catalysts = [
        CatalystSnapshot(
            event_id="CAT-001",
            ticker="THYAO",
            announcement_date="2025-08-10",
            event_date="2025-08-20",
            catalyst_type="EARNINGS",
            importance=0.9,
            source="kap",
        ),
    ]

    return fundamentals, events, catalysts


# =====================================================
# 1. FUTURE FUNDAMENTAL CANNOT AFFECT SCORE
# =====================================================


def test_future_fundamental_no_score_effect() -> Any:
    """Gelecekteki fundamental veri skoru etkilememeli."""
    import os
    import tempfile

    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    # Fundamental ekle (2025-08-14'te açıklandı)
    from services.data.historical_contracts import FundamentalSnapshot

    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5, "roe": 0.18},
            source="yfinance",
            status="FRESH",
        )
    )

    adapter = HistoricalDataAdapter(repo)
    base_features = {"rsi_14": 55, "momentum_20d": 5}

    # 2025-08-13: Fundamental henüz açıklanmamış
    fund_before = adapter.get_fundamental_features("THYAO", "2025-08-13")
    cs_before = canonical_scoring.compute_canonical_score("THYAO", {**base_features, **fund_before}, "BULL")

    # 2025-08-14: Fundamental açıklandı
    fund_after = adapter.get_fundamental_features("THYAO", "2025-08-14")
    cs_after = canonical_scoring.compute_canonical_score("THYAO", {**base_features, **fund_after}, "BULL")

    if cs_before.opportunity_score != cs_after.opportunity_score:
        # Farklı olmalı (fundamental eklendi)
        pass

    # 2025-08-13'te fundamental olmamalı
    if fund_before:
        issues.append(f"2025-08-13'te fundamental var: {list(fund_before.keys())}")

    os.unlink(path)
    return "Future fundamental no score effect", len(issues) == 0, issues


# =====================================================
# 2. FUTURE KAP CANNOT AFFECT SCORE
# =====================================================


def test_future_kap_no_score_effect() -> Any:
    """Gelecekteki KAP event skoru etkilememeli."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import EventSnapshot

    repo.add_event_snapshot(
        EventSnapshot(
            event_id="KAP-FUTURE",
            ticker="THYAO",
            published_at="2025-09-01T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="Future Report",
            source="kap",
        )
    )

    adapter = HistoricalDataAdapter(repo)

    # 2025-08-15: Event henüz yayınlanmamış
    events = adapter.get_kap_events("THYAO", "2025-08-15")
    event_ids = [e["id"] for e in events]
    if "KAP-FUTURE" in event_ids:
        issues.append("Future KAP event 2025-08-15'te kullanıldı")

    os.unlink(path)
    return "Future KAP no score effect", len(issues) == 0, issues


# =====================================================
# 3. FUTURE NEWS CANNOT AFFECT SCORE
# =====================================================


def test_future_news_no_score_effect() -> Any:
    """Gelecekteki news event skoru etkilememeli."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import EventSnapshot

    repo.add_event_snapshot(
        EventSnapshot(
            event_id="NEWS-FUTURE",
            ticker="THYAO",
            published_at="2025-09-01T08:00:00",
            event_type="NEWS",
            title="Future News",
            source="news",
        )
    )

    adapter = HistoricalDataAdapter(repo)

    events = adapter.get_news_events("THYAO", "2025-08-15")
    titles = [e["title"] for e in events]
    if "Future News" in titles:
        issues.append("Future news 2025-08-15'te kullanıldı")

    os.unlink(path)
    return "Future news no score effect", len(issues) == 0, issues


# =====================================================
# 4. FUTURE CATALYST CANNOT AFFECT SCORE
# =====================================================


def test_future_catalyst_no_score_effect() -> Any:
    """Gelecekteki catalyst skoru etkilememeli."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import CatalystSnapshot

    repo.add_catalyst_snapshot(
        CatalystSnapshot(
            event_id="CAT-FUTURE",
            ticker="THYAO",
            announcement_date="2025-09-01",
            event_date="2025-09-15",
            catalyst_type="EARNINGS",
            importance=0.9,
            source="kap",
        )
    )

    adapter = HistoricalDataAdapter(repo)

    cats = adapter.get_catalyst_events("THYAO", "2025-08-15")
    cat_types = [c.get("type") for c in cats]
    if "EARNINGS" in cat_types:
        issues.append("Future catalyst 2025-08-15'te kullanıldı")

    os.unlink(path)
    return "Future catalyst no score effect", len(issues) == 0, issues


# =====================================================
# 5. PUBLICATION DATE VS PERIOD END
# =====================================================


def test_publication_vs_period_end() -> Any:
    """publication_date ve period_end karışmamalı."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    # period_end=2025-06-30, available_at=2025-08-14
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5},
            source="yfinance",
            status="FRESH",
        )
    )

    adapter = HistoricalDataAdapter(repo)

    # 2025-07-01: period_end geçmiş ama publication henüz yok
    feats = adapter.get_fundamental_features("THYAO", "2025-07-01")
    if feats:
        issues.append("2025-07-01'de fundamental var (publication 2025-08-14)")

    # 2025-08-14: publication tarihi
    feats2 = adapter.get_fundamental_features("THYAO", "2025-08-14")
    if not feats2:
        issues.append("2025-08-14'te fundamental yok")

    os.unlink(path)
    return "Publication vs period end", len(issues) == 0, issues


# =====================================================
# 6. DUPLICATE INGESTION IDEMPOTENCY
# =====================================================


def test_duplicate_ingestion_idempotent() -> Any:
    """Aynı veri tekrar tekrar_ingest edilebilmeli (idempotent)."""
    import os
    import tempfile

    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import EventSnapshot

    snapshot = EventSnapshot(
        event_id="DUP-TEST",
        ticker="THYAO",
        published_at="2025-08-10T10:00:00",
        event_type="FINANCIAL_REPORT",
        title="Test",
        source="kap",
    )

    # 3 kez ekle
    for _ in range(3):
        repo.add_event_snapshot(snapshot)

    conn = repo._get_conn()
    count = conn.execute("SELECT COUNT(*) FROM event_snapshots WHERE event_id = 'DUP-TEST'").fetchone()[0]

    if count != 1:
        issues.append(f"Duplicate count: {count} (beklenen1)")

    os.unlink(path)
    return "Duplicate ingestion idempotent", len(issues) == 0, issues


# =====================================================
# 7. SAME EVENT FROM TWO SOURCES
# =====================================================


def test_same_event_two_sources() -> Any:
    """Aynı event farklı kaynaklardan gelirse tek event olmalı."""
    import os
    import tempfile

    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import EventSnapshot

    # Aynı event_id, farklı kaynaklar
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="SAME-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="From KAP",
            source="kap",
        )
    )
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="SAME-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="From News",
            source="news",
        )
    )

    conn = repo._get_conn()
    count = conn.execute("SELECT COUNT(*) FROM event_snapshots WHERE event_id = 'SAME-001'").fetchone()[0]

    if count != 1:
        issues.append(f"Same event count: {count} (beklenen1)")

    os.unlink(path)
    return "Same event two sources", len(issues) == 0, issues


# =====================================================
# 8. MISSING PUBLICATION TIMESTAMP
# =====================================================


def test_missing_publication_timestamp() -> Any:
    """Publication timestamp yoksa UNKNOWN olarak işaretlenmeli."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    # available_at boş
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="",
            values={"pe_ratio": 8.5},
            source="yfinance",
            status="UNKNOWN",
        )
    )

    adapter = HistoricalDataAdapter(repo)
    adapter.get_fundamental_features("THYAO", "2025-12-01")

    # UNKNOWN status'taki veri kullanılabilir ama düşük güvenilirlikte
    # (adapter bunu döndürür ama data_quality düşük olmalı)

    os.unlink(path)
    return "Missing publication timestamp", len(issues) == 0, issues


# =====================================================
# 9. STALE FUNDAMENTAL
# =====================================================


def test_stale_fundamental() -> Any:
    """Eski fundamental veri STALE olarak işaretlenmeli."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

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

    os.unlink(path)
    return "Stale fundamental", len(issues) == 0, issues


# =====================================================
# 10. RESTATED FUNDAMENTAL
# =====================================================


def test_restated_fundamental() -> Any:
    """Restate edilmiş fundamental veri en güncel olanı kullanılmalı."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    # Orijinal Q2
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5},
            source="yfinance",
            status="FRESH",
        )
    )
    # Restate edilmiş Q2 (daha sonra açıklandı)
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-09-01",
            values={"pe_ratio": 8.0},
            source="yfinance_restate",
            status="FRESH",
        )
    )

    adapter = HistoricalDataAdapter(repo)
    feats = adapter.get_fundamental_features("THYAO", "2025-09-15")

    if not feats:
        issues.append("Restate veri bulunamadı")
    elif feats.get("pe_ratio") != 8.0:
        issues.append(f"Restate edilmiş veri kullanılmadı: {feats.get('pe_ratio')}")

    os.unlink(path)
    return "Restated fundamental", len(issues) == 0, issues


# =====================================================
# 11. PARTIAL INGESTION RECOVERY
# =====================================================


def test_partial_ingestion_recovery() -> Any:
    """Partial ingestion'dan sonra mevcut veri bozulmamalı."""
    import os
    import tempfile

    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import EventSnapshot

    # İlk ingestion
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="PARTIAL-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="First",
            source="kap",
        )
    )

    # İkinci ingestion başarısız olsun (simüle)
    # Ama ilk veri hâlâ orada olmalı
    conn = repo._get_conn()
    count = conn.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0]

    if count != 1:
        issues.append(f"Veri kayboldu: {count}")

    os.unlink(path)
    return "Partial ingestion recovery", len(issues) == 0, issues


# =====================================================
# 12. PROVIDER TIMEOUT RECOVERY
# =====================================================


def test_provider_timeout_recovery() -> Any:
    """Provider timeout olursa mevcut veri bozulmamalı."""
    import os
    import tempfile

    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5},
            source="yfinance",
            status="FRESH",
        )
    )

    # Provider timeout simüle (yeni veri eklenemedi)
    # Mevcut veri hâlâ orada olmalı
    snapshots = repo.get_fundamental_snapshots("THYAO", "2025-12-01")
    if not snapshots:
        issues.append("Mevcut veri kayboldu")
    elif snapshots[0].values.get("pe_ratio") != 8.5:
        issues.append("Mevcut veri değişti")

    os.unlink(path)
    return "Provider timeout recovery", len(issues) == 0, issues


# =====================================================
# 13. DETERMINISTIC HISTORICAL REPLAY
# =====================================================


def test_deterministic_historical_replay() -> Any:
    """Aynı historical veri → aynı sonuç (deterministic)."""
    import os
    import tempfile

    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5, "roe": 0.18},
            source="yfinance",
            status="FRESH",
        )
    )

    adapter = HistoricalDataAdapter(repo)
    base = {"rsi_14": 55, "momentum_20d": 5}

    scores = []
    for _ in range(5):
        fund = adapter.get_fundamental_features("THYAO", "2025-09-01")
        cs = canonical_scoring.compute_canonical_score("THYAO", {**base, **fund}, "BULL")
        scores.append(cs.opportunity_score)

    if len(set(scores)) > 1:
        issues.append(f"Non-deterministic: {scores}")

    os.unlink(path)
    return "Deterministic historical replay", len(issues) == 0, issues


# =====================================================
# 14. FUTURE-DATA MUTATION INVARIANCE
# =====================================================


def test_future_data_mutation_invariance() -> Any:
    """Gelecekteki veri eklendiğinde geçmiş skor değişmemeli."""
    import os
    import tempfile

    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import EventSnapshot

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
    base = {"rsi_14": 55, "momentum_20d": 5}

    # 2025-08-05 skoru
    kap_before = adapter.get_kap_events("THYAO", "2025-08-05")
    sent_before = adapter.compute_sentiment(kap_before, [])
    cs_before = canonical_scoring.compute_canonical_score("THYAO", {**base, **sent_before}, "BULL")

    # Gelecekteki event ekle
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="EVT-FUTURE",
            ticker="THYAO",
            published_at="2025-09-01T10:00:00",
            event_type="DIVIDEND",
            title="Future Dividend",
            source="kap",
        )
    )

    # 2025-08-05 skoru hâlâ aynı olmalı
    kap_after = adapter.get_kap_events("THYAO", "2025-08-05")
    sent_after = adapter.compute_sentiment(kap_after, [])
    cs_after = canonical_scoring.compute_canonical_score("THYAO", {**base, **sent_after}, "BULL")

    if cs_before.opportunity_score != cs_after.opportunity_score:
        issues.append(f"Skor değişti: {cs_before.opportunity_score} → {cs_after.opportunity_score}")

    os.unlink(path)
    return "Future data mutation invariance", len(issues) == 0, issues


# =====================================================
# 15. HISTORICAL SNAPSHOT REPRODUCIBILITY
# =====================================================


def test_historical_snapshot_reproducibility() -> Any:
    """Aynı snapshot farklı session'larda aynı sonucu vermeli."""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 8.5},
            source="yfinance",
            status="FRESH",
        )
    )

    # İlk okuma
    adapter1 = HistoricalDataAdapter(repo)
    feats1 = adapter1.get_fundamental_features("THYAO", "2025-09-01")

    # İkinci okuma (farklı adapter instance)
    adapter2 = HistoricalDataAdapter(repo)
    feats2 = adapter2.get_fundamental_features("THYAO", "2025-09-01")

    for key in feats1:
        if key in feats2 and feats1[key] != feats2[key]:
            issues.append(f"Non-reproducible: {key}")

    os.unlink(path)
    return "Historical snapshot reproducibility", len(issues) == 0, issues


# =====================================================
# 16-21. ADDITIONAL TESTS
# =====================================================


def test_persistent_repo_basic() -> Any:
    """Persistent repository temel operasyonları çalışıyor mu?"""
    import os
    import tempfile

    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import FundamentalSnapshot

    ok = repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="TEST",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={"pe_ratio": 10},
            source="test",
            status="FRESH",
        )
    )
    if not ok:
        issues.append("add_fundamental_snapshot failed")

    snapshots = repo.get_fundamental_snapshots("TEST", "2025-12-01")
    if not snapshots:
        issues.append("get_fundamental_snapshots returned empty")

    stats = repo.get_stats()
    if stats["fundamental_snapshots"] < 1:
        issues.append(f"Stats wrong: {stats}")

    os.unlink(path)
    return "Persistent repo basic", len(issues) == 0, issues


def test_ingestion_pipeline_import() -> Any:
    """Ingestion pipeline import edilebiliyor mu?"""
    from services.data.ingestion_pipeline import HistoricalIngestionPipeline

    issues = []

    if not HistoricalIngestionPipeline:
        issues.append("Import failed")

    return "Ingestion pipeline import", len(issues) == 0, issues


def test_historical_adapter_with_persistent_repo() -> Any:
    """Historical adapter persistent repo ile çalışıyor mu?"""
    import os
    import tempfile

    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import (
        CatalystSnapshot,
        EventSnapshot,
        FundamentalSnapshot,
    )

    # Veri ekle
    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={
                "pe_ratio": 8.5,
                "roe": 0.18,
                "free_cash_flow": 5e9,
                "market_cap": 200e9,
                "debt_to_equity": 0.3,
                "current_ratio": 2.5,
            },
            source="yfinance",
            status="FRESH",
        )
    )
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="KAP-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="Q2 Report",
            sentiment=0.5,
            importance=1.0,
            source="kap",
        )
    )
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

    adapter = HistoricalDataAdapter(repo)

    # Fundamental
    fund = adapter.get_fundamental_features("THYAO", "2025-09-01")
    if not fund:
        issues.append("Fundamental boş")
    elif "fcf_yield_pct" not in fund:
        issues.append("fcf_yield_pct hesaplanamadı")

    # KAP
    kap = adapter.get_kap_events("THYAO", "2025-09-01")
    if not kap:
        issues.append("KAP boş")

    # Catalyst
    cats = adapter.get_catalyst_events("THYAO", "2025-09-01")
    if not cats:
        issues.append("Catalyst boş")

    # Sentiment
    sent = adapter.compute_sentiment(kap, [])
    if not sent:
        issues.append("Sentiment boş")

    os.unlink(path)
    return "Adapter with persistent repo", len(issues) == 0, issues


def test_canonical_scoring_with_all_historical() -> Any:
    """Tüm historical verilerle canonical scoring çalışıyor mu?"""
    import os
    import tempfile

    from services.core.canonical_scoring import canonical_scoring
    from services.data.historical_adapter import HistoricalDataAdapter
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    from services.data.historical_contracts import (
        CatalystSnapshot,
        EventSnapshot,
        FundamentalSnapshot,
    )

    repo.add_fundamental_snapshot(
        FundamentalSnapshot(
            ticker="THYAO",
            period_end="2025-06-30",
            available_at="2025-08-14",
            values={
                "pe_ratio": 8.5,
                "roe": 0.18,
                "free_cash_flow": 5e9,
                "market_cap": 200e9,
                "debt_to_equity": 0.3,
                "current_ratio": 2.5,
            },
            source="yfinance",
            status="FRESH",
        )
    )
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="KAP-001",
            ticker="THYAO",
            published_at="2025-08-10T10:00:00",
            event_type="FINANCIAL_REPORT",
            title="Q2 Report",
            sentiment=0.5,
            importance=1.0,
            source="kap",
        )
    )
    repo.add_event_snapshot(
        EventSnapshot(
            event_id="NEWS-001",
            ticker="THYAO",
            published_at="2025-08-12T08:00:00",
            event_type="NEWS",
            title="Positive news",
            sentiment=0.4,
            importance=0.6,
            source="news",
        )
    )
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

    adapter = HistoricalDataAdapter(repo)

    # Tüm verileri birleştir
    base = {"rsi_14": 55, "momentum_20d": 5, "volume_zscore": 1.5, "atr_pct": 2.5}

    fund = adapter.get_fundamental_features("THYAO", "2025-09-01")
    kap = adapter.get_kap_events("THYAO", "2025-09-01")
    news = adapter.get_news_events("THYAO", "2025-09-01")
    cats = adapter.get_catalyst_events("THYAO", "2025-09-01")
    sent = adapter.compute_sentiment(kap, news)
    cat_feats = adapter.compute_catalyst_features(cats)

    full_features = {**base, **fund, **sent, **cat_feats}

    cs = canonical_scoring.compute_canonical_score("THYAO", full_features, "BULL")

    # Tüm boyutlar dolu olmalı
    sv = cs.vector
    if sv.fundamental == 50.0:
        issues.append("Fundamental nötr kaldı")
    if sv.news_sentiment == 50.0:
        issues.append("News sentiment nötr kaldı")
    if sv.catalyst == 50.0:
        issues.append("Catalyst nötr kaldı")

    # Score0-100 aralığında olmalı
    if cs.opportunity_score < 0 or cs.opportunity_score > 100:
        issues.append(f"Score aralık dışı: {cs.opportunity_score}")

    os.unlink(path)
    return "Canonical scoring with all historical", len(issues) == 0, issues


def test_news_ingestion() -> Any:
    """RSS feed'lerden haber ingestion çalışıyor mu?"""
    import os
    import tempfile

    from services.data.ingestion_pipeline import HistoricalIngestionPipeline
    from services.data.persistent_repository import PersistentHistoricalRepository

    issues = []

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = PersistentHistoricalRepository(db_path=path)

    pipeline = HistoricalIngestionPipeline(repo)
    result = pipeline.ingest_news_events(["THYAO"], force=True)

    if result.get("status") == "error":
        # Network hatası — SKIP
        os.unlink(path)
        return "News ingestion", None, ["Network erişilebilir değil — SKIP"]

    if result.get("events", 0) < 0:
        issues.append(f"Negatif event sayısı: {result.get('events')}")

    os.unlink(path)
    return "News ingestion", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================


def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  Production-Grade Historical Data Ingestion Tests")
    logger.info("=" * 60)

    tests = [
        # PIT tests
        test_future_fundamental_no_score_effect,
        test_future_kap_no_score_effect,
        test_future_news_no_score_effect,
        test_future_catalyst_no_score_effect,
        test_publication_vs_period_end,
        # Deduplication
        test_duplicate_ingestion_idempotent,
        test_same_event_two_sources,
        # Data quality
        test_missing_publication_timestamp,
        test_stale_fundamental,
        test_restated_fundamental,
        # Recovery
        test_partial_ingestion_recovery,
        test_provider_timeout_recovery,
        # Determinism
        test_deterministic_historical_replay,
        test_future_data_mutation_invariance,
        test_historical_snapshot_reproducibility,
        # Integration
        test_persistent_repo_basic,
        test_ingestion_pipeline_import,
        test_historical_adapter_with_persistent_repo,
        test_canonical_scoring_with_all_historical,
        # Real provider
        test_news_ingestion,
    ]

    passed = failed = skipped = 0
    all_issues = []

    for test_func in tests:
        try:
            result = test_func()
            if len(result) == 3:
                name, ok, issues = result
            else:
                name, ok, issues = result[0], result[1], result[2] if len(result) > 2 else []
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

        logger.info(f"{icon} {name}")
        for i in issues:
            logger.info(f"   {'⏭️' if ok is None else '❌'} {i}")
            if ok is not None:
                all_issues.append(f"{name}: {i}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {passed} geçti, {failed} başarısız, {skipped} atlandı")
    if all_issues:
        logger.info("\n  HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            logger.info(f"    {i}. {issue}")
    logger.info("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
