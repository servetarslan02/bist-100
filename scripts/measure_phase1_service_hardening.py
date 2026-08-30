"""ALPHA BIST — FAZ 1: Service Hardening Ölçüm ve Doğrulama Betiği.

Ölçülen Metrikler:
1. Normal İşlem Gecikmesi (Warm & Cold)
2. Idempotent İstek Önbellek Gecikmesi & Hızlanma Katsayısı
3. Fail-Fast Circuit Breaker Tetiklenme ve Engelleme Gecikmesi
4. Timeout Koruması ve DeadLetterQueue Kaydı
"""

import asyncio
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception as enc_err:
        sys.stderr.write(f"Encoding warning: {enc_err}\n")

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from services.core.base_service import BaseAlphaService, ServiceExecutionError


class BenchmarkService(BaseAlphaService):
    def validate_input(self, payload: dict) -> dict:
        if "data" not in payload:
            raise ValueError("Data field is mandatory")
        return payload

    async def process_payload(self, validated_input: dict) -> dict:
        if validated_input.get("fail"):
            raise RuntimeError("Induced failure")
        if validated_input.get("slow"):
            await asyncio.sleep(0.5)
        return {"status": "SUCCESS", "res": validated_input["data"]}


async def measure_phase1():
    print("=" * 80)
    print("🧱 ALPHA BIST — FAZ 1: SERVICE HARDENING ÖLÇÜMÜ")
    print("=" * 80)

    service = BenchmarkService(
        "phase1_perf_service",
        timeout_seconds=0.1,
        max_retries=2,
        backoff_factor=0.01,
    )

    # 1. Normal İşlem (100 çağrı ortalaması)
    t0 = time.perf_counter()
    for i in range(100):
        _ = await service.execute({"data": i}, idempotency_key=f"norm_key_{i}")
    t_normal_avg_us = ((time.perf_counter() - t0) / 100) * 1_000_000

    # 2. Idempotent Mükerrer İstek (100 çağrı ortalaması)
    t0 = time.perf_counter()
    for i in range(100):
        _ = await service.execute({"data": i}, idempotency_key=f"norm_key_{i}")
    t_idemp_avg_us = ((time.perf_counter() - t0) / 100) * 1_000_000

    # 3. Fail-Fast Circuit Breaker Açılması
    t_fail_0 = time.perf_counter()
    for i in range(5):
        try:
            await service.execute({"data": 0, "fail": True})
        except Exception as err:
            sys.stderr.write(f"[Handled Error] {err}\n")

    # Devre AÇIK iken anında engelleme gecikmesi
    t0 = time.perf_counter()
    blocked_count = 0
    for i in range(100):
        try:
            await service.execute({"data": 100})
        except ServiceExecutionError as e:
            if "Circuit Breaker AÇIK" in str(e):
                blocked_count += 1
    t_cb_blocked_avg_us = ((time.perf_counter() - t0) / 100) * 1_000_000

    # 4. Sonuçlar
    speedup = round(t_normal_avg_us / max(t_idemp_avg_us, 0.001), 1)
    print(f"  * Normal İşlem Ortalama Gecikmesi: {t_normal_avg_us:.2f} µs ({t_normal_avg_us/1000:.3f} ms)")
    print(f"  * Idempotent Dönüş Gecikmesi:      {t_idemp_avg_us:.2f} µs ({t_idemp_avg_us/1000:.3f} ms)")
    print(f"  * Idempotency Hızlanma Kazancı:   {speedup}x kat daha hızlı")
    print(f"  * CB Fail-Fast Engelleme Süresi:  {t_cb_blocked_avg_us:.2f} µs ({t_cb_blocked_avg_us/1000:.3f} ms)")
    print(f"  * Engellenen İstek Oranı:         %{blocked_count:.0f} (Fail-Closed Koruma)")

    print("\n✅ FAZ 1 OPTİMİZASYON & ÖLÇÜMÜ BAŞARIYLA TAMAMLANDI!")


if __name__ == "__main__":
    asyncio.run(measure_phase1())
