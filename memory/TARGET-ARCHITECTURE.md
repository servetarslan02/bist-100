# ALPHA — TARGET ARCHITECTURE

## 1. Hedef
ALPHA, erişilebilen tüm Borsa İstanbul evreni ve onu etkileyen global bilgi bağlamı üzerinde sürekli çalışan, governed autonomous financial intelligence sistemidir.

Ölçekleme varlık/kaynak dışlayarak değil, adaptive prioritization ve incremental computation ile yapılır.

## 2. Scope Topology
### Asset Universe
- tüm güncel Borsa İstanbul evreni;
- tarihsel BIST üyelikleri ve delist/removed securities;
- BIST endeks ve sektör endeksleri;
- ilgili Türkiye FX/faiz/fon/türev değişkenleri;
- BIST'i açıklamak/öngörmek için gerekli global endeks, faiz, FX, emtia, equity ve risk değişkenleri.

### Information Universe
- KAP;
- şirket IR ve resmi açıklamalar;
- Türkiye resmi makro/regülasyon/politika kaynakları;
- global merkez bankaları ve makro kaynaklar;
- güvenilir Türkiye/global haber;
- sektör, enerji, emtia, lojistik, shipping, geopolitics;
- hukuken/teknik olarak erişilebilir public web;
- lisanslı feed/API;
- tarihsel archive ve research datasets.

## 3. Adaptive Coverage: HOT / WARM / COLD
### HOT
Portföyde bulunan, büyük event/anomaly yaşayan, volatilitesi veya uncertainty'si yükselen, kritik relationship ile tetiklenen varlık/olay/kaynaklar. En düşük latency ve en derin evidence.

### WARM
Tüm aktif BIST varlıkları ve doğrudan ilgili Türkiye/sektör/global değişkenleri. Sürekli incremental state ve düzenli ranking kapsamı.

### COLD
Long-tail global kaynak/entity ve eski tarih. Discoverability korunur, scheduled refresh yapılır. Her event COLD entity'yi anında HOT'a çıkarabilir.

Tier = compute priority. Eligibility filter değildir.

## 4. End-to-End Plane
`SOURCE REGISTRY -> CONNECTOR/API/CRAWLER -> RAW IMMUTABLE STORE -> NORMALIZATION -> ENTITY RESOLUTION -> DEDUP -> DATA QUALITY/TEMPORAL VALIDATION -> CANONICAL EVENT LEDGER -> STATE ENGINES -> FEATURE PLATFORM -> MODEL ZOO/RANKING -> UNCERTAINTY -> RISK -> PAPER EXECUTION -> PORTFOLIO LEDGER -> OUTCOME -> ATTRIBUTION -> RESEARCH -> GOVERNANCE`

## 5. Source Registry
Her source versioned metadata taşır:
- source_id/category/provider;
- access/legal/licensing status;
- timezone/expected latency/freshness threshold;
- rate limits/authentication;
- parser/extractor version;
- historical availability;
- measured reliability history.

Source failure saklanacak bir state'tir.

## 6. Raw + Canonical Event Ledger
Mümkün olduğunda raw input transformation öncesi saklanır. Canonical event:
- immutable event_id;
- event_type + schema_version;
- source_id;
- source_timestamp;
- ingest/observed/effective timestamps;
- entities/assets;
- payload;
- quality/novelty/uncertainty;
- provenance chain;
- parser/model version.

Correction ve late-arrival eski kaydı sessizce değiştirmez; versioned update oluşturur.

## 7. Entity Resolution + Knowledge Graph
Canonical identity en az:
security, company, parent/subsidiary, sector/industry, person, institution, country, commodity, currency, customer, supplier, competitor, contract/project, macro indicator.

Graph ilişkiyle birlikte relationship evidence ve confidence tutar.

## 8. State Architecture
- WorldState: global risk, rates, USD, commodities, geopolitics, liquidity.
- TurkeyState: inflation, rates, FX, policy, fiscal/regulatory, local liquidity/credit.
- MarketState: breadth, dispersion, correlation, trend, volatility, liquidity, regime.
- SectorState: returns, breadth, valuation, momentum, events, macro sensitivity.
- CompanyState: business model, segments, customers, suppliers, backlog, capacity, debt, cash, events.
- AssetState: market/liquidity/technical/fundamental/relative/event/catalyst/model evidence.
- PortfolioState: cash, positions, orders, P&L, exposures, risk.
- ModelState: champion/challenger, calibration, drift, OOS/paper quality.
- ResearchState: experiments, hypotheses, failures, backlog.
- DataQualityState: source freshness, disagreement, masks, integrity.

## 9. Mask-First
Mask raw/normalized data seviyesinde dependent calculations'dan önce oluşur:
missing, stale, future/not-yet-known, halt/suspension, invalid OHLC, corporate-action inconsistency, liquidity/unexecutable, source disagreement, low-confidence, insufficient history.

## 10. Feature Platform
Feature'lar point-in-time, mask-aware, cross-sectional, horizon-aware, versioned ve reproducible olmalıdır.

