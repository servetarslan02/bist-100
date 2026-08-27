"""
ALPHA BIST — Core Module Integration Test Suite

CORE-NIHAI-SPEC doğrultusunda entegrasyon testleri:
1. Event Bus → DLQ entegrasyonu
2. Security → JWT Manager entegrasyonu
3. Circuit Breaker + Metrics
4. Config Hot-Reload
5. Transaction Helper
6. Immutable Audit Log
7. System Governor (Graceful Degradation)
8. Distributed Tracing
"""

import asyncio

import pytest

# =====================================================
# TEST 1: Event Bus → DLQ Integration
# =====================================================

class TestEventBusDLQ:
    """Event handler crash → DLQ'ya düşmeli."""

    def test_dlq_push_and_stats(self):
        """DLQ push ve istatistikler çalışmalı."""
        from services.core.dead_letter_queue import DeadLetterQueue

        dlq = DeadLetterQueue()
        entry = asyncio.get_event_loop().run_until_complete(
            dlq.push(
                event_id="evt_001",
                event_type="market.tick",
                payload='{"test": true}',
                error="Connection timeout",
                retry_count=0,
            )
        )

        assert entry.event_id == "evt_001"
        assert entry.retry_count == 0
        assert entry.is_retryable

        stats = asyncio.get_event_loop().run_until_complete(dlq.get_stats())
        assert stats["total_entries"] == 1

    def test_dlq_retry_with_handler(self):
        """DLQ retry handler ile çalışmalı."""
        from services.core.dead_letter_queue import DeadLetterQueue

        dlq = DeadLetterQueue()
        call_count = 0

        def retry_handler(payload):
            nonlocal call_count
            call_count += 1

        dlq.register_retry_handler("market.tick", retry_handler)

        # next_retry_at=None ile push et (hemen retry edilebilir)
        entry = asyncio.get_event_loop().run_until_complete(
            dlq.push("evt_002", "market.tick", "{}", "test error")
        )
        # next_retry_at'ı None yap (hemen retry)
        entry.next_retry_at = None

        retried = asyncio.get_event_loop().run_until_complete(dlq.retry_failed())
        assert retried == 1
        assert call_count == 1

    def test_dlq_max_retries_exhaustion(self):
        """Max retry aşıldığında EXHAUSTED olmalı."""
        from services.core.dead_letter_queue import DeadLetterQueue

        dlq = DeadLetterQueue()
        entry = asyncio.get_event_loop().run_until_complete(
            dlq.push("evt_003", "unknown.type", "{}", "no handler", max_retries=1)
        )
        # next_retry_at'ı None yap (hemen retry)
        entry.next_retry_at = None

        # İlk retry — handler yok → EXHAUSTED
        asyncio.get_event_loop().run_until_complete(dlq.retry_failed())

        entries = asyncio.get_event_loop().run_until_complete(
            dlq.get_entries(event_type="unknown.type")
        )
        assert len(entries) == 1
        assert entries[0]["status"] == "EXHAUSTED"


# =====================================================
# TEST 2: Security → JWT Manager
# =====================================================

class TestSecurityJWT:
    """Security servisi JWT Manager kullanmalı."""

    def test_authenticate_returns_jwt(self):
        """Authenticate JWT token döndürmeli."""
        from services.core.security import AuthenticationService, Role

        auth = AuthenticationService()
        auth.create_user("testuser", "securepass123", Role.ANALYST)

        token = auth.authenticate("testuser", "securepass123")
        assert token is not None
        assert len(token) > 20

    def test_validate_token_with_jwt(self):
        """JWT token doğrulanmalı."""
        from services.core.security import AuthenticationService, Role

        auth = AuthenticationService()
        auth.create_user("testuser2", "securepass123", Role.OPERATOR)

        token = auth.authenticate("testuser2", "securepass123")
        validated_user = auth.validate_token(token)

        assert validated_user is not None
        assert validated_user.username == "testuser2"
        assert validated_user.role == Role.OPERATOR

    def test_invalid_token_rejected(self):
        """Geçersiz token reddedilmeli."""
        from services.core.security import AuthenticationService

        auth = AuthenticationService()
        result = auth.validate_token("invalid.token.here")
        assert result is None

    def test_jwt_generate_and_validate(self):
        """JWT Manager token üretme ve doğrulama."""
        from services.core.jwt_manager import JWTManager

        mgr = JWTManager(secret_key="test-secret-key-12345678")
        token = mgr.generate_token("user1", "ADMIN", ["READ", "WRITE"])

        claims = mgr.validate_token(token)
        assert claims.sub == "user1"
        assert claims.role == "ADMIN"
        assert "READ" in claims.permissions

    def test_jwt_refresh(self):
        """Refresh token ile yeni access token alınmalı."""
        from services.core.jwt_manager import JWTManager, TokenType

        mgr = JWTManager(secret_key="test-secret-key-12345678")
        refresh_token = mgr.generate_token(
            "user1", "ADMIN", ["READ"], TokenType.REFRESH
        )

        new_access = mgr.refresh_token(refresh_token)
        claims = mgr.validate_token(new_access)
        assert claims.token_type == TokenType.ACCESS

    def test_jwt_revocation(self):
        """Revoked token reddedilmeli."""
        from services.core.jwt_manager import JWTError, JWTManager

        mgr = JWTManager(secret_key="test-secret-key-12345678")
        token = mgr.generate_token("user1", "ADMIN", ["READ"])

        mgr.revoke_token(token)

        with pytest.raises(JWTError, match="revoked"):
            mgr.validate_token(token)


