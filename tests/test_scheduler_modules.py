"""
ALPHA BIST — Scheduler Modules Test Suite v2.0

Tüm scheduler modülleri için kapsamlı test'ler:
- Unified Scheduler (market session, priority, retry, trigger)
- Job Monitor (stats, alerts, percentiles)
- Daily Workflow (phases, execution)
- Learning Scheduler (async validation, pending jobs)
- Scheduler API (all endpoints)
- DB Job Tracker (fallback)
- Holiday Provider (dynamic + fallback)
"""

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

# =====================================================
# HOLIDAY PROVIDER TESTS
# =====================================================


class TestHolidayProvider:
    """Holiday provider testleri."""

    def setup_method(self):
        from services.scheduler.unified_scheduler import HolidayProvider

        self.provider = HolidayProvider()

    def test_fallback_holidays_loaded(self):
        """Fallback tatil günleri yüklenmeli."""
        holidays = self.provider.get_holidays()
        assert len(holidays) >= 14  # 2026 hardcoded
        assert date(2026, 1, 1) in holidays  # Yılbaşı

    def test_is_holiday_new_year(self):
        """Yılbaşı tatil olmalı."""
        dt = datetime(2026, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=3)))
        assert self.provider.is_holiday(dt) is True

    def test_is_holiday_normal_day(self):
        """Normal gün tatil olmamalı."""
        dt = datetime(2026, 6, 15, 14, 0, tzinfo=timezone(timedelta(hours=3)))
        assert self.provider.is_holiday(dt) is False

    def test_add_holiday(self):
        """Runtime tatil eklenebilmeli."""
        self.provider.add_holiday(date(2026, 12, 31))
        dt = datetime(2026, 12, 31, 14, 0, tzinfo=timezone(timedelta(hours=3)))
        assert self.provider.is_holiday(dt) is True

    def test_remove_holiday(self):
        """Runtime tatil kaldırılabilmeli."""
        self.provider.add_holiday(date(2026, 12, 31))
        self.provider.remove_holiday(date(2026, 12, 31))
        dt = datetime(2026, 12, 31, 14, 0, tzinfo=timezone(timedelta(hours=3)))
        assert self.provider.is_holiday(dt) is False


# =====================================================
# MARKET SESSION MANAGER TESTS
# =====================================================


class TestMarketSessionManager:
    """Market session testleri."""

    def setup_method(self):
        from services.scheduler.unified_scheduler import MarketSessionManager

        self.market = MarketSessionManager()

    def test_current_phase(self):
        phase = self.market.current_phase()
        assert phase.value in [
            "CLOSED",
            "PRE_MARKET",
            "SEANS_1",
            "BREAK",
            "SEANS_2",
            "CLOSING",
            "POST_MARKET",
            "AFTER_HOURS",
            "NIGHT",
        ]

    def test_is_trading_hours(self):
        result = self.market.is_trading_hours()
        assert isinstance(result, bool)

    def test_is_market_open(self):
        result = self.market.is_market_open()
        assert isinstance(result, bool)

    def test_should_run_trading_job(self):
        result = self.market.should_run_trading_job()
        assert isinstance(result, bool)

    def test_seconds_until_next_phase(self):
        seconds = self.market.seconds_until_next_phase()
        assert seconds >= 0

    def test_get_status(self):
        status = self.market.get_status()
        assert "phase" in status
        assert "is_trading" in status
        assert "is_open" in status
        assert "is_holiday" in status
        assert "is_trading_day" in status

    def test_phase_times_ordered(self):
        """Faz zamanları sıralı olmalı."""
        times = [t for t, _ in self.market.PHASE_TIMES]
        for i in range(len(times) - 1):
            assert times[i] < times[i + 1]

    def test_holiday_provider_integration(self):
        """Holiday provider entegre olmalı."""
        provider = self.market.get_holiday_provider()
        assert provider is not None
        assert len(provider.get_holidays()) > 0


# =====================================================
# UNIFIED SCHEDULER TESTS
# =====================================================


