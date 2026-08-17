# ALPHA — ROADMAP v4

**STATUS:** ACTIVE
**VERSION:** 4.0
**UPDATED_AT:** 2026-08-16
**SUPERSEDES AS ACTIVE PLAN:** ROADMAP.md, ROADMAP-v2.md, ROADMAP-v3.md
**DEPENDS_ON:** SYSTEM-CONSTITUTION.md, MASTER-SPEC.md, TARGET-ARCHITECTURE.md, EVENT-INTELLIGENCE-SPEC.md

## Ana Hedef
Eski LLM tarafından üretilmiş, birbirine tam bağlanmamış çok sayıdaki modülü yamamak değil; ALPHA'yı dürüst, test edilebilir, point-in-time, persistent, full-BIST + global-context, event-understanding, self-researching fakat governed autonomous system olarak yeniden kurmak.

Hiçbir faz dosya sayısı veya test ismi nedeniyle tamamlanmış sayılmaz.

---

# FAZ 0 — REPOSITORY TRUTH AUDIT
Amaç: mevcut kodun gerçekte ne yaptığını ortaya çıkarmak.

- tüm entry point'leri bul
- dependency/import graph çıkar
- duplicate API/runtime nesillerini ayır
- hard-coded market data bul
- silent exception/pass bul
- mock/fake/placeholder davranışları bul
- hard coverage caps (`[:50]`, `[:100]`, vb.) bul
- in-memory state/persistence açıklarını bul
- testlerin gerçekten assertion yaptığını doğrula
- README/ROADMAP iddialarını implementation ile eşleştir
- KEEP / REWRITE / ARCHIVE matrisi üret

**Exit gate:** tüm kritik component'ler status + evidence ile sınıflandırılmış.

---

# FAZ 1 — CANONICAL RUNTIME & PROJECT CONTRACTS
Amaç: tek gerçek çalışma yolu.

- tek canonical Python runtime entry point
- dev/test/research/paper execution mode ayrımı
- coherent requirements/lock strategy
- config/secrets temizliği
- structured logging/error taxonomy
- service health model
- canonical schemas
- event contract
- entity/instrument contract
- state contract
- feature contract
- dataset manifest contract
- label contract
- model artifact contract
- portfolio ledger contract

**Exit gate:** fresh checkout üzerinde tek documented bootstrap yolu ve contract tests.

---

# FAZ 2 — UNIVERSE / ENTITY / SOURCE REGISTRY
Amaç: sabit ticker listelerinden çıkmak.

- tüm erişilebilir BIST security master
- instrument/company ayrımı
- ticker/name changes
- corporate actions
- IPO/delist/history
- historical universe membership
- sector/industry/peer mappings
- source registry
- company identities
- global entity identity layer
- customer/supplier/competitor/parent relations için evidence model

**Kural:** business-level fixed universe cap yok.

**Exit gate:** point-in-time universe snapshot üretilebiliyor.

---

# FAZ 3 — RAW DATA + POINT-IN-TIME + MASK-FIRST
Amaç: modelden önce doğru veri.

- raw immutable ingestion
- market OHLCV
- adjusted/unadjusted policy
- corporate actions
- benchmark/sector
- fundamentals with publication/effective timestamps
- KAP raw disclosures
- macro/global raw feeds
- source freshness
- correction/version handling
- deduplication
- temporal availability
- tradability/data-quality masks BEFORE features
- missing/stale/invalid/source-disagreement states

**Exit gate:** hiçbir downstream hesap gelecek veya invalid observation'ı sessizce kullanamıyor.

---

# FAZ 4 — EVENT INTELLIGENCE FOUNDATION
Amaç: haber puanlamak değil, olay anlamak.

- event ontology
- multilingual event extraction
- entity resolution
- event thread/lifecycle
- contract/agreement extraction
- company materiality ratios
- binding/conditionality
- counterparty intelligence
- expectation/surprise
- novelty/pre-priced inference
- evidence spans
- contradiction handling
- company memory
- event reaction windows
- benchmark/sector relative reactions
- historical event memory

**Exit gate:** KAP/haber structured event olarak source evidence ile yeniden üretilebiliyor; tek sentiment score zorunluluğu yok.

---

# FAZ 5 — WORLD / TURKEY / MARKET / SECTOR / COMPANY STATE
Amaç: piyasanın o anki durumunu çok katmanlı temsil etmek.

- WorldState
- TurkeyState
- MarketState
- SectorState
- CompanyState
- AssetState
- DataQualityState
- incremental updates
- versioned snapshots
- state freshness
- knowledge graph propagation
- event -> entity -> sector/company/asset influence candidates

**Exit gate:** state snapshot belirli timestamp için replay edilebiliyor.

---

# FAZ 6 — FEATURE PLATFORM / 9+ INTELLIGENCE FAMILIES
Amaç: feature dosyası değil, versioned feature platform.

Initial families:
1. Relative Strength
2. Momentum + Trend
3. Volume + Microstructure
4. Fundamental / FCF / Quality / Value / Growth
5. Event Intelligence / KAP / News
6. Catalyst
7. Why Is It Falling?
8. Mean Reversion
9. Seasonality
10+. Research tarafından kanıtlanan yeni families

- cross-sectional features
- peer/sector relative
- macro/world interactions
- event state features
- missingness contract
- feature availability timestamp
- incremental compute
- feature lineage
- leakage tests

**Exit gate:** feature manifest ve point-in-time reproducibility.

---

# FAZ 7 — LABEL / DATASET / VALIDATION LAB
Amaç: sistem kendisini kandıramasın.

