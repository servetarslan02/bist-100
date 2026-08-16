# ALPHA — REPOSITORY TRUTH AUDIT v4

**STATUS:** ACTIVE AUDIT
**BRANCH:** `alpha-rebuild-v4`
**UPDATED_AT:** 2026-08-16
**PURPOSE:** Legacy kodun varlığını tamamlanmış sistem özelliği saymamak; her kritik parçayı KEEP / REWRITE / ARCHIVE olarak sınıflandırmak.

## Sınıflandırma

- **KEEP:** Kavram + implementation yeterince sağlam; V4 contract/test kapısına taşınabilir.
- **REWRITE:** Kavram değerli fakat mevcut implementation güvenilir değil veya hedef mimariyle uyumsuz.
- **ARCHIVE:** Duplicate, misleading, dead-end veya architecture-theater; production omurgasına taşınmamalı.
- **VERIFY:** Henüz yeterli evidence yok; taşımadan önce test/audit gerekir.

## Kritik Bulgular

### Runtime / Entry Points

| Component | Status | Evidence / Reason |
|---|---|---|
| root `alpha` bash script | **ARCHIVE** | `start` ve `scan` yolları `start.py` çağırıyor; `start.py` main branch'te yok. Canonical runtime olamaz. |
| README start instructions | **REWRITE** | Eski runtime zincirine ve tamamlanmışlık varsayımlarına bağlı. |
| `services/api/main.py` | **REWRITE** | Gerçek API kodu var fakat full-BIST kuralını ihlal eden `BIST_STOCKS[:50]`, silent exceptions ve unreachable regime branch içeriyor. |
| `services/api/server.py` | **ARCHIVE/VERIFY** | İkinci API nesli; Docker'ın canonical entry point'i değil. Duplicate runtime riski. |
| `alpha_v4/__main__.py` | **KEEP (V4)** | Yeni canonical CLI; fresh DB bootstrap ve health testleri CI'da çalışıyor. |

### Data / Quality / Point-in-Time

| Component | Status | Evidence / Reason |
|---|---|---|
| legacy `services/core/data_quality.py` | **REWRITE** | Mask bazı feature'lara post-hoc uygulanıyor; constitution'daki mask-before-features şartını sağlamıyor. |
| legacy DB adapters | **VERIFY/REWRITE** | PostgreSQL/ClickHouse/Redis erişimi var fakat dependency ve runtime tutarlılığı yeniden kurulmalı. |
| `alpha_v4/data_quality.py` | **KEEP (V4 bootstrap)** | Raw OHLCV feature hesaplanmadan önce VALID/MISSING/STALE/INVALID/NOT_YET_KNOWN/UNTRADABLE olarak ayrılıyor. |
| `alpha_v4/storage.py` | **KEEP (bootstrap persistence)** | Canonical event history append-only SQLite store ile restart sonrası korunuyor; point-in-time query testli. Final OLAP/OLTP teknolojisi kararı değildir. |

### Event / News / Intelligence

| Component | Status | Evidence / Reason |
|---|---|---|
| legacy sentiment-style news features | **REWRITE** | Tek sentiment/skor yaklaşımı yeni Event Intelligence spec ile uyumsuz. |
| legacy agent fallback logic | **REWRITE** | Farklı agent rollerinin aynı rule-based fiyat fallback'ine düşmesi domain reasoning değildir. |
| `alpha_v4/event_intelligence.py` | **KEEP (foundation)** | Contract value şirket ölçeğine göre materiality, binding status, novelty, unknowns ve cautions olarak ayrılıyor; tek news score yok. |
| `alpha_v4/reaction.py` | **KEEP (foundation)** | Raw return ile benchmark/sector-relative reaction ayrı; pozitif ham getiri otomatik pozitif event reaction sayılmıyor. |
| `alpha_v4/event_threads.py` | **KEEP (foundation)** | Tender -> win -> signed -> execution gibi aynı olayın lifecycle aşamaları ayrı pozitif haber diye double-count edilmiyor. |
| `alpha_v4/company_memory.py` | **KEEP (foundation)** | Company context karar zamanında gerçekten bilinen snapshot üzerinden seçiliyor. |

### ML / Ranking

| Component | Status | Evidence / Reason |
|---|---|---|
| `services/ml/ranking_model.py` | **REWRITE** | Dosya LambdaRank + Adjusted-MSE iddiasında; training path Adjusted-MSE kullanmıyor. Input modeli `ticker -> tek feature row` yapısında ve tarih grubu sırası X ile güvenilir biçimde bağlanmıyor. |
| legacy ranking confidence | **REWRITE** | Confidence rank percentile'dan 0.5-0.99 üretiliyor; calibrated probability değil. Constitution ihlali. |
| legacy rule-based/LambdaRank score direction | **REWRITE** | Rule score yükselmesi ile final ascending sort semantiği çelişebiliyor. |
| `tests/test_faz3_ranking.py` | **ARCHIVE/REWRITE** | Testler mevcut ranking API'sinde olmayan class'ları import ediyor ve `assert ... or True` içeriyor; pass sayısı kalite kanıtı değil. |

