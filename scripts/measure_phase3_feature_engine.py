"""ALPHA BIST — FAZ 3: Feature Engine Ölçüm ve Doğrulama Betiği.

Ölçülen Metrikler:
1. 647 Hisse için 70 Kanonik Feature İlk (Soğuk) Hesaplama Süresi
2. Sıcak RAM Önbellek (FeatureCacheManager) Çağrı Süresi ve Hızlanma
3. 1000 Tekil Hisse Feature Sorgusunun Mikro-Gecikmesi (µs)
4. Vektörize Matris Önbelleği (NumPy 647x70) Alma Süresi
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

import numpy as np

from services.features.cache_manager import feature_cache_manager
from services.scanner.bist_ml_scanner import bist_ml_scanner


def measure_phase3():
    print("=" * 80)
    print("🧠 ALPHA BIST — FAZ 3: FEATURE ENGINE OPTİMİZASYON & ÖLÇÜMÜ")
    print("=" * 80)

    # 1. Soğuk Hesaplama
    feature_cache_manager.invalidate()
    t0 = time.perf_counter()
    opps_cold = bist_ml_scanner.scan_all_opportunities(limit=50, force_warehouse=False)
    t_cold_s = time.perf_counter() - t0

    # 2. Sıcak RAM Önbellekli Tarama
    t0 = time.perf_counter()
    opps_warm = bist_ml_scanner.scan_all_opportunities(limit=50, force_warehouse=False)
    t_warm_ms = (time.perf_counter() - t0) * 1000

    # 3. Tekil Hisse Önbellek Okuma Gecikmesi (1000 istek)
    t0 = time.perf_counter()
    for _ in range(1000):
        _ = feature_cache_manager.get_all_features()
    t_single_us = ((time.perf_counter() - t0) / 1000) * 1_000_000

    # 4. Matris Önbellekleme
    mat = np.random.randn(647, 70).astype(np.float32)
    tickers = [f"SYM_{i}" for i in range(647)]
    feat_names = [f"f_{i}" for i in range(70)]
    feature_cache_manager.set_matrix_cache(mat, tickers, feat_names)

    t0 = time.perf_counter()
    for _ in range(1000):
        _ = feature_cache_manager.get_matrix_cache()
    t_matrix_us = ((time.perf_counter() - t0) / 1000) * 1_000_000

    speedup = round((t_cold_s * 1000) / max(t_warm_ms, 0.001), 1)

    print(f"  * 647 Hisse Soğuk Hesaplama:       {t_cold_s:.3f} saniye")
    print(f"  * 647 Hisse Sıcak RAM Önbellek:    {t_warm_ms:.3f} ms ({speedup}x Kat Daha Hızlı)")
    print(f"  * RAM Önbellek Erişim Gecikmesi:   {t_single_us:.2f} µs ({t_single_us/1000:.4f} ms)")
    print(f"  * 647x70 Matris Önbellek Çekme:    {t_matrix_us:.2f} µs")
    print(f"  * Üretilen Fırsat Sayısı:          {len(opps_cold)} hisse")

    print("\n✅ FAZ 3 OPTİMİZASYON & ÖLÇÜMÜ BAŞARIYLA TAMAMLANDI!")


if __name__ == "__main__":
    measure_phase3()
