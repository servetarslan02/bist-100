"""
ALPHA BIST — Scanner Modules Test Suite v1.0

Tüm yeni scanner modülleri için test'ler:
- Deduplication
- Adaptive Scan Scheduler
- Scan Persistence
- Performance Tracker
- Scan Alerts
- Custom Filters
- Scan API
"""

import os
import tempfile
from datetime import UTC, datetime

import pytest

# =====================================================
# DEDUPLICATION TESTS
# =====================================================

class TestScanDeduplicator:
    """Deduplication testleri."""

    def setup_method(self):
        from services.scanner.deduplicator import ScanDeduplicator
        self.dedup = ScanDeduplicator(cooldown_seconds=5)

    def test_first_scan_allowed(self):
        assert self.dedup.should_scan("THYAO") is True

    def test_cooldown_blocks(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=70)
        assert self.dedup.should_scan("THYAO") is False

    def test_cooldown_expires(self):
        from services.scanner.deduplicator import ScanDeduplicator
        dedup = ScanDeduplicator(cooldown_seconds=0)  # 0 saniye cooldown
        dedup.should_scan("THYAO")
        dedup.record_scan("THYAO", score=70)
        assert dedup.should_scan("THYAO") is True

    def test_force_scan_bypasses_cooldown(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=70)
        assert self.dedup.should_scan("THYAO") is False

        self.dedup.force_scan("THYAO")
        assert self.dedup.should_scan("THYAO") is True

    def test_force_scan_batch(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=70)
        self.dedup.should_scan("GARAN")
        self.dedup.record_scan("GARAN", score=60)

        self.dedup.force_scan_batch(["THYAO", "GARAN"])
        assert self.dedup.should_scan("THYAO") is True
        assert self.dedup.should_scan("GARAN") is True

    def test_stats(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=70)
        self.dedup.should_scan("THYAO")  # Blocked

        stats = self.dedup.get_stats()
        assert stats["total_checks"] == 2
        assert stats["total_blocked"] == 1
        assert stats["tracked_tickers"] == 1

    def test_cooldown_remaining(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=70)
        remaining = self.dedup.get_cooldown_remaining("THYAO")
        assert remaining > 0

    def test_last_scan_info(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=75, signal="MOMENTUM")
        info = self.dedup.get_last_scan_info("THYAO")
        assert info is not None
        assert info["last_score"] == 75
        assert info["last_signal"] == "MOMENTUM"

    def test_set_cooldown(self):
        self.dedup.set_cooldown(10)
        assert self.dedup._cooldown == 10

    def test_clear(self):
        self.dedup.should_scan("THYAO")
        self.dedup.record_scan("THYAO", score=70)
        self.dedup.clear()
        assert self.dedup.get_stats()["tracked_tickers"] == 0


# =====================================================
# ADAPTIVE SCAN SCHEDULER TESTS
# =====================================================

