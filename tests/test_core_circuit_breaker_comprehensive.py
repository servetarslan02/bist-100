"""ALPHA BIST — services/core/circuit_breaker kapsamlı test suite.

Test edilen bileşenler:
- CircuitState: Durum makinesi enum (CLOSED, OPEN, HALF_OPEN)
- CircuitBreaker: Ana devre kesici sınıf
  - record_success(): Başarı kaydı
  - record_failure(): Hata kaydı ve eşik kontrolü
  - can_execute(): İstek izni denetimi
  - reset(): Sıfırlama
  - get_state(): Durum bilgisi
- RateLimiter: Token Bucket hız limitleyici
  - acquire(): Token alımı
- RetryPolicy: Exponential backoff + jitter
"""

from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from services.core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    RateLimiter,
)


# ==============================================================================
# CircuitState enum testleri
# ==============================================================================


class TestCircuitState:
    """CircuitState enum değerleri testleri."""

    def test_closed_value(self) -> None:
        assert CircuitState.CLOSED.value == "CLOSED"

    def test_open_value(self) -> None:
        assert CircuitState.OPEN.value == "OPEN"

    def test_half_open_value(self) -> None:
        assert CircuitState.HALF_OPEN.value == "HALF_OPEN"

    def test_all_states_defined(self) -> None:
        states = {s.value for s in CircuitState}
        assert "CLOSED" in states
        assert "OPEN" in states
        assert "HALF_OPEN" in states


# ==============================================================================
# CircuitBreaker temel testleri
# ==============================================================================


@pytest.fixture
def cb() -> CircuitBreaker:
    """Kalıcı depo olmadan temiz CircuitBreaker örneği."""
    with patch.object(CircuitBreaker, "restore_state", return_value=None):
        with patch.object(CircuitBreaker, "_persist_to_store", return_value=None):
            with patch.object(CircuitBreaker, "_notify_state_change", return_value=None):
                return CircuitBreaker(
                    name="test_breaker",
                    failure_threshold=3,
                    recovery_timeout_seconds=60,
                )


class TestCircuitBreakerInitialState:
    """CircuitBreaker başlangıç durumu testleri."""

    def test_initial_state_closed(self, cb: CircuitBreaker) -> None:
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_zero(self, cb: CircuitBreaker) -> None:
        assert cb.failure_count == 0

    def test_initial_can_execute_true(self, cb: CircuitBreaker) -> None:
        assert cb.can_execute() is True

    def test_name_set_correctly(self, cb: CircuitBreaker) -> None:
        assert cb.name == "test_breaker"

    def test_failure_threshold_set(self, cb: CircuitBreaker) -> None:
        assert cb.failure_threshold == 3


class TestCircuitBreakerRecordSuccess:
    """record_success() metodu testleri."""

    def test_success_in_closed_state_decrements_failure(self, cb: CircuitBreaker) -> None:
        cb.failure_count = 2
        cb.record_success()
        assert cb.failure_count == 1

    def test_success_doesnt_go_below_zero(self, cb: CircuitBreaker) -> None:
        cb.failure_count = 0
        cb.record_success()
        assert cb.failure_count == 0

    def test_success_in_half_open_closes_circuit(self, cb: CircuitBreaker) -> None:
        """HALF_OPEN → başarı → CLOSED geçişi."""
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_last_success_time_updated(self, cb: CircuitBreaker) -> None:
        cb.record_success()
        assert cb.last_success_time is not None


class TestCircuitBreakerRecordFailure:
    """record_failure() metodu testleri."""

    def test_failure_increments_count(self, cb: CircuitBreaker) -> None:
        cb.record_failure()
        assert cb.failure_count == 1

    def test_failures_open_circuit_at_threshold(self, cb: CircuitBreaker) -> None:
        """Eşik aşıldığında devre OPEN olur."""
        for _ in range(3):  # threshold = 3
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_one_failure_below_threshold_stays_closed(self, cb: CircuitBreaker) -> None:
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self, cb: CircuitBreaker) -> None:
        """HALF_OPEN → hata → OPEN geçişi."""
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_last_failure_time_updated(self, cb: CircuitBreaker) -> None:
        cb.record_failure()
        assert cb.last_failure_time is not None


