# ALPHA — TARGET ARCHITECTURE

## 1. Architectural Goal
Build a continuously operating, full-scope, governed autonomous financial intelligence system for the complete accessible BIST universe and its global information context.

The architecture must scale by prioritization and incremental computation, not by permanently excluding assets or sources.

## 2. Scope Topology

### 2.1 Asset Universe
- Full current Borsa Istanbul universe
- Historical BIST constituents and delisted/removed securities for bias-safe research
- BIST indices and sector indices
- Relevant Turkish FX/rates/funds/derivatives where accessible
- Global indices, rates, currencies, commodities and equities needed to explain/forecast BIST states

### 2.2 Information Universe
- KAP disclosures
- Official company disclosures and investor relations
- Turkish official macro/regulatory sources
- Central banks and major global macro sources
- Reputable global and Turkish news
- Sector/commodity/shipping/energy/geopolitical sources
- Public web sources that can legally/technically be collected
- Licensed APIs/feeds when available
- Historical archives and research datasets

## 3. No-Cap Processing Strategy
No fixed coverage cap is allowed. Instead use adaptive tiers:

### HOT
Assets/events currently important due to position, anomaly, major event, volatility, liquidity, portfolio relevance or model uncertainty. Process with lowest latency and deepest evidence.

### WARM
All active BIST instruments and directly relevant sector/global variables. Maintain regular incremental state and ranking coverage.

### COLD
Long-tail global sources, older history and low-immediacy entities. Maintain discoverability and scheduled refresh/research processing.

An event can promote any cold entity/source to hot immediately. The tiers are resource priorities, not eligibility filters.

## 4. End-to-End Data Plane

SOURCE REGISTRY
  -> CONNECTORS / CRAWLERS / API ADAPTERS
  -> RAW IMMUTABLE STORE
  -> CANONICAL EVENT NORMALIZATION
  -> ENTITY RESOLUTION + DEDUPLICATION
  -> DATA QUALITY + TEMPORAL VALIDATION
  -> EVENT LEDGER
  -> STATE ENGINES
  -> FEATURE ENGINES
  -> MODEL/RANKING ENGINES
  -> UNCERTAINTY
  -> RISK
  -> PAPER EXECUTION
  -> PORTFOLIO LEDGER
  -> OUTCOMES
  -> ATTRIBUTION
  -> RESEARCH / GOVERNANCE

## 5. Source Registry
Every source has versioned metadata:
- source_id
- category
- owner/provider
- access method
- legal/licensing status
- expected latency
- timezone
- reliability history
- parser/extractor version
- freshness threshold
- rate limits
- authentication class
- historical availability
- trust score (measured, not hand-waved)

Source failure is data, not an exception to hide.

## 6. Raw Data and Event Ledger
Raw input is stored before transformation when legally/technically appropriate. Derived canonical events reference raw provenance.

Canonical event fields include:
- immutable event_id
- event_type + schema version
- source_id
- source_timestamp
- observed/ingest timestamp
- effective timestamp
- entities/assets
- payload
- quality
- novelty
- confidence/uncertainty
- provenance chain
- parser/model version

Late-arriving and corrected events create versioned updates rather than silently rewriting history.

## 7. Entity Resolution and Knowledge Graph
Canonical identities are maintained for:
- security
- company
- parent/subsidiary
- sector/industry
- person
- government/institution
- country
- commodity
- currency
- customer/supplier/competitor
- contract/project
- macro indicator

The graph stores both relationships and evidence supporting those relationships.

## 8. State Architecture
State is incremental and event-driven.

### WorldState
Global risk, rates, USD, commodities, geopolitics, global liquidity and major market states.

### TurkeyState
Rates, inflation, FX, policy, credit, fiscal/regulatory and local liquidity variables.

### MarketState
Breadth, dispersion, correlation, index trend, volatility, liquidity and regime.

### SectorState
Sector returns, breadth, valuation, momentum, event pressure and macro sensitivity.

### AssetState
Price/volume/liquidity, technical, fundamental, event, relative, catalyst, uncertainty and model evidence.

### PortfolioState
Cash, positions, orders, exposures, risk, P&L and execution state.

### ModelState
Champion/challenger versions, calibration, drift, recent OOS/paper quality and health.

## 9. Mask-First Data Quality
Tradability and validity masks are produced at the raw/normalized data level before dependent state/features are computed.

Masks include:
- missing/stale
- not-yet-known
- halted/suspended
- invalid OHLC
- corporate-action inconsistency
- illiquid/unexecutable
- source disagreement
- low confidence
- newly listed/history-insufficient

Feature functions consume mask-aware series. Missingness itself may be a feature only when explicitly modeled without leaking future information.

## 10. Feature Platform
Feature computation is:
- point-in-time
- mask-aware
- cross-sectional
- incremental where possible
- versioned
- reproducible
- horizon-aware

Feature families begin with relative strength, momentum/trend, volume/microstructure, fundamentals, KAP/news, catalysts, falling-reason analysis, mean reversion and seasonality, and expand through governed research.

Each feature has a contract: definition, input sources, time availability, update frequency, missing policy, expected range, owner/version and leakage tests.

## 11. Research Data Plane
Research uses immutable dataset manifests rather than ad-hoc current tables.

A dataset manifest pins:
- universe snapshot logic
- source/event ranges
- corporate-action policy
- feature versions
- labels
- masks
- sampling frequency
- train/validation/test windows
- hash/checksum

## 12. Labels and Evaluation Horizons
Labels are computed from strictly future point-in-time outcomes. Multiple horizons remain separate.

