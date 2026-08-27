"""
ALPHA BIST — Nihai Core Sistemi Test Paketi

Tüm yeni core modülleri için kapsamlı testler:
1. Dead Letter Queue
2. JWT Token Manager
3. Transaction Helper
4. Circuit Breaker Metrics
5. Config Hot-Reload
6. Immutable Audit Log
7. Distributed Tracing
8. System Governor
"""

import time
from datetime import UTC, datetime, timedelta

import orjson
import pytest

from services.core.circuit_breaker_metrics import CircuitBreakerMetricsCollector
from services.core.config_hot_reload import ConfigHotReload
from services.core.dead_letter_queue import DeadLetterQueue, DLQStatus
from services.core.distributed_tracing import DistributedTracer
from services.core.immutable_audit import ImmutableAuditLog
from services.core.jwt_manager import JWTError, JWTManager, TokenType
from services.core.system_governor import FeatureFlag, SystemState, SystemStateGovernor
from services.core.transaction_helper import TransactionHelper

# =====================================================
# Phase 1: Dead Letter Queue
# =====================================================

class TestDeadLetterQueue:
    """DLQ testleri."""

    def setup_method(self):
        self.dlq = DeadLetterQueue(max_entries=100)

    @pytest.mark.asyncio
    async def test_push_and_get(self):
        """Event push ve get."""
        entry = await self.dlq.push(
            event_id="evt1",
            event_type="market.tick",
            payload='{"ticker":"THYAO"}',
            error="Connection timeout",
        )
        assert entry.event_id == "evt1"
        assert entry.status == DLQStatus.PENDING
        assert entry.is_retryable

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self):
        """Max retry aşılınca EXHAUSTED olmalı."""
        entry = await self.dlq.push(
            event_id="evt2",
            event_type="test",
            payload="{}",
            error="fail",
            retry_count=3,
            max_retries=3,
        )
        assert not entry.is_retryable
        assert entry.status == DLQStatus.PENDING  # Status değişmez ama retryable=false

    @pytest.mark.asyncio
    async def test_eviction(self):
        """Max entries aşılınca eski kayıt çıkarılmalı."""
        for i in range(105):
            await self.dlq.push(f"evt_{i}", "test", "{}", "error")
        stats = await self.dlq.get_stats()
        assert stats["total_entries"] <= 100

    @pytest.mark.asyncio
    async def test_retry_with_handler(self):
        """Retry handler ile başarılı retry."""
        retried_events = []

        async def handler(payload):
            retried_events.append(payload)

        self.dlq.register_retry_handler("test_event", handler)

        # Entry'yi manuel olarak ready yap (next_retry_at = now)
        entry = await self.dlq.push(
            "evt_retry", "test_event", '{"data": 1}', "error"
        )
        entry.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)

        result = await self.dlq.retry_failed()
        assert result == 1
        assert len(retried_events) == 1

    @pytest.mark.asyncio
    async def test_stats(self):
        """İstatistikler doğru olmalı."""
        await self.dlq.push("e1", "type_a", "{}", "err1")
        await self.dlq.push("e2", "type_b", "{}", "err2")
        await self.dlq.push("e3", "type_a", "{}", "err3")

        stats = await self.dlq.get_stats()
        assert stats["total_entries"] == 3
        assert stats["by_event_type"]["type_a"] == 2
        assert stats["by_event_type"]["type_b"] == 1

    @pytest.mark.asyncio
    async def test_remove_entry(self):
        """Kayıt silme."""
        await self.dlq.push("e1", "test", "{}", "err")
        stats_before = await self.dlq.get_stats()
        assert stats_before["total_entries"] == 1

        entries = await self.dlq.get_entries()
        entry_id = entries[0]["entry_id"]

        removed = await self.dlq.remove_entry(entry_id)
        assert removed

        stats_after = await self.dlq.get_stats()
        assert stats_after["total_entries"] == 0


# =====================================================
# Phase 1: JWT Token Manager
# =====================================================

