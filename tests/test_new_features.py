"""
Yeni özellikler için testler:
- Circuit Breaker
- Memory TTL
- Trace Context
- Dead Letter Queue
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from services.agents.circuit_breaker import CircuitBreaker, CircuitBreakerLLMClient, CircuitState
from services.agents.agent_memory import AgentMemory, EpisodicMemory, MemoryEntry, WorkingMemory
from services.agents.communication_bus import AgentCommunicationBus, AgentMessage
from services.agents.agent_system import AgentRole
from services.agents.trace_context import TraceContext, get_trace_id, get_ticker


# =====================================================
# CIRCUIT BREAKER TESTS
# =====================================================


class TestCircuitBreaker:
    """Circuit Breaker testleri."""

    def test_initial_state_closed(self):
        """Başlangıç durumu CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_opens_after_threshold(self):
        """Eşik aşıldığında OPEN olur."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_rejects_when_open(self):
        """OPEN durumunda çağrı reddedilir."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False
        assert cb._stats.rejected_calls == 1

    def test_half_open_after_timeout(self):
        """Timeout sonra HALF_OPEN olur."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.can_execute() is True

    def test_closes_on_success_in_half_open(self):
        """HALF_OPEN'da başarılı çağrı → CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_in_half_open(self):
        """HALF_OPEN'da başarısız çağrı → OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        """Başarılı çağrı failure count'ı sıfırlar."""
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2
        cb.record_success()
        assert cb._failure_count == 0

    def test_stats(self):
        """İstatistikler doğru tutulur."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["total_calls"] == 3
        assert stats["successful_calls"] == 2
        assert stats["failed_calls"] == 1

    def test_repr(self):
        """repr çalışır."""
        cb = CircuitBreaker(failure_threshold=5)
        assert "CLOSED" in repr(cb)


# =====================================================
# MEMORY TTL TESTS
# =====================================================


class TestMemoryTTL:
    """Memory TTL testleri."""

    def test_working_memory_ttl_auto_set(self):
        """Working memory'ye eklenen entry'ye otomatik TTL atanır."""
        wm = WorkingMemory(max_items=10, ttl_hours=1)
        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
        )
        wm.add(entry)
        assert entry.expires_at is not None
        exp = datetime.fromisoformat(entry.expires_at)
        assert exp > datetime.now(UTC)

    def test_working_memory_cleanup_expired(self):
        """Süresi dolan working memory kayıtları temizlenir."""
        wm = WorkingMemory(max_items=10, ttl_hours=1)
        # Süresi dolmuş entry
        expired_entry = MemoryEntry(
            task_id="expired", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        )
        # Geçerli entry
        valid_entry = MemoryEntry(
            task_id="valid", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
        wm.add(expired_entry)
        wm.add(valid_entry)
        assert len(wm.items) == 2

        cleaned = wm.cleanup_expired()
        assert cleaned == 1
        assert len(wm.items) == 1
        assert wm.items[0].task_id == "valid"

    def test_episodic_memory_ttl_auto_set(self):
        """Episodic memory'ye eklenen entry'ye otomatik TTL atanır."""
        em = EpisodicMemory(max_items=10, ttl_days=7)
        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
        )
        em.add(entry)
        assert entry.expires_at is not None

    def test_episodic_memory_cleanup_expired(self):
        """Süresi dolan episodic memory kayıtları temizlenir."""
        em = EpisodicMemory(max_items=10, ttl_days=7)
        expired_entry = MemoryEntry(
            task_id="expired", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )
        em.add(expired_entry)
        assert len(em.episodes) == 1

        cleaned = em.cleanup_expired()
        assert cleaned == 1
        assert len(em.episodes) == 0
        assert "expired" not in em._episode_index

    def test_agent_memory_cleanup(self):
        """AgentMemory.cleanup_expired() tüm katmanları temizler."""
        mem = AgentMemory("TECHNICAL")
        # Expired entry ekle
        expired = MemoryEntry(
            task_id="expired", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        )
        mem.working.add(expired)
        result = mem.cleanup_expired()
        assert result["working"] >= 1

    def test_memory_entry_is_expired(self):
        """MemoryEntry.is_expired() doğru çalışır."""
        # Süresi dolmuş
        expired = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        )
        assert expired.is_expired() is True

        # Süresi dolmamış
        valid = MemoryEntry(
            task_id="t2", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
        assert valid.is_expired() is False

        # TTL yok
        no_ttl = MemoryEntry(
            task_id="t3", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
        )
        assert no_ttl.is_expired() is False


# =====================================================
# TRACE CONTEXT TESTS
# =====================================================


class TestTraceContext:
    """Trace Context testleri."""

    def test_trace_context_sets_id(self):
        """TraceContext trace ID oluşturur."""
        with TraceContext(ticker="THYAO") as trace:
            assert len(trace.trace_id) == 12
            assert get_trace_id() == trace.trace_id
            assert get_ticker() == "THYAO"

    def test_trace_context_custom_id(self):
        """Özel trace ID atanabilir."""
        with TraceContext(ticker="THYAO", trace_id="custom123") as trace:
            assert trace.trace_id == "custom123"
            assert get_trace_id() == "custom123"

    def test_trace_context_cleanup(self):
        """Context çıkışında temizlenir."""
        with TraceContext(ticker="THYAO") as trace:
            pass
        assert get_trace_id() == ""
        assert get_ticker() == ""

    def test_trace_context_set_phase(self):
        """Faz ayarlanabilir."""
        with TraceContext(ticker="THYAO") as trace:
            trace.set_phase("PHASE_1")
            fields = trace.log_fields()
            assert fields["phase"] == "PHASE_1"

    def test_trace_context_elapsed(self):
        """Geçen süre hesaplanır."""
        with TraceContext(ticker="THYAO") as trace:
            time.sleep(0.01)
            assert trace.elapsed_ms() > 0

    def test_trace_context_log_fields(self):
        """log_fields doğru alanları döndürür."""
        with TraceContext(ticker="THYAO") as trace:
            fields = trace.log_fields()
            assert "trace_id" in fields
            assert "ticker" in fields
            assert "phase" in fields


# =====================================================
# DEAD LETTER QUEUE TESTS
# =====================================================


class TestDeadLetterQueue:
    """Dead Letter Queue testleri."""

    def test_send_with_retry_success(self):
        """Başarılı mesaj DLQ'ya gitmez."""
        bus = AgentCommunicationBus()
        msg = AgentMessage(
            sender=AgentRole.TECHNICAL,
            receiver=AgentRole.FUNDAMENTAL,
            task_id="t1",
            message_type="CONTEXT",
            payload={"data": "test"},
        )
        result = bus.send_with_retry(msg)
        assert result is True
        assert len(bus.get_dlq()) == 0

    def test_dlq_empty_by_default(self):
        """Başlangıçta DLQ boş."""
        bus = AgentCommunicationBus()
        assert len(bus.get_dlq()) == 0

    def test_retry_dlq_empty(self):
        """Boş DLQ'da retry hiçbir şey yapmaz."""
        bus = AgentCommunicationBus()
        assert bus.retry_dlq() == 0

    def test_clear_clears_dlq(self):
        """clear() DLQ'yu da temizler."""
        bus = AgentCommunicationBus()
        # DLQ'ya manuel ekleme
        bus._dlq.append({"test": "data"})
        bus.clear()
        assert len(bus.get_dlq()) == 0

    def test_repr_includes_dlq(self):
        """repr DLQ bilgisini içerir."""
        bus = AgentCommunicationBus()
        assert "dlq=0" in repr(bus)