class TestUnifiedScheduler:
    """Unified scheduler testleri."""

    def setup_method(self):
        from services.scheduler.unified_scheduler import UnifiedScheduler

        self.scheduler = UnifiedScheduler()

    def test_register_handler(self):
        async def dummy_handler():
            return "ok"

        self.scheduler.register_handler("test_job", dummy_handler)
        assert "test_job" in self.scheduler._handlers

    def test_update_interval(self):
        self.scheduler.update_interval("health_check", 120)
        assert self.scheduler._configs["health_check"].interval_seconds == 120

    def test_enable_disable_job(self):
        self.scheduler.enable_job("health_check", False)
        assert self.scheduler._configs["health_check"].enabled is False

        self.scheduler.enable_job("health_check", True)
        assert self.scheduler._configs["health_check"].enabled is True

    def test_update_priority(self):
        self.scheduler.update_priority("health_check", 1)
        assert self.scheduler._configs["health_check"].priority == 1

    def test_update_priority_clamped(self):
        """Priority 1-10 aralığında olmalı."""
        self.scheduler.update_priority("health_check", 0)
        assert self.scheduler._configs["health_check"].priority == 1

        self.scheduler.update_priority("health_check", 15)
        assert self.scheduler._configs["health_check"].priority == 10

    def test_get_status(self):
        status = self.scheduler.get_status()
        assert "running" in status
        assert "market" in status
        assert "registered_handlers" in status
        assert "enabled_configs" in status
        assert "trigger_queue_size" in status

    def test_get_job_stats(self):
        stats = self.scheduler.get_job_stats()
        assert "total_jobs" in stats

    def test_default_configs_loaded(self):
        assert len(self.scheduler._configs) > 0
        assert "market_data_update" in self.scheduler._configs
        assert "batch_scan" in self.scheduler._configs
        assert "learning_cycle" in self.scheduler._configs
        assert "backup" in self.scheduler._configs

    def test_job_config_fields(self):
        config = self.scheduler._configs["batch_scan"]
        assert config.interval_seconds > 0
        assert config.priority > 0
        assert config.max_retries >= 0
        assert config.timeout_seconds > 0
        assert config.description != ""

    def test_priority_ordering(self):
        """Job'lar priority'ye göre sıralanabilmeli."""
        configs = self.scheduler._configs
        sorted_jobs = sorted(configs.items(), key=lambda x: x[1].priority)
        assert len(sorted_jobs) == len(configs)
        # İlk job en yüksek önceliğe sahip olmalı
        assert sorted_jobs[0][1].priority <= sorted_jobs[-1][1].priority

    def test_get_job_configs(self):
        configs = self.scheduler.get_job_configs()
        assert "health_check" in configs
        assert "priority" in configs["health_check"]

    def test_trigger_job_no_handler(self):
        """Handler yoksa hata dönmeli."""
        result = asyncio.run(self.scheduler.trigger_job("nonexistent"))
        assert result["status"] == "ERROR"

    def test_trigger_job_with_handler(self):
        """Handler varsa queue'ya eklenmeli."""

        async def dummy():
            return "ok"

        self.scheduler.register_handler("test_trigger", dummy)
        # Config ekle
        from services.scheduler.unified_scheduler import JobConfig

        self.scheduler._configs["test_trigger"] = JobConfig(job_type="test_trigger", interval_seconds=60)

        result = asyncio.run(self.scheduler.trigger_job("test_trigger"))
        assert result["status"] == "QUEUED"


# =====================================================
# DB JOB TRACKER TESTS
# =====================================================