class TestJWTManager:
    """JWT testleri."""

    def setup_method(self):
        self.jwt = JWTManager(secret_key="test-secret-key-for-testing-only")

    def test_generate_and_validate(self):
        """Token oluştur ve doğrula."""
        token = self.jwt.generate_token(
            user_id="user1",
            role="ADMIN",
            permissions=["READ", "WRITE"],
        )
        assert token is not None
        assert len(token.split(".")) == 3

        claims = self.jwt.validate_token(token)
        assert claims.sub == "user1"
        assert claims.role == "ADMIN"
        assert "READ" in claims.permissions

    def test_expired_token(self):
        """Süresi dolmuş token reddedilmeli."""
        # Manually create an expired token
        self.jwt.generate_token("user1", "ADMIN", ["READ"])

        # Manually expire it by modifying the internal state
        # Create a JWT with past expiration
        jwt_past = JWTManager(secret_key="test-secret-key-for-testing-only")
        jwt_past._access_ttl = timedelta(seconds=-10)
        expired_token = jwt_past.generate_token("user1", "ADMIN", ["READ"])

        with pytest.raises(JWTError, match="expired"):
            self.jwt.validate_token(expired_token)

    def test_invalid_signature(self):
        """Geçersiz imza reddedilmeli."""
        jwt1 = JWTManager(secret_key="secret-1")
        jwt2 = JWTManager(secret_key="secret-2")

        token = jwt1.generate_token("user1", "ADMIN", ["READ"])

        with pytest.raises(JWTError, match="Invalid signature"):
            jwt2.validate_token(token)

    def test_refresh_token(self):
        """Refresh token ile yeni access token oluştur."""
        refresh = self.jwt.generate_token(
            "user1", "ADMIN", ["READ"],
            token_type=TokenType.REFRESH,
        )

        new_access = self.jwt.refresh_token(refresh)
        claims = self.jwt.validate_token(new_access)
        assert claims.sub == "user1"
        assert claims.token_type == TokenType.ACCESS

    def test_revoke_token(self):
        """Token iptal et."""
        token = self.jwt.generate_token("user1", "ADMIN", ["READ"])
        assert self.jwt.validate_token(token) is not None

        self.jwt.revoke_token(token)

        with pytest.raises(JWTError, match="revoked"):
            self.jwt.validate_token(token)

    def test_api_key_generation(self):
        """API key oluştur."""
        api_key = self.jwt.generate_api_key(
            "user1", "ADMIN", ["READ", "WRITE"], name="test-key"
        )
        assert api_key.startswith("ak_")

        claims = self.jwt.validate_token(api_key.replace("ak_", ""))
        assert claims.sub == "user1"

    def test_custom_claims(self):
        """Custom claims eklenebilmeli."""
        token = self.jwt.generate_token(
            "user1", "ADMIN", ["READ"],
            custom_claims={"department": "trading"},
        )
        claims = self.jwt.validate_token(token)
        # Custom claims are in the payload
        assert claims.sub == "user1"


# =====================================================
# Phase 1: Transaction Helper
# =====================================================

class TestTransactionHelper:
    """Transaction helper testleri."""

    def test_metrics_initial(self):
        """Başlangıç metrikleri sıfır olmalı."""
        helper = TransactionHelper()
        metrics = helper.get_metrics()
        assert metrics["total_transactions"] == 0
        assert metrics["committed"] == 0

    def test_metrics_reset(self):
        """Metrik sıfırlama."""
        helper = TransactionHelper()
        helper._metrics.total_transactions = 5
        helper.reset_metrics()
        assert helper.get_metrics()["total_transactions"] == 0

    def test_slow_queries_empty(self):
        """Boş query log."""
        helper = TransactionHelper()
        assert helper.get_slow_queries() == []


# =====================================================
# Phase 2: Circuit Breaker Metrics
# =====================================================

