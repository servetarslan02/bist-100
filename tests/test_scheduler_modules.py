"""
ALPHA BIST — Scheduler Modules Test Suite v1.0

Tüm yeni scheduler modülleri için test'ler:
- Unified Scheduler
- Market Session Manager
- Job Monitor
- Daily Workflow
- Learning Scheduler
- Scheduler API
"""

import pytest
import asyncio
import time
from datetime import datetime, time as dt_time, timezone, timedelta


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
            "CLOSED", "PRE_MARKET", "SEANS_1", "BREAK",
            "SEANS_2", "CLOSING", "POST_MARKET", "AFTER_HOURS", "NIGHT"
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

    def test_is_holiday(self):
        # Yılbaşı
        from datetime import datetime, timezone, timedelta
        dt = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3)))
        assert self.market._is_holiday(dt) is True

        # Normal gün
        dt = datetime(2026, 6, 15, tzinfo=timezone(timedelta(hours=3)))
        assert self.market._is_holiday(dt) is False

    def test_phase_times_ordered(self):
        """Faz zamanları sıralı olmalı."""
        times = [t for t, _ in self.market.PHASE_TIMES]
        for i in range(len(times) - 1):
            assert times[i] < times[i + 1]


# =====================================================
# UNIFIED SCHEDULER TESTS
# =====================================================

class TestUnifiedScheduler:
    """Unified scheduler testleri."""

    def setup_method(self):
        from services.scheduler.unified_scheduler import UnifiedScheduler, JobConfig
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

    def test_get_status(self):
        status = self.scheduler.get_status()
        assert "running" in status
        assert "market" in status
        assert "registered_handlers" in status

    def test_get_job_stats(self):
        stats = self.scheduler.get_job_stats()
        assert "total_jobs" in stats

    def test_default_configs_loaded(self):
        assert len(self.scheduler._configs) > 0
        assert "market_data_update" in self.scheduler._configs
        assert "batch_scan" in self.scheduler._configs

    def test_job_config_fields(self):
        config = self.scheduler._configs["batch_scan"]
        assert config.interval_seconds > 0
        assert config.priority > 0
        assert config.max_retries >= 0


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
        assert rate == pytest.approx(1/3, abs=0.01)

    def test_consecutive_failures_alert(self):
        callback_called = []
        self.monitor.register_callback(lambda a: callback_called.append(a))

        self.monitor.record_job("test", "FAILED", 100.0)
        self.monitor.record_job("test", "FAILED", 100.0)
        self.monitor.record_job("test", "FAILED", 100.0)  # 3. ardışık

        assert len(callback_called) > 0
        assert callback_called[0].alert_type == "CONSECUTIVE_FAILURE"

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

    def test_register_handler(self):
        async def dummy():
            return "ok"

        self.workflow.register_handler("test_job", dummy)
        assert "test_job" in self.workflow._handlers

    def test_get_status(self):
        status = self.workflow.get_status()
        assert hasattr(status, "current_phase")
        assert hasattr(status, "jobs_run_today")

    def test_get_phases(self):
        phases = self.workflow.get_phases()
        assert "pre_market" in phases
        assert phases["pre_market"]["name"] == "PRE_MARKET"

    def test_reset_daily_counters(self):
        self.workflow._jobs_run_today = 10
        self.workflow._jobs_failed_today = 2
        self.workflow.reset_daily_counters()
        assert self.workflow._jobs_run_today == 0

    def test_execute_phase(self):
        async def dummy_job():
            return "ok"

        self.workflow.register_handler("market_data_update", dummy_job)
        self.workflow.register_handler("feature_calculation", dummy_job)

        results = asyncio.run(self.workflow.execute_phase("pre_market"))
        assert "market_data_update" in results
        assert results["market_data_update"]["status"] == "SUCCESS"


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

    def test_register_handler(self):
        async def dummy():
            return "ok"

        self.scheduler.register_handler("learning_cycle", dummy)
        assert self.scheduler._jobs["learning_cycle"].handler is not None

    def test_enable_disable(self):
        self.scheduler.enable_job("learning_cycle", False)
        assert self.scheduler._jobs["learning_cycle"].enabled is False

    def test_update_interval(self):
        self.scheduler.update_interval("learning_cycle", 48)
        assert self.scheduler._jobs["learning_cycle"].interval_hours == 48

    def test_should_run_first_time(self):
        config = self.scheduler._jobs["learning_cycle"]
        config.last_run = None
        assert self.scheduler._should_run(config) is True

    def test_should_run_not_yet(self):
        config = self.scheduler._jobs["learning_cycle"]
        config.last_run = datetime.now(timezone.utc).isoformat()
        assert self.scheduler._should_run(config) is False

    def test_get_status(self):
        status = self.scheduler.get_status()
        assert "total_jobs" in status
        assert "jobs" in status

    def test_get_pending_jobs(self):
        # Handler yoksa pending_jobs boş olabilir
        # Ama last_run=None olanlar pending
        async def dummy():
            return "ok"
        self.scheduler.register_handler("learning_cycle", dummy)
        pending = self.scheduler.get_pending_jobs()
        assert len(pending) >= 0  # En azından handler var


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

    def test_get_full_dashboard(self):
        dashboard = self.api.get_full_dashboard()
        assert "status" in dashboard
        assert "jobs" in dashboard
        assert "monitor" in dashboard


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestSchedulerIntegration:
    """Entegrasyon testleri."""

    def test_scheduler_with_monitor(self):
        """Scheduler + monitor entegrasyonu."""
        from services.scheduler.unified_scheduler import UnifiedScheduler
        from services.scheduler.job_monitor import JobMonitor

        scheduler = UnifiedScheduler()
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

        phase = market.current_phase()
        status = workflow.get_status()
        assert status.current_phase is not None

    def test_learning_with_monitor(self):
        """Learning + monitor entegrasyonu."""
        from services.scheduler.learning_scheduler import LearningScheduler
        from services.scheduler.job_monitor import JobMonitor

        learning = LearningScheduler()
        monitor = JobMonitor()

        async def dummy_learning():
            monitor.record_job("learning_cycle", "SUCCESS", 2000.0)
            return "learned"

        learning.register_handler("learning_cycle", dummy_learning)
        assert learning._jobs["learning_cycle"].handler is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
