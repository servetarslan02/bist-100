# LABELS — Etiket Üretim Katmanı

> Bu belge hedef mimariyi tanımlar, bugün kodda gerçekte var olan/olmayan kısımlar için `CURRENT-STATE.md`'ye bakın.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────────┐
│                      LABEL SERVICES                             │
├─────────────────────────────────────────────────────────────────┤
│  generator.py                                                   │
│  ├─ LabelGenerator                                              │
│  │  ├─ generate_labels()           → Tek hisse için tüm label'lar│
│  │  ├─ generate_cross_sectional_ranks() → Cross-sectional rank  │
│  │  └─ get_label_names()           → Label isim listesi         │
│  │                                                              │
│  ├─ LabelResult                                                 │
│  │  ├─ ticker                                                  │
│  │  ├─ labels: Dict[str, np.ndarray]                           │
│  │  ├─ valid_mask: np.ndarray                                  │
│  │  └─ stats: Dict[str, float]                                 │
│  │                                                              │
│  └─ Label Tipleri:                                              │
│     ├─ y_1d, y_5d, y_10d, y_20d       (forward return %)       │
│     ├─ y_Xd_binary                     (pozitif mi? 0/1)        │
│     ├─ y_Xd_vs_sector                  (sektöre göre fazla getiri)│
│     ├─ y_Xd_vs_benchmark               (BIST'e göre fazla getiri)│
│     ├─ y_Xd_outperform                 (BIST'i geçti mi? 0/1)   │
│     ├─ y_max_dd_20d                    (max drawdown %)         │
│     └─ y_volatility_20d                (forward volatilite %)   │
└─────────────────────────────────────────────────────────────────┘
```

## Neden Bu Teknoloji / Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| **Forward return** tabanlı label'lar | En basit ve en yaygın target variable; Du (2026) cross-sectional ranking yaklaşımı |
| **Çoklu ufuk** (1d, 5d, 10d, 20d) | Farklı trading stratejileri için farklı ufuklar; kısa vadeli momentum vs. orta vadeli trend |
| **Binary label** (pozitif/negatif) | Sınıflandırma modelleri için; regresyon modelleri continuous label kullanır |
| **Cross-sectional rank** | Hisse-hisse karşılaştırma; mutlak getiri yerine göreli performans |
| **Sektör/Benchmark relative** | Sektör ve piyasa etkisinden arındırılmış alpha ölçümü |
| **Purge gap** | Feature penceresi ile label arasında sızıntı önleme (look-ahead bias) |
| **Mask-aware** | Tradability mask=0 olan günler label'dan hariç tutulur |
| **NumPy vektörize** | Büyük veri setlerinde hızlı hesaplama; Python loop yerine NumPy operations |

## Uçtan Uca Veri Akışı

```
1. LabelGenerator.generate_labels(ticker, close, mask, ...) çağrılır
2. Log returns hesaplanır (mask-aware):
   - mask[i]=1 ve mask[i-1]=1 ise: log(close[i]/close[i-1])
   - Değilse: NaN

3. Forward return'ler hesaplanır (her periyot için):
   3a. y_Xd = (close[i+X] / close[i] - 1) * 100
   3b. mask[i]=1 ve mask[i+X]=1 ise hesapla, değilse NaN
   3c. y_Xd_binary = 1 if y_Xd > 0 else 0

4. Sektör relative (varsa):
   4a. y_Xd_vs_sector = y_Xd - sector_returns[i] * X
   4b. Sektör getiri serisi dışarıdan sağlanır

5. Benchmark relative (varsa):
   5a. y_Xd_vs_benchmark = y_Xd - benchmark_returns[i] * X
   5b. y_Xd_outperform = 1 if y_Xd_vs_benchmark > 0 else 0

6. Max drawdown (forward 20 gün):
   6a. Gelecek 21 günlük fiyat serisi
   6b. Peak = accumulate(max)
   6c. drawdown = (peak - price) / peak
   6d. y_max_dd_20d = max(drawdown) * 100

7. Forward volatilite (forward 20 gün):
   7a. Gelecek 20 günlük log return'ler
   7b. std * sqrt(252) * 100 (yıllıklandırılmış)

8. Purge gap uygulanır (purge_days > 0 ise):
   8a. Son purge_days barı NaN yapılır
   8b. valid_mask son purge_days barı False yapılır

9. Cross-sectional rank (tüm hisseler için):
   9a. Her gün için tüm hisselerin label değerleri toplanır
   9b. Sıralama yapılır (0-1 arası rank)
   9c. {ticker: rank_values} döndürülür
```

## Servis Sınırları ve Sorumlulukları

| Dosya | Sorumluluk | Katman |
|-------|-----------|--------|
| `services/labels/generator.py` | Forward return label üretimi, binary label, cross-sectional rank, sector/benchmark relative, max drawdown, forward volatilite, purge gap | Üretim |

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

## Tasarım İlkeleri ve Kırmızı Çizgiler

### İlkeler

1. **Look-ahead bias = ölüm**: Label'lar sadece gelecek veri kullanılarak üretilir; feature'lar geçmiş veri ile hesaplanır
2. **Mask-aware**: Tradability mask=0 olan günler label'dan hariç tutulur
3. **Purge gap**: Feature penceresi ile label arasında purge_days kadar boşluk bırakılır
4. **Cross-sectional**: Hisse-hisse karşılaştırma; mutlak getiri yerine göreli performans
5. **Çoklu ufuk**: Farklı stratejiler için farklı ufuklar (1d, 5d, 10d, 20d)

### Kırmızı Çizgiler

- ❌ Feature hesaplama penceresindeki veri label hesaplamasında kullanılamaz (purge gap)
- ❌ mask=0 olan günler label hesaplamasına giremez
- ❌ Gelecek fiyat bilgisi feature hesaplamasına sızamaz (look-ahead bias)
- ❌ Cross-sectional rank hesaplarken NaN değerler rank'a dahil edilemez

## Bilinen Sınırlamalar

1. **Tek dosya**: Tüm label üretimi tek bir `generator.py` dosyasında; büyük universe'de paralelleştirme gerekli
2. **Sektör getiri**: `sector_returns` parametresi opsiyonel; sağlanmazsa sector-relative label'lar üretilmez
3. **Benchmark getiri**: `benchmark_returns` parametresi opsiyonel; sağlanmazsa benchmark-relative label'lar üretilmez
4. **Purge gap sabit**: `purge_days` parametre olarak gelir; otomatik feature penceresi boyutuna göre ayarlanmaz
5. **Max drawdown hesaplama**: Basit peak-to-trough; intra-day drawdown hesaplanmaz
6. **Forward volatilite**: Yıllıklandırılmış; günlük volatilite istenirse ayrı hesaplanmalı
7. **Cross-sectional rank**: Tüm hisseler aynı anda işlenmeli; incremental rank güncellemesi yok

## Cross-Reference

| Modül | Bağlantı |
|-------|----------|
| **core** | `canonical_scoring.py` → label'lar model eğitiminde target olarak kullanılır; `data_quality.py` → mask=0 olan günler label'dan hariç tutulur |
| **data** | `data_source.py` → close fiyatları label üretimi için sağlanır; `historical_adapter.py` → fundamental/event label'ları ayrı üretilir |
| **events** | Event'ler label kalitesini etkileyebilir (örn: KAP açıklaması sonrası fiyat hareketi) |
| **features** | `calculator.py` → feature'lar geçmiş veri ile, label'lar gelecek veri ile hesaplanır; purge gap aralarındaki sızıntıyı önler |
| **learning** | `integrated_learning.py` → label'lar model eğitimi ve backtest için kullanılır |