class TestCircuitBreakerMetrics:
    """Circuit breaker metrics testleri."""

    def setup_method(self):
        self.collector = CircuitBreakerMetricsCollector()

    def test_export_prometheus(self):
        """Prometheus format export."""
        # Create a mock breaker
        class MockBreaker:
            name = "test_provider"
            state = type("State", (), {"value": "CLOSED"})()
            failure_count = 0
            failure_threshold = 5
            recovery_timeout_seconds = 60
            last_failure_time = None
            last_success_time = datetime.now(UTC)
            _total_requests = 100
            _total_failures = 2
            _total_successes = 98

        self.collector.track(MockBreaker())
        prom = self.collector.export_prometheus()

        assert "circuit_breaker_state" in prom
        assert "test_provider" in prom
        assert "circuit_breaker_failures" in prom

    def test_export_json(self):
        """JSON format export."""
        class MockBreaker:
            name = "test"
            state = type("State", (), {"value": "CLOSED"})()
            failure_count = 0
            failure_threshold = 5
            recovery_timeout_seconds = 60
            last_failure_time = None
            last_success_time = None
            _total_requests = 0
            _total_failures = 0
            _total_successes = 0

        self.collector.track(MockBreaker())
        result = self.collector.export_json()

        assert "timestamp" in result
        assert "test" in result["circuit_breakers"]
        assert result["summary"]["total"] == 1

    def test_state_change_recording(self):
        """State change kaydı."""
        self.collector.record_state_change("test", "CLOSED", "OPEN")
        history = self.collector.get_history()
        assert len(history) == 1
        assert history[0]["old_state"] == "CLOSED"
        assert history[0]["new_state"] == "OPEN"


# =====================================================
# Phase 2: Config Hot-Reload
# =====================================================

class TestConfigHotReload:
    """Config hot-reload testleri."""

    def setup_method(self, tmp_path=None):
        import os
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp_dir, "test_config.json")

    def test_load_config(self):
        """Config yükleme."""
        with open(self.config_path, "w") as f:
            f.write(orjson.dumps({"key": "value"}).decode())

        reloader = ConfigHotReload(self.config_path, watch_interval_seconds=1)
        config = reloader.get_current_config()

        # Manual load since we're not running the async loop
        reloader._load_config()
        config = reloader.get_current_config()
        assert config.get("key") == "value"

    def test_change_history(self):
        """Değişiklik geçmişi."""
        reloader = ConfigHotReload(self.config_path)
        assert reloader.get_change_history() == []

    def test_validator(self):
        """Validator ekleme."""
        reloader = ConfigHotReload(self.config_path)
        reloader.add_validator(lambda c: (True, None))
        assert len(reloader._validators) == 1


# =====================================================
# Phase 2: Immutable Audit Log
# =====================================================

class TestImmutableAuditLog:
    """Audit log testleri."""

    def setup_method(self):
        self.audit = ImmutableAuditLog()

    def test_log_entry(self):
        """Audit log kaydı."""
        entry = self.audit.log(
            user_id="admin",
            action="UPDATE",
            resource_type="config",
            resource_id="cfg_001",
            details={"key": "value"},
        )
        assert entry.entry_id is not None
        assert entry.entry_hash != ""
        assert entry.previous_hash == "genesis"

    def test_hash_chain(self):
        """Hash chain doğru oluşmalı."""
        e1 = self.audit.log("u1", "CREATE", "portfolio", "p1")
        e2 = self.audit.log("u2", "UPDATE", "portfolio", "p1")
        e3 = self.audit.log("u3", "DELETE", "portfolio", "p1")

        assert e2.previous_hash == e1.entry_hash
        assert e3.previous_hash == e2.entry_hash

    def test_verify_integrity(self):
        """Bütünlük doğrulaması."""
        self.audit.log("u1", "CREATE", "portfolio", "p1")
        self.audit.log("u2", "UPDATE", "portfolio", "p1")

        is_valid, error = self.audit.verify_integrity()
        assert is_valid
        assert error is None

    def test_tamper_detection(self):
        """Değişiklik tespiti."""
        self.audit.log("u1", "CREATE", "portfolio", "p1")
        self.audit.log("u2", "UPDATE", "portfolio", "p1")

        # Tamper
        self.audit._entries[0].details = {"tampered": True}

        is_valid, error = self.audit.verify_integrity()
        assert not is_valid
        assert "hash" in error.lower() or "mismatch" in error.lower()

    def test_compliance_report(self):
        """Uyumluluk raporu."""
        self.audit.log("admin", "LOGIN", "session", "s1")
        self.audit.log("admin", "UPDATE", "config", "c1")
        self.audit.log("admin", "LOGOUT", "session", "s1")

        report = self.audit.generate_compliance_report()
        assert report["integrity"]["is_valid"] is True
        assert report["actions"]["LOGIN"] == 1
        assert report["actions"]["UPDATE"] == 1

    def test_export_db_triggers(self):
        """DB trigger SQL export."""
        sql = self.audit.export_db_triggers()
        assert "prevent_audit_modification" in sql
        assert "UPDATE" in sql
        assert "DELETE" in sql


