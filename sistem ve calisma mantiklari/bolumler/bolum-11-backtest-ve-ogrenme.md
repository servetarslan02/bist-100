# Bölüm 11 — Backtest ve Öğrenme

## Amaç

Geçmişte test etmek, sonuçlardan öğrenmek ve modeli geliştirmek. "Bu strateji geçmişte çalışır mıydı?" ve "Nerede hata yapıyorum?" sorularının cevabı.

## Çalışma Mantığı

```
Strateji → Walk-forward → Backtest → Metrikler → Hata analizi → Öğrenme → Geri bildirim
```

## Temel Prensip

Geçmişi ezberleyen model işe yaramaz. Walk-forward validation zorunlu.

---

## 1. Walk-Forward Validation

**Amaç:** Data leakage'ı önler.

**Yöntem:**
- Train: 252 gün (1 yıl)
- Test: 63 gün (3 ay)
- Step: 21 gün (1 ay)
- Purge: 5 gün (train-test arası gap)
- Embargo: 5 gün (test-train arası gap)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/backtest/enhanced_walk_forward.py`

---

## 2. Backtest Metrikleri

**Metrikler:**
- Toplam getiri
- CAGR
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Maksimum drawdown
- Kazanma oranı
- Profit factor
- Ortalama kazanç / kayıp
- Devir hızı
- Toplam komisyon

**Durum:** ✅ Çalışıyor

**Dosya:** `services/backtest/engine.py`

---

## 3. Değerlendirme Metrikleri

**Metrikler:**
- **Alpha:** BIST'e göre fazla getiri
- **Precision@K:** İlk 5/10/20 hisseden kaç tanesi iyi
- **Information Coefficient (IC):** Model skoru ile gelecek getiri korelasyonu
- **Hit rate:** Yön doğruluğu
- **Turnover:** İşlem sıklığı

**Durum:** ✅ Çalışıyor

**Dosya:** `services/backtest/enhanced_walk_forward.py`

---

## 4. Overfitting Tespiti

**Metrik:** Deflated Sharpe Ratio

**Yöntem:** Backtest sayısı arttıkça Sharpe'ın güvenilirliği düşer. Multiple testing düzeltmesi.

**Durum:** ✅ Çalışıyor

**Dosya:** `services/backtest/enhanced_walk_forward.py`

---

## 5. Learning Engine

**Amaç:** Tahminlerden ve sonuçlardan öğrenir.

**İşlem:**
1. Her karar → prediction kaydet (feature snapshot ile)
2. Zaman geçti → outcome kaydet (gerçek fiyat)
3. Eşleştir → doğru/yanlış hesapla
4. Analiz et → hangi rejimde, hangi feature'da hata yapıyor?
5. Güncelle → gelecek kararları ayarla

**Durum:** ✅ Çalışıyor (prediction → outcome → feedback döngüsü)

**Dosya:** `services/learning/integrated_learning.py`

---

## 6. Drift Detection

**Amaç:** Piyasa değiştiğinde modelin eskidiğini tespit eder.

**Türler:**
- Feature drift (feature dağılımı değişti)
- Prediction drift (tahmin dağılımı değişti)
- Outcome drift (gerçek sonuç dağılımı değişti)
- Regime drift (piyasa rejimi değişti)

**Durum:** ⚠️ Model tanımlı, otomatik tetikleme eksik

---

## 7. Model Lifecycle

```
TRAIN → VALIDATE → BACKTEST → WALK-FORWARD → PAPER → SHADOW → PROMOTE → MONITOR → RETIRE
```

**Durum:** ⚠️ Kısmen (train → backtest → monitor var, shadow/promote eksik)

---

## 8. Çıktı

```
BACKTEST SONUÇLARI
──────────────────────────────
Dönem:           2024-01-01 → 2026-08-15
Başlangıç:       ₺100,000
Bitiş:           ₺142,500
Toplam Getiri:   +%42.5
CAGR:            +%18.2
Sharpe:          1.85
Max Drawdown:    -%8.3
──────────────────────────────
Precision@5:     %72
Precision@10:    %68
IC:              0.15
Hit Rate:        %58
Turnover:        %35/yıl
──────────────────────────────
Walk-Forward:    8 fold
Stability:       0.82
Deflated Sharpe: 1.45
```
