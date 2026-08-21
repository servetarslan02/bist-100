#!/usr/bin/env python3
"""
Realistic Integration Testleri

Kapsam:
- Mock HTTP server ile provider integration
- Environment config sistemi
- Scanner market integration (100+ hisse)
- Intelligence büyük veri edge cases
- End-to-end pipeline doğrulama
"""

import sys
import os
import json
import asyncio
import time
import numpy as np
import pandas as pd
from datetime import datetime
from aiohttp import web
import aiohttp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.core.async_http import AsyncHTTPClient, close_all_clients
from services.core.config_loader import ConfigLoader
from services.features.calculator import FeatureCalculator
from services.core.tradability_mask import TradabilityMask
from services.scanner.alpha_scanner import AlphaScanner
from services.scanner.opportunity_engine import OpportunityDiscoveryEngine


# =====================================================
# MOCK HTTP SERVER
# =====================================================

class MockFinanceServer:
    """Gerçekçi finansal veri mock server."""

    def __init__(self, port: int = 18924):
        self.port = port
        self.requests = []
        self._runner = None
        self._site = None

    async def start(self):
        app = web.Application()
        app.router.add_get("/api/bist/index", self._bist_index)
        app.router.add_get("/api/bist/stock/{ticker}", self._bist_stock)
        app.router.add_get("/api/kap/disclosures", self._kap_disclosures)
        app.router.add_get("/api/tcmb/rates", self._tcmb_rates)
        app.router.add_get("/api/news", self._news_feed)
        app.router.add_get("/api/slow", self._slow_response)
        app.router.add_get("/api/rate-limited", self._rate_limited)
        app.router.add_get("/api/broken-json", self._broken_json)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "localhost", self.port)
        await self._site.start()

    async def stop(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    async def _bist_index(self, request):
        self.requests.append(("GET", "/api/bist/index"))
        return web.json_response({
            "XU100": {"lastPrice": 10250.5, "changePercent": 1.2, "volume": 15000000000},
            "XU030": {"lastPrice": 11800.3, "changePercent": 0.8, "volume": 8000000000},
        })

    async def _bist_stock(self, request):
        ticker = request.match_info["ticker"]
        self.requests.append(("GET", f"/api/bist/stock/{ticker}"))
        prices = {"THYAO": 250.5, "GARAN": 102.3, "AKBNK": 55.8, "EREGL": 48.2, "TUPRS": 180.5}
        price = prices.get(ticker, 100.0)
        return web.json_response({
            "lastPrice": price,
            "changePercent": round(np.random.uniform(-3, 3), 2),
            "volume": int(np.random.uniform(100000, 5000000)),
            "high": price * 1.02,
            "low": price * 0.98,
            "open": price * 0.999,
            "close": price,
        })

    async def _kap_disclosures(self, request):
        self.requests.append(("GET", "/api/kap/disclosures"))
        return web.json_response([
            {"disclosureId": "KAP001", "stockTicker": "THYAO", "title": "Kar açıklaması",
             "summary": "THYAO 3. çeyrek karı %30 arttı", "category": "FINANCIAL",
             "publishDate": "2026-08-15T10:00:00Z", "url": "/disclosure/KAP001"},
            {"disclosureId": "KAP002", "stockTicker": "GARAN", "title": "Temettü kararı",
             "summary": "GARAN hisse başına 2.5 TL temettü verecek", "category": "DIVIDEND",
             "publishDate": "2026-08-14T14:00:00Z", "url": "/disclosure/KAP002"},
        ])

    async def _tcmb_rates(self, request):
        self.requests.append(("GET", "/api/tcmb/rates"))
        return web.json_response({
            "usd_try": 34.50, "eur_try": 37.20, "gbp_try": 43.80,
            "policy_rate": 45.0, "inflation": 58.9, "date": "2026-08-15",
        })

    async def _news_feed(self, request):
        self.requests.append(("GET", "/api/news"))
        return web.json_response([
            {"title": "BIST100 rekor kırdı", "source": "bloomberght", "sentiment": "positive",
             "timestamp": "2026-08-15T16:00:00Z"},
            {"title": "TCMB faiz kararı açıklandı", "source": "aa", "sentiment": "neutral",
             "timestamp": "2026-08-15T14:00:00Z"},
        ])

    async def _slow_response(self, request):
        self.requests.append(("GET", "/api/slow"))
        await asyncio.sleep(5)
        return web.json_response({"status": "ok"})

    async def _rate_limited(self, request):
        self.requests.append(("GET", "/api/rate-limited"))
        return web.Response(status=429, text="Rate Limited", headers={"Retry-After": "2"})

    async def _broken_json(self, request):
        self.requests.append(("GET", "/api/broken-json"))
        return web.Response(text="not json{broken", content_type="text/plain")

    @property
    def base_url(self):
        return f"http://localhost:{self.port}/api"


# =====================================================
# HTTP PROVIDER INTEGRATION TESTS
# =====================================================

async def test_bist_index_format():
    """BIST index response format doğru parse edilmeli."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=5)
        data = await client.get_json(f"{server.base_url}/bist/index")

        if not data:
            issues.append("Response boş")
        elif "XU100" not in data:
            issues.append("XU100 eksik")
        elif data["XU100"]["lastPrice"] != 10250.5:
            issues.append(f"XU100 price: {data['XU100']['lastPrice']}")

        await client.close()
    finally:
        await server.stop()

    return "BIST Index Format", len(issues) == 0, issues


async def test_bist_stock_format():
    """BIST stock response format doğru parse edilmeli."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=5)
        for ticker in ["THYAO", "GARAN", "AKBNK"]:
            data = await client.get_json(f"{server.base_url}/bist/stock/{ticker}")
            if not data:
                issues.append(f"{ticker}: boş response")
            elif "lastPrice" not in data:
                issues.append(f"{ticker}: lastPrice eksik")

        await client.close()
    finally:
        await server.stop()

    return "BIST Stock Format", len(issues) == 0, issues


async def test_kap_disclosures_format():
    """KAP disclosures response format doğru parse edilmeli."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=5)
        data = await client.get_json(f"{server.base_url}/kap/disclosures")

        if not isinstance(data, list):
            issues.append("Response list değil")
        elif len(data) != 2:
            issues.append(f"Count: {len(data)}")
        elif data[0]["stockTicker"] != "THYAO":
            issues.append(f"Ticker: {data[0]['stockTicker']}")

        await client.close()
    finally:
        await server.stop()

    return "KAP Disclosures Format", len(issues) == 0, issues


async def test_tcmb_rates_format():
    """TCMB rates response format doğru parse edilmeli."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=5)
        data = await client.get_json(f"{server.base_url}/tcmb/rates")

        if not data:
            issues.append("Response boş")
        elif "usd_try" not in data:
            issues.append("usd_try eksik")
        elif data["policy_rate"] != 45.0:
            issues.append(f"policy_rate: {data['policy_rate']}")

        await client.close()
    finally:
        await server.stop()

    return "TCMB Rates Format", len(issues) == 0, issues


async def test_timeout_behavior():
    """Timeout davranışı doğru olmalı."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=0.5, max_retries=1)
        start = time.time()
        result = await client.get_text(f"{server.base_url}/slow")
        elapsed = time.time() - start

        if result is not None:
            issues.append("Timeout döndü ama result None değil")

        if elapsed > 3:
            issues.append(f"Timeout çok geç: {elapsed:.1f}s")

        await client.close()
    finally:
        await server.stop()

    return "Timeout Behavior", len(issues) == 0, issues


async def test_retry_mechanism():
    """Retry mekanizması çalışmalı."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=5, max_retries=3, retry_delay_s=0.1)

        # Rate limited endpoint — retry yapmalı
        result = await client.get_text(f"{server.base_url}/rate-limited")

        # 429 dönerse retry yapar ama sonunda None döner
        # Veya Retry-After header'ı ile bekler
        requests_count = len([r for r in server.requests if r[1] == "/api/rate-limited"])
        if requests_count < 2:
            issues.append(f"Retry yapılmadı: {requests_count} istek")

        await client.close()
    finally:
        await server.stop()

    return "Retry Mechanism", len(issues) == 0, issues


async def test_broken_json_recovery():
    """Bozuk JSON response recovery çalışmalı."""
    server = MockFinanceServer()
    await server.start()
    issues = []

    try:
        client = AsyncHTTPClient(timeout=5, max_retries=1)
        result = await client.get_json(f"{server.base_url}/broken-json")

        if result is not None:
            issues.append("Bozuk JSON parse edildi (None olmalı)")

        await client.close()
    finally:
        await server.stop()

    return "Broken JSON Recovery", len(issues) == 0, issues


async def test_network_error():
    """Network error recovery çalışmalı."""
    issues = []

    client = AsyncHTTPClient(timeout=1, max_retries=1)
    result = await client.get_text("http://localhost:1/nonexistent")

    if result is not None:
        issues.append("Network error None döndürmedi")

    await client.close()
    return "Network Error", len(issues) == 0, issues


# =====================================================
# ENVIRONMENT CONFIG TESTS
# =====================================================

async def test_environment_config_files():
    """Tüm environment config dosyaları mevcut olmalı."""
    issues = []

    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
    required = ["alpha_config.json", "alpha_development.json", "alpha_test.json", "alpha_production.json"]

    for f in required:
        path = os.path.join(config_dir, f)
        if not os.path.exists(path):
            issues.append(f"{f} eksik")
        else:
            with open(path) as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                issues.append(f"{f}: geçersiz JSON")

    return "Environment Config Files", len(issues) == 0, issues


async def test_config_priority():
    """Config öncelik sırası: ENV > environment > default."""
    ConfigLoader.reset()
    issues = []

    # Test environment config yükle
    os.environ["APP_ENV"] = "production"
    config = ConfigLoader.load("config/alpha_config.json", environment="production")

    # Production config override etmeli
    if not config.is_production:
        issues.append("production tespit edilemedi")

    # Debug False olmalı (production)
    debug = config.get_bool("app.debug")
    if debug:
        issues.append(f"production debug=True (beklenen: False)")

    # ENV override
    os.environ["ALPHA_APP_PORT"] = "443"
    ConfigLoader.reset()
    config2 = ConfigLoader.load("config/alpha_config.json", environment="production")
    port = config2.get_int("app.port")
    if port != 443:
        issues.append(f"ENV override çalışmadı: port={port}")

    del os.environ["APP_ENV"]
    del os.environ["ALPHA_APP_PORT"]
    ConfigLoader.reset()
    return "Config Priority", len(issues) == 0, issues


async def test_config_secret_isolation():
    """Secret'lar config dosyasında olmamalı, sadece ENV'de."""
    issues = []

    config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
    secret_patterns = ["password", "secret_key", "api_key", "token", "private"]

    for filename in os.listdir(config_dir):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(config_dir, filename)) as f:
            content = f.read().lower()
        for pattern in secret_patterns:
            if pattern in content:
                # Value olarak mı var, key olarak mı?
                data = json.loads(content)
                for key in data:
                    if pattern in str(key).lower():
                        # Key olarak var — value'nun secret olmadığından emin ol
                        val = str(data[key])
                        if len(val) > 20 and not val.startswith("$"):
                            issues.append(f"{filename}: {key} = {val[:20]}... (secret olabilir)")

    return "Config Secret Isolation", len(issues) == 0, issues


