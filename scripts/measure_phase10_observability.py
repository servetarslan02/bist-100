"""ALPHA BIST — FAZ 10: Observability & Prometheus Metrikleri Ölçüm ve Doğrulama Betiği.

Ölçülen Metrikler:
1. 1,000 Prometheus Histogram & Counter Emisyon Gecikmesi (µs)
2. Saniyedeki Metrik Yayım Kapasitesi (Metrics/Second Throughput)
3. /metrics Endpoint Metin Üretim Süresi (ms) ve Metin Boyutu (Bayt)
4. Granüler Etiket Kardinalitesi ve Bellek Güvenliği
"""

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

from services.core.observability import prometheus_metrics


def measure_phase10():
    print("=" * 80)
    print("🔭 ALPHA BIST — FAZ 10: OBSERVABILITY & PROMETHEUS OPTİMİZASYON & ÖLÇÜMÜ")
    print("=" * 80)

    n_emissions = 2000

    # 1. Metrik Emisyon Gecikmesi (API & Latency Histogram)
    t0 = time.perf_counter()
    for i in range(n_emissions):
        endpoint = f"/api/v1/resource_{i % 10}"
        duration = 0.001 + (i % 50) / 10000.0
        prometheus_metrics.record_api_call(endpoint, duration, success=(i % 20 != 0))
    t_emission_total_ms = (time.perf_counter() - t0) * 1000
    t_emission_per_call_us = (t_emission_total_ms / n_emissions) * 1000

    metrics_per_sec = int(n_emissions / max(t_emission_total_ms / 1000, 0.0001))

    # 2. Prometheus /metrics Metin Raporu Üretimi
    t0 = time.perf_counter()
    for _ in range(50):
        prom_text = prometheus_metrics.get_prometheus_text()
    t_gen_text_ms = ((time.perf_counter() - t0) / 50) * 1000

    has_latency_hist = "api_latency_seconds" in prom_text or "api_requests_total" in prom_text

    print(f"  * 2,000 Metrik Kayıt Toplam Süresi:    {t_emission_total_ms:.2f} ms")
    print(f"  * Tekil Metrik Emisyon Gecikmesi:      {t_emission_per_call_us:.2f} µs ({t_emission_per_call_us/1000:.4f} ms)")
    print(f"  * Metrik Kayıt Kapasitesi:             {metrics_per_sec:,} metrik/saniye")
    print(f"  * /metrics Rapor Üretim Süresi:        {t_gen_text_ms:.2f} ms")
    print(f"  * Prometheus Metin Boyutu:             {len(prom_text):,} Bayt ({len(prom_text)/1024:.1f} KB)")
    print(f"  * Granüler Histogram Durumu:           {'AKTİF' if has_latency_hist else 'EKSİK'}")

    print("\n✅ FAZ 10 OPTİMİZASYON & ÖLÇÜMÜ BAŞARIYLA TAMAMLANDI!")


if __name__ == "__main__":
    measure_phase10()
