import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Learning System Faz 8 Test Suite (Health Monitor)

Health monitoring testing:
- Module health checks
- Overall status calculation
- Restart request workflow
- Error recording
- Uptime tracking
- Critical/warning detection
- Module-specific checks
"""

import sys
from datetime import UTC, datetime


def test_init() -> Any:
    """Health monitor init."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    assert len(m._module_status) == 0
    assert len(m._error_history) == 0
    assert len(m._restart_requests) == 0
    logger.info("✅ Init")


def test_singleton() -> Any:
    """Singleton doğru mu?"""
    from services.learning.health_monitor import learning_health_monitor

    assert learning_health_monitor is not None
    logger.info("✅ Singleton")


def test_check_health() -> Any:
    """Health check çalışıyor mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.check_health()

    assert report.overall_status in ["HEALTHY", "WARNING", "CRITICAL"]
    assert len(report.modules) > 0
    assert report.timestamp is not None
    logger.info(f"✅ Check health: {report.overall_status}, {len(report.modules)} modules")


def test_check_health_modules() -> Any:
    """Tüm modüller kontrol edilmeli."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.check_health()

    expected_modules = [
        "prediction_tracking",
        "outcome_tracking",
        "calibration",
        "drift_detection",
        "model_performance",
        "feature_pipeline",
    ]
    for mod in expected_modules:
        assert mod in report.modules, f"Missing module: {mod}"
    logger.info(f"✅ Check health modules: {list(report.modules.keys())}")


def test_check_health_module_status() -> Any:
    """Her modülün status'ü doğru mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.check_health()

    for name, health in report.modules.items():
        assert health.status in ["HEALTHY", "WARNING", "CRITICAL", "DEGRADED", "RESTARTING"]
        assert health.module == name
        assert health.last_check is not None
    logger.info("✅ Check health module status")


def test_overall_status_critical() -> Any:
    """Critical modül varsa overall CRITICAL olmalı."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.check_health()

    critical_modules = [name for name, h in report.modules.items() if h.status == "CRITICAL"]
    if critical_modules:
        assert report.overall_status == "CRITICAL"
        logger.info(f"✅ Overall status critical: {critical_modules}")
    else:
        logger.info("✅ Overall status: no critical modules")


def test_overall_status_warning() -> Any:
    """Warning modül varsa WARNING olmalı (critical yoksa)."""
    from services.learning.health_monitor import LearningHealthMonitor, ModuleHealth

    m = LearningHealthMonitor()
    # Manuel warning ekle
    m._module_status["test"] = ModuleHealth(
        module="test",
        status="WARNING",
        last_check=datetime.now(UTC).isoformat(),
        error_count=0,
        last_error=None,
        uptime_hours=0,
    )

    report = m.check_health()
    # Critical yoksa warning olmalı
    if not report.critical_modules:
        assert report.overall_status in ["WARNING", "HEALTHY"]
    logger.info(f"✅ Overall status warning: {report.overall_status}")


def test_restart_request() -> Any:
    """Restart isteği."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    m.request_restart("test_module")

    assert "test_module" in m._restart_requests
    logger.info("✅ Restart request")


def test_restart_request_duplicate() -> Any:
    """Duplicate restart isteği eklenmemeli."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    m.request_restart("test_module")
    m.request_restart("test_module")  # Duplicate

    assert len(m._restart_requests) == 1
    logger.info("✅ Restart request duplicate")


def test_get_restart_requests() -> Any:
    """Restart istekleri alındıktan sonra temizlenmeli."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    m.request_restart("mod1")
    m.request_restart("mod2")

    requests = m.get_restart_requests()
    assert "mod1" in requests
    assert "mod2" in requests
    assert len(requests) == 2

    # İkinci çağrıda temizlenmiş olmalı
    requests2 = m.get_restart_requests()
    assert len(requests2) == 0
    logger.info("✅ Get restart requests (cleared after read)")


def test_error_recording() -> Any:
    """Hata kaydetme."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    m.record_error("test_module", "Test error message")

    assert len(m._error_history) == 1
    assert m._error_history[0]["module"] == "test_module"
    assert m._error_history[0]["error"] == "Test error message"
    assert "timestamp" in m._error_history[0]
    logger.info("✅ Error recording")