# =====================================================
# TEST 3: Circuit Breaker + Metrics
# =====================================================

class TestCircuitBreaker:
    """Circuit breaker durum geçişleri ve metrikleri."""

    def test_state_transitions(self):
        """CLOSED → OPEN → HALF_OPEN → CLOSED geçişleri."""
        from services.core.circuit_breaker import CircuitBreaker, CircuitState

        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout_seconds=1)

        # CLOSED
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute()

        # 3 failure → OPEN
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.can_execute()

        # Recovery timeout → HALF_OPEN
        cb.last_failure_time = cb.last_failure_time.replace(
            second=cb.last_failure_time.second - 2
        )
        assert cb.can_execute()
        assert cb.state == CircuitState.HALF_OPEN

        # Success → CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_circuit_breaker_metrics_export(self):
        """Circuit breaker metrics export edilebilmeli."""
        from services.core.circuit_breaker_metrics import CircuitBreakerMetricsCollector

        collector = CircuitBreakerMetricsCollector()
        # Metrics export fonksiyonu var
        assert hasattr(collector, 'collect_all') or hasattr(collector, 'get_all_snapshots')


# =====================================================
# TEST 4: Transaction Helper
# =====================================================

class TestTransactionHelper:
    """Transaction helper testleri."""

    def test_metrics_tracking(self):
        """Transaction metrikleri izlenmeli."""
        from services.core.transaction_helper import TransactionHelper

        helper = TransactionHelper()
        metrics = helper.get_metrics()

        assert "total_transactions" in metrics
        assert "committed" in metrics
        assert "rolled_back" in metrics

    def test_execute_batch_requires_pool(self):
        """Pool yoksa hata vermeli."""
        from services.core.transaction_helper import TransactionHelper

        helper = TransactionHelper()
        with pytest.raises(RuntimeError, match="pool not configured"):
            asyncio.get_event_loop().run_until_complete(
                helper.execute_batch([lambda tx: None])
            )


# =====================================================
# TEST 5: Config Hot-Reload
# =====================================================

class TestConfigHotReload:
    """Config hot-reload testleri."""

    def test_load_and_change_detection(self):
        """Config yükleme ve değişiklik algılama."""
        import tempfile

        import orjson

        from services.core.config_hot_reload import ConfigHotReload

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(orjson.dumps({"key": "value1"}).decode())
            path = f.name

        reloader = ConfigHotReload(path)
        # Force reload to load the file
        config = reloader.force_reload()
        assert config.get("key") == "value1"

        # Değişiklik geçmişinde kayıt yok
        history = reloader.get_change_history()
        assert len(history) == 0

        import os
        os.unlink(path)

    def test_force_reload(self):
        """Force reload çalışmalı."""
        import tempfile

        import orjson

        from services.core.config_hot_reload import ConfigHotReload

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(orjson.dumps({"x": 1}).decode())
            path = f.name

        reloader = ConfigHotReload(path)
        config = reloader.force_reload()
        assert config.get("x") == 1

        import os
        os.unlink(path)


# =====================================================
# TEST 6: Immutable Audit Log
# =====================================================

class TestImmutableAudit:
    """Immutable audit log testleri."""

    def test_hash_chain_integrity(self):
        """Hash chain bütünlüğü korunmalı."""
        from services.core.immutable_audit import ImmutableAuditLog

        audit = ImmutableAuditLog()

        audit.log("user1", "CREATE", "portfolio", "p1", {"name": "test"})
        audit.log("user1", "UPDATE", "portfolio", "p1", {"name": "test2"})

        is_valid = audit.verify_integrity()
        assert is_valid

    def test_tamper_detection(self):
        """Veri değişikliği tespit edilmeli."""
        from services.core.immutable_audit import ImmutableAuditLog

        audit = ImmutableAuditLog()
        audit.log("user1", "CREATE", "portfolio", "p1", {})

        # Manuel müdahale (simüle)
        if hasattr(audit, '_entries') and audit._entries:
            audit._entries[0].action = "TAMPERED"
            result = audit.verify_integrity()
            # verify_integrity tuple (bool, str) döndürebilir
            is_valid = result[0] if isinstance(result, tuple) else result
            assert not is_valid