- immutable dataset manifests
- multi-horizon labels
- absolute / benchmark-relative / sector-relative / risk-adjusted returns
- cross-sectional rank labels
- adverse excursion / drawdown labels
- event reaction labels
- execution-aware outcomes
- temporal split
- purge/embargo
- walk-forward retraining inside every fold
- survivorship-safe universe
- leakage scanners
- independent metric recomputation
- multiple-testing registry

**Exit gate:** deterministic/reproducible OOS benchmark suite.

---

# FAZ 8 — HONEST BASELINE + MODEL ZOO
Amaç: önce basit ama gerçek baseline.

- naive baselines
- linear/rule baselines
- LightGBM ranking baseline
- calibrated classification where appropriate
- horizon-specific models
- regime specialists only if validated
- model uncertainty/health
- model artifact registry
- no arbitrary confidence
- ranking metrics: IC/RankIC, Precision@K, spread, NDCG where appropriate
- portfolio-aware metrics after cost

**Exit gate:** en az bir baseline bağımsız OOS evaluation ile reproducible.

---

# FAZ 9 — GOVERNANCE + CHAMPION/CHALLENGER
Amaç: self-learning'i güvenli yapmak.

Lifecycle:
`RESEARCH -> VALIDATED -> SHADOW -> CHALLENGER -> PAPER-ELIGIBLE -> CHAMPION -> DEGRADED -> RETIRED/QUARANTINED`

- independent validator
- promotion policy
- reproducibility gate
- cost realism gate
- data integrity gate
- drift gate
- multiple-testing gate
- experiment registry
- failed research retention

**Exit gate:** Research Brain kendi modelini doğrudan production'a taşıyamıyor.

---

# FAZ 10 — PERSISTENT PAPER TRADING OS
Amaç: gerçek zamanlı yıllarca ölçülebilen sanal işletim.

- virtual accounts
- persistent cash
- orders
- fills
- positions
- average cost
- realized/unrealized P&L
- corporate actions
- commission
- spread
- slippage
- liquidity constraints
- partial fills where data supports
- execution timing
- turnover
- equity curve
- daily snapshots
- portfolio reconciliation
- immutable audit

**Exit gate:** restart sonrası state kaybolmuyor; bütün paper trade zinciri replay ediliyor.

---

# FAZ 11 — RISK / UNCERTAINTY / SAFE MODE
Amaç: modelden bağımsız koruma.

- data uncertainty
- model uncertainty
- regime uncertainty
- event uncertainty
- execution uncertainty
- liquidity gates
- concentration
- covariance/correlation
- volatility targeting
- drawdown
- daily loss
- turnover/cost budget
- kill switch
- safe mode ladder

`NORMAL -> DEGRADED -> REDUCED EXPOSURE -> NO-TRADE -> HALT`

**Exit gate:** kritik dependency bozukken sistem trade üretmiyor.

---

# FAZ 12 — PERFORMANCE / ATTRIBUTION / FAILURE DIAGNOSIS
Amaç: sadece getiri değil, neden.

- CAGR/Sharpe/Sortino/Calmar/MaxDD
- Alpha/Beta
- IC/ICIR
- Precision@K
- top-bottom spread
- transaction cost
- exposure
- turnover
- regime attribution
- feature/model attribution
- event attribution
- execution attribution
- failure classification
- source quality history

**Exit gate:** performans kötüleşmesi `model kötü` diye tek sebebe indirgenmiyor.

---

# FAZ 13 — AUTONOMOUS RESEARCH BRAIN
Amaç: ALPHA'nın yeni soru üretmesi.

Research triggers:
- model drift/decay
- unexplained residuals
- repeated failed predictions
- new event clusters
- new source
- new regime
- feature interaction
- graph anomaly
- human research request

Capabilities:
- hypothesis generation
- economic rationale
- experiment design
- isolated code/feature/model creation
- dataset manifest creation
- OOS/robustness experiments
- negative result logging
- challenger proposal

**Kural:** discovery production değildir.

---

# FAZ 14 — GOVERNED AUTONOMOUS CODING
Amaç: sistem kendi araştırma kodunu üretebilir ama production'ı keyfi değiştiremez.

- isolated branch/worktree/sandbox
- static analysis
- schema checks
- unit/integration tests
- resource limits
- security checks
- reproducibility
- benchmark/OOS
- governance review
- promotion event

**Exit gate:** autonomous code production branch'e doğrudan yazamıyor.

---

# FAZ 15 — GLOBAL INFORMATION EXPANSION
Amaç: BIST merkezli fakat dünya kapsamlı intelligence.

- source discovery registry
- official/global macro
- currencies/rates/commodities
- global equities/indices
- sector supply chains
- energy/shipping/logistics
- geopolitical events
- multilingual web sources
- credibility/contradiction models
- graph propagation learning
- HOT/WARM/COLD adaptive prioritization

**Exit gate:** global event'in BIST etkisi source/evidence üzerinden araştırılabilir; hard-coded relationship kalıcı truth değildir.

---

# FAZ 16 — LONG-RUN AUTONOMOUS PAPER PROOF
Amaç: yıllarca canlıya yakın paper evidence.

- daily autonomous operation
- source outage history
- model promotion/retirement history
- paper portfolio persistence
- multi-regime performance
- cost realism
- drawdown/recovery
- failure/safe-mode events
- research contribution attribution

Real-money execution bu roadmap'in otomatik sonucu değildir.

---

# Faz Tamamlanma Kuralı
Bir faz `COMPLETE` ancak:
1. implementation;
2. integration;
3. deterministic tests;
4. failure/edge tests;
5. real or controlled representative data validation;
6. observability;
7. documentation;
8. audit/reproducibility evidence;
9. no known critical placeholder/mock/fake path;
10. independent verification gerekiyorsa verification
ile kanıtlanır.

`Dosya mevcut`, `class var`, `test passed yazıyor`, `LLM raporu tamam dedi` completion değildir.