class TestAdaptiveScanScheduler:
    """Adaptive scheduler testleri."""

    def setup_method(self):
        from services.scanner.scan_scheduler import AdaptiveScanScheduler
        self.scheduler = AdaptiveScanScheduler(base_interval=60)

    def test_default_interval(self):
        interval = self.scheduler.get_scan_interval()
        assert interval > 0

    def test_high_volatility_reduces_interval(self):
        self.scheduler.update_market_state(volatility=0.10)
        low_vol_interval = self.scheduler.get_scan_interval()

        self.scheduler.update_market_state(volatility=0.40)
        high_vol_interval = self.scheduler.get_scan_interval()

        assert high_vol_interval < low_vol_interval

    def test_panic_regime_reduces_interval(self):
        self.scheduler.update_market_state(regime="RANGE")
        range_interval = self.scheduler.get_scan_interval()

        self.scheduler.update_market_state(regime="PANIC")
        panic_interval = self.scheduler.get_scan_interval()

        assert panic_interval < range_interval

    def test_event_reduces_interval(self):
        self.scheduler.update_market_state(has_event=False)
        normal_interval = self.scheduler.get_scan_interval()

        self.scheduler.update_market_state(has_event=True)
        event_interval = self.scheduler.get_scan_interval()

        assert event_interval < normal_interval

    def test_interval_bounds(self):
        # Minimum
        self.scheduler.update_market_state(volatility=1.0, regime="PANIC", has_event=True)
        interval = self.scheduler.get_scan_interval()
        assert interval >= 10

        # Maximum
        self.scheduler.update_market_state(volatility=0.05, regime="LOW-VOLATILITY")
        interval = self.scheduler.get_scan_interval()
        assert interval <= 300

    def test_scan_mode(self):
        mode = self.scheduler.get_scan_mode()
        assert mode.value in ["CONTINUOUS", "SCHEDULED", "EVENT_DRIVEN", "PAUSED", "MANUAL"]

    def test_trigger_event_scan(self):
        self.scheduler.trigger_event_scan(["THYAO"])
        assert self.scheduler._has_recent_event is True

    def test_stats(self):
        stats = self.scheduler.get_stats()
        assert "running" in stats
        assert "mode" in stats
        assert "current_interval_seconds" in stats

    def test_volatility_scales(self):
        from services.scanner.scan_scheduler import AdaptiveScanScheduler
        s = AdaptiveScanScheduler()

        assert s._get_volatility_scale(0.05) == 2.0   # very_low → yavaş
        assert s._get_volatility_scale(0.20) == 1.0   # normal
        assert s._get_volatility_scale(0.40) == 0.25  # very_high → hızlı


# =====================================================
# SCAN PERSISTENCE TESTS
# =====================================================