# =====================================================
# SCANNER MARKET INTEGRATION
# =====================================================

def make_market_data(n_stocks=100, n_days=120):
    """Gerçekçi market dataset oluştur."""
    np.random.seed(42)
    tickers = [f"STOCK{i:03d}" for i in range(n_stocks)]

    # Bazı hisseleri özel yap
    special = {
        "STOCK001": {"trend": 0.003, "vol": 0.015},  # Güçlü yukarı
        "STOCK002": {"trend": -0.003, "vol": 0.020},  # Güçlü aşağı
        "STOCK003": {"trend": 0.0, "vol": 0.005},     # Sabit
        "STOCK004": {"trend": 0.0, "vol": 0.05},      # Yüksek volatilite
        "STOCK005": {"trend": 0.001, "vol": 0.001},   # Düşük hacim (sonradan)
    }

    market = {}
    for ticker in tickers:
        params = special.get(ticker, {"trend": np.random.uniform(-0.002, 0.002),
                                       "vol": np.random.uniform(0.01, 0.03)})
        dates = pd.date_range(end=datetime.now(), periods=n_days, freq='B')
        close = 100 * np.exp(np.cumsum(np.random.randn(n_days) * params["vol"] + params["trend"]))
        high = close * (1 + np.abs(np.random.randn(n_days) * 0.01))
        low = close * (1 - np.abs(np.random.randn(n_days) * 0.01))
        volume = np.random.randint(10000, 1000000, n_days).astype(float)

        # STOCK005: düşük hacim
        if ticker == "STOCK005":
            volume = np.random.randint(100, 1000, n_days).astype(float)

        # STOCK006: eksik veri (son 10 gün NaN)
        if ticker == "STOCK006":
            close[-10:] = np.nan
            volume[-10:] = 0

        # STOCK007: tavan fiyat (son gün %10+)
        if ticker == "STOCK007":
            close[-1] = close[-2] * 1.10

        market[ticker] = pd.DataFrame({
            'Open': close * 0.999, 'High': high, 'Low': low,
            'Close': close, 'Volume': volume
        }, index=dates)

    return market