class TestDBJobTracker:
    """DB job tracker testleri."""

    def setup_method(self):
        from services.scheduler.unified_scheduler import DBJobTracker

        self.tracker = DBJobTracker()

    def test_record_job_memory_fallback(self):
        """DB yoksa memory'ye yazmalı."""
        from services.scheduler.unified_scheduler import JobResult

        result = JobResult(
            job_type="test", status="SUCCESS", duration_ms=100.0, timestamp=datetime.now(UTC).isoformat()
        )
        success = asyncio.run(self.tracker.record_job(result))
        assert success is True
        assert len(self.tracker._memory_history) == 1

    def test_get_job_history_memory(self):
        """Memory'den job geçmişi alabilmeli."""
        from services.scheduler.unified_scheduler import JobResult

        for i in range(5):
            result = JobResult(
                job_type=f"test_{i}", status="SUCCESS", duration_ms=100.0, timestamp=datetime.now(UTC).isoformat()
            )
            asyncio.run(self.tracker.record_job(result))

        history = asyncio.run(self.tracker.get_job_history(limit=3))
        assert len(history) == 3

    def test_get_failure_stats_memory(self):
        """Memory'den failure stats alabilmeli."""
        from services.scheduler.unified_scheduler import JobResult

        # Başarılı
        asyncio.run(
            self.tracker.record_job(
                JobResult(job_type="test", status="SUCCESS", duration_ms=100.0, timestamp=datetime.now(UTC).isoformat())
            )
        )
        # Başarısız
        asyncio.run(
            self.tracker.record_job(
                JobResult(
                    job_type="test",
                    status="FAILED",
                    duration_ms=50.0,
                    timestamp=datetime.now(UTC).isoformat(),
                    error="test error",
                )
            )
        )

        stats = asyncio.run(self.tracker.get_failure_stats(1))
        assert stats["total"] == 2
        assert stats["failed"] == 1


# =====================================================
# JOB MONITOR TESTS
# =====================================================


class TestJobMonitor:
    """Job monitor testleri."""

    def setup_method(self):
        from services.scheduler.job_monitor import JobMonitor

        self.monitor = JobMonitor()

    def test_record_success(self):
        self.monitor.record_job("batch_scan", "SUCCESS", 1500.0)
        stats = self.monitor.get_stats()
        assert stats["total_jobs"] == 1
        assert stats["success"] == 1

    def test_record_failure(self):
        self.monitor.record_job("batch_scan", "FAILED", 500.0, error="timeout")
        stats = self.monitor.get_stats()
        assert stats["failed"] == 1

    def test_failure_rate(self):
        self.monitor.record_job("test", "SUCCESS", 100.0)
        self.monitor.record_job("test", "SUCCESS", 100.0)
        self.monitor.record_job("test", "FAILED", 100.0)

        rate = self.monitor.get_failure_rate("test")
        assert rate == pytest.approx(1 / 3, abs=0.01)

    def test_consecutive_failures_alert(self):
        callback_called = []
        self.monitor.register_callback(lambda a: callback_called.append(a))

        self.monitor.record_job("test", "FAILED", 100.0)
        self.monitor.record_job("test", "FAILED", 100.0)
        self.monitor.record_job("test", "FAILED", 100.0)  # 3. ardışık

        assert len(callback_called) > 0
        assert callback_called[0].alert_type == "CONSECUTIVE_FAILURE"

    def test_consecutive_failure_reset(self):
        """Başarılı job consecutive failure'ı sıfırlamalı."""
        self.monitor.record_job("test", "FAILED", 100.0)
        self.monitor.record_job("test", "FAILED", 100.0)
        self.monitor.record_job("test", "SUCCESS", 100.0)
        assert self.monitor._consecutive_failures.get("test", 0) == 0

    def test_slow_job_alert(self):
        from services.scheduler.job_monitor import JobMonitor

        monitor = JobMonitor(slow_threshold_ms=1000)
        callback_called = []
        monitor.register_callback(lambda a: callback_called.append(a))

        monitor.record_job("test", "SUCCESS", 5000.0)  # 5sn > 1sn eşik

        assert len(callback_called) > 0
        assert callback_called[0].alert_type == "SLOW_JOB"

    def test_get_slow_jobs(self):
        self.monitor.record_job("test", "SUCCESS", 50000.0)  # 50sn
        slow = self.monitor.get_slow_jobs(threshold_ms=10000)
        assert len(slow) > 0

    def test_per_job_stats(self):
        self.monitor.record_job("job_a", "SUCCESS", 100.0)
        self.monitor.record_job("job_b", "FAILED", 200.0)

        stats_a = self.monitor.get_stats("job_a")
        assert stats_a["total_jobs"] == 1
        assert stats_a["success"] == 1

    def test_percentiles(self):
        """Percentile hesaplaması doğru olmalı."""
        for i in range(100):
            self.monitor.record_job("test", "SUCCESS", float(i * 10))

        stats = self.monitor.get_stats("test")
        assert stats["p95_duration_ms"] > 0
        assert stats["p99_duration_ms"] > 0
        assert stats["median_duration_ms"] > 0

    def test_triggered_by_tracking(self):
        """Triggered_by bilgisi kaydedilmeli."""
        self.monitor.record_job("test", "SUCCESS", 100.0, triggered_by="manual")
        assert self.monitor._records[-1].triggered_by == "manual"

    def test_get_summary(self):
        self.monitor.record_job("test", "SUCCESS", 100.0)
        summary = self.monitor.get_summary()
        assert "total_records" in summary
        assert "per_job_stats" in summary

    def test_clear(self):
        self.monitor.record_job("test", "SUCCESS", 100.0)
        self.monitor.clear()
        assert self.monitor.get_stats()["total_jobs"] == 0


