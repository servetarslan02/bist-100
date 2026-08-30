import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST - API and Integration Testing Suite
Fetches OpenAPI schema from the running FastAPI instance,
discovers all endpoints, tests them, measures response times,
and validates integrations.
"""

import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

API_BASE_URL = "http://127.0.0.1:8000"
OPENAPI_URL = f"{API_BASE_URL}/openapi.json"


def fetch_openapi_schema() -> Any:
    """Otomatik eklendi."""
    try:
        req = urllib.request.Request(OPENAPI_URL)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            return json.loads(data)
    except Exception as e:
        logger.info(f"Failed to fetch OpenAPI schema: {e}")
        return None


def test_endpoint(method: str, path: str, url: str) -> dict:
    """Otomatik eklendi."""
    t0 = time.time()
    result = {"method": method, "path": path, "status": None, "time_ms": None, "error": None}

    # We'll only test GET endpoints without path parameters for this automated sweep
    # Testing POST or parameterized GETs requires specific payload knowledge
    if method.upper() != "GET" or "{" in path:
        result["status"] = "SKIPPED"
        result["error"] = "Requires parameters or specific payload"
        return result

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Alpha-APITester/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            result["time_ms"] = (time.time() - t0) * 1000
            result["status"] = resp.getcode()
    except urllib.error.HTTPError as e:
        result["time_ms"] = (time.time() - t0) * 1000
        result["status"] = e.code
        # 401/403 are expected for protected endpoints
        if e.code not in (401, 403, 422):
            result["error"] = str(e)
    except Exception as e:
        result["time_ms"] = (time.time() - t0) * 1000
        result["status"] = "ERROR"
        result["error"] = str(e)

    return result


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("  ALPHA BIST — CANLI API & ENTEGRASYON TESTİ (Response Times)")
    logger.info("=" * 80)

    schema = fetch_openapi_schema()
    if not schema:
        logger.info("API şeması alınamadı. Servis ayakta mı?")
        # Fallback to checking just the health endpoint
        endpoints = {"/health": {"get": {}}}
    else:
        endpoints = schema.get("paths", {})
        logger.info(f"Toplam {len(endpoints)} API route'u bulundu.")
        logger.info("-" * 80)

    logger.info(f"{'Metot':<7} | {'Endpoint':<40} | {'Durum':<10} | {'Yanıt Süresi'}")
    logger.info("-" * 80)

    success = 0
    skipped = 0
    failed = 0

    for path, methods in endpoints.items():
        for method in methods.keys():
            url = f"{API_BASE_URL}{path}"
            res = test_endpoint(method, path, url)

            status_str = str(res["status"])
            time_str = f"{res['time_ms']:.1f} ms" if res["time_ms"] is not None else "-"

            if res["status"] == "SKIPPED":
                skipped += 1
                status_str = "ATLANDI"
            elif isinstance(res["status"], int) and res["status"] < 500:
                success += 1
                if res["status"] in (401, 403):
                    status_str = f"{res['status']} (Auth)"
            else:
                failed += 1

            logger.info(f"{method.upper():<7} | {path:<40} | {status_str:<10} | {time_str}")

            if res["error"] and res["status"] != "SKIPPED":
                logger.info(f"          └─ Hata: {res['error']}")

    logger.info("-" * 80)
    logger.info(
        f"Toplam: {success + skipped + failed} | Başarılı/Beklenen: {success} | Atlanan: {skipped} | Hatalı: {failed}"
    )
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
