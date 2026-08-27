"""
ALPHA BIST — FAZ 5.4 Test Suite

Broker Abstraction + Risk Gate + Circuit Breaker
"""

import sys
import time

# ────────────────────────────────────────────────────────────
# 1. Broker — valid order
# ────────────────────────────────────────────────────────────

def test_broker_valid_order():
    """Geçerli order fill edilmeli."""
    from services.core.broker import Order, OrderSide, OrderStatus, PaperBroker

    passed = 0
    failed = 0

    broker = PaperBroker(initial_capital=1_000_000)
    order = Order(
        order_id="", ticker="THYAO", side=OrderSide.BUY.value,
        quantity=100, price=300.0, idempotency_key="test_valid"
    )

    result = broker.submit_order(order)
    assert result.status == OrderStatus.FILLED.value, f"Expected FILLED, got {result.status}"
    assert result.filled_quantity == 100
    assert result.avg_fill_price == 300.0
    assert broker.get_positions().get("THYAO", {}).get("qty") == 100

    print("  ✓ Valid order: FILLED, qty=100, price=300")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 2. Broker — rejected order (insufficient capital)
# ────────────────────────────────────────────────────────────

def test_broker_rejected_order():
    """Yetersiz sermaye ile order reddedilmeli."""
    from services.core.broker import Order, OrderSide, OrderStatus, PaperBroker

    passed = 0
    failed = 0

    broker = PaperBroker(initial_capital=1000)
    order = Order(
        order_id="", ticker="THYAO", side=OrderSide.BUY.value,
        quantity=100, price=300.0
    )

    result = broker.submit_order(order)
    assert result.status == OrderStatus.REJECTED.value, f"Expected REJECTED, got {result.status}"
    assert "capital" in result.reject_reason.lower() or "insufficient" in result.reject_reason.lower()

    print(f"  ✓ Rejected order: {result.status}, reason={result.reject_reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 3. Broker — duplicate order
# ────────────────────────────────────────────────────────────

def test_broker_duplicate_order():
    """Aynı idempotency_key ile iki order engellenmeli."""
    from services.core.broker import Order, OrderSide, PaperBroker

    passed = 0
    failed = 0

    broker = PaperBroker(initial_capital=1_000_000)

    order1 = Order(
        order_id="", ticker="THYAO", side=OrderSide.BUY.value,
        quantity=100, price=300.0, idempotency_key="dup_key_1"
    )
    result1 = broker.submit_order(order1)

    order2 = Order(
        order_id="", ticker="THYAO", side=OrderSide.BUY.value,
        quantity=100, price=300.0, idempotency_key="dup_key_1"
    )
    result2 = broker.submit_order(order2)

    assert result2.order_id == result1.order_id, "Duplicate should return same order"
    assert broker.get_positions().get("THYAO", {}).get("qty") == 100, "Should not double-fill"

    print(f"  ✓ Duplicate blocked: same order_id={result1.order_id[:8]}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 4. Broker — cancel order
# ────────────────────────────────────────────────────────────

def test_broker_cancel_order():
    """Order iptal edilebilmeli."""
    from services.core.broker import Order, OrderSide, PaperBroker

    passed = 0
    failed = 0

    broker = PaperBroker(initial_capital=1_000_000)
    order = Order(
        order_id="cancel_test", ticker="THYAO", side=OrderSide.BUY.value,
        quantity=100, price=300.0
    )
    broker.submit_order(order)

    # Already filled — cancel should fail
    cancelled = broker.cancel_order("cancel_test")
    assert not cancelled, "Filled order should not be cancellable"

    print("  ✓ Cancel: filled order not cancellable")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 5. Risk gate — valid order allowed
# ────────────────────────────────────────────────────────────

def test_risk_gate_valid():
    """Geçerli order risk gate'den geçmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate(max_position_pct=10, max_single_order_pct=5, min_confidence=0.3)

    decision = gate.check_order(
        ticker="THYAO", side="BUY", quantity=10, price=300,
        portfolio_value=1_000_000, current_positions={},
        model_confidence=0.7, market_open=True, data_valid=True
    )

    assert decision.allowed, f"Should be allowed: {decision.reason}"
    assert decision.checks_passed >= 7
    assert decision.checks_failed == 0

    print(f"  ✓ Valid order: allowed, passed={decision.checks_passed}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 6. Risk gate — rejected (position too large)
# ────────────────────────────────────────────────────────────

def test_risk_gate_position_limit():
    """Pozisyon limiti aşıldığında reddedilmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate(max_position_pct=10, max_single_order_pct=50)

    decision = gate.check_order(
        ticker="THYAO", side="BUY", quantity=1000, price=300,
        portfolio_value=1_000_000, current_positions={},
        model_confidence=0.7
    )

    # 1000 * 300 = 300,000 → 30% > 10% limit
    assert not decision.allowed, f"Should be rejected: {decision.reason}"
    assert "position" in decision.reason.lower() or "order" in decision.reason.lower()

    print(f"  ✓ Position limit: rejected, reason={decision.reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 7. Risk gate — confidence rejection
# ────────────────────────────────────────────────────────────

def test_risk_gate_confidence():
    """Düşük confidence reddedilmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate(min_confidence=0.5)

    decision = gate.check_order(
        ticker="THYAO", side="BUY", quantity=10, price=300,
        portfolio_value=1_000_000, current_positions={},
        model_confidence=0.1
    )

    assert not decision.allowed
    assert "confidence" in decision.reason.lower()

    print(f"  ✓ Confidence rejection: {decision.reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 8. Risk gate — market closed
# ────────────────────────────────────────────────────────────

def test_risk_gate_market_closed():
    """Market kapalıyken order reddedilmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate()

    decision = gate.check_order(
        ticker="THYAO", side="BUY", quantity=10, price=300,
        portfolio_value=1_000_000, current_positions={},
        market_open=False
    )

    assert not decision.allowed
    assert "market" in decision.reason.lower() or "closed" in decision.reason.lower()

    print(f"  ✓ Market closed: {decision.reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 9. Risk gate — stale data
# ────────────────────────────────────────────────────────────

def test_risk_gate_stale_data():
    """Eski veri ile order reddedilmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate()

    decision = gate.check_order(
        ticker="THYAO", side="BUY", quantity=10, price=300,
        portfolio_value=1_000_000, current_positions={},
        data_valid=False
    )

    assert not decision.allowed
    assert "data" in decision.reason.lower()

    print(f"  ✓ Stale data: {decision.reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 10. Circuit breaker — open blocks orders
# ────────────────────────────────────────────────────────────

def test_circuit_breaker_open():
    """Circuit açıkken order reddedilmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate()

    decision = gate.check_order(
        ticker="THYAO", side="BUY", quantity=10, price=300,
        portfolio_value=1_000_000, current_positions={},
        circuit_open=True
    )

    assert not decision.allowed
    assert "circuit" in decision.reason.lower()

    print(f"  ✓ Circuit open: {decision.reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 11. Circuit breaker — recovery
# ────────────────────────────────────────────────────────────

def test_circuit_breaker_recovery():
    """Circuit breaker recovery çalışmalı."""
    from services.core.circuit_breaker import CircuitBreaker, CircuitState

    passed = 0
    failed = 0

    cb = CircuitBreaker(
        name="test", failure_threshold=3,
        recovery_timeout_seconds=0.01, state=CircuitState.CLOSED
    )

    # 3 failure → OPEN
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.can_execute()

    # recovery_timeout bekle → HALF_OPEN
    time.sleep(0.02)
    assert cb.can_execute()
    assert cb.state == CircuitState.HALF_OPEN

    # Success → CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED

    print("  ✓ Circuit recovery: CLOSED→OPEN→HALF_OPEN→CLOSED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 12. Circuit breaker — half-open failure
# ────────────────────────────────────────────────────────────

def test_circuit_breaker_half_open_failure():
    """Half-open'da failure tekrar OPEN yapmalı."""
    from services.core.circuit_breaker import CircuitBreaker, CircuitState

    passed = 0
    failed = 0

    cb = CircuitBreaker(
        name="test", failure_threshold=2,
        recovery_timeout_seconds=0.01, state=CircuitState.CLOSED
    )

    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    time.sleep(0.02)
    assert cb.can_execute()  # HALF_OPEN

    cb.record_failure()  # Half-open failure
    assert cb.state == CircuitState.OPEN

    print("  ✓ Half-open failure: re-OPENED")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 13. Broker — sell without position
# ────────────────────────────────────────────────────────────

def test_broker_sell_no_position():
    """Pozisyon olmadan satış reddedilmeli."""
    from services.core.broker import Order, OrderSide, OrderStatus, PaperBroker

    passed = 0
    failed = 0

    broker = PaperBroker(initial_capital=1_000_000)
    order = Order(
        order_id="", ticker="THYAO", side=OrderSide.SELL.value,
        quantity=100, price=300.0
    )

    result = broker.submit_order(order)
    assert result.status == OrderStatus.REJECTED.value
    assert "position" in result.reject_reason.lower() or "insufficient" in result.reject_reason.lower()

    print(f"  ✓ Sell no position: {result.reject_reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# 14. Risk gate — portfolio exposure
# ────────────────────────────────────────────────────────────

def test_risk_gate_portfolio_exposure():
    """Portföy exposure limiti aşıldığında reddedilmeli."""
    from services.core.risk_gate import RiskGate

    passed = 0
    failed = 0

    gate = RiskGate(max_portfolio_exposure_pct=90)

    # %95 exposure
    positions = {
        "A": {"qty": 100, "avg_cost": 5000},  # 500,000
        "B": {"qty": 100, "avg_cost": 4500},  # 450,000
    }
    sum(p["qty"] * p["avg_cost"] for p in positions.values())  # 950,000

    decision = gate.check_order(
        ticker="C", side="BUY", quantity=10, price=100,
        portfolio_value=1_000_000, current_positions=positions,
        model_confidence=0.7
    )

    # 950,000 / 1,000,000 = 95% > 90%
    assert not decision.allowed
    assert "exposure" in decision.reason.lower()

    print(f"  ✓ Portfolio exposure: {decision.reason}")
    passed += 1

    return passed, failed


# ────────────────────────────────────────────────────────────
# Ana çalıştırıcı
# ────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("Broker valid order", test_broker_valid_order),
        ("Broker rejected order", test_broker_rejected_order),
        ("Broker duplicate order", test_broker_duplicate_order),
        ("Broker cancel order", test_broker_cancel_order),
        ("Broker sell no position", test_broker_sell_no_position),
        ("Risk gate valid", test_risk_gate_valid),
        ("Risk gate position limit", test_risk_gate_position_limit),
        ("Risk gate confidence", test_risk_gate_confidence),
        ("Risk gate market closed", test_risk_gate_market_closed),
        ("Risk gate stale data", test_risk_gate_stale_data),
        ("Risk gate portfolio exposure", test_risk_gate_portfolio_exposure),
        ("Circuit breaker open", test_circuit_breaker_open),
        ("Circuit breaker recovery", test_circuit_breaker_recovery),
        ("Circuit breaker half-open failure", test_circuit_breaker_half_open_failure),
    ]

    total_passed = 0
    total_failed = 0

    print("=" * 70)
    print("FAZ 5.4 — Broker + Risk Gate + Circuit Breaker")
    print("=" * 70)

    for name, test_fn in tests:
        print(f"\n▸ {name}")
        try:
            p, f = test_fn()
            total_passed += p
            total_failed += f
            if f > 0:
                print(f"  ⚠ {f} FAILED")
        except Exception as e:
            import traceback
            print(f"  ✗ EXCEPTION: {e}")
            traceback.print_exc()
            total_failed += 1

    print("\n" + "=" * 70)
    print(f"SONUÇ: {total_passed} passed, {total_failed} failed")
    print("=" * 70)

    return total_failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