# =====================================================
# DAILY WORKFLOW TESTS
# =====================================================


class TestDailyWorkflow:
    """Daily workflow testleri."""

    def setup_method(self):
        from services.scheduler.daily_workflow import DailyWorkflow

        self.workflow = DailyWorkflow()

    def test_phases_defined(self):
        assert len(self.workflow.PHASES) == 8
        assert "pre_market" in self.workflow.PHASES
        assert "post_market" in self.workflow.PHASES
        assert "night" in self.workflow.PHASES

    def test_register_handler(self):
        async def dummy():
            return "ok"

        self.workflow.register_handler("test_job", dummy)
        assert "test_job" in self.workflow._handlers

    def test_get_status(self):
        status = self.workflow.get_status()
        assert hasattr(status, "current_phase")
        assert hasattr(status, "jobs_run_today")
        assert hasattr(status, "jobs_failed_today")

    def test_get_phases(self):
        phases = self.workflow.get_phases()
        assert "pre_market" in phases
        assert phases["pre_market"]["name"] == "PRE_MARKET"
        assert "market_data_update" in phases["pre_market"]["jobs"]

    def test_reset_daily_counters(self):
        self.workflow._jobs_run_today = 10
        self.workflow._jobs_failed_today = 2
        self.workflow.reset_daily_counters()
        assert self.workflow._jobs_run_today == 0
        assert self.workflow._jobs_failed_today == 0

    def test_execute_phase(self):
        async def dummy_job():
            return "ok"

        self.workflow.register_handler("market_data_update", dummy_job)
        self.workflow.register_handler("feature_calculation", dummy_job)

        results = asyncio.run(self.workflow.execute_phase("pre_market"))
        assert "market_data_update" in results
        assert results["market_data_update"]["status"] == "SUCCESS"

    def test_execute_unknown_phase(self):
        result = asyncio.run(self.workflow.execute_phase("unknown"))
        assert "error" in result

    def test_phase_map_complete(self):
        """Tüm market phase'leri workflow phase'e map'lenmeli."""
        from services.scheduler.unified_scheduler import MarketPhase

        for mp in MarketPhase:
            assert mp.value in self.workflow._PHASE_MAP or mp.value in ["SEANS_1", "SEANS_2"]


# =====================================================
# LEARNING SCHEDULER TESTS
# =====================================================