### Backtest / Validation

| Component | Status | Evidence / Reason |
|---|---|---|
| `services/backtest/engine.py` | **REWRITE** | `price_data` gerçek mark-to-market için kullanılmıyor; başka pozisyonlar cost'ta kalıyor; holding_days=1, CAGR=total return, DD duration=0, exposure=0 hard-coded. |
| legacy walk-forward helpers | **REWRITE** | Precomputed prediction slicing gerçek fold-içi retraining değildir. |
| historical '35 fold/31 OOS/LambdaRank champion' claims | **UNVERIFIED** | Dataset manifest, exact code commit, fold artifacts ve independent recomputation olmadan kanıt kabul edilmez. |

### Learning / Self-Improvement

| Component | Status | Evidence / Reason |
|---|---|---|
| `services/learning/integrated_learning.py` | **REWRITE** | Tahmin/outcome çoğunlukla process RAM'inde; feature importance fiilen öğrenilmiyor; gerçek retrain/champion-challenger yok. |
| model drift rule | **REWRITE** | Son 20 accuracy vs all-time accuracy*0.8 yalnız kaba heuristic; feature/data/regime/execution drift ayrımı yok. |

### Event Bus / Reliability

| Component | Status | Evidence / Reason |
|---|---|---|
| `services/core/event_bus.py` | **REWRITE** | Faydalı idempotency/stream fikirleri var ancak kritik yerlerde `except: pass`, Redis/Kafka dual semantics ve fail-open davranış var. |
| in-memory fallback bus | **ARCHIVE for production** | Process restart sonrası event history/consumer guarantees sağlamaz. |

### Infrastructure / Security

| Component | Status | Evidence / Reason |
|---|---|---|
| `docker-compose.yml` | **REWRITE** | Database/Grafana credentials source control içinde hard-coded; constitution secret policy ile çelişiyor. |
| Docker service graph | **VERIFY/REWRITE** | Birçok service module adı var ancak implementation/dependency coherence bağımsız doğrulanmalı. |
| `requirements.txt` | **REWRITE** | Legacy code bazı yerlerde Polars/ClickHouse/Kafka kullanırken requirements bunları tam temsil etmiyor. |

### Dashboard

| Component | Status | Evidence / Reason |
|---|---|---|
| Next.js UI structure | **KEEP DESIGN / REWRITE DATA CONTRACTS** | Sayfalar ve görsel temel yeniden kullanılabilir; data API contract'ları V4 state/event/runtime'a göre yeniden bağlanmalı. |
| legacy static dashboard HTML | **ARCHIVE/VERIFY** | Duplicate UI nesli; canonical frontend belirlenmeli. |

## V4'te Şu Ana Kadar Gerçekten Doğrulanmış Parçalar

Aşağıdakiler dosya adı nedeniyle değil, GitHub Actions CI ile gerçek çalıştırma sonucu nedeniyle doğrulanmıştır:

- Python 3.11 ve 3.12 üzerinde V4 package compile;
- canonical event deterministic ID + point-in-time availability;
- evidence timestamp integrity;
- raw OHLCV mask-before-features;
- invalid observation üzerinden return bridge edilmemesi;
- şirket ölçeğine göre contract materiality;
- missing finansal veride fake değer üretilmemesi;
- append-only event persistence + restart recovery;
- duplicate event rejection;
- point-in-time event query;
- benchmark/sector-relative event reaction;
- measured source reliability başlangıç davranışı;
- company snapshot point-in-time memory;
- event lifecycle threading/dedup;
- canonical CLI/runtime bootstrap;
- unregistered source event rejection.

## Migration Sırası

1. V4 contract/runtime foundation
2. persistent universe/entity/source registry
3. raw point-in-time market/fundamental/event stores
4. company/event intelligence state
5. state engine
6. feature platform
7. dataset/label/walk-forward lab
8. honest baseline models
9. governance/champion-challenger
10. persistent paper OS
11. autonomous research
12. governed self-coding

## Audit Kuralı

Legacy bir component `KEEP` olmadan V4 runtime'a import edilemez. `REWRITE` statüsündeki component'ten yalnız kavram/algoritma fikri taşınabilir; implementation doğrudan production'a bağlanamaz.
