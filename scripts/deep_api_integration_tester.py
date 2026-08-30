import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST - Deep API and Integration Testing Suite
Comprehensive end-to-end audit testing all endpoints (including parameterized GET, POST, PUT, DELETE)
with realistic test parameters and mock payloads.
"""

import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

API_BASE_URL = "http://127.0.0.1:8000"
OPENAPI_URL = f"{API_BASE_URL}/openapi.json"

# Realistic values for path parameters
PATH_PARAM_VALUES = {
    "ticker": "THYAO",
    "symbol": "THYAO",
    "sector": "XU100",
    "year": "2026",
    "date_str": "2026-12-31",
    "decision_id": "test-dec-123",
    "backtest_id": "test-bt-123",
    "model_name": "momentum",
    "strategy_name": "alpha",
    "days": "30",
    "period": "1mo",
}

# Payloads for POST endpoints
POST_PAYLOADS = {
    "/api/v1/portfolio/reset": {},
    "/api/v1/portfolio/deposit": {"amount": 10000.0},
    "/api/v1/portfolio/optimize": {"method": "max_sharpe", "tickers": ["THYAO", "GARAN", "ASELS"]},
    "/api/v1/portfolio/auto_rebalance": {"dry_run": True},
    "/api/v1/portfolio/trigger_eod_signals": {},
    "/api/v1/portfolio/trigger_morning_execution": {},
    "/api/v1/portfolio/trigger_phase18": {},
    "/api/v1/portfolio/rebalance/orders": {"orders": []},
    "/api/v1/strategy/reset": {},
    "/api/v1/strategy/deposit": {"amount": 10000.0},
    "/api/v1/strategy/optimize": {"method": "max_sharpe", "tickers": ["THYAO", "GARAN", "ASELS"]},
    "/api/v1/strategy/auto_rebalance": {"dry_run": True},
    "/api/v1/strategy/trigger_eod_signals": {},
    "/api/v1/strategy/trigger_morning_execution": {},
    "/api/v1/strategy/trigger_phase18": {},
    "/api/v1/strategy/rebalance/orders": {"orders": []},
    "/api/v1/risk/check": {
        "portfolio": {"THYAO": 1000},
        "proposed_trade": {"ticker": "GARAN", "action": "BUY", "quantity": 100, "price": 100.0},
    },
    "/api/v1/risk/stress-test": {"scenario": "bist_crash", "custom_drop": 0.15},
    "/api/v1/risk/stress-test/run": {"scenario": "bist_crash", "custom_drop": 0.15},
    "/api/v1/risk/tail-hedge/analyze": {"confidence_level": 0.99},
    "/api/v1/risk/risk-parity/optimize": {"tickers": ["THYAO", "GARAN", "ASELS"]},
    "/api/v1/intelligence/ask_gemini": {"prompt": "BIST-100 genel görünüm nedir?"},
    "/api/v1/decisions/create": {"symbol": "THYAO", "action": "HOLD", "confidence": 0.85, "reasoning": "Test decision"},
    "/api/v1/backtests/run": {
        "strategy": "momentum",
        "tickers": ["THYAO"],
        "start_date": "2026-01-01",
        "end_date": "2026-06-01",
    },
    "/api/v1/backtests/walk-forward": {"strategy": "momentum", "tickers": ["THYAO"]},
    "/api/v1/learning/cycle": {"force": False},
    "/api/v1/learning/record_prediction": {
        "model_name": "momentum",
        "ticker": "THYAO",
        "prediction": 0.05,
        "confidence": 0.8,
    },
    "/api/v1/learning/record_outcome": {"model_name": "momentum", "ticker": "THYAO", "actual_return": 0.04},
    "/api/v1/models/retrain": {"model_name": "all"},
    "/api/v1/agents/run": {"agent_name": "market_analyst", "context": {}},
    "/api/v1/scanner/trigger": {"universe": "BIST30"},
    "/api/v1/scanner/event": {"event_type": "breakout", "ticker": "THYAO"},
    "/api/v1/system/optimize_storage": {},
    "/api/v1/holidays/": {"name": "Test Holiday", "date": "2026-12-31", "half_day": False},
    "/api/v1/holidays/sync": {},
    "/api/v1/tatil/": {"name": "Test Tatil", "date": "2026-12-31", "half_day": False},
    "/api/v1/tatil/sync": {},
    "/api/v1/trigger": {"universe": "BIST30"},
    "/api/v1/event": {"event_type": "breakout", "ticker": "THYAO"},
    "/api/v1/optimize_storage": {},
    # VIOP
    "/api/v1/viop/options/price": {
        "spot_price": 300.0,
        "strike_price": 300.0,
        "time_to_maturity": 0.25,
        "risk_free_rate": 0.45,
        "volatility": 0.30,
        "option_type": "call",
    },
    "/api/v1/viop/options/implied-vol": {
        "target_price": 15.0,
        "spot_price": 300.0,
        "strike_price": 300.0,
        "time_to_maturity": 0.25,
        "risk_free_rate": 0.45,
        "option_type": "call",
    },
    "/api/v1/viop/greeks": {
        "spot_price": 300.0,
        "strike_price": 300.0,
        "time_to_maturity": 0.25,
        "risk_free_rate": 0.45,
        "volatility": 0.30,
        "option_type": "call",
    },
    "/api/v1/viop/strategies/analyze": {
        "strategy": "straddle",
        "spot_price": 300.0,
        "strike_price": 300.0,
        "time_to_maturity": 0.25,
        "risk_free_rate": 0.45,
        "volatility": 0.30,
    },
    "/api/v1/viop/hedge": {"portfolio_delta": 50.0, "spot_price": 300.0, "target_delta": 0.0},
    "/api/v1/viop/hedge/gamma-scalp": {"portfolio_gamma": 0.05, "spot_price": 300.0, "price_move": 5.0},
    "/api/v1/viop/margin": {"positions": [{"symbol": "F_THYAO0826", "quantity": 10, "type": "future"}]},
    "/api/v1/viop/arbitrage": {
        "spot_price": 300.0,
        "future_price": 315.0,
        "time_to_maturity": 0.25,
        "risk_free_rate": 0.45,
        "dividend_yield": 0.0,
    },
    "/api/v1/viop/parity": {
        "spot_price": 300.0,
        "strike_price": 300.0,
        "call_price": 20.0,
        "put_price": 15.0,
        "time_to_maturity": 0.25,
        "risk_free_rate": 0.45,
    },
    "/api/v1/viop/risk": {"positions": [{"symbol": "F_THYAO0826", "quantity": 10, "type": "future"}]},
}


def resolve_path(path: str) -> str:
    """Otomatik eklendi."""
    res = path
    for param, val in PATH_PARAM_VALUES.items():
        res = res.replace(f"{{{param}}}", val)
    return res


def fetch_openapi_schema() -> Any:
    """Otomatik eklendi."""
    try:
        req = urllib.request.Request(OPENAPI_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.info(f"Failed to fetch OpenAPI schema: {e}")
        return None


def test_endpoint(method: str, path: str, url: str) -> dict:
    """Otomatik eklendi."""
    t0 = time.time()
    result = {
        "method": method.upper(),
        "path": path,
        "resolved_url": url,
        "status": None,
        "time_ms": None,
        "error": None,
        "detail": None,
    }

    headers = {"User-Agent": "Alpha-APITester/2.0", "Content-Type": "application/json"}

    data = None
    if method.upper() in ("POST", "PUT", "PATCH"):
        payload = POST_PAYLOADS.get(path, {})
        data = json.dumps(payload).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        with urllib.request.urlopen(req, timeout=15) as resp:
            result["time_ms"] = (time.time() - t0) * 1000
            result["status"] = resp.getcode()
            try:
                body = resp.read()
                result["detail"] = json.loads(body)
            except Exception:
                logger.error("Exception caught", exc_info=True)
    except urllib.error.HTTPError as e:
        result["time_ms"] = (time.time() - t0) * 1000
        result["status"] = e.code
        try:
            body = e.read()
            err_json = json.loads(body)
            result["error"] = err_json.get("detail", str(e))
        except Exception:
            result["error"] = str(e)
    except Exception as e:
        result["time_ms"] = (time.time() - t0) * 1000
        result["status"] = "ERROR"
        result["error"] = str(e)

    return result


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 90)
    logger.info("  ALPHA BIST — DERİNLEMESİNE (100% KAPSAM) CANLI API & ENTEGRASYON DENETİMİ")
    logger.info("=" * 90)

    schema = fetch_openapi_schema()
    if not schema:
        logger.info("API şeması alınamadı.")
        return

    paths = schema.get("paths", {})
    all_endpoints = []

    for path, methods in paths.items():
        for method in methods.keys():
            all_endpoints.append((method.upper(), path))

    logger.info(f"Toplam Denetlenecek Uç Nokta Sayısı: {len(all_endpoints)}")
    logger.info("-" * 90)
    logger.info(f"{'Metot':<7} | {'Endpoint':<45} | {'Durum':<12} | {'Yanıt Süresi'}")
    logger.info("-" * 90)

    success = 0
    client_err = 0
    server_err = 0

    results = []

    for method, path in all_endpoints:
        resolved_path = resolve_path(path)
        url = f"{API_BASE_URL}{resolved_path}"
        res = test_endpoint(method, path, url)
        results.append(res)

        status_val = res["status"]
        time_str = f"{res['time_ms']:.1f} ms" if res["time_ms"] is not None else "-"

        if isinstance(status_val, int) and status_val < 400:
            success += 1
            status_str = f"{status_val} OK"
        elif isinstance(status_val, int) and status_val < 500:
            client_err += 1
            status_str = f"{status_val} (Client)"
        else:
            server_err += 1
            status_str = f"{status_val} (ERR)"

        logger.info(f"{method:<7} | {path:<45} | {status_str:<12} | {time_str}")
        if res["error"] and (not isinstance(status_val, int) or status_val >= 500):
            logger.info(f"          └─ [KRİTİK HATA]: {res['error']}")
        elif res["error"] and status_val in (400, 404, 422):
            logger.info(f"          └─ (Bilgi/Validasyon): {res['error']}")

    logger.info("-" * 90)
    logger.info(
        f"SONUÇ: Toplam: {len(all_endpoints)} | Başarılı (2xx/3xx): {success} | İstemci/Validasyon (4xx): {client_err} | Sunucu Hatası (5xx): {server_err}"
    )
    logger.info("=" * 90)

    logger.info("\n--- 🔴 KONTROL EDILMESI GEREKEN ENDPOINTLER (HATALAR) ---")
    for res in results:
        status_val = res["status"]
        if not isinstance(status_val, int) or status_val >= 500:
            time_str = f"{res['time_ms']:.1f} ms" if res["time_ms"] is not None else "-"
            logger.info(f"{res['method']:<7} | {res['path']:<45} | {res['status']:<12} | {time_str}")

    logger.info("\n--- 🟠 OPTIMIZE EDILMESI GEREKEN ENDPOINTLER (YÜKSEK GECİKME > 2000ms) ---")
    for res in results:
        status_val = res["status"]
        if isinstance(status_val, int) and status_val < 500 and res["time_ms"] is not None and res["time_ms"] > 2000:
            logger.info(f"{res['method']:<7} | {res['path']:<45} | {res['status']:<12} | {res['time_ms']:.1f} ms")

    # Dump full json report for analysis
    import os

    report_dir = "audit raporlar"
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(report_dir, "deep_audit_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
