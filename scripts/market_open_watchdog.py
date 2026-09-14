"""
ALPHA BIST - Automated Market Open Watchdog
Borsa İstanbul açılış öncesi (09:10 - 10:05) sistem entegrasyonu, veri akışı ve yürütme gözlemcisi.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
import os
import sys
import httpx
import orjson
import structlog

# Windows UTF-8 / CP1254 guard
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logger = structlog.get_logger("market_open_watchdog")

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TURKEY_TZ = timezone(timedelta(hours=3))


async def run_market_check() -> dict:
    now = datetime.now(TURKEY_TZ)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    report = {
        "timestamp": now_str,
        "market_phase": "UNKNOWN",
        "containers_healthy": False,
        "api_healthy": False,
        "signals_ready": False,
        "kap_connected": False,
        "checks": [],
    }
    
    # 1. Market Phase Determination
    time_val = now.time()
    if time_val < datetime.strptime("09:40", "%H:%M").time():
        report["market_phase"] = "PRE_SESSION_PREPARATION (09:00 - 09:40)"
    elif time_val < datetime.strptime("09:55", "%H:%M").time():
        report["market_phase"] = "OPENING_AUCTION_ORDER_COLLECTION (09:40 - 09:55)"
    elif time_val < datetime.strptime("10:00", "%H:%M").time():
        report["market_phase"] = "OPENING_PRICE_DETERMINATION (09:55 - 10:00)"
    elif time_val < datetime.strptime("18:00", "%H:%M").time():
        report["market_phase"] = "CONTINUOUS_AUCTION_LIVE (10:00 - 18:00)"
    else:
        report["market_phase"] = "POST_MARKET_EOD (18:00+)"

    # 2. Check API Health
    async with httpx.AsyncClient(timeout=10.0) as client:
        # /api/v1/system/health
        try:
            r = await client.get(f"{API_BASE_URL}/api/v1/system/health")
            if r.status_code == 200:
                h_data = r.json()
                report["api_healthy"] = True
                report["checks"].append({
                    "name": "API & Services Health",
                    "status": "OK",
                    "details": h_data.get("services", {})
                })
            else:
                report["checks"].append({"name": "API Health", "status": "FAIL", "code": r.status_code})
        except Exception as e:
            report["checks"].append({"name": "API Health", "status": "ERROR", "error": str(e)})

        # /api/v1/scanner/signals
        try:
            r = await client.get(f"{API_BASE_URL}/api/v1/scanner/signals?limit=15")
            if r.status_code == 200:
                sigs = r.json()
                sig_count = len(sigs) if isinstance(sigs, list) else len(sigs.get("signals", []))
                report["signals_ready"] = sig_count > 0
                report["checks"].append({
                    "name": "Live Scanner & Signal Engine",
                    "status": "OK",
                    "signal_count": sig_count
                })
            else:
                report["checks"].append({"name": "Scanner", "status": "FAIL", "code": r.status_code})
        except Exception as e:
            report["checks"].append({"name": "Scanner", "status": "ERROR", "error": str(e)})

        # /api/v1/intelligence/kap-feed
        try:
            r = await client.get(f"{API_BASE_URL}/api/v1/intelligence/kap-feed?limit=10")
            if r.status_code == 200:
                report["kap_connected"] = True
                report["checks"].append({"name": "KAP Intelligence Feed", "status": "OK"})
            else:
                report["checks"].append({"name": "KAP Feed", "status": "FAIL", "code": r.status_code})
        except Exception as e:
            report["checks"].append({"name": "KAP Feed", "status": "ERROR", "error": str(e)})

    # Print summary cleanly
    print(f"\n[{report['timestamp']}] WATCHDOG RAPORU")
    print(f"  Piyasa Fazı:       {report['market_phase']}")
    print(f"  API Durumu:        {'AKTIF' if report['api_healthy'] else 'HATA'}")
    print(f"  Sinyal Motoru:     {'HAZIR' if report['signals_ready'] else 'BEKLEMEDE'}")
    print(f"  KAP Servisi:       {'BAGLI' if report['kap_connected'] else 'HATA'}")
    for c in report["checks"]:
        print(f"  - {c['name']}: {c['status']}")
    
    return report


if __name__ == "__main__":
    asyncio.run(run_market_check())
