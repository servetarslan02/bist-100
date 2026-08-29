"""
ALPHA BIST — Canli Veri ve Servis Handshake Testi
PostgreSQL, ClickHouse, Redis, NATS servislerine gercek veri gonderip yanıt alir.
"""
import sys
import asyncio
import os
from pathlib import Path
def load_env_file():
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env_file()

sys.stdout.reconfigure(encoding="utf-8")

async def test_postgres():
    try:
        import asyncpg
        user = os.getenv("POSTGRES_USER", "alpha")
        pwd = os.getenv("POSTGRES_PASSWORD", "")
        db = os.getenv("POSTGRES_DB", "alpha_bist")
        host = "127.0.0.1"
        port = int(os.getenv("POSTGRES_PORT", "5432"))
        
        conn = await asyncpg.connect(user=user, password=pwd, database=db, host=host, port=port, timeout=5)
        val = await conn.fetchval("SELECT 1 + 1;")
        version = await conn.fetchval("SELECT version();")
        await conn.close()
        return True, f"Handshake Başarılı (Sonuç: {val}, Version: {version.split()[0]} {version.split()[1]})"
    except Exception as e:
        return False, f"Postgres Bağlantı Hatası: {e}"

async def test_redis():
    try:
        import redis.asyncio as aioredis
        pwd = os.getenv("REDIS_PASSWORD", None)
        host = "127.0.0.1"
        port = int(os.getenv("REDIS_PORT", "6379"))
        
        r = aioredis.Redis(host=host, port=port, password=pwd, socket_timeout=3)
        pong = await r.ping()
        await r.set("alpha:healthcheck:test_key", "active", ex=10)
        val = await r.get("alpha:healthcheck:test_key")
        await r.aclose()
        return True, f"PING={pong}, SET/GET={val.decode() if isinstance(val, bytes) else val} (OK)"
    except Exception as e:
        return False, f"Redis Bağlantı Hatası: {e}"

async def test_clickhouse():
    try:
        import urllib.request
        user = os.getenv("CLICKHOUSE_USER", "alpha")
        pwd = os.getenv("CLICKHOUSE_PASSWORD", "")
        url = f"http://127.0.0.1:8123/?query=SELECT%20version()"
        
        req = urllib.request.Request(url)
        if user and pwd:
            import base64
            auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            req.add_header("Authorization", f"Basic {auth}")
            
        with urllib.request.urlopen(req, timeout=3) as resp:
            ver = resp.read().decode().strip()
            return True, f"ClickHouse Query OK (Version: {ver})"
    except Exception as e:
        return False, f"ClickHouse Hatası: {e}"

async def test_nats():
    try:
        import nats
        nc = await nats.connect("nats://127.0.0.1:4222", connect_timeout=3)
        received = []
        async def handler(msg):
            received.append(msg.data.decode())
        sub = await nc.subscribe("alpha.healthcheck.test", cb=handler)
        await nc.publish("alpha.healthcheck.test", b"LIVE_PAYLOAD_TEST_OK")
        await nc.flush(timeout=2)
        await asyncio.sleep(0.1)
        await sub.unsubscribe()
        await nc.close()
        if received and received[0] == "LIVE_PAYLOAD_TEST_OK":
            return True, f"Pub/Sub Mesajlaşma Başarılı ({received[0]})"
        return False, f"NATS mesajı alınamadı (Boş yanıt)"
    except Exception as e:
        return False, f"NATS Hatası: {e}"

async def main():
    print("=" * 80)
    print("  ALPHA BIST — CANLI VERİ TABANI & MESAJLAŞMA HANDSHAKE TESTİ")
    print("=" * 80)
    
    tests = [
        ("PostgreSQL TimescaleDB", test_postgres()),
        ("Redis Master Cache", test_redis()),
        ("ClickHouse Analitik DB", test_clickhouse()),
        ("NATS Event Bus", test_nats()),
    ]
    
    for name, coro in tests:
        ok, msg = await coro
        status = "✅ ÇALIŞIYOR" if ok else "❌ HATA"
        print(f"  [{status}] {name:<25} : {msg}")
        
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
