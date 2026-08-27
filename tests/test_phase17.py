"""
ALPHA BIST — FAZ 17 Test Suite

Observability, Recovery, Config System testleri.
"""

import asyncio
import sys


def test_observability():
    """Observability & Monitoring testleri."""
    from services.core.observability import (
        config_manager,
        cost_monitor,
        distributed_tracing,
        health_checker,
        performance_monitor,
        prometheus_metrics,
    )

    passed = 0
    failed = 0

    # 1. Prometheus metrics - counter
    prometheus_metrics._counters.clear()
    prometheus_metrics.inc("events_total")
    prometheus_metrics.inc("events_total")
    prometheus_metrics.inc("events_total", labels={"type": "tick"})
    assert prometheus_metrics._counters["events_total"] == 2
    assert prometheus_metrics._counters['events_total{type=tick}'] == 1
    passed += 1
    print(f"  ✓ Counter: {prometheus_metrics._counters}")

    # 2. Prometheus metrics - gauge
    prometheus_metrics.set_gauge("portfolio_equity", 105000.0)
    assert prometheus_metrics._gauges["portfolio_equity"] == 105000.0
    passed += 1
    print(f"  ✓ Gauge: {prometheus_metrics._gauges}")

    # 3. Prometheus metrics - histogram
    prometheus_metrics._histograms.clear()
    for v in [10, 20, 30, 40, 50]:
        prometheus_metrics.observe("api_latency_ms", v)
    metrics = prometheus_metrics.get_metrics()
    assert "api_latency_ms" in metrics["histograms"]
    assert metrics["histograms"]["api_latency_ms"]["count"] == 5
    passed += 1
    print(f"  ✓ Histogram: avg={metrics['histograms']['api_latency_ms']['avg']:.1f}ms")

    # 4. Distributed tracing
    distributed_tracing._traces.clear()
    trace_id = distributed_tracing.start_trace("market_scan")
    assert len(trace_id) == 16
    distributed_tracing.add_span(trace_id, "fetch_data", 150.0)
    distributed_tracing.add_span(trace_id, "compute_features", 50.0)
    trace = distributed_tracing.get_trace(trace_id)
    assert len(trace) == 3  # start + 2 spans
    passed += 1
    print(f"  ✓ Tracing: {len(trace)} spans")

    # 5. Performance monitor
    performance_monitor._latencies.clear()
    performance_monitor.record_latency("api_call", 100)
    performance_monitor.record_latency("api_call", 150)
    performance_monitor.record_latency("api_call", 200)
    stats = performance_monitor.get_stats("api_call")
    assert stats["count"] == 3
    assert stats["avg_ms"] == 150.0
    passed += 1
    print(f"  ✓ Performance: avg={stats['avg_ms']}ms")

    # 6. Cost monitor
    cost_monitor._costs.clear()
    cost_monitor._total_cost = 0
    cost_monitor.record("openai", "gpt-4", 1000, 0.03)
    cost_monitor.record("openai", "gpt-4", 500, 0.015)
    summary = cost_monitor.get_summary()
    assert summary["total_cost_usd"] == 0.045
    assert summary["total_entries"] == 2
    passed += 1
    print(f"  ✓ Cost: ${summary['total_cost_usd']}")

    # 7. Config manager
    config_manager._config.clear()
    config_manager._versions.clear()
    config_manager.set("risk.max_position_pct", 15.0, actor="admin", reason="increase limit")
    assert config_manager.get("risk.max_position_pct") == 15.0
    history = config_manager.get_history("risk.max_position_pct")
    assert len(history) == 1
    assert history[0]["actor"] == "admin"
    passed += 1
    print(f"  ✓ Config: {config_manager.get('risk.max_position_pct')}")

    # 8. Health checker
    health_checker._components.clear()
    health_checker.register("database")
    health_checker.register("redis")
    health_checker.update_status("database", "HEALTHY")
    health_checker.update_status("redis", "DEGRADED", "slow response")
    result = health_checker.check_all()
    assert result["overall"] == "DEGRADED"
    assert result["components"]["database"]["status"] == "HEALTHY"
    passed += 1
    print(f"  ✓ Health: overall={result['overall']}")

    return passed, failed


def test_recovery():
    """Recovery & Resilience testleri."""
    from services.core.recovery import (
        event_replay,
        failure_injector,
        graceful_shutdown,
        startup_recovery,
    )

    passed = 0
    failed = 0

    # 1. Event replay
    event_replay._event_log.clear()
    event_replay.log_event("market.tick", {"ticker": "THYAO", "price": 300}, "2026-08-15T10:00:00")
    event_replay.log_event("market.tick", {"ticker": "THYAO", "price": 301}, "2026-08-15T10:05:00")
    event_replay.log_event("market.tick", {"ticker": "THYAO", "price": 302}, "2026-08-15T10:10:00")
    assert event_replay.get_log_count() == 3

    replayed = []
    count = event_replay.replay_from("2026-08-15T10:03:00", lambda e: replayed.append(e))
    assert count == 2  # 10:05 and 10:10
    passed += 1
    print(f"  ✓ Event replay: {count} events replayed")

    # 2. Event replay range
    replayed2 = []
    count2 = event_replay.replay_range("2026-08-15T10:00:00", "2026-08-15T10:06:00", lambda e: replayed2.append(e))
    assert count2 == 2  # 10:00 and 10:05
    passed += 1
    print(f"  ✓ Replay range: {count2} events")

    # 3. Graceful shutdown
    graceful_shutdown._shutdown_handlers.clear()
    graceful_shutdown._is_shutting_down = False
    shutdown_called = []
    graceful_shutdown.register_handler(lambda: shutdown_called.append(True))
    asyncio.get_event_loop().run_until_complete(graceful_shutdown.shutdown("test"))
    assert len(shutdown_called) == 1
    assert graceful_shutdown.is_shutting_down
    passed += 1
    print(f"  ✓ Graceful shutdown: {len(shutdown_called)} handlers called")

    # 4. Startup recovery
    result = asyncio.get_event_loop().run_until_complete(
        startup_recovery.recover(snapshot={"portfolio": {"value": 100000}})
    )
    assert result["success"]
    assert len(result["steps"]) >= 3
    passed += 1
    print(f"  ✓ Startup recovery: {len(result['steps'])} steps, success={result['success']}")

    # 5. Failure injector
    failure_injector.clear_all()
    failure_injector.inject("database", "down")
    assert failure_injector.is_failing("database")
    assert not failure_injector.is_failing("redis")
    failure_injector.clear("database", "down")
    assert not failure_injector.is_failing("database")
    passed += 1
    print("  ✓ Failure injector: inject/clear")

    # 6. Multiple failures
    failure_injector.inject("redis", "down")
    failure_injector.inject("llm", "timeout")
    active = failure_injector.get_active()
    assert len(active) == 2
    failure_injector.clear_all()
    assert len(failure_injector.get_active()) == 0
    passed += 1
    print(f"  ✓ Multiple failures: {len(active)} active")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 17 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Observability", test_observability),
        ("Recovery", test_recovery),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            print(f"  ✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
