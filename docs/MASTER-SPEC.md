# ALPHA — MASTER SYSTEM SPEC

## Status
This document is the primary product/system vision for ALPHA. If older roadmap, architecture or correction documents conflict with this file, this file wins unless SYSTEM-CONSTITUTION.md states otherwise.

## Mission
ALPHA is not a stock-picking bot and is not limited to BIST 100. It is an autonomous, governed financial research, market-intelligence, ranking, simulation and virtual-portfolio operating system.

Its objective is to continuously observe markets and the information environment, represent the current state of the world and assets, discover and test hypotheses, rank opportunities probabilistically, manage uncertainty and risk, operate a persistent paper portfolio, evaluate outcomes, detect failure and improve through controlled research.

## Scope Principle: No Fixed Coverage Cap
ALPHA MUST NOT contain a product-level hard cap such as first 50 stocks, first 100 stocks, BIST 100 only, first N news items, or a fixed global source count.

Target coverage is:
- the full currently available Borsa Istanbul security universe, including historical/delisted instruments where required for bias-safe research;
- BIST indices, sectors, peer groups and related Turkish instruments;
- KAP disclosures and issuer events;
- Turkish macroeconomic, regulatory and policy information;
- global macroeconomic data;
- global equities, indices, rates, FX, commodities, credit/risk proxies and other variables relevant to Turkish assets;
- company, sector, supply-chain, customer, competitor and ownership relationships;
- open-web news and public information sources that can legally and technically be accessed;
- licensed/contracted feeds when available;
- structured and unstructured historical datasets used for research and validation.

No fixed universe cap does NOT mean every source receives equal compute at every moment. ALPHA uses adaptive prioritization, tiered processing and compute budgets while preserving discovery coverage.

## Core Operating Principle
The primary question is not:

> Will ticker X rise tomorrow?

It is:

> Given the current world state, market regime, sector state, asset state, information state, liquidity, execution constraints and uncertainty, which assets offer the strongest risk-adjusted opportunity relative to the available universe over each relevant horizon?

## Three Brains
### 1. Operating Brain
Responsible for live observation, state updates, ranking, risk, paper execution, portfolio management, performance measurement and safe-mode behavior.

### 2. Research Brain
Responsible for hypothesis generation, feature/factor discovery, model research, robustness testing, causal/counterfactual research, strategy discovery and challenger creation.

### 3. Governance Brain
Responsible for preventing self-deception and unsafe promotion. It independently verifies data lineage, leakage protection, OOS performance, reproducibility, risk policy, promotion rules and audit integrity.

The Research Brain MUST NOT promote itself. The Operating Brain MUST NOT rewrite governance rules. The Governance Brain MUST NOT fabricate research results.

## Information Universe
ALPHA treats the internet and market data ecosystem as a continuously changing information graph, not as a small list of RSS feeds.

Information acquisition should support:
- source registry and provenance;
- source credibility history;
- deduplication and canonical event formation;
- multilingual extraction;
- entity resolution;
- novelty detection;
- contradiction detection;
- event timing and source timing;
- information decay;
- affected-asset inference;
- global-to-local propagation;
- evidence linking and replay.

Every externally derived fact that can affect a decision must be traceable to its source and timestamp.

## World Model
ALPHA maintains dynamic state at multiple levels:
- global world state;
- Turkey macro/policy state;
- BIST market state;
- sector state;
- company/asset state;
- portfolio state;
- model/research state;
- data-quality state.

Events can propagate through a dynamic graph:
EVENT -> ENTITY -> GLOBAL/MACRO FACTOR -> COUNTRY -> SECTOR -> COMPANY -> ASSET -> PORTFOLIO.

This graph is evidence-based, versioned and learnable. Hard-coded rules may bootstrap the system but must not be treated as permanent truth.

## Core Intelligence Engines
The initial evidence families include but are not limited to:
1. Relative Strength
2. Momentum + Trend
3. Volume + Microstructure
4. Fundamental / FCF / Quality / Growth / Value
5. KAP + News
6. Catalyst
7. Why Is It Falling?
8. Mean Reversion
9. Seasonality

The system may discover new engines/factors. New discoveries remain research artifacts until governed validation promotes them.

## Cross-Sectional First
Assets are evaluated within the complete eligible universe and relevant peer sets. Features, labels, ranks, dispersion and relative performance are point-in-time and universe-aware.

## Time Horizons
ALPHA is multi-horizon. Separate targets/models/decision logic may exist for intraday (where data supports it), 1-5D, 1-4W, 1-6M and longer research horizons. A single score must not silently mix incompatible horizons.

## Model Philosophy
Ranking is a primary mechanism, not a dogma. Learning-to-rank, calibrated classification, regression, survival/hazard models, anomaly detection, state-space models, ensembles and specialist models may all be used when justified by out-of-sample evidence.

No model is trusted because of its name or complexity.

## Research Lifecycle
Every new model, feature or strategy follows:
IDEA -> ECONOMIC/BEHAVIORAL RATIONALE -> DATA CONTRACT -> POINT-IN-TIME DATASET -> TRAIN -> PURGED/EMBARGOED OOS -> ROBUSTNESS -> COST/EXECUTION TEST -> QUALITY GATE -> SHADOW -> CHALLENGER -> PAPER EVIDENCE -> PROMOTE/REJECT/RETIRE.

Discovery is never production.

## Self-Learning
ALPHA learns from:
- prediction outcomes;
- ranking quality;
- portfolio outcomes;
- execution outcomes;
- regime-conditioned performance;
- data/source reliability;
- feature/model drift;
- research experiment history.

Self-learning means controlled model/data/research evolution. It does not mean arbitrary self-modification of constitutional rules.

## Uncertainty
ALPHA separately estimates where possible:
- data uncertainty;
- model uncertainty;
- regime uncertainty;
- event interpretation uncertainty;
- execution uncertainty;
- portfolio uncertainty.

Low evidence or high uncertainty must be allowed to produce NO-TRADE.

## Paper-First Operating Model
Real-money execution is outside the current system objective. The production target is persistent, live-data paper trading with realistic simulation of commissions, spread, slippage, liquidity, timing, turnover, partial fills where possible and market impact approximations where justified.

The paper portfolio persists across restarts and maintains immutable history.

## Persistent Audit and Reproducibility
Every decision must be reproducible from versioned artifacts including:
- source/event IDs and timestamps;
- universe snapshot;
- data-quality/mask state;
- feature-set and feature version;
- label definition;
- model artifact and model version;
- code commit;
- configuration hash;
- regime/state snapshot;
- score/rank/calibration;
- risk decision;
- order/execution simulation;
- outcome and attribution.

## Failure-Aware Autonomy
ALPHA must detect and classify failures such as:
- source outage or stale data;
- contradictory sources;
- distribution shift;
- feature drift;
- model decay;
- regime mismatch;
- execution anomaly;
- portfolio drawdown;
- data integrity failure;
- leakage or reproducibility failure.

The default response to unresolved integrity uncertainty is degraded operation, reduced exposure or NO-TRADE—not invented confidence.

## Success Definition
ALPHA is successful when it can run for years with minimal daily human intervention while producing independently verifiable evidence that:
- data is point-in-time and traceable;
- research is reproducible;
- OOS testing is honest;
- live paper results survive realistic costs;
- model promotion is governed;
- risk failures trigger protection;
- new research improves the system only after proof;
- the system can explain what it knows, what it does not know, and why it acted.