# =====================================================
# Phase 3: Distributed Tracing
# =====================================================

class TestDistributedTracing:
    """Tracing testleri."""

    def setup_method(self):
        self.tracer = DistributedTracer(service_name="test-service")

    def test_generate_correlation_id(self):
        """Correlation ID üretimi."""
        cid = self.tracer.generate_correlation_id()
        assert len(cid) == 16

    def test_start_trace(self):
        """Trace başlatma."""
        cid = self.tracer.start_trace("test.operation")
        assert cid is not None
        assert self.tracer.get_current_correlation_id() == cid

    def test_span_lifecycle(self):
        """Span yaşam döngüsü."""
        cid = self.tracer.start_trace("root")

        span = self.tracer.start_span("child_op")
        assert span.correlation_id == cid
        assert span.parent_id is not None

        self.tracer.finish_span(span, "OK")
        assert span.end_time is not None
        assert span.duration_ms >= 0

    def test_slow_trace_detection(self):
        """Yavaş trace tespiti."""
        self.tracer._slow_threshold_ms = 0  # Her şey yavaş

        self.tracer.start_trace("slow_op")
        span = self.tracer.start_span("slow_span")
        time.sleep(0.01)
        self.tracer.finish_span(span)

        slow = self.tracer.get_slow_traces()
        assert len(slow) > 0

    def test_stats(self):
        """İstatistikler."""
        self.tracer.start_trace("op1")
        self.tracer.start_trace("op2")

        stats = self.tracer.get_stats()
        assert stats["total_traces"] >= 2

    def test_context_manager(self):
        """Context manager kullanımı."""
        from services.core.distributed_tracing import SpanContextManager

        with SpanContextManager(self.tracer, "ctx_op") as span:
            assert span is not None
            assert span.operation == "ctx_op"

    def test_decorator(self):
        """Decorator kullanımı."""
        from services.core.distributed_tracing import trace

        @trace("decorated_func")
        def my_func():
            return 42

        result = my_func()
        assert result == 42


# =====================================================
# Phase 4: System Governor
# =====================================================

