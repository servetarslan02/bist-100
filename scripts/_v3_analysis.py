# PATCH: v3 giriş filtresi hafifletmesi ve v2 ile hibrit test
import sys

sys.path.insert(0, ".")
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception as err:
        sys.stderr.write(f"[Handled Error] {err}\n")

# v2 vs v3 yil yil karsilastirma ozeti
results = {
    "v1": {"10y": 113.2, "sharpe": 0.45, "maxdd": -59.0, "beat": 1},
    "v2": {"10y": 1500.8, "sharpe": 1.45, "maxdd": -30.1, "beat": 4},
    "v3": {"10y": 962.2, "sharpe": 1.27, "maxdd": -33.6, "beat": 4},
    "BIST": {"10y": 1757.1, "sharpe": 0, "maxdd": 0, "beat": 0},
}

print("\n" + "="*65)
print("  STRATEJI VERSIYONU KARSILASTIRMA  (2016-2026)")
print("="*65)
print(f"  {'Versiyon':<12} {'10Y Getiri':>12} {'Sharpe':>10} {'MaxDD':>10} {'Beat Yil':>10}")
print("-"*57)
for v, r in results.items():
    print(f"  {v:<12} {r['10y']:>11.1f}% {r['sharpe']:>10.2f} {r['maxdd']:>9.1f}% {r['beat']:>10}")
print("="*65)

print("""
TEŞHİS:
  v2 > v3 olmasının nedeni: v3'te agirlik hesabı gürültü yaratıyor.
  BIST-100'ü tutarli sekilde gecme sorunu devam ediyor.

NEDEN BIST'İ GEÇEMIYORUZ?
  1. BIST nominal getiriler TAMAMEN enflasyon gurdumlu (2019-2025 arası)
  2. En büyük getiriler "geride kalan kalite hisseler"den geliyor
  3. Momentum filtresi bu hisseleri eliyor (henüz hareket etmemişler)
  4. Sektör rotasyonu: Hangi sektör, hangi yıl liderdi?
     2021: Holding/Koç grubu: +%60 (vs BIST +%29) - biz tutamadık
     2023: Küçük cap: çok yüksek getiri - evrende yok
     2024: Holding/Enerji: biz ağır hisselerde kaldık

ÇÖZÜM (v4 Hibrit):
  1. v2'nin güçlü tarafını koru (hiç cash tutma, SMA50 rejim)
  2. Sektör liderini takip et: SMA50 üstünde olan SEKTÖRDE pozisyon al
  3. Aylık yerine HAFTALIK rebalancing ile sektor rotasyonuna hızlı uy
  4. "Düşük momentum ama yükselen" hisseleri de al (dip tarayıcı)
  5. Tek sektörde max %40 konsantrasyon limiti
""")
