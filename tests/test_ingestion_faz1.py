"""
ALPHA BIST — Ingestion Faz 1 Tests

Reconciliation, Point-in-Time, Deduplication, Incremental testleri.
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import sys
import os

from services.ingestion.reconciliation import SourceReconciler, ReconciliationResult
from services.ingestion.point_in_time import PointInTimeValidator
from services.ingestion.deduplication import EventDeduplicator
from services.ingestion.incremental import IncrementalFetcher


# =====================================================
# Reconciliation Tests
# =====================================================

@pytest.mark.asyncio
class TestSourceReconciler:
    """Cross-source reconciliation testleri."""

    async def test_single_source(self):
        """Tek kaynak — düşük kalite."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {"yfinance": 308.50})
        assert result.canonical_price == 308.50
        assert result.source == "yfinance"
        assert result.quality_score == 0.6
        assert len(result.warnings) > 0

    async def test_consistent_sources(self):
        """Tutarlı kaynaklar — yüksek kalite."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "yfinance": 308.50,
            "matriks": 308.50,
            "bist_official": 308.50,
        })
        assert result.conflict is False
        assert result.quality_score > 0.8
        assert result.source == "reconciled"

    async def test_small_deviation_no_conflict(self):
        """Küçük sapma — çakışma yok."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "yfinance": 308.50,
            "matriks": 308.60,  # %0.03 sapma
        })
        assert result.conflict is False

    async def test_large_deviation_conflict(self):
        """Büyük sapma — çakışma var."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "yfinance": 308.50,
            "matriks": 312.00,  # ~%1.1 sapma
        })
        assert result.conflict is True
        assert len(result.warnings) > 0

    async def test_weighted_canonical(self):
        """Ağırlıklı canonical price."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {
            "bist_official": 100.0,  # weight 1.0
            "yfinance": 110.0,       # weight 0.85
        })
        # Ağırlıklı ortalama: (100*1.0 + 110*0.85) / (1.0+0.85) = 193.5/1.85 ≈ 104.59
        assert 104.0 < result.canonical_price < 105.0

    async def test_empty_prices(self):
        """Boş fiyat listesi."""
        reconciler = SourceReconciler()
        result = await reconciler.reconcile_price("THYAO", {})
        assert result.canonical_price == 0.0
        assert result.quality_score == 0.0

    async def test_batch_reconcile(self):
        """Toplu uzlaştırma."""
        reconciler = SourceReconciler()
        results = await reconciler.reconcile_batch({
            "THYAO": {"yfinance": 308.50, "matriks": 308.50},
            "ASELS": {"yfinance": 381.00, "matriks": 381.00},
        })
        assert len(results) == 2
        assert "THYAO" in results
        assert "ASELS" in results

    async def test_quality_report(self):
        """Kalite raporu."""
        reconciler = SourceReconciler()
        results = await reconciler.reconcile_batch({
            "THYAO": {"yfinance": 308.50, "matriks": 308.50},
            "ASELS": {"yfinance": 381.00, "matriks": 385.00},  # Çakışma
        })
        report = reconciler.get_quality_report(results)
        assert report["total_tickers"] == 2
        assert "avg_quality_score" in report


# =====================================================
# Point-in-Time Tests
# =====================================================

