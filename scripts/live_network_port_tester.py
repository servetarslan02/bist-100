import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""
ALPHA BIST — Canli Port, Ag ve Servis Entegrasyon Testi
Tum Docker servislerinin TCP portlarini, HTTP health endpoint'lerini,
veritabani baglantilarini (Postgres, ClickHouse, Redis, NATS, QuestDB) canli test eder.
"""

import socket
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

PORTS_TO_CHECK = [
    {"name": "Traefik HTTP", "host": "127.0.0.1", "port": 80, "protocol": "TCP"},
    {"name": "Traefik Dashboard", "host": "127.0.0.1", "port": 8080, "protocol": "TCP"},
    {
        "name": "Alpha API (FastAPI)",
        "host": "127.0.0.1",
        "port": 8000,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:8000/health",
    },
    {"name": "Alpha gRPC Port", "host": "127.0.0.1", "port": 50051, "protocol": "TCP"},
    {"name": "PostgreSQL Primary", "host": "127.0.0.1", "port": 5432, "protocol": "TCP"},
    {"name": "PostgreSQL Replica", "host": "127.0.0.1", "port": 5433, "protocol": "TCP"},
    {"name": "PgBouncer Pooler", "host": "127.0.0.1", "port": 6432, "protocol": "TCP"},
    {
        "name": "ClickHouse 1 (HTTP)",
        "host": "127.0.0.1",
        "port": 8123,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:8123/ping",
    },
    {"name": "ClickHouse 1 (Native)", "host": "127.0.0.1", "port": 9002, "protocol": "TCP"},
    {
        "name": "ClickHouse 2 (HTTP)",
        "host": "127.0.0.1",
        "port": 8124,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:8124/ping",
    },
    {"name": "ClickHouse 2 (Native)", "host": "127.0.0.1", "port": 9001, "protocol": "TCP"},
    {"name": "Redis Master", "host": "127.0.0.1", "port": 6379, "protocol": "TCP"},
    {"name": "NATS Client", "host": "127.0.0.1", "port": 4222, "protocol": "TCP"},
    {
        "name": "NATS Monitor",
        "host": "127.0.0.1",
        "port": 8222,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:8222/healthz",
    },
    {
        "name": "QuestDB (Web/REST)",
        "host": "127.0.0.1",
        "port": 9000,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:9000/",
    },
    {"name": "QuestDB (PG Wire)", "host": "127.0.0.1", "port": 8812, "protocol": "TCP"},
    {"name": "QuestDB (ILP Influx)", "host": "127.0.0.1", "port": 9009, "protocol": "TCP"},
    {"name": "Zookeeper", "host": "127.0.0.1", "port": 2181, "protocol": "TCP"},
    {
        "name": "Prometheus",
        "host": "127.0.0.1",
        "port": 9090,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:9090/-/healthy",
    },
    {
        "name": "Grafana Dashboard",
        "host": "127.0.0.1",
        "port": 3001,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:3001/api/health",
    },
    {
        "name": "Redis Exporter",
        "host": "127.0.0.1",
        "port": 9121,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:9121/health",
    },
    {"name": "Postgres Exporter", "host": "127.0.0.1", "port": 9187, "protocol": "TCP"},
    {
        "name": "Frontend Dashboard",
        "host": "127.0.0.1",
        "port": 3000,
        "protocol": "HTTP",
        "url": "http://127.0.0.1:3000/",
    },
]


def check_tcp(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float, str]:
    """Otomatik eklendi."""
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed_ms = (time.time() - t0) * 1000
            return True, elapsed_ms, "AÇIK (Socket OK)"
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        return False, elapsed_ms, str(e)


def check_http(url: str, timeout: float = 2.5) -> tuple[bool, float, str]:
    """Otomatik eklendi."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Alpha-Healthcheck/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = (time.time() - t0) * 1000
            code = resp.getcode()
            return True, elapsed_ms, f"HTTP {code} OK"
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.time() - t0) * 1000
        # 200-399 veya 401/403 (servis ayakta ama auth istiyor)
        if e.code in (200, 301, 302, 401, 403):
            return True, elapsed_ms, f"HTTP {e.code} (Ayakta/Korumalı)"
        return False, elapsed_ms, f"HTTP {e.code}"
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        return False, elapsed_ms, str(e)


def run_suite() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 80)
    logger.info("  ALPHA BIST — CANLI AĞ, PORT & SERVİS ENTEGRASYON TESTİ")
    logger.info(f"  Zaman: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    logger.info(f"{'#':<3} | {'Servis Adı':<26} | {'Port':<6} | {'Protokol':<8} | {'Gecikme':<9} | {'Durum'}")
    logger.info("-" * 80)

    success_count = 0
    fail_count = 0

    for i, target in enumerate(PORTS_TO_CHECK, 1):
        name = target["name"]
        host = target["host"]
        port = target["port"]
        proto = target["protocol"]

        if proto == "HTTP" and "url" in target:
            ok, ms, msg = check_http(target["url"])
            if not ok:
                # HTTP basarisizsa en azindan TCP socket acik mi dene
                tcp_ok, tcp_ms, tcp_msg = check_tcp(host, port)
                if tcp_ok:
                    ok = True
                    msg = f"TCP Açık, HTTP Yanıt: {msg}"
                    ms = tcp_ms
        else:
            ok, ms, msg = check_tcp(host, port)

        if ok:
            status_symbol = "✅ BAŞARILI"
            success_count += 1
        else:
            status_symbol = "❌ BAŞARISIZ"
            fail_count += 1

        logger.info(f"{i:<3} | {name:<26} | {port:<6} | {proto:<8} | {ms:>6.1f} ms | {status_symbol} ({msg})")

    logger.info("-" * 80)
    logger.info(f"  Toplam Port: {len(PORTS_TO_CHECK)} | Başarılı: {success_count} | Başarısız: {fail_count}")
    logger.info("=" * 80)


if __name__ == "__main__":
    run_suite()
