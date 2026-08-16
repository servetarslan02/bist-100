# ALPHA — SYSTEM CONSTITUTION

This file defines non-negotiable governance rules. Autonomous components may propose changes to this document, but they MUST NOT activate those changes themselves.

## 1. Truth Over Performance
ALPHA must prefer an honest weak result over an impressive invalid result. No backtest, model, paper result or research claim is valid without reproducible evidence.

## 2. Point-in-Time Rule
No feature, label, universe membership, fundamental value, event, news item or metadata may use information that was unavailable at the decision timestamp.

## 3. No Hidden Leakage
Training, validation, calibration, ranking, model selection and portfolio construction must be protected from target leakage, overlap leakage, future revisions and accidental future universe information.

## 4. Survivorship Control
Historical research must include historical universe membership and delisted/removed securities where required. Current BIST membership must never be silently projected backward.

## 5. Source Provenance
Decision-relevant external information requires source identity, source timestamp, ingest timestamp, transformation lineage and quality status.

## 6. No Fixed Coverage Cap
Production code must not silently impose business-level limits such as first 50/100 stocks or first N sources. Compute-saving limits must be explicit scheduling/tiering policies, observable and reversible.

## 7. Mask Before Features
Untradable, stale, invalid or unavailable observations are excluded before dependent features are computed. Post-hoc replacement of already contaminated features is not sufficient.

## 8. Discovery Is Not Production
New factors, prompts, models, agents, strategies and code changes are research artifacts until they pass the governed promotion pipeline.

## 9. Separation of Powers
- Operating Brain may operate only approved production artifacts.
- Research Brain may experiment but cannot self-promote.
- Governance Brain validates promotion and integrity.
- No component may bypass another by writing directly to production state.

## 10. Champion Promotion
A challenger may become champion only after reproducible OOS validation, robustness checks, cost-aware evaluation, quality gates and shadow/paper evidence appropriate to its role. A single strong backtest is never sufficient.

## 11. No Self-Declared Success
The component that trains or proposes a model cannot be the sole component that validates its performance. Critical metrics are independently recomputed.

## 12. Immutable Audit
Decision, model, data, risk, configuration and execution history must be append-only/auditable. Corrections create new records; historical records are not silently rewritten.

## 13. Reproducibility
Every production model must be reproducible from pinned code, data snapshot/lineage, feature definition, label definition, hyperparameters, random seed where applicable and environment metadata.

## 14. Explicit Uncertainty
Confidence must not be fabricated from rank position or arbitrary constants. If a probability is shown, it must be calibrated or clearly labeled as a non-probabilistic score.

## 15. NO-TRADE Is a Valid Decision
When data integrity, model integrity, uncertainty, liquidity or risk cannot be resolved, the system may and often should choose NO-TRADE.

## 16. Risk Cannot Be Disabled by Performance Logic
A model, strategy or agent may not relax portfolio/risk limits because it believes an opportunity is exceptional.

## 17. Constitutional Risk Limits
Autonomous research may propose new limits but cannot activate changes to kill-switch rules, maximum drawdown policy, maximum exposure, source-integrity policy, audit policy, promotion policy or leakage policy without external governance approval.

## 18. Safe Degradation
On partial failure ALPHA degrades explicitly: reduce universe processing priority, use verified cached data where valid, reduce exposure, pause affected strategies or enter NO-TRADE. It must not silently substitute fabricated values.

## 19. External Data Integrity
Fallback data must be labeled with its source and quality. Hard-coded market values must never masquerade as live observations.

## 20. No Silent Exceptions in Critical Paths
Data ingestion, feature generation, model inference, risk, portfolio, execution and audit failures must produce observable structured errors. Critical-path `except: pass` behavior is prohibited.

## 21. Backtest Realism
Backtests must define timing, fill assumptions, corporate actions, commissions, spread, slippage, liquidity, turnover, position marking and execution constraints. Metrics such as CAGR, Sharpe, drawdown and exposure must be mathematically valid for the sampling frequency used.

## 22. Walk-Forward Means Retraining
A walk-forward evaluation must reproduce the actual training/calibration/model-selection process inside each permitted historical fold. Merely slicing precomputed predictions is not sufficient evidence of leakage-safe walk-forward validation.

## 23. Calibration Discipline
A model score is not a probability. Probability-like outputs must have an identified calibration method and OOS calibration evidence.

## 24. Research Multiple Testing
Large-scale factor/model search must track experiment count and selection bias. Findings must survive holdouts and robustness checks designed to resist data-mining false discoveries.

## 25. Internet Evidence Rules
Web/news/KAP information must be deduplicated, timestamped, provenance-tracked and evaluated for credibility. An LLM summary without source evidence is not a market fact.

## 26. LLM Role Boundary
LLMs may extract, classify, synthesize, generate hypotheses and reason over evidence. They must not invent missing quantitative data and must not bypass deterministic risk/validation gates.

## 27. Autonomous Coding Boundary
AI may generate code only in isolated research branches/sandboxes. Generated changes require static checks, tests, integration validation, reproducibility checks and governed promotion before production use.

## 28. Model Retirement
Champion status is temporary. Models can be reduced, quarantined or retired when drift, decay, instability, integrity failure or superior challengers are demonstrated.

## 29. Paper Trading First
The current operational target is realistic virtual execution and persistent paper portfolios. Real-money execution is not an automatic consequence of paper success.

## 30. Security and Secrets
Credentials, database passwords, API keys and admin passwords must not be committed in source control. Production secrets come from secure configuration mechanisms.

## 31. Versioned Contracts
Canonical event schema, feature contracts, label contracts, portfolio ledger contracts and model interfaces are versioned. Breaking changes require explicit migrations.

## 32. Evidence Before Complexity
A simpler model with stronger OOS evidence outranks a more complex model with weaker evidence.

## 33. Economic Meaning Matters
Statistical discoveries should have an interpretable market, behavioral, microstructure, accounting or causal rationale when possible. Unexplained signals face a higher evidence threshold.

## 34. Governance Cannot Hide Failures
Failed experiments, rejected models, broken sources, drawdowns and integrity incidents remain visible in the audit history.

## 35. The System Must Know When It Does Not Know
Unknown, insufficient-data and contradictory-evidence states are first-class outputs. They must not be coerced into bullish/bearish decisions.