Her feature contract:
definition, input sources, availability time, update frequency, missing policy, expected range/unit, version, leakage tests.

Başlangıç families:
relative strength; momentum/trend; volume/microstructure; fundamental/FCF/quality/value/growth; event intelligence; catalyst; why-falling; mean reversion; seasonality; macro/world/graph interactions.

## 11. Research Data Plane
Ad-hoc current tables yerine immutable dataset manifests kullanılır. Manifest:
universe logic, source ranges, corporate-action policy, features, labels, masks, sampling, train/valid/test windows, checksums, code/config versions.

## 12. Labels
Strictly future point-in-time outcomes:
absolute return, benchmark/sector relative return, risk-adjusted return, cross-sectional rank, drawdown/adverse excursion, event reaction, execution-adjusted outcome.

Horizonlar ayrı kalır.

## 13. Model Zoo
Tek kutsal model yoktur:
learning-to-rank, classifiers, regressors, regime specialists, anomaly models, event-impact, causal/counterfactual, volatility/risk, execution/liquidity, ensembles/meta-models.

Her model intended universe/horizon/regime ve uncertainty/health metadata ilan eder.

## 14. Ranking
Approved model/evidence outputs universe-relative opportunity ordering üretir. Ranking trading değildir; calibration, uncertainty, signal policy ve risk'e input olur.

## 15. Regime
Regime probabilistic/hierarchical olabilir: trend × volatility × liquidity × correlation × dispersion. Model switching kuralları OOS ile doğrulanır.

## 16. Event/LLM Intelligence
LLM unrestricted trader değildir. Görevleri:
- event extraction;
- entity linking;
- financial term extraction;
- contradiction synthesis;
- KAP/news understanding;
- company materiality reasoning;
- research question/hypothesis proposal;
- experiment planning;
- report synthesis.

Her factual downstream claim evidence reference taşır.

## 17. Research Brain
Backlog kaynakları:
model degradation, unexplained residuals, failed predictions, new source/regime, feature interactions, event clusters, graph anomalies, human research requests.

Experiments isolated ve başarısız sonuçlar dahil kayıtlıdır.

## 18. Governance Brain
Bağımsız olarak:
schema/contract checks, temporal integrity, leakage, reproducibility, OOS metric recompute, multiple-testing controls, stress, cost/execution validation, promotion gate, audit verification yürütür.

## 19. Model Lifecycle
`RESEARCH -> VALIDATED -> SHADOW -> CHALLENGER -> PAPER-ELIGIBLE -> CHAMPION -> DEGRADED -> RETIRED/QUARANTINED`

Her geçiş event ve audit kaydıdır.

## 20. Paper Trading OS
Persistent:
virtual accounts, cash ledger, order ledger, fill simulator, positions, corporate actions, fees, realized/unrealized P&L, equity/risk snapshots, decision links.

## 21. Risk
Data integrity -> model integrity -> liquidity -> position sizing -> concentration -> covariance -> volatility target -> cost/turnover -> drawdown/daily loss -> kill switch.

Output: APPROVE / REDUCE / DELAY / NO-TRADE.

## 22. Safe Mode
`NORMAL -> DEGRADED -> REDUCED EXPOSURE -> NO-TRADE -> SYSTEM HALT`

## 23. Storage Roles
Technology değil görev önce gelir:
relational metadata; analytical time-series/event; low-latency state/cache; immutable object lake; experiment/model registry; vector/semantic index; append-only audit.

## 24. Compute Scheduling
Market hours: freshness/state/risk/paper execution.
After close: reconciliation/outcomes/attribution/data repair.
Overnight: challenger research/web processing/feature discovery.
Weekend/idle: expensive walk-forward, stress, graph rebuild, archives.

## 25. Observability
Throughput, lag, freshness, quality/mask rates, source reliability, feature health, inference latency, model drift/quality, portfolio risk, execution realism, research queue, governance failures.

## 26. Migration From Existing Repo
Her component: KEEP / REWRITE / DELETE-ARCHIVE.

Sıra:
1. canonical memory + contracts + constitution;
2. tek runtime entry point;
3. coherent dependency/infrastructure;
4. point-in-time + mask-first data pipeline;
5. universe/entity/source registry;
6. dataset/label/walk-forward platform;
7. honest baseline + independent evaluation;
8. persistent paper ledger/execution;
9. champion/challenger governance;
10. event/KAP/web/global world model;
11. autonomous research only after governance proves itself.

## 27. Full Autonomy Definition
`OBSERVE -> VALIDATE -> UNDERSTAND -> UPDATE STATE -> RANK -> ESTIMATE UNCERTAINTY -> RISK -> PAPER ACT -> RECONCILE -> ATTRIBUTE -> DIAGNOSE -> CREATE RESEARCH TASK -> EXPERIMENT -> INDEPENDENT VALIDATE -> SHADOW -> PROMOTE/REJECT`

Günlük insan operasyonu gerektirmeden, constitution bypass yetkisi olmadan çalışabilmelidir.