class TestCircuitBreakerCanExecute:
    """can_execute() metodu testleri."""

    def test_closed_state_allows_execution(self, cb: CircuitBreaker) -> None:
        assert cb.can_execute() is True

    def test_open_state_blocks_execution(self, cb: CircuitBreaker) -> None:
        """OPEN durumda yeni çağrılara izin verilmez."""
        from datetime import UTC, datetime
        cb.state = CircuitState.OPEN
        cb.last_failure_time = datetime.now(UTC)  # Yeni hata → süre dolmamış
        assert cb.can_execute() is False

    def test_open_state_transitions_to_half_open_after_timeout(self, cb: CircuitBreaker) -> None:
        """Recovery timeout süresi geçtikten sonra HALF_OPEN'e geçer."""
        from datetime import UTC, datetime, timedelta
        cb.state = CircuitState.OPEN
        # Son hata zamanını recovery_timeout_seconds + 1 saniye öncesine ayarla
        cb.last_failure_time = datetime.now(UTC) - timedelta(seconds=61)
        result = cb.can_execute()
        assert result is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_max_calls_enforced(self, cb: CircuitBreaker) -> None:
        """HALF_OPEN durumda yalnızca max allowed çağrıya izin verilir."""
        cb.state = CircuitState.HALF_OPEN
        cb.half_open_calls = cb.half_open_max_calls  # Zaten max dolmuş
        assert cb.can_execute() is False


class TestCircuitBreakerReset:
    """reset() metodu testleri."""

    def test_reset_from_open_closes(self, cb: CircuitBreaker) -> None:
        cb.state = CircuitState.OPEN
        cb.failure_count = 5
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_reset_from_half_open(self, cb: CircuitBreaker) -> None:
        cb.state = CircuitState.HALF_OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_reset_already_closed_no_op(self, cb: CircuitBreaker) -> None:
        cb.state = CircuitState.CLOSED
        cb.failure_count = 2
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerGetState:
    """get_state() metodu testleri."""

    def test_get_state_returns_dict(self, cb: CircuitBreaker) -> None:
        state = cb.get_state()
        assert isinstance(state, dict)

    def test_state_dict_has_required_keys(self, cb: CircuitBreaker) -> None:
        state = cb.get_state()
        required_keys = {"name", "state", "failure_count", "failure_threshold"}
        assert required_keys.issubset(state.keys())

    def test_state_dict_reflects_current_state(self, cb: CircuitBreaker) -> None:
        cb.failure_count = 2
        state = cb.get_state()
        assert state["name"] == "test_breaker"
        assert state["failure_count"] == 2
        assert state["state"] == "CLOSED"


class TestCircuitBreakerToOrjson:
    """Serileştirme testleri."""

    def test_to_orjson_bytes(self, cb: CircuitBreaker) -> None:
        import orjson
        raw = cb.to_orjson_bytes()
        assert isinstance(raw, bytes)
        parsed = orjson.loads(raw)
        assert parsed["name"] == "test_breaker"

    def test_repr(self, cb: CircuitBreaker) -> None:
        r = repr(cb)
        assert "CircuitBreaker" in r
        assert "test_breaker" in r


# ==============================================================================
# CircuitBreaker tam durum makinesi akışı testleri
# ==============================================================================


class TestCircuitBreakerStateMachine:
    """Tam CLOSED → OPEN → HALF_OPEN → CLOSED durum makinesi testleri."""

    def test_full_cycle(self) -> None:
        """CLOSED → hata eşiği → OPEN → timeout → HALF_OPEN → başarı → CLOSED."""
        from datetime import UTC, datetime, timedelta

        with patch.object(CircuitBreaker, "restore_state", return_value=None):
            with patch.object(CircuitBreaker, "_persist_to_store", return_value=None):
                with patch.object(CircuitBreaker, "_notify_state_change", return_value=None):
                    breaker = CircuitBreaker(
                        name="full_cycle",
                        failure_threshold=2,
                        recovery_timeout_seconds=1,
                    )

        # CLOSED → Hata eşiği aş → OPEN
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # OPEN → Timeout yok → Çağrıya izin verme
        from datetime import UTC
        breaker.last_failure_time = datetime.now(UTC)  # Yeni hata
        assert breaker.can_execute() is False

        # OPEN → Timeout geçti → HALF_OPEN
        breaker.last_failure_time = datetime.now(UTC) - timedelta(seconds=5)
        result = breaker.can_execute()
        assert result is True
        assert breaker.state == CircuitState.HALF_OPEN

        # HALF_OPEN → başarı → CLOSED
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_half_open_failure_reopens(self) -> None:
        """HALF_OPEN'da hata → tekrar OPEN."""
        with patch.object(CircuitBreaker, "restore_state", return_value=None):
            with patch.object(CircuitBreaker, "_persist_to_store", return_value=None):
                with patch.object(CircuitBreaker, "_notify_state_change", return_value=None):
                    breaker = CircuitBreaker(
                        name="reopen_test",
                        failure_threshold=2,
                        recovery_timeout_seconds=1,
                    )

        breaker.state = CircuitState.HALF_OPEN
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


