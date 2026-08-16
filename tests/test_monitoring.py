#!/usr/bin/env python3
"""
Monitoring & Observability Testleri

Kapsam:
- PortfolioMonitor health report
- Prometheus metrics format
- Lock metrics API
- Portfolio health API
- Health status değişim testleri
- Metrics sync
- Invariant failure tracking
"""

import sys
import os
import asyncio
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.core.monitoring import PortfolioMonitor
from services.core.db_lock import (
    DatabaseLock, get_lock_metrics, get_all_metrics, get_health_report,
    LockMetrics,
)
from services.core.observability import prometheus_metrics
from services.portfolio.main import PortfolioService
from services.core.database_dev import dev_db


async def setup_portfolio():
    """Test portfolio servisi oluştur."""
    dev_db._db = None
    await dev_db.init()
    for t in ['daily_pnl', 'equity_snapshots', 'position_history', 'cash_ledger', 'positions', 'portfolios']:
        try:
            await dev_db.pg_execute(f"DELETE FROM {t}")
        except:
            pass
    await dev_db.pg_execute("INSERT OR IGNORE INTO sectors (code, name) VALUES ('T', 'T')")
    await dev_db.pg_execute("INSERT OR IGNORE INTO companies (ticker, name, sector_id) SELECT 'X', 'X', id FROM sectors WHERE code = 'T'")
    await dev_db.pg_execute("INSERT OR IGNORE INTO instruments (company_id, symbol) SELECT id, 'X' FROM companies WHERE ticker = 'X'")

    svc = PortfolioService(initial_capital=100000)
    await svc.start()
    return svc


async def test_monitor_health_report():
    """Portfolio monitor health report doğru bilgi vermeli."""
    svc = await setup_portfolio()
    monitor = PortfolioMonitor()
    monitor.bind(svc)
    issues = []

    # Alım yap
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    await svc.execute_buy("X", 100, 100.0, instrument_id=row["id"])

    health = await monitor.get_health_detailed()

    if "status" not in health:
        issues.append("status eksik")
    if "portfolio" not in health:
        issues.append("portfolio eksik")
    if "locks" not in health:
        issues.append("locks eksik")
    if "components" not in health:
        issues.append("components eksik")
    if "timestamp" not in health:
        issues.append("timestamp eksik")

    if health["status"] not in ("HEALTHY", "DEGRADED", "UNHEALTHY"):
        issues.append(f"Geçersiz status: {health['status']}")

    await svc.stop()
    return "Monitor Health Report", len(issues) == 0, issues


async def test_prometheus_format():
    """Prometheus text format doğru olmalı."""
    svc = await setup_portfolio()
    monitor = PortfolioMonitor()
    monitor.bind(svc)
    issues = []

    # Metrik üret
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    await svc.execute_buy("X", 50, 100.0, instrument_id=row["id"])
    await monitor.sync_metrics()

    text = await monitor.get_prometheus_text()

    # Prometheus format kontrolü
    if "portfolio_equity" not in text:
        issues.append("portfolio_equity metrik eksik")
    if "portfolio_cash" not in text:
        issues.append("portfolio_cash metrik eksik")
    if "portfolio_positions_count" not in text:
        issues.append("portfolio_positions_count metrik eksik")

    # TYPE declarations
    if "# TYPE portfolio_equity gauge" not in text:
        issues.append("TYPE declaration eksik")

    await svc.stop()
    return "Prometheus Format", len(issues) == 0, issues


async def test_lock_metrics_api():
    """Lock metrics API doğru bilgi vermeli."""
    svc = await setup_portfolio()
    monitor = PortfolioMonitor()
    monitor.bind(svc)
    issues = []

    # Lock operasyonları yap
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    await svc.execute_buy("X", 10, 100.0, instrument_id=row["id"])

    result = await monitor.get_lock_metrics_api()

    if "metrics" not in result:
        issues.append("metrics eksik")
    if "health" not in result:
        issues.append("health eksik")
    if "timestamp" not in result:
        issues.append("timestamp eksik")

    # portfolio_trade metrikleri olmalı
    if "portfolio_trade" not in result.get("metrics", {}):
        issues.append("portfolio_trade metrikleri eksik")

    await svc.stop()
    return "Lock Metrics API", len(issues) == 0, issues


