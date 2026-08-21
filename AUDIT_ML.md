# ALPHA BIST — ML / Feature / Intelligence Derinlemesine Kod Kalitesi Analizi

**Tarih:** 2026-08-22  
**Kapsam:** services/features/, services/ml/, services/intelligence/, services/labels/, services/learning/, services/scanner/  
**Toplam Bulgu:** 47 (P0: 8, P1: 18, P2: 21)

---

## Özet Tablo

| Kategori | P0 | P1 | P2 | Toplam |
|---|---|---|---|---|
| 1. Look-ahead Bias / Sızıntı | 3 | 2 | 1 | 6 |
| 2. Mask-First İhlali | 1 | 2 | 1 | 4 |
| 3. Ranking Model Sözleşme Uyuşmazlığı | 1 | 2 | 1 | 4 |
| 4. Purge+Embargo Eksikliği | 1 | 2 | 0 | 3 |
| 5. Walk-Forward Sahte Yeniden Eğitim | 1 | 2 | 1 | 4 |
| 6. Dead Code / Kullanılmayan Fonksiyon | 0 | 2 | 5 | 7 |
| 7. Hard-Coded Sabitler / Uydurma Değerler | 0 | 3 | 4 | 7 |
| 8. Regime Mantık Hataları | 1 | 1 | 2 | 4 |
| 9. Cross-Sectional Hesaplama Hataları | 0 | 1 | 2 | 3 |
| 10. Feature İsimlendirme Tutarsızlığı | 0 | 1 | 3 | 4 |
| **Toplam** | **8** | **18** | **21** | **47** |

---

## 1. LOOK-AHEAD BIAS / VERİ SIZINTISI

### F-001 · Label üretimi gelecek veriyi feature'lara sızdırıyor
- **Dosya:** `services/features/seven_motors.py`, satır ~680-695 (`SevenMotorEngine.compute_all`)
- **Sorun:** Motor 7 ("Neden Düşüyor?") için `stock_ret_5d` ve `stock_ret_20d` değerleri `all_features.get("roc_5d", 0)` ve `all_features.get("roc_20d", 0)` ile alınır. Bu feature'lar geçmişe bakar (look-back), dolayısıyla tek başına sorunlu değildir. **Ancak** `labels/generator.py` satır ~50-65'te `future_ret_5d = (close[i+period] / close[i] - 1) * 100` hesaplanırken, `close` dizisi mask-aware olarak filtrelenmez — mask=0 olan günlerin fiyatları label hesabında kullanılır. Bu, likit olmayan günlerden üretilen label'ların feature'larla çaprazlandığında sızıntı yaratır.
- **Öncelik:** P0
- **Düzeltme:** `generator.py`'de forward return hesaplamasında `close[i]` ve `close[i+period]` değerlerinin her ikisinin de mask=1 olduğunu kontrol et. Mevcut kod satır 56-58'de bunu kısmen yapıyor ama `sector_returns` ve `benchmark_returns` için aynı kontrolü yapmıyor.

### F-002 · HMM regim tespitinde gelecek veriye erişim
- **Dosya:** `services/intelligence/regime.py`, satır ~100-115
- **Sorun:** `detect_regime()` içinde HMM entegrasyonu yapılırken `returns = np.array([features.get("momentum_avg", 0) / 100] * 63)` ile tek bir değer 63 kez tekrarlanarak HMM'ye veriliyor. Bu, gerçek bir zaman serisi değil, sabit bir dizi. HMM'nin forward-backward algoritması bu sabit diziyle anlamsız sonuçlar üretir. Ayrıca `momentum_avg` zaten hesaplanmış bir feature olduğu için, HMM'nin tarihsel pattern detection'ı tamamen devre dışı kalır.
- **Öncelik:** P0
- **Düzeltme:** HMM'ye gerçek rolling return serisi verilmeli. `features` dict'i yerine son 63 günlük ham getiri serisi `detect_regime()`'e parametre olarak geçirilmeli.

### F-003 · Label'larda purge uygulanmaması
- **Dosya:** `services/labels/generator.py`, satır ~40-50
- **Sorun:** `generate_labels()` fonksiyonu forward return'leri hesaplarken `mask[i] == 1 and mask[i + period] == 1` kontrolü yapıyor. Ancak feature hesaplama ile label üretimi arasında purge gap yok. Feature'lar t anında hesaplanıyor (son 60 bar lookback), label'lar t+5 veya t+20'ye bakıyor. Feature hesabında kullanılan son bar t, label'ın başlangıcı da t — purge yok.
- **Öncelik:** P0
- **Düzeltme:** Label üretimi sırasında feature hesaplama penceresinin son `purge_days` barı label hesabında hariç tutulmalı. Örneğin `y_5d` label'ı için feature'ların hesaplandığı son 5 bar purge edilmeli.

### F-004 · Real BIST walk-forward'da gelecek fiyat sızıntısı
- **Dosya:** `services/learning/real_bist_walkforward_backtest.py`, satır ~95-105 (`compute_strict_features`)
- **Sorun:** `feats["future_ret_5d"] = (close.shift(-5) / close - 1.0) * 100.0` ve `feats["future_price_5d"] = close.shift(-5)` hesaplanıyor. Bu değerler feature DataFrame'ine ekleniyor ve daha sonra `row["future_ret_5d"]` ve `row["future_price_5d"]` olarak evaluation loop'unda doğrudan erişiliyor. Bu teknik olarak "label" olarak kullanılmalı, feature olarak değil. Ancak `compute_strict_features` return etmeden önce `dropna()` çağrısı yapıyor — bu, gelecek fiyatı NaN olan son 5 satırı atıyor ama geri kalan tüm satırlarda gelecek fiyat bilgisi DataFrame'de mevcut.
- **Öncelik:** P1
- **Düzeltme:** `future_ret_5d` ve `future_price_5d` sütunları feature DataFrame'inden ayrılmalı, sadece evaluation anında erişilebilir olmalı.