class TestPointInTimeValidator:
    """Point-in-time validation testleri."""

    def test_market_price_15min_delay(self):
        """Market price 15dk gecikmeli."""
        pit = PointInTimeValidator()
        data_ts = datetime(2024, 1, 15, 10, 0, 0)  # 10:00'da veri
        query_ts = datetime(2024, 1, 15, 10, 10, 0)  # 10:10'da sorgu
        # 10:00 + 15dk = 10:15 → 10:10 < 10:15 → henüz bilinmiyor
        assert pit.is_available_at("market_price", data_ts, query_ts) is False

    def test_market_price_after_delay(self):
        """Market price gecikme sonrası biliniyor."""
        pit = PointInTimeValidator()
        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        query_ts = datetime(2024, 1, 15, 10, 20, 0)  # 20dk sonra
        assert pit.is_available_at("market_price", data_ts, query_ts) is True

    def test_kap_disclosure_immediate(self):
        """KAP açıklaması anında biliniyor."""
        pit = PointInTimeValidator()
        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        query_ts = datetime(2024, 1, 15, 10, 0, 1)  # 1 saniye sonra
        assert pit.is_available_at("kap_disclosure", data_ts, query_ts) is True

    def test_fundamental_next_day(self):
        """Bilanço ertesi gün biliniyor."""
        pit = PointInTimeValidator()
        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        query_ts = datetime(2024, 1, 16, 10, 0, 0)  # Ertesi gün
        assert pit.is_available_at("fundamental", data_ts, query_ts) is True

    def test_fundamental_same_day_unknown(self):
        """Bilanço aynı gün bilinmiyor."""
        pit = PointInTimeValidator()
        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        query_ts = datetime(2024, 1, 15, 15, 0, 0)  # Aynı gün
        assert pit.is_available_at("fundamental", data_ts, query_ts) is False

    def test_filter_available(self):
        """Filtreleme çalışır."""
        pit = PointInTimeValidator()
        data = [
            {"timestamp": "2024-01-15T10:00:00", "price": 100},
            {"timestamp": "2024-01-15T10:20:00", "price": 101},
            {"timestamp": "2024-01-15T10:05:00", "price": 99},
        ]
        query_ts = datetime(2024, 1, 15, 10, 10, 0)
        filtered = pit.filter_available(data, "market_price", query_ts)
        # 10:00 + 15dk = 10:15 → 10:10 < 10:15 → filtrelenir
        # 10:20 + 15dk = 10:35 → 10:10 < 10:35 → filtrelenir
        # 10:05 + 15dk = 10:20 → 10:10 < 10:20 → filtrelenir
        assert len(filtered) == 0

    def test_filter_available_with_later_query(self):
        """Geç sorgu ile filtreleme."""
        pit = PointInTimeValidator()
        data = [
            {"timestamp": "2024-01-15T10:00:00", "price": 100},
            {"timestamp": "2024-01-15T10:20:00", "price": 101},
        ]
        query_ts = datetime(2024, 1, 15, 10, 40, 0)
        filtered = pit.filter_available(data, "market_price", query_ts)
        # 10:00 + 15dk = 10:15 → 10:40 >= 10:15 → geçer
        # 10:20 + 15dk = 10:35 → 10:40 >= 10:35 → geçer
        assert len(filtered) == 2

    def test_validate_no_lookahead(self):
        """Look-ahead bias kontrolü."""
        pit = PointInTimeValidator()
        data = [
            {"timestamp": "2024-01-15T10:00:00", "price": 100},
            {"timestamp": "2024-01-15T10:30:00", "price": 101},  # Gelecek veri
        ]
        query_ts = datetime(2024, 1, 15, 10, 10, 0)
        report = pit.validate_no_lookahead(data, "market_price", query_ts)
        assert report["clean"] is False
        assert report["violation_count"] > 0

    def test_unknown_data_type(self):
        """Bilinmeyen veri tipi — anında kabul et."""
        pit = PointInTimeValidator()
        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        query_ts = datetime(2024, 1, 15, 10, 0, 1)
        assert pit.is_available_at("unknown_type", data_ts, query_ts) is True

    def test_set_custom_delay(self):
        """Özel gecikme tanımlama."""
        pit = PointInTimeValidator()
        pit.set_custom_delay("custom_type", timedelta(hours=2), "Custom delay")
        data_ts = datetime(2024, 1, 15, 10, 0, 0)
        query_ts = datetime(2024, 1, 15, 11, 0, 0)  # 1 saat sonra
        assert pit.is_available_at("custom_type", data_ts, query_ts) is False
        query_ts = datetime(2024, 1, 15, 12, 30, 0)  # 2.5 saat sonra
        assert pit.is_available_at("custom_type", data_ts, query_ts) is True


# =====================================================
# Deduplication Tests
# =====================================================