class TestScanPersistence:
    """Scan persistence testleri."""

    def setup_method(self):
        from services.scanner.scan_persistence import ScanPersistence, ScanResultRecord
        self.db_path = tempfile.mktemp(suffix=".db")
        self.persistence = ScanPersistence(db_path=self.db_path)
        self.ScanResultRecord = ScanResultRecord

    def teardown_method(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_save_and_retrieve(self):
        record = self.ScanResultRecord(
            scan_id="test_1",
            scan_type="batch",
            ticker="THYAO",
            score=75.5,
            signal="MOMENTUM",
            direction="LONG",
            confidence=0.8,
            tier=2,
            regime="BULL",
            price=250.0,
            volume=1000000,
            features={"rsi": 65, "momentum": 5.2},
            timestamp=datetime.now(UTC).isoformat(),
        )
        self.persistence.save_scan_result(record)

        history = self.persistence.get_scan_history("THYAO", days=1)
        assert len(history) == 1
        assert history[0]["ticker"] == "THYAO"
        assert history[0]["score"] == 75.5

    def test_save_batch_results(self):
        results = [
            {"ticker": "THYAO", "score": 75, "signal": "MOMENTUM", "direction": "LONG"},
            {"ticker": "GARAN", "score": 65, "signal": "BREAKOUT", "direction": "LONG"},
        ]
        self.persistence.save_batch_results("batch", results, regime="BULL")

        stats = self.persistence.get_scan_stats(scan_type="batch", days=1)
        assert stats["total_records"] == 2

    def test_get_scan_stats(self):
        # Kaydet
        for i in range(5):
            record = self.ScanResultRecord(
                scan_id=f"test_{i}",
                scan_type="batch",
                ticker=f"TICK{i}",
                score=50 + i * 10,
                signal="MOMENTUM" if i % 2 == 0 else "",
                direction="LONG",
                confidence=0.5,
                tier=1,
                regime="RANGE",
                price=100.0,
                volume=500000,
                features={},
                timestamp=datetime.now(UTC).isoformat(),
            )
            self.persistence.save_scan_result(record)

        stats = self.persistence.get_scan_stats(scan_type="batch", days=1)
        assert stats["total_records"] == 5
        assert stats["signals_generated"] == 3  # 3 tane sinyal var

    def test_get_top_scanned_tickers(self):
        # Aynı hisseyi birden fazla kez kaydet
        for i in range(3):
            record = self.ScanResultRecord(
                scan_id=f"test_{i}",
                scan_type="batch",
                ticker="THYAO",
                score=70 + i,
                signal="MOMENTUM",
                direction="LONG",
                confidence=0.7,
                tier=1,
                regime="RANGE",
                price=250.0,
                volume=1000000,
                features={},
                timestamp=datetime.now(UTC).isoformat(),
            )
            self.persistence.save_scan_result(record)

        top = self.persistence.get_top_scanned_tickers(days=1, limit=10)
        assert len(top) > 0
        assert top[0]["ticker"] == "THYAO"
        assert top[0]["scan_count"] == 3


# =====================================================
# PERFORMANCE TRACKER TESTS
# =====================================================

class TestScanPerformanceTracker:
    """Performance tracker testleri."""

    def setup_method(self):
        from services.scanner.performance_tracker import ScanPerformanceTracker
        self.tracker = ScanPerformanceTracker()

    def test_record_scan(self):
        self.tracker.record_scan(
            scan_type="batch",
            tickers_scanned=800,
            opportunities_found=50,
            signals_generated=5,
            duration_ms=1500.0,
            regime="BULL",
        )
        stats = self.tracker.get_stats()
        assert stats["total_scans"] == 1

    def test_stats_by_scan_type(self):
        self.tracker.record_scan("batch", 800, 50, 5, 1500.0, "BULL")
        self.tracker.record_scan("live", 1, 0, 0, 50.0, "BULL")
        self.tracker.record_scan("event", 10, 3, 1, 200.0, "BULL")

        batch_stats = self.tracker.get_stats("batch")
        assert batch_stats["total_scans"] == 1

        live_stats = self.tracker.get_stats("live")
        assert live_stats["total_scans"] == 1

    def test_regime_performance(self):
        self.tracker.record_scan("batch", 800, 50, 5, 1500.0, "BULL")
        self.tracker.record_scan("batch", 800, 30, 3, 1200.0, "BEAR")

        regime_perf = self.tracker.get_regime_performance()
        assert "BULL" in regime_perf
        assert "BEAR" in regime_perf

    def test_signal_accuracy(self):
        from services.scanner.performance_tracker import SignalOutcome
        self.tracker.record_signal_outcome(SignalOutcome(
            ticker="THYAO", signal_type="MOMENTUM", direction="LONG",
            score=80, confidence=0.8, entry_price=250.0,
            entry_time=datetime.now(UTC).isoformat(),
            exit_price=260.0, return_pct=4.0, correct=True,
        ))
        self.tracker.record_signal_outcome(SignalOutcome(
            ticker="GARAN", signal_type="BREAKOUT", direction="LONG",
            score=70, confidence=0.7, entry_price=100.0,
            entry_time=datetime.now(UTC).isoformat(),
            exit_price=95.0, return_pct=-5.0, correct=False,
        ))

        accuracy = self.tracker.get_signal_accuracy()
        assert accuracy["total_signals"] == 2
        assert accuracy["correct_signals"] == 1

    def test_top_performing_filters(self):
        from services.scanner.performance_tracker import SignalOutcome
        for i in range(5):
            self.tracker.record_signal_outcome(SignalOutcome(
                ticker=f"T{i}", signal_type="MOMENTUM", direction="LONG",
                score=80, confidence=0.8, entry_price=100.0,
                entry_time=datetime.now(UTC).isoformat(),
                exit_price=105.0, return_pct=5.0, correct=True,
            ))

        top = self.tracker.get_top_performing_filters()
        assert len(top) > 0
        assert top[0]["signal_type"] == "MOMENTUM"

    def test_summary(self):
        self.tracker.record_scan("batch", 800, 50, 5, 1500.0, "BULL")
        summary = self.tracker.get_summary()
        assert "total_scans" in summary


# =====================================================
# SCAN ALERTS TESTS
# =====================================================

class TestScanAlertManager:
    """Scan alert testleri."""

    def setup_method(self):
        from services.scanner.scan_alerts import ScanAlertManager
        self.manager = ScanAlertManager()

    def test_high_score_alert(self):
        results = [{"ticker": "THYAO", "score": 85, "signal": "MOMENTUM", "direction": "LONG"}]
        alerts = self.manager.check_scan_results(results)
        assert any(a.alert_type.value == "HIGH_SCORE" for a in alerts)

    def test_very_high_score_alert(self):
        results = [{"ticker": "THYAO", "score": 95, "signal": "MOMENTUM", "direction": "LONG"}]
        alerts = self.manager.check_scan_results(results)
        severity_alerts = [a for a in alerts if a.severity.value == "WARNING"]
        assert len(severity_alerts) > 0

    def test_new_signal_alert(self):
        # İlk tarama — sinyal yok
        results1 = [{"ticker": "THYAO", "score": 70, "signal": "", "direction": "NEUTRAL"}]
        self.manager.check_scan_results(results1)

        # İkinci tarama — yeni sinyal
        results2 = [{"ticker": "THYAO", "score": 75, "signal": "BREAKOUT", "direction": "LONG"}]
        alerts = self.manager.check_scan_results(results2)
        assert any(a.alert_type.value == "NEW_SIGNAL" for a in alerts)

    def test_volume_anomaly_alert(self):
        results = [{"ticker": "THYAO", "score": 60, "signal": "", "direction": "NEUTRAL",
                    "volume_zscore": 5.0}]
        alerts = self.manager.check_scan_results(results)
        assert any(a.alert_type.value == "ANOMALY" for a in alerts)

    def test_no_alert_low_score(self):
        results = [{"ticker": "THYAO", "score": 40, "signal": "", "direction": "NEUTRAL"}]
        alerts = self.manager.check_scan_results(results)
        assert len(alerts) == 0

    def test_callback_called(self):
        callback_called = []
        self.manager.register_callback(lambda a: callback_called.append(a))

        results = [{"ticker": "THYAO", "score": 85, "signal": "MOMENTUM", "direction": "LONG"}]
        self.manager.check_scan_results(results)
        assert len(callback_called) > 0

    def test_alert_summary(self):
        results = [{"ticker": "THYAO", "score": 85, "signal": "MOMENTUM", "direction": "LONG"}]
        self.manager.check_scan_results(results)

        summary = self.manager.get_alert_summary()
        assert summary["total_alerts"] > 0


# =====================================================
# CUSTOM FILTERS TESTS
# =====================================================

class TestCustomFilterEngine:
    """Custom filter testleri."""

    def setup_method(self):
        from services.scanner.custom_filters import CustomFilter, CustomFilterEngine
        self.engine = CustomFilterEngine()
        self.CustomFilter = CustomFilter

    def test_min_volume_filter(self):
        results = [
            {"ticker": "THYAO", "score": 80, "volume": 500000, "price": 250.0},
            {"ticker": "SMALL", "score": 90, "volume": 50000, "price": 10.0},  # Düşük hacim
        ]
        filtered, log = self.engine.apply_filters(results)
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "THYAO"

    def test_min_price_filter(self):
        results = [
            {"ticker": "THYAO", "score": 80, "price": 250.0, "volume": 500000},
            {"ticker": "PENNY", "score": 90, "price": 0.50, "volume": 500000},
        ]
        filtered, log = self.engine.apply_filters(results)
        assert len(filtered) == 1

    def test_custom_filter_added(self):
        self.engine.add_filter(self.CustomFilter(
            name="test_filter",
            description="Test filtre",
            condition=lambda r: r.get("score", 0) > 60,
            action="exclude",
        ))

        results = [
            {"ticker": "THYAO", "score": 80, "price": 250.0, "volume": 500000},
            {"ticker": "LOW", "score": 50, "price": 100.0, "volume": 500000},
        ]
        filtered, log = self.engine.apply_filters(results)
        assert len(filtered) == 1
        assert filtered[0]["ticker"] == "THYAO"

    def test_score_adjustment(self):
        self.engine.add_filter(self.CustomFilter(
            name="bonus",
            description="Bonus",
            condition=lambda r: r.get("score", 0) > 70,
            action="adjust_score",
            score_adjustment=10.0,
        ))

        results = [{"ticker": "THYAO", "score": 80, "price": 250.0, "volume": 500000}]
        filtered, log = self.engine.apply_filters(results)
        # Score adjustment uygulanmalı
        assert len(filtered) == 1
        assert filtered[0].get("score_adjustment", 0) == 10.0 or filtered[0]["score"] == 90

    def test_enable_disable_filter(self):
        self.engine.enable_filter("min_volume", enabled=False)
        results = [{"ticker": "SMALL", "score": 90, "volume": 50000, "price": 10.0}]
        filtered, log = self.engine.apply_filters(results)
        assert len(filtered) == 1  # Filtre devre dışı

    def test_get_filters(self):
        filters = self.engine.get_filters()
        assert len(filters) > 0
        assert any(f["name"] == "min_volume" for f in filters)

    def test_filter_stats(self):
        results = [
            {"ticker": "THYAO", "score": 80, "price": 250.0, "volume": 500000},
            {"ticker": "SMALL", "score": 90, "price": 0.50, "volume": 50000},
        ]
        stats = self.engine.get_filter_stats(results)
        assert "min_volume" in stats
        assert "min_price" in stats


# =====================================================
# SCAN API TESTS
# =====================================================

class TestScanAPI:
    """Scan API testleri."""

    def setup_method(self):
        from services.scanner.scan_api import ScanAPI
        self.api = ScanAPI()

    def test_get_status(self):
        status = self.api.get_status()
        assert "timestamp" in status
        assert "scheduler" in status
        assert "deduplicator" in status

    def test_get_results(self):
        results = self.api.get_results(limit=10)
        assert "timestamp" in results
        assert "total_results" in results

    def test_get_performance(self):
        perf = self.api.get_performance()
        assert "timestamp" in perf
        assert "tracker" in perf

    def test_get_alerts(self):
        alerts = self.api.get_alerts(limit=10)
        assert "timestamp" in alerts
        assert "summary" in alerts

    def test_get_tiers(self):
        tiers = self.api.get_tiers()
        assert "timestamp" in tiers
        assert "summary" in tiers

    def test_get_filters(self):
        filters = self.api.get_filters()
        assert "timestamp" in filters
        assert "filters" in filters

    def test_get_full_dashboard(self):
        dashboard = self.api.get_full_dashboard()
        assert "timestamp" in dashboard
        assert "status" in dashboard
        assert "results" in dashboard
        assert "performance" in dashboard


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestScannerIntegration:
    """Entegrasyon testleri."""

    def test_dedup_with_scanner(self):
        """Deduplication scanner ile entegrasyon."""
        from services.scanner.deduplicator import ScanDeduplicator
        dedup = ScanDeduplicator(cooldown_seconds=5)

        # İlk tarama
        assert dedup.should_scan("THYAO") is True
        dedup.record_scan("THYAO", score=75)

        # İkinci tarama — blok
        assert dedup.should_scan("THYAO") is False

        # Event force scan
        dedup.force_scan("THYAO")
        assert dedup.should_scan("THYAO") is True

    def test_alert_with_filter(self):
        """Alert sistemi filtre ile entegrasyon."""
        from services.scanner.custom_filters import CustomFilterEngine
        from services.scanner.scan_alerts import ScanAlertManager

        alert_mgr = ScanAlertManager()
        filter_eng = CustomFilterEngine()

        # Düşük hacimli hisseyi filtrele
        results = [
            {"ticker": "THYAO", "score": 85, "signal": "MOMENTUM", "direction": "LONG",
             "price": 250.0, "volume": 500000},
            {"ticker": "SMALL", "score": 95, "signal": "BREAKOUT", "direction": "LONG",
             "price": 10.0, "volume": 50000},  # Düşük hacim
        ]

        # Filtre uygula
        filtered, _ = filter_eng.apply_filters(results)
        assert len(filtered) == 1

        # Alert kontrolü
        alerts = alert_mgr.check_scan_results(filtered)
        # Sadece THYAO alert üretmeli
        assert all(a.ticker == "THYAO" for a in alerts)

    def test_scheduler_with_dedup(self):
        """Scheduler dedup ile entegrasyon."""
        from services.scanner.deduplicator import ScanDeduplicator
        from services.scanner.scan_scheduler import AdaptiveScanScheduler

        scheduler = AdaptiveScanScheduler()
        dedup = ScanDeduplicator(cooldown_seconds=5)

        # Event tetikle
        scheduler.trigger_event_scan(["THYAO"])
        assert scheduler._has_recent_event is True

        # Dedup force scan
        dedup.force_scan("THYAO")
        assert dedup.should_scan("THYAO") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