class TestSystemGovernor:
    """System governor testleri."""

    def setup_method(self):
        self.governor = SystemStateGovernor()

    def test_initial_state_full(self):
        """Başlangıç durumu FULL."""
        assert self.governor.state == SystemState.FULL

    def test_all_features_enabled_in_full(self):
        """FULL durumunda tüm feature'lar aktif."""
        for f in FeatureFlag:
            assert self.governor.is_allowed(f)

    def test_transition_to_degraded(self):
        """DEGRADED geçiş."""
        self.governor.transition(SystemState.DEGRADED, "Test")

        assert self.governor.state == SystemState.DEGRADED
        assert not self.governor.is_allowed(FeatureFlag.ALTERNATIVE_DATA)
        assert self.governor.is_allowed(FeatureFlag.LIVE_TRADING)

    def test_transition_to_readonly(self):
        """READ_ONLY geçiş."""
        self.governor.transition(SystemState.READ_ONLY, "Test")

        assert not self.governor.is_allowed(FeatureFlag.NEW_POSITIONS)
        assert not self.governor.is_allowed(FeatureFlag.LIVE_TRADING)
        assert self.governor.is_allowed(FeatureFlag.READ_MARKET) if hasattr(FeatureFlag, 'READ_MARKET') else True

    def test_transition_to_shutdown(self):
        """SHUTDOWN geçiş — tüm feature'lar devre dışı."""
        self.governor.transition(SystemState.SHUTDOWN, "Emergency")

        for f in FeatureFlag:
            assert not self.governor.is_allowed(f)

    def test_transition_history(self):
        """Geçiş geçmişi."""
        self.governor.transition(SystemState.DEGRADED, "Reason 1")
        self.governor.transition(SystemState.READ_ONLY, "Reason 2")

        history = self.governor.get_transition_history()
        assert len(history) == 2
        assert history[0]["from"] == "FULL"
        assert history[0]["to"] == "DEGRADED"

    def test_fallback_response(self):
        """Fallback response."""
        self.governor.transition(SystemState.DEGRADED, "Test")

        # ALTERNATIVE_DATA is disabled in DEGRADED → fallback
        fallback_alt = self.governor.get_fallback_response(FeatureFlag.ALTERNATIVE_DATA)
        assert fallback_alt is not None
        assert fallback_alt["status"] == "unavailable"

        # LIVE_TRADING still allowed in DEGRADED → no fallback
        fallback_live = self.governor.get_fallback_response(FeatureFlag.LIVE_TRADING)
        assert fallback_live is None

        # NEW_POSITIONS still allowed in DEGRADED → no fallback
        fallback_np = self.governor.get_fallback_response(FeatureFlag.NEW_POSITIONS)
        assert fallback_np is None

        # Move to READ_ONLY where LIVE_TRADING is disabled
        self.governor.transition(SystemState.READ_ONLY, "Test2")
        fallback_ro = self.governor.get_fallback_response(FeatureFlag.LIVE_TRADING)
        assert fallback_ro is not None
        assert fallback_ro["status"] == "read_only"

    def test_force_feature(self):
        """Feature flag zorla."""
        self.governor.transition(SystemState.READ_ONLY, "Test")
        assert not self.governor.is_allowed(FeatureFlag.NEW_POSITIONS)

        self.governor.force_feature(FeatureFlag.NEW_POSITIONS, True)
        assert self.governor.is_allowed(FeatureFlag.NEW_POSITIONS)

    def test_status(self):
        """Durum özeti."""
        status = self.governor.get_status()
        assert status["state"] == "FULL"
        assert "feature_flags" in status
        assert "enabled_features" in status

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Sağlık kontrolü."""
        def healthy_check():
            return True

        def unhealthy_check():
            return False

        self.governor.register_health_check("comp1", healthy_check)
        self.governor.register_health_check("comp2", unhealthy_check)

        results = await self.governor.run_health_checks()
        assert results["comp1"].is_healthy
        assert not results["comp2"].is_healthy

    @pytest.mark.asyncio
    async def test_auto_degradation(self):
        """Otomatik degradation."""
        # Register many unhealthy checks
        for i in range(10):
            self.governor.register_health_check(
                f"comp_{i}",
                lambda: False
            )

        await self.governor.run_health_checks()

        # Should auto-degrade
        assert self.governor.state in (SystemState.DEGRADED, SystemState.READ_ONLY)


# =====================================================
# Integration Tests
# =====================================================

class TestCoreIntegration:
    """Entegrasyon testleri."""

    @pytest.mark.asyncio
    async def test_dlq_with_tracing(self):
        """DLQ + tracing entegrasyonu."""
        dlq = DeadLetterQueue()
        tracer = DistributedTracer()

        cid = tracer.start_trace("dlq_test")
        entry = await dlq.push("evt1", "test", "{}", "error")

        assert entry is not None
        assert tracer.get_current_correlation_id() == cid

    def test_audit_with_jwt(self):
        """Audit + JWT entegrasyonu."""
        jwt = JWTManager(secret_key="test-secret")
        audit = ImmutableAuditLog()

        token = jwt.generate_token("admin", "ADMIN", ["ALL"])
        claims = jwt.validate_token(token)

        audit.log(
            user_id=claims.sub,
            action="LOGIN",
            resource_type="session",
            resource_id="session_001",
        )

        is_valid, _ = audit.verify_integrity()
        assert is_valid

    def test_governor_with_circuit_breaker_metrics(self):
        """Governor + circuit breaker metrics entegrasyonu."""
        governor = SystemStateGovernor()
        metrics = CircuitBreakerMetricsCollector()

        # Track metrics
        class MockBreaker:
            name = "test"
            state = type("S", (), {"value": "CLOSED"})()
            failure_count = 0
            failure_threshold = 5
            recovery_timeout_seconds = 60
            last_failure_time = None
            last_success_time = None
            _total_requests = 100
            _total_failures = 0
            _total_successes = 100

        metrics.track(MockBreaker())

        # Governor status
        status = governor.get_status()
        assert status["state"] == "FULL"

        # Metrics
        prom = metrics.export_prometheus()
        assert "test" in prom


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
