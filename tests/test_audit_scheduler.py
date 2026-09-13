"""
ALPHA BIST — Scheduler ve Tasks Servisi Kapsamlı Denetim ve Doğrulama Testleri
"""


from services.scheduler.daily_report import generate_daily_report
from services.scheduler.daily_workflow import (
    DailyWorkflow,
    WorkflowPhase,
    WorkflowStatus,
)
from services.scheduler.job_monitor import (
    JobAlert,
    JobMonitor,
    JobRecord,
    JobStatus,
)
from services.scheduler.learning_scheduler import (
    LearningJobConfig,
    LearningScheduler,
)
from services.scheduler.scheduler_api import SchedulerAPI
from services.scheduler.unified_scheduler import (
    JobConfig,
    JobResult,
    MarketPhase,
    MarketSessionManager,
    UnifiedScheduler,
)
from services.tasks.queue import (
    _MockAsyncResult,
    _MockCeleryApp,
    _MockConf,
    get_task_status,
    submit_task,
)


def test_job_monitor_and_records():
    """JobMonitor, JobRecord ve JobAlert işlevselliği ve __repr__ doğrulaması."""
    monitor = JobMonitor(max_history=50, slow_threshold_ms=5000)
    assert "JobMonitor" in repr(monitor)

    rec = JobRecord(
        job_type="test_scan",
        status=JobStatus.SUCCESS,
        duration_ms=1200.5,
        timestamp="2026-09-12T10:00:00Z",
    )
    assert "JobRecord" in repr(rec)
    assert rec.status == JobStatus.SUCCESS

    alert = JobAlert(
        alert_type="SLOW",
        job_type="test_scan",
        message="Job exceeded 5s threshold",
        severity="WARNING",
        timestamp="2026-09-12T10:01:00Z",
    )
    assert "JobAlert" in repr(alert)

    monitor.record_job("test_scan", "SUCCESS", 1200.0)
    monitor.record_job("test_scan", "FAILED", 6000.0, error="DB Timeout")
    summary = monitor.get_summary()
    assert summary["total_records"] == 2
    assert summary["overall_stats"]["total_jobs"] == 2
    assert "test_scan" in summary["job_types"]


def test_daily_workflow_and_phases():
    """DailyWorkflow, WorkflowPhase ve WorkflowStatus modelleri."""
    wf = DailyWorkflow()
    assert "DailyWorkflow" in repr(wf)

    phase = WorkflowPhase(
        name="TEST_PHASE",
        start_time="10:00",
        end_time="11:00",
        jobs=["job1", "job2"],
        description="Test description",
    )
    assert "WorkflowPhase" in repr(phase)

    status = WorkflowStatus(
        current_phase="CONTINUOUS",
        next_phase="CLOSING",
        next_phase_in_seconds=3600.0,
        jobs_run_today=10,
        jobs_failed_today=1,
        daily_report_generated=False,
        timestamp="2026-09-12T14:00:00Z",
    )
    assert "WorkflowStatus" in repr(status)

    res = wf.get_status()
    assert res.jobs_run_today == 0


def test_learning_scheduler():
    """LearningScheduler ve LearningJobConfig modelleri."""
    ls = LearningScheduler()
    assert "LearningScheduler" in repr(ls)

    config = LearningJobConfig(
        job_type="test_learning",
        interval_hours=24,
        description="Daily retraining test",
    )
    assert "LearningJobConfig" in repr(config)
    assert config.interval_hours == 24


def test_unified_scheduler_models():
    """JobConfig, JobResult, MarketSessionManager ve UnifiedScheduler."""
    cfg = JobConfig(
        job_type="test_scan",
        interval_seconds=60,
        priority=2,
    )
    assert "JobConfig" in repr(cfg)

    res = JobResult(
        job_type="test_scan",
        status="SUCCESS",
        duration_ms=45.0,
        timestamp="2026-09-12T12:00:00Z",
    )
    assert "JobResult" in repr(res)

    msm = MarketSessionManager()
    assert "MarketSessionManager" in repr(msm)
    assert msm.current_phase() in list(MarketPhase)

    us = UnifiedScheduler()
    assert "UnifiedScheduler" in repr(us)
    assert len(us.get_job_configs()) > 0


def test_scheduler_api_and_daily_report():
    """SchedulerAPI ve generate_daily_report fonksiyonu doğrulaması."""
    api = SchedulerAPI()
    assert "SchedulerAPI" in repr(api)

    status = api.get_status()
    assert "scheduler" in status
    assert "workflow" in status

    report = generate_daily_report(
        date="2026-09-12",
        market_state={"regime": "BULL", "breadth_pct": 65.5, "advancing": 60, "declining": 40},
        signals=[{"ticker": "THYAO", "spec_score": 88, "spec_category": "STRONG_BUY", "price": 310.0}],
        trade_plans=[],
        anomalies=[],
        portfolio={},
        world_state={"vix_level": 14.5, "usd_strength": 0.5, "turkey_macro_risk": 0.3, "global_risk_appetite": 0.7},
    )
    assert "ALPHA BIST — GÜNLÜK RAPOR" in report
    assert "THYAO" in report


def test_tasks_queue_fallbacks():
    """Services/tasks fallback sınıfları ve submit_task işlevselliği."""
    conf = _MockConf()
    assert "_MockConf" in repr(conf)

    app = _MockCeleryApp()
    assert "_MockCeleryApp" in repr(app)

    async_res = _MockAsyncResult("task-123", status="SUCCESS")
    assert "_MockAsyncResult" in repr(async_res)
    assert async_res.ready() is True
    assert async_res.successful() is True

    # submit_task testi
    sub = submit_task("health_check")
    assert sub["success"] is True
    assert "task_id" in sub

    status = get_task_status(sub["task_id"])
    assert "status" in status