async def test_scanner_100_stocks():
    """100+ hisse taraması çalışmalı."""
    issues = []

    market = make_market_data(100)
    calc = FeatureCalculator()
    tm = TradabilityMask()
    scanner = AlphaScanner()

    results = []
    errors = 0

    for ticker, df in market.items():
        try:
            mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                                  df['Low'].values, df['Close'].values, df['Volume'].values)
            features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)
            result = scanner._scan_single(ticker, features)
            if result:
                results.append(result)
        except Exception:
            errors += 1

    if errors > 5:
        issues.append(f"Çok fazla hata: {errors}/100")

    if len(results) < 50:
        issues.append(f"Çok az sonuç: {len(results)}/100")

    return "Scanner 100 Stocks", len(issues) == 0, issues


async def test_scanner_delisted_stock():
    """İşlem dışı hisse filtrelenebilmeli."""
    issues = []

    market = make_market_data(10)
    calc = FeatureCalculator()
    tm = TradabilityMask()

    # STOCK006: eksik veri
    df = market.get("STOCK006")
    if df is not None:
        mask = tm.compute_mask("STOCK006", df['Open'].values, df['High'].values,
                              df['Low'].values, df['Close'].values, df['Volume'].values)
        # Mask'in son 10 günü 0 olmalı
        masked_zeros = np.sum(mask.mask[-10:] == 0)
        if masked_zeros < 5:
            issues.append(f"Eksik veri maskelenmedi: {masked_zeros}/10")

    return "Scanner Delisted Stock", len(issues) == 0, issues