### F-005 · Real BIST backtest'te model eğitimi yapılmıyor
- **Dosya:** `services/learning/real_bist_walkforward_backtest.py`, satır ~130-200
- **Sorun:** Walk-forward simülasyonu her gün 6 farklı "model" için prediction üretiyor ama hiçbirinde gerçek bir model eğitimi yok. `Cross_Sectional_Momentum` modeli sadece `momentum_20d > 0` kontrolü yapıyor. `LightGBM_LambdaRank` modeli `0.4 * roc_5d + 0.3 * price_vs_sma20 + 0.3 * volume_zscore` formülüyle sabit ağırlıklı bir lineer skor üretiyor. Hiçbir model `fit()` çağrılmıyor.
- **Öncelik:** P1
- **Düzeltme:** Her walk-forward split'te modeli train verisiyle eğit, test verisiyle predict et. Mevcut kod "walk-forward" adı altında deterministik kurallar kullanıyor.

### F-006 · CCI hesabında look-ahead
- **Dosya:** `services/features/seven_motors.py`, satır ~505-510 (`MeanReversionMotor.compute`)
- **Sorun:** CCI hesabında `tp = (valid_close[-20:] + valid_close[-20:] + valid_close[-20:]) / 3` kullanılmış. Bu, typical price hesabının yanlışlığı (High ve Low yerine Close üç kez kullanılmış) ve ayrıca `valid_close[-1]` ile `sma_tp` karşılaştırması yapılıyor — bu tek başına look-ahead değil ama CCI tanımına uymuyor (Close, High, Low üçlüsü kullanılmalı).
- **Öncelik:** P2
- **Düzeltme:** `tp = (valid_high[-20:] + valid_low[-20:] + valid_close[-20:]) / 3` olarak düzeltilmeli.

---

## 2. MASK-FIRST İHLALLERİ

### M-001 · Seasonality motoru mask uyguluyor ama tarih eşleştirmesini kırıyor
- **Dosya:** `services/features/seven_motors.py`, satır ~555-570 (`SeasonalityMotor.compute`)
- **Sorun:** `valid_dates = [d for d, m in zip(dates, mask if mask is not None else [1]*len(dates)) if m == 1]` ifadesi mask=1 olan günleri filtreliyor. Ancak `valid_close` ile `valid_dates` arasında uzunluk farkı olabilir çünkü `close` NaN olmayan değerlerle filtreleniyor ama `dates` mask=1 ile filtreleniyor. Mask=1 olup close NaN olan günlerde `valid_close` ve `valid_dates` farklı uzunluklarda olur.
- **Öncelik:** P0
- **Düzeltme:** Filtreleme kriterini birleştir: `valid_mask = mask == 1 & ~np.isnan(close)` ve bu mask'i hem close hem dates için kullan.

### M-002 · SevenMotorEngine compute_all'da mask motorlara düzgün aktarılmıyor
- **Dosya:** `services/features/seven_motors.py`, satır ~620-640
- **Sorun:** `compute_all()` fonksiyonunda mask parametresi Motor 1-3 ve 8-9'a aktarılıyor ama Motor 4 (Fundamental), Motor 5 (KAP+Haber), Motor 6 (Katalizör) ve Motor 7 ("Neden Düşüyor?") mask almıyor. Motor 7'nin mask almaması mantıksal olarak kabul edilebilir (zaten scalar input) ama Motor 5 ve 6'da tarih bazlı filtreleme yok — KAP event'leri ve katalizörler hangi günün verisiyle eşleşiyor?
- **Öncelik:** P1
- **Düzeltme:** Motor 5 ve 6'ya `as_of_date` parametresi eklenmeli, sadece o tarihe kadar olan event'ler kullanılmalı.