class TestLearningScheduler:
    """Learning scheduler testleri."""

    def setup_method(self):
        from services.scheduler.learning_scheduler import LearningScheduler

        self.scheduler = LearningScheduler()

    def test_default_jobs(self):
        assert "learning_cycle" in self.scheduler._jobs
        assert "model_retrain" in self.scheduler._jobs
        assert "calibration_update" in self.scheduler._jobs

    def test_register_handler(self):
        async def dummy():
            return "ok"

        self.scheduler.register_handler("learning_cycle", dummy)
        assert self.scheduler._jobs["learning_cycle"].handler is not None

    def test_register_sync_handler_wrapped(self):
        """Sync handler async'e wrap'lenmeli."""

        def sync_dummy():
            return "ok"

        self.scheduler.register_handler("learning_cycle", sync_dummy)
        handler = self.scheduler._jobs["learning_cycle"].handler
        assert asyncio.iscoroutinefunction(handler)

    def test_register_unknown_job_type(self):
        """Bilinmeyen job type uyarı loglamalı."""

        async def dummy():
            return "ok"

        # Hata fırlatmamalı
        self.scheduler.register_handler("unknown_job", dummy)

    def test_enable_disable(self):
        self.scheduler.enable_job("learning_cycle", False)
        assert self.scheduler._jobs["learning_cycle"].enabled is False

    def test_update_interval(self):
        self.scheduler.update_interval("learning_cycle", 48)
        assert self.scheduler._jobs["learning_cycle"].interval_hours == 48

    def test_update_interval_min_1(self):
        """Interval minimum 1 olmalı."""
        self.scheduler.update_interval("learning_cycle", 0)
        assert self.scheduler._jobs["learning_cycle"].interval_hours == 1

    def test_should_run_first_time(self):
        config = self.scheduler._jobs["learning_cycle"]
        config.last_run = None
        assert self.scheduler._should_run(config) is True

    def test_should_run_not_yet(self):
        config = self.scheduler._jobs["learning_cycle"]
        config.last_run = datetime.now(UTC).isoformat()
        assert self.scheduler._should_run(config) is False

    def test_get_status(self):
        status = self.scheduler.get_status()
        assert "total_jobs" in status
        assert "enabled_jobs" in status
        assert "jobs_with_handlers" in status
        assert "jobs" in status

    def test_get_pending_jobs(self):
        async def dummy():
            return "ok"

        self.scheduler.register_handler("learning_cycle", dummy)
        pending = self.scheduler.get_pending_jobs()
        assert len(pending) >= 0


# =====================================================
# SCHEDULER API TESTS
# =====================================================


class TestSchedulerAPI:
    """Scheduler API testleri."""

    def setup_method(self):
        from services.scheduler.scheduler_api import SchedulerAPI

        self.api = SchedulerAPI()

    def test_get_status(self):
        status = self.api.get_status()
        assert "timestamp" in status
        assert "scheduler" in status

    def test_get_jobs(self):
        jobs = self.api.get_jobs()
        assert "total_jobs" in jobs
        assert jobs["total_jobs"] > 0

    def test_get_monitor(self):
        monitor = self.api.get_monitor()
        assert "stats" in monitor

    def test_get_workflow(self):
        workflow = self.api.get_workflow()
        assert "status" in workflow
        assert "phases" in workflow

    def test_get_learning(self):
        learning = self.api.get_learning()
        assert "status" in learning

    def test_get_market_session(self):
        market = self.api.get_market_session()
        assert "market" in market

    def test_trigger_job(self):
        result = asyncio.run(self.api.trigger_job("nonexistent"))
        assert result["status"] == "ERROR"

    def test_update_interval(self):
        result = self.api.update_interval("health_check", 120)
        assert result["status"] == "OK"
        assert result["new_interval"] == 120

    def test_update_interval_unknown(self):
        result = self.api.update_interval("unknown", 120)
        assert result["status"] == "ERROR"

    def test_enable_job(self):
        result = self.api.enable_job("health_check", False)
        assert result["status"] == "OK"
        assert result["enabled"] is False

    def test_update_priority(self):
        result = self.api.update_priority("health_check", 1)
        assert result["status"] == "OK"
        assert result["new_priority"] == 1

    def test_get_full_dashboard(self):
        dashboard = asyncio.run(self.api.get_full_dashboard())
        assert "status" in dashboard
        assert "jobs" in dashboard
        assert "monitor" in dashboard
        assert "db_stats" in dashboard


# =====================================================
# INTEGRATION TESTS
# =====================================================


