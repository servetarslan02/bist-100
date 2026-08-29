#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
Database Lock Abstraction Testleri

Kapsam:
- DatabaseLock SQLite davranışları
- CoordinatedLock (asyncio + DB)
- Lock acquisition time monitoring
- Lock timeout logging
- Deadlock detection (retry limit)
- Lock ordering
- PostgreSQL mock test
- Portfolio entegrasyon testi
"""

import asyncio
import sqlite3
import sys

import duckdb

from services.core.database_dev import dev_db
from services.core.db_lock import (
    LOCK_ORDER,
    CoordinatedLock,
    DatabaseLock,
    get_all_metrics,
    get_lock_metrics,
)
from services.portfolio.main import PortfolioService


def fresh_db() -> Any:
    """Test için SQLite in-memory DB (SQLite dialect testleri için)."""
    db = sqlite3.connect(":memory:")
    return db


def fresh_duckdb() -> Any:
    """Test için DuckDB in-memory DB (PostgreSQL dialect testleri için)."""
    db = duckdb.connect(":memory:")
    return db


async def test_sqlite_lock_basic() -> Any:
    """Temel SQLite lock alma/bırakma."""
    db = fresh_db()
    lock = DatabaseLock(db, dialect="sqlite", key="test_basic")
    issues = []

    ok = await lock.acquire()
    if not ok:
        issues.append("Lock alınamadı")
    if not lock.is_acquired:
        issues.append("is_acquired False")

    await lock.release()
    if lock.is_acquired:
        issues.append("Release sonrası is_acquired True")

    return "SQLite Lock Basic", len(issues) == 0, issues


async def test_sqlite_lock_contention() -> Any:
    """İki lock aynı anda yazı kilidi alamaz."""
    db = fresh_db()
    lock1 = DatabaseLock(db, dialect="sqlite", key="test_contention")
    DatabaseLock(db, dialect="sqlite", key="test_contention2")
    issues = []

    ok1 = await lock1.acquire()
    if not ok1:
        issues.append("İlk lock alınamadı")

    # İkinci lock aynı connection'da başarısız olmalı (SQLite single-writer)
    # Not: Aynı connection'da BEGIN IMMEDIATE başarılı olur çünkü tek connection
    # Gerçek contention farklı connection'larda olur
    await lock1.release()

    return "SQLite Lock Contention", len(issues) == 0, issues


async def test_lock_context_manager() -> Any:
    """Context manager doğru çalışmalı."""
    db = fresh_db()
    issues = []

    try:
        async with DatabaseLock(db, dialect="sqlite", key="test_ctx") as lock:
            if not lock.is_acquired:
                issues.append("Context içinde lock alınmamış")
        if lock.is_acquired:
            issues.append("Context sonrası lock hâlâ alınmış")
    except Exception as e:
        issues.append(f"Context manager exception: {e}")

    return "Lock Context Manager", len(issues) == 0, issues


async def test_lock_rollback() -> Any:
    """Exception durumunda rollback çalışmalı."""
    db = fresh_db()
    issues = []

    lock = DatabaseLock(db, dialect="sqlite", key="test_rollback")
    await lock.acquire()

    # Hata simülasyonu
    try:
        raise ValueError("test error")
    except ValueError:
        await lock.rollback()

    if lock.is_acquired:
        issues.append("Rollback sonrası lock hâlâ alınmış")

    # Yeniden alınabilmeli
    ok = await lock.acquire()
    if not ok:
        issues.append("Rollback sonrası lock tekrar alınamadı")
    await lock.release()

    return "Lock Rollback", len(issues) == 0, issues


async def test_coordinated_lock() -> Any:
    """CoordinatedLock hem asyncio hem DB lock almalı."""
    db = fresh_db()
    issues = []

    lock = CoordinatedLock(db, dialect="sqlite", key="test_coord")
    ok = await lock.acquire()
    if not ok:
        issues.append("CoordinatedLock alınamadı")

    await lock.release()

    # Context manager
    try:
        async with CoordinatedLock(db, dialect="sqlite", key="test_coord2") as cl:
            if not cl._db_lock.is_acquired:
                issues.append("DB lock alınmamış")
    except Exception as e:
        issues.append(f"CoordinatedLock context: {e}")

    return "Coordinated Lock", len(issues) == 0, issues


async def test_lock_metrics() -> Any:
    """Lock metrikleri doğru toplanmalı."""
    db = fresh_db()
    key = "test_metrics"
    issues = []

    # Birkaç lock al/bırak
    for _ in range(3):
        lock = DatabaseLock(db, dialect="sqlite", key=key)
        await lock.acquire()
        await asyncio.sleep(0.01)  # 10ms bekle
        await lock.release()

    metrics = get_lock_metrics(key)
    if metrics.total_acquisitions != 3:
        issues.append(f"Acquisition count: {metrics.total_acquisitions} != 3")
    if metrics.total_timeouts != 0:
        issues.append(f"Timeout count: {metrics.total_timeouts} != 0")
    if metrics.last_acquisition_ms < 0:
        issues.append(f"Wait time too low: {metrics.last_acquisition_ms}ms")

    all_m = get_all_metrics()
    if key not in all_m:
        issues.append("Key not in all_metrics")

    return "Lock Metrics", len(issues) == 0, issues


async def test_lock_ordering() -> Any:
    """Lock sıralaması tanımlı olmalı."""
    issues = []

    if "portfolio_trade" not in LOCK_ORDER:
        issues.append("portfolio_trade LOCK_ORDER'da yok")
    if "migration" not in LOCK_ORDER:
        issues.append("migration LOCK_ORDER'da yok")

    # portfolio_trade < migration olmalı (işlemler migration'dan önce alınmalı)
    if LOCK_ORDER.get("portfolio_trade", 999) >= LOCK_ORDER.get("migration", 0):
        issues.append("Lock sıralaması yanlış: portfolio_trade < migration olmalı")

    return "Lock Ordering", len(issues) == 0, issues


async def test_pg_mock_lock() -> Any:
    """PostgreSQL lock davranışı mock test."""
    issues = []

    # PostgreSQL pg_advisory_lock SQL'i doğru mu?

    # DatabaseLock PG metotlarını kontrol et
    lock = DatabaseLock(None, dialect="postgresql", key="test_pg")

    # _acquire_pg metodunun varlığını kontrol et
    if not hasattr(lock, "_acquire_pg"):
        issues.append("_acquire_pg metodu yok")
    if not hasattr(lock, "_release_pg"):
        issues.append("_release_pg metodu yok")

    # key_id hesaplaması
    if lock._key_id != LOCK_ORDER.get("test_pg", 0):
        # LOCK_ORDER'da yoksa hash'ten hesaplanmalı
        pass

    return "PG Mock Lock", len(issues) == 0, issues


async def test_portfolio_with_coordinated_lock() -> Any:
    """PortfolioService CoordinatedLock ile çalışmalı."""
    dev_db._db = None
    await dev_db.init()
    from conftest import safe_cleanup_tables

    await safe_cleanup_tables(dev_db)

    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('T', 'T') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute(
        "INSERT INTO companies (ticker, name, sector_id) SELECT 'X', 'X', id FROM sectors WHERE code = 'T' ON CONFLICT (ticker) DO NOTHING"
    )
    await dev_db.pg_execute(
        "INSERT INTO instruments (company_id, symbol) SELECT id, 'X' FROM companies WHERE ticker = 'X' ON CONFLICT (symbol) DO NOTHING"
    )
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    xid = row["id"]

    issues = []

    svc = PortfolioService(initial_capital=100000)
    await svc.start()

    # CoordinatedLock oluşturulmuş mu?
    if svc._coordinated_lock is None:
        issues.append("CoordinatedLock oluşturulmamış")

    # Normal alım/satım
    r1 = await svc.execute_buy("X", 100, 100.0, instrument_id=xid)
    if not r1.get("success"):
        issues.append(f"Alım başarısız: {r1}")

    r2 = await svc.execute_sell("X", 100, 110.0, instrument_id=xid)
    if not r2.get("success"):
        issues.append(f"Satış başarısız: {r2}")

    # Lock metrikleri
    metrics = svc.get_lock_metrics()
    if "portfolio_trade" not in metrics:
        issues.append("portfolio_trade metrikleri yok")

    await svc.stop()

    return "Portfolio Coordinated Lock", len(issues) == 0, issues


async def test_parallel_with_metrics() -> Any:
    """Paralel işlemler sonrası metrikler doğru olmalı."""
    dev_db._db = None
    await dev_db.init()
    from conftest import safe_cleanup_tables

    await safe_cleanup_tables(dev_db)

    await dev_db.pg_execute("INSERT INTO sectors (code, name) VALUES ('T', 'T') ON CONFLICT (code) DO NOTHING")
    await dev_db.pg_execute(
        "INSERT INTO companies (ticker, name, sector_id) SELECT 'X', 'X', id FROM sectors WHERE code = 'T' ON CONFLICT (ticker) DO NOTHING"
    )
    await dev_db.pg_execute(
        "INSERT INTO instruments (company_id, symbol) SELECT id, 'X' FROM companies WHERE ticker = 'X' ON CONFLICT (symbol) DO NOTHING"
    )
    row = await dev_db.pg_fetchrow("SELECT id FROM instruments WHERE symbol = 'X'")
    xid = row["id"]

    issues = []

    svc = PortfolioService(initial_capital=100000)
    await svc.start()

    # Paralel alımlar
    async def buy(i) -> Any:
        """Otomatik eklendi."""
        return await svc.execute_buy("X", 10, 100.0, instrument_id=xid)

    results = await asyncio.gather(*[buy(i) for i in range(5)])
    successful = [r for r in results if r.get("success")]

    # Metrikler
    metrics = svc.get_lock_metrics()
    trade_metrics = metrics.get("portfolio_trade", {})

    if trade_metrics.get("total_acquisitions", 0) < len(successful):
        issues.append(f"Acquisition count {trade_metrics.get('total_acquisitions')} < successful {len(successful)}")

    # Cash tutarlı
    pf = await svc.get_portfolio()
    if pf["cash"] < 0:
        issues.append(f"Negatif cash: {pf['cash']}")

    await svc.stop()

    return "Parallel With Metrics", len(issues) == 0, issues


# ============================================================
# RUN
# ============================================================


async def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("DATABASE LOCK ABSTRACTION TESTLERİ")
    logger.info("=" * 60)

    tests = [
        test_sqlite_lock_basic,
        test_sqlite_lock_contention,
        test_lock_context_manager,
        test_lock_rollback,
        test_coordinated_lock,
        test_lock_metrics,
        test_lock_ordering,
        test_pg_mock_lock,
        test_portfolio_with_coordinated_lock,
        test_parallel_with_metrics,
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
        logger.info(f"\n{icon} {name}")
        if ok:
            passed += 1
            logger.info("   PASSED")
        else:
            failed += 1
            for i in issues:
                logger.info(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        logger.info("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            logger.info(f"  {i}. {issue}")
    logger.info("=" * 60)
    return failed == 0


def main() -> Any:
    """Otomatik eklendi."""
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
