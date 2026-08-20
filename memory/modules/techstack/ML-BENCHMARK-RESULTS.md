# ML Benchmark Sonuçları — LightGBM vs CatBoost vs XGBoost

**Tarih:** 2026-08-21
**Test:** BIST benzeri classification (50K sample, 100 feature)
**Validation:** Time-based split (80/20) + 5-Fold Time Series CV

---

## 1. Tek Model Performansı

| Model | Süre | AUC | Accuracy | Sıra |
|-------|------|-----|----------|------|
| **LightGBM** | 3.35s | 0.9909 | 0.9620 | 🥇 En hızlı + en iyi AUC |
| **XGBoost** | 3.88s | 0.9906 | 0.9604 | 🥈 |
| **CatBoost** | 4.10s | 0.9872 | 0.9506 | 🥉 |

---

## 2. Ensemble Performansı

| Model | AUC | Accuracy |
|-------|-----|----------|
| **Ensemble (avg)** | 0.9911 | 0.9615 |
| **En iyi tek model (LightGBM)** | 0.9909 | 0.9620 |
| **İyileştirme** | +0.02% AUC | -0.05% Acc |

**Sonuç:** Ensemble'ın iyileştirmesi minimal (+0.02% AUC). Bu synthetic data'da beklenir. Gerçek BIST verisinde farklı olabilir.

---

## 3. 5-Fold Time Series Cross-Validation

| Model | AUC (mean ± std) |
|-------|------------------|
| **XGBoost** | 0.9810 ± 0.0016 |
| **LightGBM** | 0.9798 ± 0.0015 |
| **CatBoost** | 0.9703 ± 0.0014 |
| **Ensemble** | 0.9770 ± 0.0015 |

**Sonuç:** CV'de XGBoost hafif önde, ama fark istatistiksel olarak anlamsız.

---

## 4. Bulgular

### 4.1 Hız
- LightGBM en hızlı (3.35s)
- XGBoost orta (3.88s)
- CatBoost en yavaş (4.10s)
- **Fark:** LightGBM CatBoost'tan %18 daha hızlı

### 4.2 AUC
- LightGBM en iyi (0.9909)
- XGBoost çok yakın (0.9906)
- CatBoost biraz düşük (0.9872)
- **Fark:** LightGBM CatBoost'tan %0.37 daha iyi

### 4.3 Ensemble
- Ensemble iyileştirmesi minimal (+0.02% AUC)
- Synthetic data'da beklenir
- Gerçek BIST verisinde farklı olabilir

### 4.4 Stabilite (CV)
- XGBoost en stabil (0.9810 ± 0.0016)
- LightGBM çok yakın (0.9798 ± 0.0015)
- CatBoost en az stabil (0.9703 ± 0.0014)

---

## 5. Sonuç ve Öneriler

### Mevcut Durum
- **En iyi model:** LightGBM (hız + AUC kombinasyonu)
- **En stabil model:** XGBoost (CV'de en iyi)
- **Ensemble:** Minimal iyileştirme, ama ek karmaşıklık getiriyor

### Öneriler
1. **LightGBM primary model olarak kalmalı** — en hızlı, en iyi AUC
2. **XGBoost secondary model olarak kalmalı** — en stabil
3. **CatBoost** — kategorik feature'larda avantajlı olabilir (BIST sektör/pazar)
4. **Ensemble** — gerçek BIST verisinde test edilmeli

### Kanıtlanmayan İddialar
| İddia | Gerçek Sonuç | Durum |
|-------|-------------|-------|
| "Ensemble %8-12 daha iyi" | +0.02% AUC | ❌ Kanıtlanmadı |
| "CatBoost kategorik'te en iyi" | Synthetic data'da test edilemedi | ⚠️ Gerçek veri gerekli |
| "LightGBM en hızlı" | ✅ 3.35s (en hızlı) | ✅ Kanıtlandı |

---

## 6. Benchmark Ortamı

- **CPU:** 4 core
- **RAM:** 8GB
- **Python:** 3.12
- **LightGBM:** 4.7.0
- **XGBoost:** 3.4.1
- **CatBoost:** 1.2.10
- **scikit-learn:** 1.9.0