# =====================================================
# ENTEGRASYON TESTLERİ
# =====================================================


class TestIntegration:
    """Entegrasyon testleri."""

    def test_circuit_breaker_llm_client_rejects_when_open(self):
        """OPEN durumunda CircuitBreakerLLMClient çağrı yapmaz."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Mock client
        class MockClient:
            async def generate_with_retry(self, **kwargs):
                return "should not reach"

        wrapped = CircuitBreakerLLMClient(MockClient(), cb)

        async def test():
            response = await wrapped.generate_with_retry(
                system_prompt="test", user_prompt="test"
            )
            return response

        response = asyncio.run(test())
        assert response.success is False
        assert "Circuit breaker" in response.error

    def test_memory_entry_to_dict_with_ttl(self):
        """TTL'li entry to_dict() expires_at içerir."""
        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        )
        d = entry.to_dict()
        assert "expires_at" in d

    def test_memory_entry_to_dict_without_ttl(self):
        """TTL'siz entry to_dict() expires_at içermez."""
        entry = MemoryEntry(
            task_id="t1", agent_role="TECHNICAL", ticker="THYAO",
            direction="LONG", confidence=0.8, reasoning="test",
            timestamp=datetime.now(UTC).isoformat(),
        )
        d = entry.to_dict()
        assert "expires_at" not in d
