#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
Async Provider Testleri

Kapsam:
- Async HTTP client
- Provider async migration
- Timeout/retry behavior
- Config loading
"""

import asyncio
import os
import sys

import orjson

from services.core.async_http import AsyncHTTPClient, close_all_clients, get_client

# =====================================================
# ASYNC HTTP CLIENT TESTS
# =====================================================


async def test_client_creation() -> Any:
    """Client oluşturma çalışmalı."""
    issues = []

    client = AsyncHTTPClient(timeout=5.0, max_retries=2)
    if client._timeout.total != 5.0:
        issues.append(f"Timeout: {client._timeout.total}")
    if client._max_retries != 2:
        issues.append(f"Max retries: {client._max_retries}")

    await client.close()
    assert len(issues) == 0, f"Client Creation: {issues}"


async def test_client_singleton() -> Any:
    """Singleton client aynı instance döndürmeli."""
    issues = []

    c1 = get_client("test_singleton", timeout=10)
    c2 = get_client("test_singleton", timeout=20)

    if c1 is not c2:
        issues.append("Singleton farklı instance döndürdü")

    await close_all_clients()
    assert len(issues) == 0, f"Client Singleton: {issues}"


async def test_client_timeout() -> Any:
    """Timeout çalışmalı."""

    client = AsyncHTTPClient(timeout=0.1, max_retries=1)

    # Çok kısa timeout ile istek
    result = await client.get_text("http://httpbin.org/delay/5")

    # Timeout olmalı: çok kısa timeout ile uzak sunucuya istek atıldığında
    # result None dönmeli veya exception fırlatılmalı
    timeout_detected = (result is None) or (isinstance(result, str) and "timeout" in result.lower())
    await client.close()
    assert timeout_detected, (
        f"Client Timeout: beklenen None veya timeout hatası, alınan: {type(result).__name__}={result!r}"
    )


async def test_client_retry() -> Any:
    """Retry mekanizması çalışmalı."""
    issues = []

    client = AsyncHTTPClient(timeout=1.0, max_retries=2, retry_delay_s=0.1)

    # Var olmayan URL — retry denemeli
    result = await client.get_text("http://localhost:1/nonexistent")

    if result is not None:
        issues.append("Var olmayan URL sonuç döndürdü")

    await client.close()
    assert len(issues) == 0, f"Client Retry: {issues}"


async def test_client_close() -> Any:
    """Client kapatma çalışmalı."""
    issues = []

    client = AsyncHTTPClient()
    session = await client._get_session()

    if session.closed:
        issues.append("Session başlangıçta kapalı")

    await client.close()

    if not session.closed:
        issues.append("Close sonrası session açık")

    assert len(issues) == 0, f"Client Close: {issues}"


async def test_context_manager() -> Any:
    """Context manager çalışmalı."""
    issues = []

    async with AsyncHTTPClient() as client:
        session = await client._get_session()
        if session.closed:
            issues.append("Context içinde session kapalı")

    # Context sonrası kapalı olmalı
    # Not: client._session hâlâ referans tutuyor ama closed=True
    assert len(issues) == 0, f"Context Manager: {issues}"


# =====================================================
# PROVIDER ASYNC TESTS
# =====================================================


async def test_bist_provider_async() -> Any:
    """BIST provider async methodlara sahip olmalı."""
    issues = []

    from services.ingestion.providers.bist_provider import bist_provider

    if not hasattr(bist_provider, "fetch_index_data"):
        issues.append("fetch_index_data yok")

    # Method'un async olduğunu kontrol et
    import inspect

    if not inspect.iscoroutinefunction(bist_provider.fetch_index_data):
        issues.append("fetch_index_data async değil")
    if not inspect.iscoroutinefunction(bist_provider.fetch_market_summary):
        issues.append("fetch_market_summary async değil")
    if not inspect.iscoroutinefunction(bist_provider.fetch_stock_price):
        issues.append("fetch_stock_price async değil")

    await bist_provider.close()
    assert len(issues) == 0, f"BIST Provider Async: {issues}"


async def test_kap_provider_async() -> Any:
    """KAP provider async methodlara sahip olmalı."""
    issues = []

    import inspect

    from services.ingestion.providers.kap_provider import kap_provider

    if not inspect.iscoroutinefunction(kap_provider.fetch_disclosures):
        issues.append("fetch_disclosures async değil")
    if not inspect.iscoroutinefunction(kap_provider.fetch_company_info):
        issues.append("fetch_company_info async değil")

    await kap_provider.close()
    assert len(issues) == 0, f"KAP Provider Async: {issues}"


async def test_news_provider_async() -> Any:
    """News provider zaten async olmalı."""
    issues = []

    import inspect

    from services.ingestion.providers.news_provider import NewsProvider

    provider = NewsProvider()
    if not inspect.iscoroutinefunction(provider.fetch_financial_news_rss):
        issues.append("fetch_news async değil")

    assert len(issues) == 0, f"News Provider Async: {issues}"


# =====================================================
# CONFIG TESTS
# =====================================================


async def test_config_file_exists() -> Any:
    """Config dosyaları mevcut olmalı."""
    issues = []

    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")

    if not os.path.exists(os.path.join(config_dir, "alert_policy.json")):
        issues.append("alert_policy.json eksik")
    if not os.path.exists(os.path.join(config_dir, "alpha_config.json")):
        issues.append("alpha_config.json eksik")

    assert len(issues) == 0, f"Config File Exists: {issues}"


async def test_config_json_valid() -> Any:
    """Config dosyaları geçerli JSON olmalı."""
    issues = []

    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")

    for filename in ["alert_policy.json", "alpha_config.json"]:
        path = os.path.join(config_dir, filename)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = orjson.loads(f.read())
                if not isinstance(data, dict):
                    issues.append(f"{filename}: dict değil")
            except orjson.JSONDecodeError as e:
                issues.append(f"{filename}: geçersiz JSON: {e}")

    assert len(issues) == 0, f"Config JSON Valid: {issues}"


async def test_config_values() -> Any:
    """Config değerleri mantıklı olmalı."""
    issues = []

    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
    path = os.path.join(config_dir, "alpha_config.json")

    if os.path.exists(path):
        with open(path) as f:
            config = orjson.loads(f.read())

        # Portfolio config
        pf = config.get("portfolio", {})
        if pf.get("initial_capital", 0) <= 0:
            issues.append(f"initial_capital: {pf.get('initial_capital')}")
        if pf.get("max_position_pct", 0) <= 0 or pf.get("max_position_pct", 0) > 1:
            issues.append(f"max_position_pct: {pf.get('max_position_pct')}")

        # Risk config
        risk = config.get("risk", {})
        if risk.get("max_drawdown_pct", 0) <= 0 or risk.get("max_drawdown_pct", 0) > 100:
            issues.append(f"max_drawdown_pct: {risk.get('max_drawdown_pct')}")

    assert len(issues) == 0, f"Config Values: {issues}"


# =====================================================
# RUN
# =====================================================


async def run_all() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("ASYNC PROVIDER & CONFIG TESTLERİ")
    logger.info("=" * 60)

    tests = [
        # HTTP Client
        test_client_creation,
        test_client_singleton,
        test_client_timeout,
        test_client_retry,
        test_client_close,
        test_context_manager,
        # Providers
        test_bist_provider_async,
        test_kap_provider_async,
        test_news_provider_async,
        # Config
        test_config_file_exists,
        test_config_json_valid,
        test_config_values,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            await test_func()
            name = test_func.__name__
            passed += 1
            logger.info(f"\n✅ {name}")
            logger.info("   PASSED")
        except AssertionError as e:
            name = test_func.__name__
            failed += 1
            issues = [str(e)]
            logger.info(f"\n❌ {name}")
            for i in issues:
                logger.info(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")
        except Exception as e:
            name = test_func.__name__
            failed += 1
            issues = [f"Exception: {e}"]
            logger.info(f"\n❌ {name}")
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