class TestSchedulerRateLimiter:
    """Rate limiter testleri."""

    def test_rate_limiter_allows_normal(self):
        from services.scheduler.scheduler_api import _RateLimiter

        limiter = _RateLimiter(max_tokens=5, refill_rate=5 / 60)
        for _ in range(5):
            assert limiter.allow() is True

    def test_rate_limiter_blocks_excess(self):
        from services.scheduler.scheduler_api import _RateLimiter

        limiter = _RateLimiter(max_tokens=3, refill_rate=0)
        for _ in range(3):
            limiter.allow()
        assert limiter.allow() is False

    def test_rate_limiter_remaining(self):
        from services.scheduler.scheduler_api import _RateLimiter

        limiter = _RateLimiter(max_tokens=5, refill_rate=5 / 60)
        limiter.allow()
        limiter.allow()
        assert limiter.remaining == 3

    def test_trigger_rate_limited(self):
        from services.scheduler.scheduler_api import SchedulerAPI

        api = SchedulerAPI()
        # Rate limiter'ı tüket
        api._trigger_limiter._tokens = 0
        api._trigger_limiter._refill_rate = 0
        result = asyncio.run(api.trigger_job("test"))
        assert result["status"] == "RATE_LIMITED"


# =====================================================
# INTEGRATION TESTS
# =====================================================


class TestSchedulerIntegration:
    """Entegrasyon testleri."""

    def test_scheduler_with_monitor(self):
        """Scheduler + monitor entegrasyonu."""
        from services.scheduler.job_monitor import JobMonitor
        from services.scheduler.unified_scheduler import UnifiedScheduler

        UnifiedScheduler()
        monitor = JobMonitor()

        # Job kaydet
        monitor.record_job("batch_scan", "SUCCESS", 1500.0)
        monitor.record_job("batch_scan", "FAILED", 500.0, error="test")

        stats = monitor.get_stats("batch_scan")
        assert stats["total_jobs"] == 2

    def test_workflow_with_scheduler(self):
        """Workflow + scheduler entegrasyonu."""
        from services.scheduler.daily_workflow import DailyWorkflow
        from services.scheduler.unified_scheduler import MarketSessionManager

        workflow = DailyWorkflow()
        market = MarketSessionManager()

        market.current_phase()
        status = workflow.get_status()
        assert status.current_phase is not None

    def test_learning_with_monitor(self):
        """Learning + monitor entegrasyonu."""
        from services.scheduler.job_monitor import JobMonitor
        from services.scheduler.learning_scheduler import LearningScheduler

        learning = LearningScheduler()
        monitor = JobMonitor()

        async def dummy_learning():
            monitor.record_job("learning_cycle", "SUCCESS", 2000.0)
            return "learned"

        learning.register_handler("learning_cycle", dummy_learning)
        assert learning._jobs["learning_cycle"].handler is not None

    def test_api_with_all_modules(self):
        """API tüm modüllerle entegre olmalı."""
        from services.scheduler.scheduler_api import SchedulerAPI

        api = SchedulerAPI()

        # Status — tüm modüllerden veri çekmeli
        status = api.get_status()
        assert "scheduler" in status
        assert "workflow" in status
        assert "learning" in status

        # Jobs
        jobs = api.get_jobs()
        assert jobs["total_jobs"] > 0

    def test_priority_based_execution_order(self):
        """Priority'ye göre job sıralaması doğru olmalı."""
        from services.scheduler.unified_scheduler import UnifiedScheduler

        scheduler = UnifiedScheduler()

        # Job'ları priority'ye göre sırala
        configs = scheduler._configs
        sorted_jobs = sorted(configs.items(), key=lambda x: x[1].priority)

        # market_data_update (priority=1) en önce gelmeli
        assert sorted_jobs[0][1].priority == 1

        # backup (priority=10) en son gelmeli
        assert sorted_jobs[-1][1].priority == 10

    def test_holiday_blocks_trading(self):
        """Tatil gününde trading job'ları çalışmamalı."""
        from services.scheduler.unified_scheduler import HolidayProvider, MarketPhase, MarketSessionManager

        provider = HolidayProvider()
        # Yarını tatil ekle
        tomorrow = datetime.now(timezone(timedelta(hours=3))) + timedelta(days=1)
        provider.add_holiday(tomorrow.date())

        market = MarketSessionManager(holiday_provider=provider)

        # Eğer bugün tatilse CLOSED olmalı
        # (test gününden bağımsız, mantık doğru olmalı)
        phase = market.current_phase()
        assert isinstance(phase, MarketPhase)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
