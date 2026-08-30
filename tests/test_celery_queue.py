from typing import Any

"""
ALPHA BIST — Celery Async Task Queue Test Suite
Doğrulanan Özellikler:
1. Celery App Yapılandırması: Broker/Backend URL, Late Acks, Prefetch
2. Queue Routing: heavy, compute, fast kuyruk eşleştirmeleri
3. Beat Schedule: Cron tabloları (morning check, EOD report, intraday stress test)
4. Idempotency & Mükerrer Görev Engelleme (Task Signature Lock)
5. BaseTaskWithDLQ: Hata durumunda DLQ tetikleme
6. Görev Durumu ve İlerleme Sorgulama (get_task_status)
"""

from unittest.mock import MagicMock, patch

import pytest

from services.tasks.queue import (
    BaseTaskWithDLQ,
    _generate_task_signature,
    celery_app,
    get_task_status,
    submit_task,
)


class TestCeleryConfiguration:
    """Celery yapılandırma, yönlendirme ve çizelge testleri."""

    def test_celery_app_initialized(self) -> Any:
        """Otomatik eklendi."""
        assert celery_app is not None
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.worker_prefetch_multiplier == 1
        assert celery_app.conf.timezone == "Europe/Istanbul"

    def test_queue_routing_configuration(self) -> Any:
        """Otomatik eklendi."""
        routes = celery_app.conf.task_routes
        assert routes["tasks.model_train"]["queue"] == "heavy"
        assert routes["tasks.data_backfill"]["queue"] == "heavy"
        assert routes["tasks.backtest"]["queue"] == "compute"
        assert routes["tasks.risk_stress_test"]["queue"] == "compute"
        assert routes["tasks.portfolio_optimize"]["queue"] == "compute"
        assert routes["tasks.report_generate"]["queue"] == "fast"
        assert routes["tasks.health_check"]["queue"] == "fast"

    def test_beat_schedule_configuration(self) -> Any:
        """Otomatik eklendi."""
        schedule = celery_app.conf.beat_schedule
        assert "morning-pre-market-check" in schedule
        assert "post-market-daily-report" in schedule
        assert "intraday-risk-stress-test" in schedule
        assert schedule["morning-pre-market-check"]["task"] == "tasks.health_check"


class TestTaskSubmissionAndIdempotency:
    """Görev gönderimi, imzalama ve mükerrerlik testleri."""

    def test_task_signature_generation(self) -> Any:
        """Otomatik eklendi."""
        sig1 = _generate_task_signature("backtest", ("THYAO",), {"days": 30})
        sig2 = _generate_task_signature("backtest", ("THYAO",), {"days": 30})
        sig3 = _generate_task_signature("backtest", ("ASELS",), {"days": 30})

        assert sig1 == sig2
        assert sig1 != sig3

    def test_idempotent_task_submission_deduplication(self) -> Any:
        """Otomatik eklendi."""
        with patch("services.tasks.queue.run_backtest_task.delay") as mock_delay:
            mock_res = MagicMock()
            mock_res.id = "task-mock-001"
            mock_delay.return_value = mock_res

            # İlk gönderim -> QUEUED
            res1 = submit_task("backtest", ticker="THYAO", days=45, idempotent=True)
            assert res1["success"] is True
            assert res1["status"] == "QUEUED"
            assert res1["task_id"] == "task-mock-001"

            # İkinci özdeş gönderim -> DEDUPLICATED
            res2 = submit_task("backtest", ticker="THYAO", days=45, idempotent=True)
            assert res2["success"] is True
            assert res2["status"] == "DEDUPLICATED"
            assert res2["task_id"] == "task-mock-001"

    def test_invalid_task_type_submission(self) -> Any:
        """Otomatik eklendi."""
        res = submit_task("non_existent_task_name")
        assert res["success"] is False
        assert "Bilinmeyen görev" in res["error"]


class TestTaskStatusAndDLQ:
    """Durum sorgulama ve DLQ entegrasyon testleri."""

    def test_get_task_status_mocked(self) -> Any:
        """Otomatik eklendi."""
        with patch.object(celery_app, "AsyncResult") as mock_async_result:
            mock_res = MagicMock()
            mock_res.status = "SUCCESS"
            mock_res.ready.return_value = True
            mock_res.successful.return_value = True
            mock_res.result = {"pnl": 15.5}
            mock_async_result.return_value = mock_res

            status = get_task_status("test-id-123")
            assert status["task_id"] == "test-id-123"
            assert status["status"] == "SUCCESS"
            assert status["result"] == {"pnl": 15.5}

    @pytest.mark.asyncio
    async def test_base_task_dlq_on_failure(self) -> Any:
        """Otomatik eklendi."""
        task_instance = BaseTaskWithDLQ()
        task_instance.name = "tasks.backtest"

        with patch("services.core.dead_letter_queue.dead_letter_queue.push") as mock_dlq_push:
            # Simulate permanent task failure
            task_instance.on_failure(
                exc=ValueError("Simulated critical backtest crash"),
                task_id="failed-task-999",
                args=("THYAO",),
                kwargs={"days": 30},
                einfo=None,
            )
            # Check if failure was routed to DLQ
            assert mock_dlq_push.called, "Görev başarısız olduğunda DLQ'ya push yapılmalıydı"