async def test_scanner_low_volume():
    """Düşük hacimli hisse feature hesaplamasında sorun çıkarmamalı."""
    issues = []

    market = make_market_data(10)
    calc = FeatureCalculator()
    tm = TradabilityMask()

    # STOCK005: düşük hacim
    df = market.get("STOCK005")
    if df is not None:
        mask = tm.compute_mask("STOCK005", df['Open'].values, df['High'].values,
                              df['Low'].values, df['Close'].values, df['Volume'].values)
        try:
            features = calc.compute_all_features(df, mask=mask.mask, ticker="STOCK005")
            if features:
                return "Scanner Low Volume", True, [f"{len(features)} feature (düşük hacim)"]
        except Exception as e:
            issues.append(f"Crash: {e}")

    return "Scanner Low Volume", len(issues) == 0, issues


async def test_scanner_limit_up():
    """Tavan fiyat hareketi maskelenmeli."""
    issues = []

    market = make_market_data(10)
    tm = TradabilityMask()

    # STOCK007: tavan fiyat
    df = market.get("STOCK007")
    if df is not None:
        mask = tm.compute_mask("STOCK007", df['Open'].values, df['High'].values,
                              df['Low'].values, df['Close'].values, df['Volume'].values)
        # Son gün tavan olmalı
        last_day_change = abs(df['Close'].values[-1] / df['Close'].values[-2] - 1)
        if last_day_change > 0.08:
            if mask.mask[-1] != 0:
                issues.append(f"Tavan fiyat maskelenmedi: %{last_day_change*100:.1f}")

    return "Scanner Limit Up", len(issues) == 0, issues