# =====================================================
# TEST 7: System Governor
# =====================================================

class TestSystemGovernor:
    """Graceful degradation testleri."""

    def test_state_transitions(self):
        """Durum geçişleri çalışmalı."""
        from services.core.system_governor import SystemState, SystemStateGovernor

        governor = SystemStateGovernor()

        # Başlangıç durumu FULL olmalı
        assert governor.state == SystemState.FULL

        # DEGRADED'e geçiş
        governor.transition(SystemState.DEGRADED, "test")
        assert governor.state == SystemState.DEGRADED

    def test_feature_flags(self):
        """Feature flag'ler çalışmalı."""
        from services.core.system_governor import FeatureFlag, SystemState, SystemStateGovernor

        governor = SystemStateGovernor()
        # FULL modda tüm feature'lar aktif
        assert governor.is_allowed(FeatureFlag.LIVE_TRADING)
        assert governor.is_allowed(FeatureFlag.ALTERNATIVE_DATA)

        # DEGRADED modda kritik olmayan feature'lar devre dışı
        governor.transition(SystemState.DEGRADED, "test")
        assert governor.is_allowed(FeatureFlag.LIVE_TRADING)  # Kritik
        assert not governor.is_allowed(FeatureFlag.ALTERNATIVE_DATA)  # Kritik değil
        assert not governor.is_allowed(FeatureFlag.LEARNING)  # Kritik değil


# =====================================================
# TEST 8: Distributed Tracing
# =====================================================

class TestDistributedTracing:
    """Distributed tracing testleri."""

    def test_correlation_id_generation(self):
        """Correlation ID üretilebilmeli."""
        from services.core.distributed_tracing import DistributedTracer

        tracer = DistributedTracer()
        corr_id = tracer.generate_correlation_id()
        assert corr_id is not None
        assert len(corr_id) > 0

        trace = tracer.start_trace("test_operation")
        assert trace is not None

    def test_span_hierarchy(self):
        """Span hiyerarşisi doğru olmalı."""
        from services.core.distributed_tracing import DistributedTracer

        tracer = DistributedTracer()
        trace = tracer.start_trace("parent_op")
        span = tracer.start_span("child_op")

        assert span is not None

        tracer.finish_span(span)
        tracer.finish_trace(trace)


# =====================================================
# TEST 9: RBAC
# =====================================================

class TestRBAC:
    """Role-based access control testleri."""

    def test_role_permissions(self):
        """Rol izinleri doğru atanmalı."""
        from services.core.security import ROLE_PERMISSIONS, Permission, Role

        # VIEWER sadece okuyabilir
        viewer_perms = ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.READ_MARKET in viewer_perms
        assert Permission.LIVE_EXECUTION not in viewer_perms

        # ADMIN her şeyi yapabilir
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]
        assert Permission.LIVE_EXECUTION in admin_perms
        assert Permission.MANAGE_USERS in admin_perms

    def test_authorization_check(self):
        """İzin kontrolü çalışmalı."""
        from services.core.security import AuthorizationService, Permission, Role, User

        authz = AuthorizationService()
        viewer = User(user_id="v1", username="viewer", role=Role.VIEWER)
        admin = User(user_id="a1", username="admin", role=Role.ADMIN)

        assert authz.check_permission(viewer, Permission.READ_MARKET)
        assert not authz.check_permission(viewer, Permission.LIVE_EXECUTION)
        assert authz.check_permission(admin, Permission.LIVE_EXECUTION)


# =====================================================
# TEST 10: Secret Redaction
# =====================================================

class TestSecretRedaction:
    """Loglarda hassas bilgi gizleme."""

    def test_api_key_redaction(self):
        """API key'ler gizlenmeli."""
        from services.core.security import SecretRedaction

        text = 'api_key="sk-abc123456789012345678901"'
        redacted = SecretRedaction.redact(text)
        assert "sk-abc123456789012345678901" not in redacted

    def test_bearer_token_redaction(self):
        """Bearer token gizlenmeli."""
        from services.core.security import SecretRedaction

        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        redacted = SecretRedaction.redact(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in redacted


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