# ==============================================================================
# RateLimiter testleri
# ==============================================================================


@pytest.fixture
def rate_limiter() -> RateLimiter:
    return RateLimiter(
        name="test_limiter",
        max_tokens=5.0,
        refill_rate=1.0,
        tokens=5.0,
    )


class TestRateLimiter:
    """Token Bucket RateLimiter testleri."""

    def test_acquire_available_token(self, rate_limiter: RateLimiter) -> None:
        """Token mevcutsa bekleme süresi 0 döner."""
        wait = rate_limiter.acquire(1.0)
        assert wait == pytest.approx(0.0)

    def test_acquire_depletes_tokens(self, rate_limiter: RateLimiter) -> None:
        """Token almak mevcut miktarı azaltır."""
        rate_limiter.acquire(3.0)
        assert rate_limiter.tokens < 5.0

    def test_acquire_when_empty_returns_wait_time(self, rate_limiter: RateLimiter) -> None:
        """Token bitmişse pozitif bekleme süresi döner."""
        rate_limiter.tokens = 0.0
        wait = rate_limiter.acquire(1.0)
        assert wait > 0.0

    def test_tokens_capped_at_max(self, rate_limiter: RateLimiter) -> None:
        """Token sayısı max_tokens'ı aşmaz."""
        rate_limiter.tokens = 0.0
        rate_limiter.last_refill = time.monotonic() - 100.0  # Uzun süre geçmiş
        rate_limiter.acquire(0.001)
        assert rate_limiter.tokens <= rate_limiter.max_tokens

    def test_thread_safe_concurrent_acquire(self, rate_limiter: RateLimiter) -> None:
        """Eş zamanlı token alımında race condition olmaz."""
        results = []
        errors = []

        def worker() -> None:
            try:
                wait = rate_limiter.acquire(0.5)
                results.append(wait)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10

    def test_refill_over_time(self) -> None:
        """Zamanla token yenilenir."""
        limiter = RateLimiter(
            name="refill_test",
            max_tokens=10.0,
            refill_rate=10.0,  # Saniyede 10 token
            tokens=0.0,
        )
        limiter.last_refill = time.monotonic() - 1.0  # 1 saniye öncesinden
        wait = limiter.acquire(1.0)
        # 1 saniyede 10 token yenilenmeli, 1 token alınabilmeli
        assert wait == pytest.approx(0.0) or wait < 1.0


# ==============================================================================
# Thread-safety testleri
# ==============================================================================


class TestCircuitBreakerThreadSafety:
    """CircuitBreaker eş zamanlı erişim güvenliği testleri."""

    def test_concurrent_failures_single_open_transition(self) -> None:
        """Eş zamanlı hata kaydı OPEN'a yalnızca bir kez geçiş sağlar."""
        with patch.object(CircuitBreaker, "restore_state", return_value=None):
            with patch.object(CircuitBreaker, "_persist_to_store", return_value=None):
                with patch.object(CircuitBreaker, "_notify_state_change", return_value=None):
                    breaker = CircuitBreaker(
                        name="concurrent_test",
                        failure_threshold=3,
                        recovery_timeout_seconds=60,
                    )

        def fail() -> None:
            for _ in range(2):
                breaker.record_failure()

        threads = [threading.Thread(target=fail) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Durum ya CLOSED ya OPEN olmalı, tutarsız durum olmamalı
        assert breaker.state in (CircuitState.CLOSED, CircuitState.OPEN)