async def test_scanner_duplicate_prevention():
    """Duplicate signal engelleme çalışmalı."""
    issues = []

    scanner = AlphaScanner()
    calc = FeatureCalculator()
    tm = TradabilityMask()

    # Aynı hisseyi iki kez tara
    market = make_market_data(5)
    ticker = "STOCK000"
    df = market[ticker]

    mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                          df['Low'].values, df['Close'].values, df['Volume'].values)
    features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)

    r1 = scanner._scan_single(ticker, features)
    r2 = scanner._scan_single(ticker, features)

    # Her iki sonuç da aynı olmalı (duplicate yok)
    if r1 and r2:
        s1 = getattr(r1, 'opportunity_score', None) or 0
        s2 = getattr(r2, 'opportunity_score', None) or 0
        if s1 != s2:
            issues.append(f"Skor farklı: {s1} != {s2}")

    return "Scanner Duplicate Prevention", len(issues) == 0, issues


# =====================================================
# INTELLIGENCE EDGE CASES
# =====================================================

async def test_large_claim_set():
    """Büyük claim seti çalışmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine
    engine = EvidenceVerificationEngine()

    # 100+ farklı metin
    texts = [
        "THYAO karı %30 arttı", "GARAN temettü verecek", "BIST100 rekor kırdı",
        "TCMB faiz indirdi", "Dolar yükseldi", "Enflasyon düştü",
        "Petrol fiyatları arttı", "Altın rekor kırdı", "Euro güçlendi",
        "Bankacılık sektörü büyüdü", "Sanayi üretimi arttı", "İşsizlik düştü",
    ] * 10  # 120 metin

    total_claims = 0
    errors = 0

    for text in texts:
        try:
            claims = engine.extract_claims(text, source="test")
            total_claims += len(claims)
        except Exception:
            errors += 1

    if errors > 5:
        issues.append(f"Çok fazla hata: {errors}/{len(texts)}")

    if total_claims == 0:
        issues.append("Hiçclaim çıkarılamadı")

    return "Large Claim Set", len(issues) == 0, issues


async def test_multi_source_contradiction():
    """Çoklu kaynak çelişkisi yönetimi çalışmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine
    engine = EvidenceVerificationEngine()

    # Aynı konu hakkında zıt iddialar
    sources = [
        ("THYAO karı arttı", "kap.org.tr"),
        ("THYAO zarar açıkladı", "twitter.com"),
        ("THYAO karı %25 arttı", "bloomberght.com"),
        ("THYAO iflas ediyor", "forum.com"),
    ]

    scores = []
    for text, source in sources:
        claims = engine.extract_claims(text, ticker="THYAO", source=source)
        if claims:
            result = engine.verify_claim(claims[0])
            scores.append((source, result.evidence_score))

    # KAP ve Bloomberg daha yüksek skor almalı
    if scores:
        kap_score = next((s for src, s in scores if "kap" in src), 0)
        twitter_score = next((s for src, s in scores if "twitter" in src), 0)
        if kap_score < twitter_score:
            issues.append(f"KAP ({kap_score}) < Twitter ({twitter_score})")

    return "Multi-Source Contradiction", len(issues) == 0, issues