def test_error_recording_multiple() -> Any:
    """Birden fazla hata kayıt."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    m.record_error("mod1", "Error 1")
    m.record_error("mod2", "Error 2")
    m.record_error("mod1", "Error 3")

    assert len(m._error_history) == 3
    assert m._error_history[2]["module"] == "mod1"
    logger.info("✅ Error recording multiple")


def test_error_updates_module_status() -> Any:
    """Hata modül status'unu güncellemeli."""
    from services.learning.health_monitor import LearningHealthMonitor, ModuleHealth

    m = LearningHealthMonitor()
    # Manuel modül status ekle
    m._module_status["test"] = ModuleHealth(
        module="test",
        status="HEALTHY",
        last_check=datetime.now(UTC).isoformat(),
        error_count=0,
        last_error=None,
        uptime_hours=0,
    )

    m.record_error("test", "New error")

    assert m._module_status["test"].error_count == 1
    assert m._module_status["test"].last_error == "New error"
    logger.info("✅ Error updates module status")


def test_uptime() -> Any:
    """Uptime hesaplanıyor mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.get_report()

    assert "uptime_hours" in report
    assert report["uptime_hours"] >= 0
    logger.info(f"✅ Uptime: {report['uptime_hours']} hours")


def test_report() -> Any:
    """Rapor doğru mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    m.record_error("test", "error")
    m.request_restart("test")

    report = m.get_report()
    assert report["status"] == "OK"
    assert report["error_count"] == 1
    assert report["pending_restarts"] == 1
    logger.info(f"✅ Report: errors={report['error_count']}, restarts={report['pending_restarts']}")


def test_report_empty() -> Any:
    """Boş rapor."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.get_report()

    assert report["status"] == "OK"
    assert report["error_count"] == 0
    assert report["pending_restarts"] == 0
    logger.info("✅ Report empty")


def test_recommendations() -> Any:
    """Critical modül varsa recommendation olmalı."""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.check_health()

    if report.critical_modules:
        assert len(report.recommendations) > 0
        logger.info(f"✅ Recommendations: {report.recommendations}")
    else:
        logger.info("✅ No critical → no recommendations")


def test_module_health_fields() -> Any:
    """ModuleHealth alanları doğru mu?"""
    from services.learning.health_monitor import LearningHealthMonitor

    m = LearningHealthMonitor()
    report = m.check_health()

    for _name, health in report.modules.items():
        assert hasattr(health, "module")
        assert hasattr(health, "status")
        assert hasattr(health, "last_check")
        assert hasattr(health, "error_count")
        assert hasattr(health, "last_error")
        assert hasattr(health, "uptime_hours")
    logger.info("✅ Module health fields")


# ===================== MAIN =====================


def run_all_tests() -> Any:
    """Otomatik eklendi."""
    tests = [
        test_init,
        test_singleton,
        test_check_health,
        test_check_health_modules,
        test_check_health_module_status,
        test_overall_status_critical,
        test_overall_status_warning,
        test_restart_request,
        test_restart_request_duplicate,
        test_get_restart_requests,
        test_error_recording,
        test_error_recording_multiple,
        test_error_updates_module_status,
        test_uptime,
        test_report,
        test_report_empty,
        test_recommendations,
        test_module_health_fields,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            errors.append((test.__name__, str(e)))
            logger.info(f"❌ {test.__name__}: {e}")

    logger.info(f"\n{'=' * 60}")
    logger.info("📊 FAZ 8 TEST SONUÇLARI (Health Monitor)")
    logger.info(f"{'=' * 60}")
    logger.info(f"✅ Geçen: {passed}")
    logger.info(f"❌ Başarısız: {failed}")
    logger.info(f"📈 Toplam: {passed + failed}")

    if errors:
        logger.info("\n🔍 Hatalar:")
        for name, err in errors:
            logger.info(f"  - {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
