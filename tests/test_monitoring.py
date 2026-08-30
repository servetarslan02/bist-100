from __future__ import annotations

#!/usr/bin/env python3
from typing import Any

"""
Monitoring & Observability Testleri (Pytest Uyumlu)

Kapsam:
- PortfolioMonitor health report
- Prometheus metrics format
- Lock metrics API
- Portfolio health API
- Health status değişim testleri
- Metrics sync
- Invariant failure tracking
"""


import pytest

from services.core.db_lock import (
    get_health_report,
    get_lock_metrics,
)
from services.core.monitoring import PortfolioMonitor
from services.core.observability import prometheus_metrics


class MockPortfolioService:
    """Offline resilient mock portfolio service."""

    def __init__(self, initial_capital: float = 100000.0):
        """Otomatik eklendi."""
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions = {}
        self._invariant_ok = True

    def get_health_status(self) -> dict:
        """Otomatik eklendi."""
        return {
            "status": "HEALTHY" if self._invariant_ok else "UNHEALTHY",
            "portfolio": {
                "cash": self._cash,
                "invariant_check": self._invariant_ok,
            },
        }


@pytest.mark.asyncio
async def test_monitor_health_report() -> Any:
    """Portfolio monitor health report doğru bilgi vermeli."""
    svc = MockPortfolioService()
    monitor = PortfolioMonitor()
    monitor.bind(svc)

    health = await monitor.get_health_detailed()

    assert "status" in health, "status eksik"
    assert "portfolio" in health, "portfolio eksik"
    assert "locks" in health, "locks eksik"
    assert "components" in health, "components eksik"
    assert "timestamp" in health, "timestamp eksik"
    assert health["status"] in ("HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN")


@pytest.mark.asyncio
async def test_prometheus_format() -> Any:
    """Prometheus text format doğru olmalı."""
    svc = MockPortfolioService()
    monitor = PortfolioMonitor()
    monitor.bind(svc)

    await monitor.sync_metrics()
    text = await monitor.get_prometheus_text()

    assert "portfolio_equity" in text
    assert "portfolio_cash" in text
    assert "portfolio_positions_count" in text
    assert "# TYPE portfolio_equity gauge" in text


@pytest.mark.asyncio
async def test_lock_metrics_api() -> Any:
    """Lock metrics API doğru bilgi vermeli."""
    svc = MockPortfolioService()
    monitor = PortfolioMonitor()
    monitor.bind(svc)

    result = await monitor.get_lock_metrics_api()

    assert "metrics" in result
    assert "health" in result
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_portfolio_api() -> Any:
    """Portfolio API doğru bilgi vermeli."""
    svc = MockPortfolioService()
    monitor = PortfolioMonitor()
    monitor.bind(svc)

    result = await monitor.get_portfolio_api()

    assert "portfolio" in result
    assert "accounting" in result
    assert "health" in result
    assert result["health"]["status"] == "HEALTHY"


@pytest.mark.asyncio
async def test_health_status_change() -> Any:
    """Health status duruma göre değişmeli."""
    svc = MockPortfolioService()
    monitor = PortfolioMonitor()
    monitor.bind(svc)

    health = await monitor.get_health_detailed()
    assert health["status"] in ("HEALTHY", "DEGRADED")

    # Invariant failure simülasyonu
    svc._invariant_ok = False
    health = await monitor.get_health_detailed()
    assert health["status"] == "UNHEALTHY"


@pytest.mark.asyncio
async def test_metrics_sync() -> Any:
    """Metrics sync doğru değerler üretmeli."""
    svc = MockPortfolioService()
    monitor = PortfolioMonitor()
    monitor.bind(svc)

    # Sync
    await monitor.sync_metrics()

    # Prometheus gauge'ları kontrol et
    m = prometheus_metrics.get_metrics()
    gauges = m.get("gauges", {})

    assert "portfolio_equity" in gauges
    assert "portfolio_cash" in gauges
    assert "portfolio_positions_count" in gauges


@pytest.mark.asyncio
async def test_monitor_without_service() -> Any:
    """Service bağlanmadan monitor çağırmak hata vermemeli."""
    monitor = PortfolioMonitor()

    health = await monitor.get_health_detailed()
    assert health.get("status") in ("UNKNOWN", "HEALTHY", "DEGRADED")

    result = await monitor.get_portfolio_api()
    assert "portfolio" in result

    text = await monitor.get_prometheus_text()
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_lock_health_degraded() -> Any:
    """Lock timeout sonrası DEGRADED status."""
    metrics = get_lock_metrics("test_degraded")
    metrics.record_timeout()

    health = metrics.health_status()
    assert "recent_timeout" in health.get("issues", [])

    report = get_health_report()
    assert report.get("overall_status") in ("HEALTHY", "DEGRADED")