async def test_confidence_degradation():
    """Eksik veri ile confidence düşmeli."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine
    engine = EvidenceVerificationEngine()

    # Tam bilgi
    claims_full = engine.extract_claims(
        "THYAO 3. çeyrek net karı 5.2 milyar TL olarak açıklandı. Kaynak: KAP",
        ticker="THYAO", source="kap.org.tr"
    )

    # Eksik bilgi
    claims_partial = engine.extract_claims(
        "THYAO iyi gitmiyor",
        ticker="THYAO", source="unknown"
    )

    if claims_full and claims_partial:
        score_full = engine.verify_claim(claims_full[0]).evidence_score
        score_partial = engine.verify_claim(claims_partial[0]).evidence_score

        if score_partial >= score_full:
            issues.append(f"Eksik veri skoru ({score_partial}) >= tam veri ({score_full})")

    return "Confidence Degradation", len(issues) == 0, issues


# =====================================================
# E2E PIPELINE TEST
# =====================================================

async def test_e2e_market_pipeline():
    """Market Data → Features → Scanner → Signal tam pipeline."""
    issues = []

    # 1. Market data oluştur
    market = make_market_data(20)
    calc = FeatureCalculator()
    tm = TradabilityMask()
    scanner = AlphaScanner()
    engine = OpportunityDiscoveryEngine()

    signals = []
    for ticker, df in market.items():
        try:
            mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                                  df['Low'].values, df['Close'].values, df['Volume'].values)
            features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)

            if not features:
                continue

            result = scanner._scan_single(ticker, features)
            if result:
                score = engine.compute_opportunity_score(ticker, features, market_regime="BULL")
                signals.append({
                    "ticker": ticker,
                    "score": getattr(result, 'opportunity_score', 0),
                    "features_count": len(features),
                })
        except Exception as e:
            issues.append(f"{ticker}: {e}")

    if len(signals) == 0:
        issues.append("Hiç sinyal üretilmedi")
    elif len(signals) < 5:
        issues.append(f"Çok az sinyal: {len(signals)}/20")

    # Duplicate kontrolü
    tickers = [s["ticker"] for s in signals]
    if len(tickers) != len(set(tickers)):
        issues.append("Duplicate ticker var")

    return "E2E Market Pipeline", len(issues) == 0, issues


# =====================================================
# PERFORMANCE TEST
# =====================================================

async def test_scanner_performance():
    """100 hisse tarama performansı < 30 saniye olmalı."""
    issues = []

    market = make_market_data(100)
    calc = FeatureCalculator()
    tm = TradabilityMask()
    scanner = AlphaScanner()

    start = time.time()
    results = []
    for ticker, df in market.items():
        try:
            mask = tm.compute_mask(ticker, df['Open'].values, df['High'].values,
                                  df['Low'].values, df['Close'].values, df['Volume'].values)
            features = calc.compute_all_features(df, mask=mask.mask, ticker=ticker)
            result = scanner._scan_single(ticker, features)
            if result:
                results.append(result)
        except Exception:
            pass
    elapsed = time.time() - start

    if elapsed > 30:
        issues.append(f"Performans: {elapsed:.1f}s (limit: 30s)")

    return "Scanner Performance", len(issues) == 0, issues, f"{elapsed:.1f}s, {len(results)} results"


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("REALISTIC INTEGRATION TESTLERİ")
    print("=" * 60)

    tests = [
        # HTTP Provider
        test_bist_index_format,
        test_bist_stock_format,
        test_kap_disclosures_format,
        test_tcmb_rates_format,
        test_timeout_behavior,
        test_retry_mechanism,
        test_broken_json_recovery,
        test_network_error,
        # Environment Config
        test_environment_config_files,
        test_config_priority,
        test_config_secret_isolation,
        # Scanner Market
        test_scanner_100_stocks,
        test_scanner_delisted_stock,
        test_scanner_low_volume,
        test_scanner_limit_up,
        test_scanner_duplicate_prevention,
        # Intelligence Edge Cases
        test_large_claim_set,
        test_multi_source_contradiction,
        test_confidence_degradation,
        # E2E
        test_e2e_market_pipeline,
        # Performance
        test_scanner_performance,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            result = await test_func()
            if len(result) == 4:
                name, ok, issues, extra = result
            else:
                name, ok, issues = result
                extra = ""
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]
            extra = ""

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}" + (f" ({extra})" if extra else ""))
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