### M-003 · Calculator _ema_masked tüm geçerli değerleri kullanıyor (lookback yok)
- **Dosya:** `services/features/calculator.py`, satır ~185-195 (`_ema_masked`)
- **Sorun:** `_ema_masked` fonksiyonu `valid = data[~np.isnan(data)]` ile tüm geçerli değerleri alıyor, sonra `valid[0]`'dan itibaren EMA hesaplıyor. Eğer çok uzun bir geçmiş varsa (ör. 500 bar), EMA tüm 500 barı kullanarak hesaplanıyor — bu, sadece son `period` bara bakması gereken bir hesapta gereksiz eski veriyi dahil eder. Mask-aware olması beklenirken, mask=0 olan günler "atlanarak" EMA'nın smoothing'i değişiyor.
- **Öncelik:** P1
- **Düzeltme:** `_ema_masked` fonksiyonunda sadece son `period * 3` kadar geçerli bara bak (EMA'nın stabilize olması için yeterli). Veya en azından son `period` bara odaklan.

### M-004 · Panel engine RSI'da Wilder's smoothing kullanmıyor
- **Dosya:** `services/features/panel_engine.py`, satır ~170-200 (`_panel_rsi`)
- **Sorun:** Panel engine'in RSI hesabında "Wilder DEĞİL — calculator ile aynı" notu var. Ancak `calculator.py`'deki `_rsi_masked` fonksiyonu (satır ~188-202) **Wilder's smoothing** kullanıyor: `avg_gain = (avg_gain * (period - 1) + gains[i]) / period`. Panel engine ise basit ortalama kullanıyor: `sum_g = Gp[rh] - Gp[rh - period]` ve `avg_g = sum_g / period`. Bu iki yöntem farklı sonuçlar üretir.
- **Öncelik:** P1
- **Düzeltme:** Panel engine'in RSI hesabını Wilder's smoothing ile uyumlu hale getir. Veya calculator'ı panel engine'e uyumlu hale getir — hangisi doğruysa.

---

## 3. RANKING MODEL SÖZLEŞME UYUŞMAZLIKLARI

### R-001 · Feature isimleri ranking model ile feature calculator arasında tutarsız
- **Dosya:** `services/ml/ranking_model.py`, satır ~40-70 (`_feature_names`)
- **Sorun:** Ranking model'in beklediği feature isimleri:
  - `"rs_vs_bist_1d"`, `"rs_vs_bist_5d"` → Motor 1 bu isimleri üretiyor ✓
  - `"breakout_failure"` → Motor 2 `"breakout_failure_20d"` üretiyor, alias ile eşleniyor ✓
  - `"recovery_strength"` → Motor 2 `"recovery_strength_20d"` üretiyor ✓
  - `"sector_norm_pe_ratio"`, `"sector_norm_pb_ratio"` → Motor 4 bunları üretiyor ✓
  - **Ancak** `"rsi_14"` → Hem calculator hem Motor 8 tarafından üretiliyor. Calculator `"rsi_14"` üretirken Motor 8 `"rsi_14d"` üretiyor. Bu iki farklı isim, ranking model sadece `"rsi_14"` bekliyor.
  - `"sector_zscore_momentum_20d"` → Cross-sectional engine `"sector_zscore_{feat_name}"` formatında üretiyor ama bu isim ranking model'in feature listesinde yok.
- **Öncelik:** P1
- **Düzeltme:** Feature isimlerini merkezi bir contract'ta tanımla (feature_contract.py mevcut ama aktif kullanılmıyor). Motor çıktıları ile model girdileri arasında automated validation ekle.

### R-002 · Ranking model date×panel grup yapısı eksik
- **Dosya:** `services/ml/ranking_model.py`, satır ~90-110 (`train`)
- **Sorun:** `_prepare_training_data()` fonksiyonu `group_sizes` dizisini oluşturuyor ama `np.array([])` döndürüyor. `date_groups` parametresi gruplama için kullanılmıyor — sadece `features_map` ve `returns` dict'leri üzerinde iterate ediliyor. LightGBM LambdaRank'in `group` parametresi (aynı tarihteki hisse sayısı) düzgün hesaplanmıyor.
- **Öncelik:** P0
- **Düzeltme:** `_prepare_training_data()`'da `date_groups` kullanarak gerçek tarih bazlı gruplar oluştur. Her tarih için o tarihteki hisse sayısı `group_sizes` dizisine eklenmeli.

### R-003 · Ranking model confidence hesaplama ters
- **Dosya:** `services/ml/ranking_model.py`, satır ~195-205
- **Sorun:** LambdaRank'de düşük skor = daha iyi sıralama (yüksek getiri). Ancak confidence hesabında `percentile = (n - rank + 1) / n` kullanılıyor — rank 1 (en iyi) için percentile = 1.0. Bu doğru. Ama `confidence = max(0, min(0.99, 0.5 + percentile * 0.5))` formülüyle rank 1 → confidence 0.99, rank n → confidence 0.50. En kötü sıradaki hisse bile 0.50 confidence alıyor — bu yanlış.
- **Öncelik:** P1
- **Düzeltme:** Confidence'ı rank yerine score dağılımına göre hesapla. Veya en azından alt sınırı 0.10 yap.

### R-004 · Ranker model ve ranking model arasında duplicate mantık
- **Dosya:** `services/ml/ranker.py` ve `services/ml/ranking_model.py`
- **Sorun:** İki ayrı ranker implementasyonu var. `ranker.py` `LGBMRanker` kullanırken, `ranking_model.py` `lgb.train` ile LambdaRank eğitiyor. İkisi de aynı işi yapıyor ama farklı feature set'leri ve farklı eğitim pipeline'ları kullanıyor. Bu, model yönetimini zorlaştırır ve hangisinin production'da kullanıldığı belirsiz.
- **Öncelik:** P2
- **Düzeltme:** Tek bir ranker implementasyonuna geç. Veya hangisinin production olduğunu belirten bir config/routing mekanizması ekle.

---

## 4. PURGE + EMBARGO EKSİKLIĞI

### P-001 · Label üretimi ile feature üretimi arasında purge gap yok
- **Dosya:** `services/labels/generator.py`, satır ~40-50
- **Sorun:** `generate_labels()` fonksiyonu forward return'leri hesaplarken `close[i]` anından itibaren `close[i+period]`'a bakıyor. Feature'lar da `close[i]` anına kadar olan verileri kullanıyor. Arada purge gap yok — yani t anındaki feature'lar, t+5 gün sonraki getiriyi tahmin etmek için kullanıldığında, t ile t+5 arasında bilgi sızıntısı riski var (eğer feature'lar t+1, t+2, ... t+4 günlerinin verisini kullanıyorsa).
- **Öncelik:** P1
- **Düzeltme:** Label generation pipeline'ına purge_days parametresi ekle. `y_5d` label'ı için feature hesaplama penceresinin son 5 günü purge edilmeli.

### P-002 · Walk-forward validation'da purge eksik
- **Dosya:** `services/ml/walk_forward.py`, satır ~50-70 (`generate_splits`)
- **Sorun:** `generate_splits()` fonksiyonunda `train_end = start_idx - self._purge_size` ile purge uygulanıyor — bu doğru. Ancak `evaluate()` fonksiyonunda (satır ~80-110) `feature_fn` train ve test verileri ayrı ayrı çağrılıyor. Feature fonksiyonu rolling window kullanıyorsa, train verisinin son barları test verisinin ilk barlarıyla örtüşebilir. Purge sadece tarih indeksinde uygulanıyor, feature hesaplama penceresinde uygulanmıyor.
- **Öncelik:** P1
- **Düzeltme:** Feature fonksiyonuna purge_days parametresi geçir. Train feature'ları hesaplanırken son `purge_days` bar hariç tutulmalı.

### P-003 · Retrain engine'de purge yetersiz
- **Dosya:** `services/learning/retrain_engine.py`, satır ~120-140 (`_generate_wf_splits`)
- **Sorun:** `_generate_wf_splits()` fonksiyonunda `train_end = start_idx - cfg.wf_purge_size` ile purge uygulanıyor. Ancak `_evaluate_split()` fonksiyonunda (satır ~170-200) `X_train` ve `X_test` doğrudan indeksleniyor — purge gap'teki veriler hariç tutuluyor ama feature'ların rolling window'u purge gap'i aşabilir.
- **Öncelik:** P2
- **Düzeltme:** Feature hesaplama penceresinin purge gap'i aşmadığından emin ol. Veya purge gap'i feature lookback window kadar büyüt.

---

## 5. WALK-FORWARD'IN GERÇEKTEN YENİDEN EĞİTİM YAPMAMASI

### W-001 · Real BIST walk-forward'da model eğitimi yok (sahte walk-forward)
- **Dosya:** `services/learning/real_bist_walkforward_backtest.py`, satır ~130-200
- **Sorun:** "Walk-forward backtest" adı altında 6 farklı model için prediction üretiliyor ama hiçbirinde gerçek bir model eğitimi yok. Tüm modeller deterministik kurallarla çalışıyor:
  - `Cross_Sectional_Momentum`: `momentum_20d > 0` → UP
  - `LightGBM_LambdaRank`: `0.4 * roc_5d + 0.3 * price_vs_sma20 + 0.3 * volume_zscore` (sabit ağırlıklar)
  - `SPEC_Anomaly_Detector`: `volume_zscore > 1.5 and bb_position > 0.8`
  - `KAP_NLP_Sentiment`: `roc_5d > -1.0 and price_vs_sma50 > 0`
  - `CatBoost_Classifier`: `0.5 * roc_20d + 0.5 * (100 - atr_pct * 10)`
  - `LSTM_Sequential`: `roc_5d < -3.0 or price_vs_sma20 > 2.0`
  
  Bu, walk-forward validation değil, sadece deterministik kuralların backtest'i.
- **Öncelik:** P0
- **Düzeltme:** Her walk-forward split'te modeli train verisiyle `fit()` et, test verisiyle `predict()` yap. Mevcut kod sadece rule-based scoring yapıyor.

### W-002 · Walk-forward evaluate() fonksiyonunda model_fn() her split'te sıfırdan çağrılıyor ama eğitilmiyor
- **Dosya:** `services/ml/walk_forward.py`, satır ~85-105
- **Sorun:** `evaluate()` fonksiyonunda `model = model_fn()` ile her split'te yeni bir model实例ı oluşturuluyor ve `model.train(train_features)` çağrılıyor. Ancak `model_fn` parametresi nasıl tanımlanmamış — eğer mevcut `RankingModel` kullanılıyorsa, `train()` fonksiyonu LightGBM eğitimi yapıyor ama `predict()` fonksiyonu yok. Walk-forward validation'ın `model.predict(test_features)` çağrısı `RankingModel`'de mevcut değil.
- **Öncelik:** P1
- **Düzeltme:** Walk-forward validation ile ranking model arasında uyumlu bir interface tanımla. `RankingModel`'e `predict()` metodu ekle.

### W-003 · Walk-forward split'lerinde expanding window yok
- **Dosya:** `services/ml/walk_forward.py`, satır ~50-70
- **Sorun:** `generate_splits()` fonksiyonunda train penceresi sabit `train_size` ile sınırlı. Expanding window (her split'te train verisinin artması) uygulanmıyor. Dokümanda "Expanding window: Her adımda daha fazla veri" vaadi var ama implementasyonda yok.
- **Öncelik:** P2
- **Düzeltme:** `train_start`'ı sabit tut (ilk split'ten itibaren), `train_end`'i her split'te artır. Veya `expanding=True` parametresi ekle.

### W-004 · Walk-forward metric hesaplamasında NaN handling eksik
- **Dosya:** `services/ml/walk_forward.py`, satır ~115-125 (`_calculate_metrics`)
- **Sorun:** `_calculate_metrics()` fonksiyonunda `corr = np.corrcoef(pred_values, actuals)[0, 1]` çağrısı yapılıyor. Eğer `pred_values` veya `actuals` sabit değerlerden oluşuyorsa (std=0), `np.corrcoef` NaN döndürür. Bu durumda `float(corr)` NaN olur ve downstream'de hatalara neden olur.
- **Öncelik:** P1
- **Düzeltme:** `np.isnan(corr)` kontrolü ekle, NaN ise 0 döndür.

---

## 6. DEAD CODE / KULLANILMAYAN FONKSİYONLAR

### D-001 · SevenMotorEngine'de 9 motor var ama sınıf adı "Seven"
- **Dosya:** `services/features/seven_motors.py`, satır ~615
- **Sorun:** Sınıf adı `SevenMotorEngine` ama dokümanda "artık 9 motor" deniyor. Motor 8 (Mean Reversion) ve Motor 9 (Seasonality) eklenmiş ama sınıf adı güncellenmemiş.
- **Öncelik:** P2
- **Düzeltme:** Sınıf adını `NineMotorEngine` olarak güncelle veya genel bir `MultiMotorEngine` adı kullan.

### D-002 · FeatureContract tanımlanmış ama aktif kullanılmıyor
- **Dosya:** `services/features/feature_contract.py` (tüm dosya)
- **Sorun:** `FeatureDataPoint`, `TickerFeatureContract`, `make_fresh`, `make_missing` gibi yapılar tanımlanmış ama hiçbir motor veya calculator bu yapıları kullanmıyor. Tüm motorlar ham `Dict[str, float]` döndürüyor.
- **Öncelik:** P2
- **Düzeltme:** Ya feature_contract'ı aktif kullan (motor çıktılarını sar) ya da dead code olarak kaldır.

### D-003 · compute_extended_features() fonksiyonu kullanılmıyor
- **Dosya:** `services/features/calculator.py`, satır ~280-330
- **Sorun:** `compute_extended_features()` fonksiyonu technical_features, extended_indicators, fundamental, sentiment, macro modüllerini birleştiriyor ama hiçbir caller tarafından çağrılmıyor. Pipeline veya main modülünde bu fonksiyonun kullanıldığına dair kanıt yok.
- **Öncelik:** P2
- **Düzeltme:** Kullanılıyorsa kanıtla, kullanılmıyorsa kaldır.

### D-004 · get_ml_ensemble() fonksiyonunda import edilen modüllerin çoğu kullanılmıyor
- **Dosya:** `services/ml/ranking_model.py`, satır ~300-360
- **Sorun:** `get_ml_ensemble()` fonksiyonu 10'dan fazla modülü import etmeye çalışıyor (xgboost, lstm, transformer, ensemble, comparator, finrl, fingpt, hybrid, rl_agent, walk_forward). Çoğu `ImportError` ile geçiştiriliyor. Bu modüllerin production'da kullanılıp kullanılmadığı belirsiz.
- **Öncelik:** P2
- **Düzeltme:** Kullanılmayan modülleri kaldır veya import'ları lazy loading ile sadece gerektiğinde yap.

### D-005 · IntegratedLearningSystem._feature_importance hiç doldurulmuyor
- **Dosya:** `services/learning/integrated_learning.py`, satır ~180
- **Sorun:** `get_feature_importance()` fonksiyonu `self._feature_importance` döndürüyor ama bu dict hiçbir yerde doldurulmuyor. `__init__`'de boş olarak başlatılıyor ama `record_prediction()`, `record_outcome()` veya başka bir metodda güncellenmiyor.
- **Öncelik:** P1
- **Düzeltme:** Feature importance'ı prediction/outcome döngüsünde güncelle veya bu fonksiyonu kaldır.

### D-006 · opportunity_engine ve alpha_scanner arasındaki duplicate mantık
- **Dosya:** `services/scanner/opportunity_engine.py` ve `services/scanner/alpha_scanner.py`
- **Sorun:** Her iki modül de "fırsat skoru" hesaplıyor. `opportunity_engine` çok boyutlu bir skor (technical, fundamental, momentum, volume, vb.) hesaplarken, `alpha_scanner` benzer ama daha basit bir skor hesaplıyor. Her ikisi de singleton olarak tanımlanmış. Hangisinin production'da kullanıldığı belirsiz.
- **Öncelik:** P2
- **Düzeltme:** Tek bir opportunity scoring mekanizmasına geç veya rollerini netleştir.

### D-007 · run_full_scan() fonksiyonunda scanner modülleri import edilip kullanılmıyor
- **Dosya:** `services/scanner/opportunity_engine.py`, satır ~320-380
- **Sorun:** `run_full_scan()` fonksiyonu 5 farklı scanner modülünü import etmeye çalışıyor ama her biri `ImportError` ile geçiştiriliyor. Başarılı import'larda bile `hasattr(alpha, 'scan')` kontrolü yapılıyor — bu, interface'in garanti edilmediğini gösterir.
- **Öncelik:** P2
- **Düzeltme:** Scanner interface'ini zorunlu kıl (ABC kullan) veya bu fonksiyonu kaldır.

---

## 7. HARD-CODED SABİTLER / UYDURMA DEĞERLER

### H-001 · WhyFallingMotor'da sabit eşik değerleri
- **Dosya:** `services/features/seven_motors.py`, satır ~420-470
- **Sorun:** Düşüş tespiti için sabit eşikler kullanılıyor: `stock_return_5d < -2`, `stock_return_20d < -5`, `market_return_5d < -3`, `sector_return_5d < -5`, `rsi < 30`, `atr_pct > 5`, `volume_zscore > 2`. Bu eşikler BIST'in volatilitesine göre ayarlanmamış. Türkiye piyasasında günlük %2 düşüş normal olabilir ama ABD piyasasında büyük bir hareket.
- **Öncelik:** P1
- **Düzeltme:** Eşikleri dinamik hale getir (percentile bazlı veya rolling volatility bazlı). Veya config dosyasından oku.

### H-002 · Fundamental motorunda sabit quality_score başlangıcı
- **Dosya:** `services/features/seven_motors.py`, satır ~340-380
- **Sorun:** `quality_score = 50` ile başlayıp +25, +15, -25, -10 gibi sabit eklemeler yapılıyor. Bu skorlama sistemi tamamen ad-hoc — herhangi bir ampirik temeli yok. `balance_sheet_quality` feature'ı olarak output edilen bu değer, model tarafından öğrenilmesi gereken bir pattern yerine hard-coded bir heuristic.
- **Öncelik:** P2
- **Düzeltme:** Ya bu skoru modelin öğrenmesine bırak (raw değerleri feature olarak ver) ya da ampirik olarak calibre et.

### H-003 · Valuation engine'de sabit WACC ve vergi oranı
- **Dosya:** `services/intelligence/valuation/engine.py`, satır ~25-28
- **Sorun:** `DEFAULT_WACC = 0.20`, `DEFAULT_TERMINAL_GROWTH = 0.03`, `DEFAULT_TAX_RATE = 0.23` sabit olarak tanımlanmış. Türkiye için %20 WACC makul görünebilir ama bu değer piyasa koşullarına göre değişmeli (faiz ortamı, risk primi, vb.).
- **Öncelik:** P2
- **Düzeltme:** WACC'ı dinamik olarak hesapla (risk-free rate + beta * equity risk premium + country risk premium). Veya config'den oku.

### H-004 · Scenario engine'de sabit sektör duyarlılık matrisi
- **Dosya:** `services/intelligence/scenario.py`, satır ~140-155 (`_simplified_impact`)
- **Sorun:** Sektör bazlı duyarlılık matrisi hard-coded: `BANK: {"usdtry_change": -0.3, "interest_rate_change": 0.5}`. Bu değerler ampirik olarak doğrulanmamış. Ayrıca sadece 6 sektör tanımlanmış (BANK, AVIATION, ENERGY, TECH, RETAIL, METAL) — BIST'te bundan çok daha fazla sektör var.
- **Öncelik:** P1
- **Düzeltme:** Duyarlılık matrisini tarihsel verilerden hesapla (regression-based). Veya config dosyasına taşı.

### H-005 · Scanner'da sabit opportunity score ağırlıkları
- **Dosya:** `services/scanner/alpha_scanner.py`, satır ~150-160
- **Sorun:** Opportunity score hesaplamasında sabit ağırlıklar: `%20 momentum, %15 relative_strength, %15 volume_anomaly, %10 breakout, %10 volatility_structure, %10 regime_fit, %10 event, %10 ML`. Bu ağırlıklar optimize edilmemiş.
- **Öncelik:** P2
- **Düzeltme:** Ağırlıkları historical performance'dan optimize et. Veya regime bazlı değiştir.

### H-006 · Ranking model rule-based score'da sabit ağırlıklar
- **Dosya:** `services/ml/ranking_model.py`, satır ~230-270 (`_rule_based_score`)
- **Sorun:** Her rejim için sabit ağırlıklar tanımlanmış (ör. BULL: `w_mom=0.20, w_roc=0.12`). Bu ağırlıklar optimize edilmemiş, ad-hoc. Ayrıca `score = 50.0` başlangıcı ile momentum, RSI, vb. değerler toplanıyor — bu, skorun 0-100 aralığında kalacağını garanti etmiyor.
- **Öncelik:** P2
- **Düzeltme:** Ağırlıkları walk-forward validation ile optimize et. Skor sınırlaması için `max(0, min(100, score))` zaten var ama ağırlıkların büyüklüğü kontrol edilmeli.

### H-007 · Real BIST backtest'te model confidence sabit değerler
- **Dosya:** `services/learning/real_bist_walkforward_backtest.py`, satır ~140-200
- **Sorun:** Her model için confidence sabit veya çok basit formüllerle hesaplanıyor:
  - `KAP_NLP_Sentiment`: `confidence = 0.62` (sabit!)
  - `CatBoost_Classifier`: `confidence = 0.60` (sabit!)
  - `LSTM_Sequential`: `confidence = 0.54` (sabit!)
  - `SPEC_Anomaly_Detector`: `confidence = 0.80` (anomaly varsa) veya `0.52` (yoksa)
  
  Bu sabit confidence değerleri modelin kalibrasyonunu yansıtmıyor.
- **Öncelik:** P1
- **Düzeltme:** Confidence'ı model çıktılarından (probability, score distribution) hesapla. Veya calibration pipeline'ından geçir.

---

## 8. REGIME TESPİT MANTIK HATALARI

### G-001 · Breadth > 65 eşik değeri erişilemez (bull scoring)
- **Dosya:** `services/intelligence/regime.py`, satır ~115-125 (`_score_bull`)
- **Sorun:** `_score_bull` fonksiyonunda `if breadth > 60: score += min((breadth - 50) / 30, 0.3)` kullanılıyor. Bu, breadth=80'de maksimum 0.3 katkı sağlar. Ancak `_score_momentum_expansion` fonksiyonunda `if breadth > 60: score += min((breadth - 60) / 20, 0.3)` — burada breadth=60'dan başlıyor. Bu iki fonksiyon arasında tutarsızlık var. Bull scoring'de breadth 50-80 arası linear, momentum_expansion'da 60-80 arası linear. Breadth 65 olduğunda bull: `(65-50)/30 = 0.5 → min(0.5, 0.3) = 0.3`, momentum_expansion: `(65-60)/20 = 0.25`. Bu durumda breadth 65'te bull skoru maksimumda ama momentum_expansion henüz düşük — bu mantıksal olarak çelişkili.
- **Öncelik:** P1
- **Düzeltme:** Breadth scoring'in tüm rejim fonksiyonlarında tutarlı bir aralık kullan. Veya breadth'i normalize et (0-1 arası) ve tüm fonksiyonlarda bu normalized değeri kullan.

### G-002 · Regime scoring'de puanlar toplamı 1.0'i aşabilir
- **Dosya:** `services/intelligence/regime.py`, satır ~110-260
- **Sorun:** Her rejim fonksiyonu `min(1.0, score)` ile sınırlanmış ama `detect_regime()` fonksiyonunda tüm rejim skorları karşılaştırılıyor ve en yüksek olan seçiliyor. Eğer iki rejim skoru birbirine yakınsa (ör. bull=0.8, risk_on=0.79), confidence düşük çıkıyor ama bu durumda hangi rejimin seçildiği kritik. Ayrıca HMM entegrasyonu sonrası skorlar `* (1 - hmm_weight) + hmm_prob * hmm_weight * 100` ile yeniden hesaplanıyor — bu, skorların 1.0'i aşmasına neden olabilir.
- **Öncelik:** P2
- **Düzeltme:** HMM entegrasyonu sonrası skorları tekrar normalize et.

### G-003 · Macro regime entegrasyonu hatalı modül yolu
- **Dosya:** `services/intelligence/regime.py`, satır ~140
- **Sorun:** `from services.macro.regime_detector import macro_regime_detector` — bu import yolu muhtemelen yanlış. `services/macro/` dizini var mı kontrol edilmeli. Ayrıca bu import try-except içinde olduğu için sessizce başarısız olabilir.
- **Öncelik:** P2
- **Düzeltme:** Import yolunu doğrula. Veya bu özelliği kaldır.

### G-004 · Regime confidence hesaplama eşitlik durumunda hatalı
- **Dosya:** `services/intelligence/regime.py`, satır ~155-165
- **Sorun:** `if gap < 0.01 and sorted_scores[0] > 0.5: confidence = 0.3` — bu durumda iki rejim neredeyse eşit ama skor yüksek. Confidence 0.3 atanıyor ama bu durumda hangi rejimin seçildiği rastgele. Daha iyi bir yaklaşım: eşitlik durumunda her iki rejimi de raporla veya "MIXED" rejim üret.
- **Öncelik:** P2
- **Düzeltme:** Eşitlik durumunda "MIXED" veya "TRANSITIONAL" rejim üret. Veya confidence'ı birden fazla rejime bölen bir dağılım olarak raporla.

---

## 9. CROSS-SECTIONAL HESAPLAMA HATALARI

### X-001 · Cross-sectional rank hesaplamasında tied values için hatalı rank
- **Dosya:** `services/features/cross_sectional.py`, satır ~55-65 (`compute_rank_features`)
- **Sorun:** `rank = sum(1 for v in all_vals if v <= my_val) / len(all_vals)` — bu, tied values durumunda tüm tied değerleri "düşük" sayıyor. Örneğin 10 hissenin 5'inde aynı değer varsa, bu 5 hissenin hepsi aynı rank'i alır (0.5). Bu, rank distribution'da spike yaratır. Standart percentile rank hesaplamasında tied values için ortalama rank kullanılır.
- **Öncelik:** P1
- **Düzeltme:** `scipy.stats.percentileofscore(all_vals, my_val, kind='rank')` kullan. Veya tied values için ortalama rank hesapla.

### X-002 · Sector momentum feature'ları cross-sectional olarak hesaplanıyor ama tarih bağımlılığı yok
- **Dosya:** `services/features/cross_sectional.py`, satır ~140-160 (`compute_sector_momentum`)
- **Sorun:** `compute_sector_momentum()` fonksiyonu `universe_features` dict'indeki tüm hisselerin `return_5d`, `return_20d`, `momentum_20d` değerlerini alıp sektör bazlı ortalama hesaplıyor. Ancak bu fonksiyon hangi tarihte çağrıldığı bilinmiyor — aynı anda tüm hisselerin aynı tarihe ait feature'larının sağlanması gerekiyor ama bu garanti edilmiyor.
- **Öncelik:** P2
- **Düzeltme:** Fonksiyona `as_of_date` parametresi ekle ve sadece o tarihe ait feature'ları kullan.

### X-003 · Market breadth hesaplamasında return_1d feature'ı her zaman mevcut olmayabilir
- **Dosya:** `services/features/cross_sectional.py`, satır ~110-115
- **Sorun:** `ret = features.get("return_1d", 0)` — eğer `return_1d` feature'ı yoksa 0 kullanılıyor. Bu, hissenin yükselmediğini varsayıyor (neutral). Ancak `return_1d` yerine `roc_1d` veya başka bir isim kullanılmış olabilir (feature isimlendirme tutarsızlığı — bkz. bulgu N-001).
- **Öncelik:** P2
- **Düzeltme:** `return_1d` yerine birden fazla aday isim kontrol et: `["return_1d", "roc_1d", "daily_return"]`.

---

## 10. FEATURE İSİMLENDİRME TUTARSIZLIKLARI

### N-001 · RSI feature isimleri tutarsız
- **Dosya:** Birden fazla dosya
- **Sorun:** 
  - `calculator.py`: `"rsi_14"`, `"rsi_5"` üretiyor
  - `seven_motors.py` Motor 8: `"rsi_14d"`, `"rsi_5d"`, `"rsi_21d"` üretiyor
  - `ranking_model.py`: `"rsi_14"` bekliyor
  - `cross_sectional.py`: `"rsi_14"` kullanıyor
  - `ranker.py`: `"rsi_14"` bekliyor
  
  Calculator ve Motor 8 farklı isimler kullanıyor (`rsi_14` vs `rsi_14d`). SevenMotorEngine'in alias map'inde bu eşleme yok.
- **Öncelik:** P1
- **Düzeltme:** Motor 8'in RSI isimlerini calculator ile uyumlu hale getir (`rsi_14d` → `rsi_14`). Veya alias map'e ekle.

### N-002 · Volume feature isimleri tutarsız
- **Dosya:** Birden fazla dosya
- **Sorun:**
  - `calculator.py`: `"volume_zscore"` üretiyor
  - `seven_motors.py` Motor 3: `"volume_zscore_10d"`, `"volume_zscore_20d"`, `"volume_zscore_60d"` üretiyor
  - `seven_motors.py` alias map: `"volume_zscore_20d"` → `"volume_zscore"` eşleniyor ✓
  - `alpha_scanner.py`: `"volume_zscore"` kullanıyor ✓
  - `ranker.py`: `"volume_zscore"` bekliyor ✓
  
  Bu durumda eşleme var ama `volume_zscore_10d` ve `volume_zscore_60d` kayboluyor — sadece 20d versiyonu canonical olarak kullanılıyor.
- **Öncelik:** P2
- **Düzeltme:** Tüm periyotların isimlerini koru (alias map'e ekle) veya sadece 20d versiyonunu üret.

### N-003 · Momentum feature isimleri tutarsız
- **Dosya:** Birden fazla dosya
- **Sorun:**
  - `calculator.py`: `"momentum_20d"` üretiyor (bu aslında ROC ile aynı: `(close[-1] / close[-20-1] - 1) * 100`)
  - `seven_motors.py` Motor 2: `"momentum_20d"` üretmiyor (sadece `"momentum_acceleration"`, `"momentum_accel_2nd"`, `"momentum_accel_trend"` üretiyor)
  - `ranking_model.py`: `"momentum_20d"` bekliyor
  - `ranker.py`: `"momentum_20d"` bekliyor
  
  Calculator'ın `momentum_20d`'si aslında ROC ile aynı. Motor 2'nin momentum anlayışı farklı (ivme). Bu isim çakışması kafa karıştırıcı.
- **Öncelik:** P2
- **Düzeltme:** `calculator.py`'deki `momentum_20d`'yi `roc_20d` ile aynı şey olarak tanımla (zaten aynı hesaplama). Motor 2'nin momentum anlayışını `momentum_acceleration` olarak adlandır.

### N-004 · ATR feature isimleri tutarsız
- **Dosya:** Birden fazla dosya
- **Sorun:**
  - `calculator.py`: `"atr_14"` ve `"atr_pct"` üretiyor
  - `alpha_scanner.py`: `"atr_14_pct"` bekliyor (farklı isim!)
  - `ranking_model.py`: `"atr_pct"` bekliyor ✓
  
  `alpha_scanner.py` `atr_14_pct` bekliyor ama calculator `atr_pct` üretiyor. Bu eşleşme eksik.
- **Öncelik:** P2
- **Düzeltme:** `alpha_scanner.py`'de `"atr_14_pct"` yerine `"atr_pct"` kullan. Veya calculator'da `"atr_14_pct"` alias'ı ekle.

### N-005 · Sector-relative feature isimleri ranking model ile cross-sectional engine arasında tutarsız
- **Dosya:** `services/ml/ranking_model.py` ve `services/features/cross_sectional.py`
- **Sorun:**
  - Ranking model: `"sector_rel_return_5d"`, `"sector_zscore_momentum_20d"` bekliyor
  - Cross-sectional engine: `"sector_rel_return_5d"`, `"sector_zscore_momentum_20d"` üretiyor ✓ (ama `SECTOR_REL_TARGETS` listesinde `momentum_20d` var, `return_5d` de var)
  - Ancak `sector_zscore_momentum_20d` ismi `sector_zscore_{feat_name}` formatında üretiliyor — bu doğru.
  
  Bu durumda eşleşme var ama `SECTOR_REL_TARGETS` listesinde olmayan feature'lar için `sector_rel_*` üretilmiyor. Örneğin `sector_zscore_roc_5d` üretilmiyor ama ranking model bunu bekliyor.
- **Öncelik:** P2
- **Düzeltme:** `SECTOR_REL_TARGETS` listesini ranking model'in beklediği feature'larla eşleştir.

---

## EK BULGULAR

### E-001 · Stochastic RSI hesabında hatalı pencere
- **Dosya:** `services/features/seven_motors.py`, satır ~490-510 (`MeanReversionMotor.compute`)
- **Sorun:** Stochastic RSI hesabında `for i in range(min(14, n-14))` döngüsü kullanılıyor. `subset = valid_close[-(14+i):-i] if i > 0 else valid_close[-14:]` — bu, `i=0`'da son 14, `i=1`'de son 15, ..., `i=13`'de son 27 barı kullanıyor. Ancak Stochastic RSI tanımında RSI serisinin son 14 değeri üzerinden Stochastic hesaplanması gerekiyor — mevcut implementasyon close fiyatlarını kullanıyor, RSI serisini değil.
- **Öncelik:** P1
- **Düzeltme:** Önce bir RSI serisi hesapla (rolling 14 periyot), sonra bu RSI serisi üzerinde Stochastic hesapla.

### E-002 · Calculator _bollinger_masked ve Motor 8 Bollinger farklı hesaplıyor
- **Dosya:** `services/features/calculator.py` ve `services/features/seven_motors.py`
- **Sorun:** Calculator'ın `_bollinger_masked` fonksiyonu `std_dev=2` kullanıyor (standart). Motor 8'in Bollinger hesabı `bb_position = (close - (sma - 2*std)) / (4*std)` kullanıyor — bu aynı formül ama `bb_position` 0-1 aralığında normalize edilmiş. Calculator'ın `bb_position`'ı da aynı normalize'i yapıyor. Ancak calculator `bb_position`'ı max(0, min(1, ...)) ile sınırlarken, Motor 8 bunu yapmıyor (out of bounds değerler üretebilir).
- **Öncelik:** P2
- **Düzeltme:** Motor 8'in `bb_position` hesabına `max(0, min(1, ...))` ekle.

### E-003 · Model calibration'da Platt scaling için validation set kullanılmıyor
- **Dosya:** `services/ml/calibration.py`, satır ~90-100 (`calibrate_platt`)
- **Sorun:** `calibrate_platt()` fonksiyonunda `calibrator.fit(y_prob.reshape(-1, 1), y_true)` ile eğitim yapılıyor. Eğer `y_prob_val` verilmişse onun üzerinde predict yapılıyor ama calibrator'ın kendisi tüm veriyle eğitilmiş — validation set üzerinde overfitting riski var.
- **Öncelik:** P1
- **Düzeltme:** Calibrator'ı sadece train set üzerinde eğit, validation set üzerinde değerlendir.

### E-004 · Feature drift detector'da PSI hesaplama basitleştirilmiş
- **Dosya:** `services/ml/feature_drift.py`, satır ~120-130
- **Sorun:** SHAP-based drift kontrolünde `psi = abs(current_imp - hist_mean) / max(hist_std, 0.01)` hesaplanıyor. Bu, gerçek PSI hesaplaması değil — sadece z-score benzeri bir metrik. Gerçek PSI, iki dağılım arasındaki KL divergence'ı ölçer.
- **Öncelik:** P2
- **Düzeltme:** Bu metriğin adını `importance_zscore` olarak değiştir. Gerçek PSI hesaplamasını `_calculate_psi` metodunda zaten yapıyor ama SHAP-based kontrolde kullanmıyor.

### E-005 · Scenario engine breaking point binary search'te negatif şok desteği yok
- **Dosya:** `services/intelligence/scenario.py`, satır ~180-200 (`find_breaking_point`)
- **Sorun:** `find_breaking_point()` fonksiyonu `low=0.0, high=max_change` ile binary search yapıyor. Bu, sadece pozitif şokları test ediyor. Negatif şoklar (ör. BIST düşüşü) için `variable` parametresinin negatif değer alması gerekiyor ama `max_change=1.0` ile başlatılıyor.
- **Öncelik:** P2
- **Düzeltme:** `low = -max_change` ile başlat veya `direction` parametresi ekle.

---

## ÖNERİLEN ÖNCELİK SIRASI

### Acil (P0) — Bu sprint'te düzeltilmeli:
1. **F-001**: Label üretimi mask-aware değil
2. **F-002**: HMM regim tespitinde sahte veri
3. **F-003**: Purge gap eksik
4. **M-001**: Seasonality motoru mask kırığı
5. **R-002**: Ranking model grup yapısı eksik
6. **W-001**: Sahte walk-forward (model eğitimi yok)

### Yüksek (P1) — Gelecek sprint'te düzeltilmeli:
1. **F-004, F-005**: Real BIST backtest sızıntıları
2. **M-002, M-003, M-004**: Mask-first ihlalleri
3. **R-001, R-003**: Ranking model sözleşme uyumsuzlukları
4. **P-001, P-002**: Purge+embargo eksiklikleri
5. **W-002, W-004**: Walk-forward iyileştirmeleri
6. **H-001, H-004, H-007**: Sabit değerler
7. **G-001**: Breadth scoring tutarsızlığı
8. **X-001**: Tied values rank hatası
9. **N-001**: RSI isim tutarsızlığı
10. **E-001, E-003**: Hesaplama hataları

### Orta (P2) — Backlog'a alınmalı:
1. **D-001–D-007**: Dead code temizliği
2. **H-002, H-003, H-005, H-006**: Sabit değer iyileştirmeleri
3. **G-002–G-004**: Regime scoring iyileştirmeleri
4. **X-002, X-003**: Cross-sectional iyileştirmeleri
5. **N-002–N-005**: İsim standardizasyonu
6. **E-002, E-004, E-005**: Çeşitli iyileştirmeler