Examples:
- future absolute return
- benchmark-relative return
- sector-relative return
- risk-adjusted return
- cross-sectional percentile/rank
- drawdown / adverse excursion
- event response
- execution-adjusted outcome

## 13. Model Architecture
ALPHA supports a model zoo rather than a single sacred model:
- learning-to-rank
- calibrated classifiers
- regressors
- regime specialists
- anomaly models
- event-impact models
- causal/counterfactual models
- volatility/risk models
- execution/liquidity models
- ensembles/meta-models

Models must expose uncertainty/health metadata and declare their intended universe, horizon and regime applicability.

## 14. Ranking and Opportunity Layer
Ranking consumes approved model outputs and evidence to produce universe-relative opportunity ordering by horizon.

Ranking never automatically equals trading. It feeds signal policy, calibration, uncertainty and risk.

## 15. Regime and Context
Regime detection is probabilistic and may be hierarchical, e.g. trend state × volatility state × liquidity state × correlation state.

Models can specialize by regime, but regime definitions and switching rules require validation.

## 16. LLM / Agent Layer
LLMs are evidence processors and research assistants, not unrestricted decision makers.

Roles include:
- event extraction
- entity linking
- contradiction synthesis
- KAP/news impact structuring
- research-question generation
- hypothesis proposal
- experiment planning
- report synthesis

Every factual claim used downstream carries source/evidence references.

## 17. Research Brain
The research scheduler continuously builds a research backlog from:
- model degradation
- unexplained residuals
- new source availability
- new regimes
- failed predictions
- feature interactions
- event clusters
- human research requests

Research experiments run in isolated environments and register results whether successful or failed.

## 18. Governance Brain
Governance independently runs:
- schema/contract validation
- leakage tests
- point-in-time checks
- reproducibility
- OOS metric recomputation
- multiple-testing controls
- stress tests
- cost/execution validation
- promotion gates
- audit verification

## 19. Champion / Challenger Registry
Every model artifact has lifecycle state:
RESEARCH -> VALIDATED -> SHADOW -> CHALLENGER -> PAPER-ELIGIBLE -> CHAMPION -> DEGRADED -> RETIRED/QUARANTINED.

Transitions are evented and auditable.

## 20. Paper Trading Operating System
Persistent components:
- virtual accounts
- cash ledger
- order ledger
- fill simulator
- positions
- corporate actions
- fees
- realized/unrealized P&L
- equity snapshots
- exposure/risk snapshots
- decision links

Execution simulation supports spread/slippage/liquidity/timing and evolves as data quality improves.

## 21. Risk Architecture
Risk is independent of model confidence.

Layers:
- data integrity gate
- model integrity gate
- asset liquidity gate
- position sizing
- portfolio concentration
- covariance/correlation
- volatility targeting
- turnover/cost
- drawdown controls
- daily loss controls
- kill switch

Risk output can APPROVE, REDUCE, DELAY or NO-TRADE.

## 22. Failure Detection and Safe Mode
Health monitoring covers sources, parsers, state freshness, feature drift, model drift, execution, portfolio, databases and infrastructure.

Safe mode is graded:
NORMAL -> DEGRADED -> REDUCED EXPOSURE -> NO-TRADE -> SYSTEM HALT.

## 23. Storage Roles
Target logical roles (technology can evolve):
- relational/metadata store
- analytical time-series/event store
- low-latency state/cache
- immutable object/data lake
- experiment/model registry
- vector/semantic index
- append-only audit ledger

Technology choices must follow measured needs rather than architecture theater.

## 24. Scheduling
### Market hours
Priority: ingestion, freshness, state, risk, paper execution and critical inference.

### After close
Priority: reconciliation, outcomes, attribution, data repair, daily evaluation and light retraining.

### Overnight
Priority: challenger research, broader web processing, feature discovery, robustness and historical updates.

### Weekend/idle compute
Priority: expensive research, large walk-forward studies, stress tests, graph rebuilding and archive processing.

## 25. Observability
Every stage exposes:
- event throughput
- lag/freshness
- data-quality rates
- mask rates
- source reliability
- feature health
- inference latency
- model quality/drift
- portfolio risk
- execution realism
- research queue
- governance failures

## 26. Migration Strategy From Current Repository
Current files are not trusted because they exist. Migration classifies each component as:
- KEEP: concept and implementation are sound enough to harden
- REWRITE: useful concept but invalid/incomplete implementation
- DELETE/ARCHIVE: duplicate, misleading, dead or architecture-theater code

Migration order:
1. establish contracts and constitution;
2. create one canonical runtime entry point;
3. make dependencies/infrastructure coherent;
4. rebuild point-in-time data + mask-first pipeline;
5. rebuild dataset/label/walk-forward validation;
6. establish honest baseline model and independent evaluation;
7. build persistent paper ledger/execution;
8. add governed champion/challenger;
9. expand event/KAP/web/global world model;
10. enable autonomous research only after governance is proven.

## 27. Definition of Full Autonomy
ALPHA is considered operationally autonomous when it can continuously:
OBSERVE -> VALIDATE -> UPDATE STATE -> RANK -> ESTIMATE UNCERTAINTY -> RISK -> PAPER ACT -> RECONCILE -> ATTRIBUTE -> DETECT FAILURE -> CREATE RESEARCH TASKS -> RUN ISOLATED EXPERIMENTS -> VALIDATE -> SHADOW -> PROMOTE/REJECT,

without daily human operation and without granting itself authority to bypass its constitution.
