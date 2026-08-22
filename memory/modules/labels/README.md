# Labels

**Modül sayısı:** 1 | **Toplam satır:** ~350 | **Test sayısı:** 6

## Modüller

| Modül | Dosya | Sınıf/Fonksiyon | Açıklama |
|-------|-------|-----------------|----------|
| Label Generator | `generator.py` | LabelGenerator, LabelResult | Forward return label üretimi, binary label, cross-sectional rank, sector/benchmark relative, max drawdown, forward volatilite, purge gap |

## Spec Uyumu

| Spec Maddesi | Durum | Not |
|-------------|-------|-----|
| Forward return labels | ✅ TAM | 1d, 5d, 10d, 20d ufuklar |
| Binary labels | ✅ TAM | Pozitif/negatif (0/1) |
| Cross-sectional rank | ✅ TAM | Evren içi sıralama (0-1) |
| Sector relative | ✅ TAM | Sektör getiri farkı |
| Benchmark relative | ✅ TAM | BIST getiri farkı |
| Max drawdown | ✅ TAM | Forward 20 gün peak-to-trough |
| Forward volatilite | ✅ TAM | Yıllıklandırılmış, forward 20 gün |
| Purge gap | ✅ TAM | Feature-label sızıntı önleme |
| Mask-aware | ✅ TAM | mask=0 günler hariç |

## Label Kataloğu

| Label | Tip | Açıklama |
|-------|-----|----------|
| `y_1d` | Continuous | Gelecek 1 gün getiri (%) |
| `y_5d` | Continuous | Gelecek 5 gün getiri (%) |
| `y_10d` | Continuous | Gelecek 10 gün getiri (%) |
| `y_20d` | Continuous | Gelecek 20 gün getiri (%) |
| `y_5d_binary` | Binary | 5 gün pozitif mi? (0/1) |
| `y_20d_binary` | Binary | 20 gün pozitif mi? (0/1) |
| `y_5d_vs_sector` | Continuous | 5 gün sektöre göre fazla getiri |
| `y_20d_vs_sector` | Continuous | 20 gün sektöre göre fazla getiri |
| `y_5d_vs_benchmark` | Continuous | 5 gün BIST'e göre fazla getiri |
| `y_20d_vs_benchmark` | Continuous | 20 gün BIST'e göre fazla getiri |
| `y_5d_outperform` | Binary | 5 gün BIST'i geçti mi? (0/1) |
| `y_20d_outperform` | Binary | 20 gün BIST'i geçti mi? (0/1) |
| `y_max_dd_20d` | Continuous | Forward 20 gün max drawdown (%) |
| `y_volatility_20d` | Continuous | Forward 20 gün yıllık volatilite (%) |