class TestEventDeduplicator:
    """Event deduplication testleri."""

    def test_unique_event(self):
        """Unique event — duplicate değil."""
        dedup = EventDeduplicator()
        event = {"event_type": "market_tick", "source": "yfinance", "ticker": "THYAO", "price": 308.50}
        assert dedup.is_duplicate(event) is False

    def test_duplicate_event(self):
        """Duplicate event tespit edilir."""
        dedup = EventDeduplicator()
        event = {"event_type": "market_tick", "source": "yfinance", "ticker": "THYAO", "price": 308.50}
        dedup.mark_seen(event)
        assert dedup.is_duplicate(event) is True

    def test_check_and_mark(self):
        """check_and_mark tek adımda çalışır."""
        dedup = EventDeduplicator()
        event = {"event_type": "market_tick", "source": "yfinance", "ticker": "THYAO", "price": 308.50}
        assert dedup.check_and_mark(event) is False  # İlk kez → unique
        assert dedup.check_and_mark(event) is True   # İkinci kez → duplicate

    def test_different_events_not_duplicate(self):
        """Farklı event'ler duplicate değil."""
        dedup = EventDeduplicator()
        event1 = {"event_type": "market_tick", "source": "yfinance", "ticker": "THYAO", "price": 308.50}
        event2 = {"event_type": "market_tick", "source": "yfinance", "ticker": "THYAO", "price": 309.00}
        dedup.mark_seen(event1)
        assert dedup.is_duplicate(event2) is False

    def test_different_ticker_not_duplicate(self):
        """Farklı ticker duplicate değil."""
        dedup = EventDeduplicator()
        event1 = {"event_type": "market_tick", "source": "yfinance", "ticker": "THYAO", "price": 308.50}
        event2 = {"event_type": "market_tick", "source": "yfinance", "ticker": "ASELS", "price": 308.50}
        dedup.mark_seen(event1)
        assert dedup.is_duplicate(event2) is False

    def test_stats(self):
        """İstatistikler doğru."""
        dedup = EventDeduplicator()
        event = {"event_type": "test", "source": "test", "ticker": "TEST", "price": 100}
        dedup.check_and_mark(event)
        dedup.check_and_mark(event)  # Duplicate
        stats = dedup.get_stats()
        assert stats["total_checked"] == 2
        assert stats["total_duplicates"] == 1
        assert stats["total_unique"] == 1

    def test_reset(self):
        """Sıfırlama çalışır."""
        dedup = EventDeduplicator()
        event = {"event_type": "test", "source": "test", "ticker": "TEST", "price": 100}
        dedup.mark_seen(event)
        dedup.reset()
        assert dedup.is_duplicate(event) is False


# =====================================================
# Incremental Fetcher Tests
# =====================================================

class TestIncrementalFetcher:
    """Incremental fetcher testleri."""

    def test_should_fetch_first_time(self):
        """İlk kez çekilmeli."""
        fetcher = IncrementalFetcher()
        assert fetcher.should_fetch("THYAO") is True

    def test_should_fetch_after_interval(self):
        """Aralık geçtikten sonra çekilmeli."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("THYAO")
        # Hemen sonra → çekilmemeli
        assert fetcher.should_fetch("THYAO", min_interval_seconds=60) is False

    def test_should_fetch_within_interval(self):
        """Aralık içinde → çekilmemeli."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("THYAO")
        assert fetcher.should_fetch("THYAO", min_interval_seconds=60) is False

    def test_mark_fetched_success(self):
        """Başarılı çekme işaretleme."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("THYAO", success=True)
        states = fetcher.get_all_states()
        assert "THYAO" in states
        assert states["THYAO"]["last_success"] is True

    def test_mark_fetched_error(self):
        """Hatalı çekme işaretleme."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("THYAO", success=False, error="timeout")
        states = fetcher.get_all_states()
        assert states["THYAO"]["last_success"] is False
        assert states["THYAO"]["last_error"] == "timeout"

    def test_get_since_default(self):
        """Varsayılan lookback."""
        fetcher = IncrementalFetcher(default_lookback_hours=2)
        since = fetcher.get_since("NEW_TICKER")
        # 2 saat öncesine yakın olmalı
        now = datetime.now(timezone.utc)
        assert (now - since).total_seconds() < 7200 + 10  # 2 saat + tolerans

    def test_get_since_after_fetch(self):
        """Çekme sonrası since güncellenir."""
        fetcher = IncrementalFetcher()
        before = datetime.now(timezone.utc)
        fetcher.mark_fetched("THYAO")
        after = datetime.now(timezone.utc)
        since = fetcher.get_since("THYAO")
        assert before <= since <= after

    def test_get_stale_tickers(self):
        """Eski ticker'ları bulur."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("FRESH", success=True)
        # STALE'ı çok önce çekilmiş gibi işaretle
        fetcher._states["STALE"] = fetcher._states.get("STALE") or type(fetcher._states.get("FRESH"))(
            ticker="STALE",
            last_fetch_time=time.time() - 7200,  # 2 saat önce
            fetch_count=1,
        )
        stale = fetcher.get_stale_tickers(max_age_seconds=3600)
        assert "STALE" in stale
        assert "FRESH" not in stale

    def test_stats(self):
        """İstatistikler doğru."""
        fetcher = IncrementalFetcher()
        fetcher.should_fetch("A")  # check
        fetcher.mark_fetched("A")
        fetcher.should_fetch("A", min_interval_seconds=60)  # skip
        stats = fetcher.get_stats()
        assert stats["total_checks"] == 2
        assert stats["total_fetches"] == 1
        assert stats["total_skipped"] == 1

    def test_reset(self):
        """Sıfırlama çalışır."""
        fetcher = IncrementalFetcher()
        fetcher.mark_fetched("THYAO")
        fetcher.reset("THYAO")
        assert fetcher.get_fetch_count("THYAO") == 0


# =====================================================
# Run Tests
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