async def test_portfolio_api():
    """Portfolio API doğru bilgi vermeli."""
    svc = await setup_portfolio()
    monitor = PortfolioMonitor()
    monitor.bind(svc)
    issues = []

    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    await svc.execute_buy("X", 100, 250.0, instrument_id=row["id"])

    result = await monitor.get_portfolio_api()

    if "portfolio" not in result:
        issues.append("portfolio eksik")
    if "accounting" not in result:
        issues.append("accounting eksik")
    if "health" not in result:
        issues.append("health eksik")
    if "lock_metrics" not in result:
        issues.append("lock_metrics eksik")

    # Portfolio değerleri
    pf = result.get("portfolio", {})
    if pf.get("positions_count", 0) != 1:
        issues.append(f"Pozisyon sayısı: {pf.get('positions_count')}")

    await svc.stop()
    return "Portfolio API", len(issues) == 0, issues


async def test_health_status_change():
    """Health status duruma göre değişmeli."""
    svc = await setup_portfolio()
    monitor = PortfolioMonitor()
    monitor.bind(svc)
    issues = []

    # Normal durum — HEALTHY
    health = await monitor.get_health_detailed()
    if health["status"] != "HEALTHY":
        issues.append(f"Normal durum: {health['status']} (beklenen: HEALTHY)")

    # Invariant failure simülasyonu
    svc._pm._cash = -999999  # Kasıtlı boz
    monitor._invariant_failure_count = 0
    await monitor.sync_metrics()

    health = await monitor.get_health_detailed()
    # Invariant bozulduğunda UNHEALTHY olmalı
    if not svc._pm.get_accounting_summary().get("invariant_check", True):
        if health["status"] != "UNHEALTHY":
            issues.append(f"Invariant bozuldu ama status: {health['status']} (beklenen: UNHEALTHY)")

    svc._pm._cash = 100000  # Geri al
    await svc.stop()
    return "Health Status Change", len(issues) == 0, issues


async def test_metrics_sync():
    """Metrics sync doğru değerler üretmeli."""
    svc = await setup_portfolio()
    monitor = PortfolioMonitor()
    monitor.bind(svc)
    issues = []

    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    await svc.execute_buy("X", 100, 100.0, instrument_id=row["id"])

    # Sync
    await monitor.sync_metrics()

    # Prometheus gauge'ları kontrol et
    m = prometheus_metrics.get_metrics()
    gauges = m.get("gauges", {})

    if "portfolio_equity" not in gauges:
        issues.append("portfolio_equity gauge eksik")
    elif gauges["portfolio_equity"] <= 0:
        issues.append(f"portfolio_equity: {gauges['portfolio_equity']}")

    if "portfolio_cash" not in gauges:
        issues.append("portfolio_cash gauge eksik")
    elif gauges["portfolio_cash"] >= 100000:
        issues.append(f"portfolio_cash düşmemiş: {gauges['portfolio_cash']}")

    if "portfolio_positions_count" not in gauges:
        issues.append("portfolio_positions_count gauge eksik")
    elif gauges["portfolio_positions_count"] != 1:
        issues.append(f"positions_count: {gauges['portfolio_positions_count']}")

    await svc.stop()
    return "Metrics Sync", len(issues) == 0, issues




async def test_monitor_without_service():
    """Service bağlanmadan monitor çağırmak hata vermemeli."""
    monitor = PortfolioMonitor()
    issues = []

    health = await monitor.get_health_detailed()
    if health.get("status") == "UNKNOWN":
        pass  # Beklenen

    result = await monitor.get_portfolio_api()
    if "error" not in result:
        issues.append("Service bağlı değilken error dönmeli")

    text = await monitor.get_prometheus_text()
    if not isinstance(text, str):
        issues.append("Prometheus text string olmalı")

    return "Monitor Without Service", len(issues) == 0, issues


async def test_lock_health_degraded():
    """Lock timeout sonrası DEGRADED status."""
    issues = []

    # Lock metrics oluştur — timeout ile
    metrics = get_lock_metrics("test_degraded")
    metrics.record_timeout()

    health = metrics.health_status()
    if "recent_timeout" not in health.get("issues", []):
        issues.append("recent_timeout tespit edilemedi")

    # Global health report
    report = get_health_report()
    if report.get("overall_status") not in ("HEALTHY", "DEGRADED"):
        issues.append(f"Overall status: {report.get('overall_status')}")

    return "Lock Health Degraded", len(issues) == 0, issues


# ============================================================
# RUN
# ============================================================

async def run_all():
    print("=" * 60)
    print("MONITORING & OBSERVABILITY TESTLERİ")
    print("=" * 60)

    tests = [
        test_monitor_health_report,
        test_prometheus_format,
        test_lock_metrics_api,
        test_portfolio_api,
        test_health_status_change,
        test_metrics_sync,
        test_monitor_without_service,
        test_lock_health_degraded,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = await test_func()
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}")
        if ok:
            passed += 1
            print("   PASSED")
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)
    return failed == 0


def main():
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
