# Core — Temel Altyapı

**Modül sayısı:** 52

**Bağlandığı katmanlar:**
- Ingestion — Veri Toplama
- Features — Özellik Hesaplama
- Intelligence — Analiz ve Tahmin

**Bu katmanı kullananlar:**
- Risk — Risk Yönetimi
- Portfolio — Portföy Yönetimi
- Learning — Öğrenme Sistemi
- ML — Makine Öğrenmesi
- Backtest — Geriye Dönük Test
- Scanner — Tarama Motoru
- API — Arayüz

## Modüller

| Modül | Satır | Sınıf | Fonksiyon | Açıklama |
|-------|-------|-------|-----------|----------|
| [alert_policy](alert_policy.md) | 806 | 5 | 44 | ALPHA BIST — Alert Policy Configuration v3.0 |
| [alerting](alerting.md) | 863 | 15 | 70 | ALPHA BIST — Alerting System v3.0 |
| [algo_notification](algo_notification.md) | 15 | 0 | 0 | ALPHA BIST — Algo Trading Notification (SPK). |
| [async_http](async_http.md) | 144 | 1 | 1 | ALPHA BIST — Async HTTP Client Utility |
| [audit_log](audit_log.md) | 277 | 2 | 13 | ALPHA BIST — Audit Log v1.0 |
| [broker](broker.md) | 143 | 5 | 11 | ALPHA BIST — Broker Abstraction v1.0 |
| [canonical_scoring](canonical_scoring.md) | 741 | 3 | 19 | ALPHA BIST — Canonical Scoring Pipeline v1.0 |
| [circuit_breaker](circuit_breaker.md) | 383 | 6 | 14 | ALPHA BIST — Circuit Breaker & Rate Limiter v1.0 |
| [compliance](compliance.md) | 105 | 2 | 3 | ALPHA BIST — SPK Compliance |
| [config](config.md) | 190 | 1 | 7 | ALPHA BIST - Configuration Management v2.0 |
| [config_loader](config_loader.md) | 198 | 1 | 17 | ALPHA BIST — Config Loader with Environment Override |
| [config_watcher](config_watcher.md) | 224 | 2 | 7 | ALPHA BIST — Config Hot Reload Watcher |
| [data_quality](data_quality.md) | 231 | 5 | 12 | ALPHA BIST — Data Quality & Tradability Mask v1.0 |
| [data_quality_v2](data_quality_v2.md) | 301 | 3 | 13 | ALPHA BIST — Data Quality v2.0 [DEPRECATED → data_quality.py'ye birleştirildi] |
| [database](database.md) | 343 | 0 | 0 | ALPHA BIST — Database Connections v2.0 (Production-Hardened) |
| [database_dev](database_dev.md) | 336 | 1 | 3 | ALPHA BIST — Development Database Adapter |
| [db_lock](db_lock.md) | 587 | 3 | 18 | ALPHA BIST — Database-Agnostic Lock Abstraction v2.0 |
| [decision_engine](decision_engine.md) | 471 | 4 | 15 | ALPHA BIST — Decision Engine v2.0 (Düzeltilmiş) |
| [event_bus](event_bus.md) | 396 | 3 | 7 | ALPHA BIST - Event Bus v1.3 (Push-Based Internal Architecture) |
| [event_schema](event_schema.md) | 208 | 10 | 4 | ALPHA BIST - Canonical Event Schema v1.1 |
| [fee_calculator](fee_calculator.md) | 94 | 2 | 3 | ALPHA BIST — Fee Calculator |
| [grafana_provisioning](grafana_provisioning.md) | 266 | 4 | 4 | ALPHA BIST — Grafana Provisioning |
| [gross_settlement](gross_settlement.md) | 77 | 2 | 8 | ALPHA BIST — Gross Settlement Monitor |
| [halt_monitor](halt_monitor.md) | 85 | 2 | 7 | ALPHA BIST — Halt Monitor |
| [infrastructure](infrastructure.md) | 296 | 9 | 27 | ALPHA BIST — Event Infrastructure v1.0 |
| [insider_detector](insider_detector.md) | 31 | 2 | 1 | ALPHA BIST — Insider Trading Detector. |
| [logging](logging.md) | 37 | 0 | 0 | ALPHA BIST - Structured Logging |
| [manipulation_detector](manipulation_detector.md) | 48 | 2 | 4 | ALPHA BIST — Manipulation Detector (SPK Uyumlu). |
| [market_calendar](market_calendar.md) | 236 | 3 | 11 | ALPHA BIST — Market Calendar v1.0 |
| [market_session](market_session.md) | 150 | 2 | 11 | ALPHA BIST — Market Session Manager |
| [model_persistence](model_persistence.md) | 201 | 1 | 0 | ALPHA BIST — Model Persistence v1.0 |
| [models](models.md) | 408 | 20 | 6 | ALPHA BIST - Data Models & Schemas |
| [monitoring](monitoring.md) | 216 | 1 | 2 | ALPHA BIST — Portfolio & Lock Monitoring Integration |
| [monitoring_security](monitoring_security.md) | 369 | 8 | 15 | ALPHA BIST — Monitoring Security |
| [observability](observability.md) | 372 | 7 | 32 | ALPHA BIST — Observability & Monitoring v1.0 |
| [orchestrator](orchestrator.md) | 424 | 1 | 3 | ALPHA BIST — Master Orchestrator v1.0 |
| [pit_store](pit_store.md) | 160 | 2 | 8 | ALPHA BIST — Point-in-Time Store v1.0 |
| [price_limits](price_limits.md) | 109 | 2 | 4 | ALPHA BIST — Price Limits |
| [production_metrics](production_metrics.md) | 154 | 3 | 11 | ALPHA BIST — Production Metrics v1.0 |
| [reconciliation](reconciliation.md) | 268 | 2 | 6 | ALPHA BIST — Cross-Source Reconciliation v1.0 |
| [recovery](recovery.md) | 190 | 4 | 15 | ALPHA BIST — Recovery & Resilience v1.0 |
| [regime_detector](regime_detector.md) | 270 | 2 | 4 | ALPHA BIST — Regime Detector v3.0 |
| [reporting](reporting.md) | 19 | 0 | 0 | ALPHA BIST — Daily Report Generator. |
| [risk_gate](risk_gate.md) | 180 | 2 | 5 | ALPHA BIST — Risk Gate v1.0 |
| [security](security.md) | 260 | 8 | 16 | ALPHA BIST — Security & Governance v1.0 |
| [short_selling](short_selling.md) | 112 | 2 | 6 | ALPHA BIST — Short Selling Monitor |
| [state_recovery](state_recovery.md) | 216 | 1 | 4 | ALPHA BIST — State Recovery v2.0 |
| [streaming_anomaly](streaming_anomaly.md) | 204 | 2 | 6 | ALPHA BIST — Streaming Anomaly Detector v1.0 |
| [tax](tax.md) | 33 | 1 | 0 | ALPHA BIST — Tax Calculator. |
| [tradability_mask](tradability_mask.md) | 210 | 2 | 4 | ALPHA BIST — Tradability Mask v1.0 |
| [viop_monitor](viop_monitor.md) | 102 | 2 | 5 | ALPHA BIST — VIOP Monitor |
| [worker](worker.md) | 331 | 3 | 3 | ALPHA BIST — Job Worker v1.0 |
