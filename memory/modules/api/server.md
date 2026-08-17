# api/server

**Dosya:** `services/api/server.py`
**Satır:** 871

## Açıklama

ALPHA BIST — FastAPI Production Server v2.0

Endpoints:
- GET /health → Sistem sağlığı
- GET /api/market → Piyasa verisi
- GET /api/opportunities → Fırsatlar
- GET /api/portfolio → Portföy
- GET /api/decisions → Kararlar
- GET /api/learning → Öğrenme
- GET /api/signals → Sinyaller
- GET /api/features/{ticker} → Feature'lar
- GET /api/regime → Rejim durumu
- GET /api/risk → Risk metrikleri
- GET /api/notifications → Bildirimler
- GET /api/audit → Audit log
- GET /api/stats → İstatistikler
- WebSo

## Sınıflar (1)

- `ConnectionManager`

## Fonksiyonlar (2)

- `__init__()`
- `disconnect()`

## Bağlantılar

Bu modül şu modülleri kullanır:

- `core/monitoring_security`
- `core/observability`
- `core/alerting`
- `core/config`
- `learning/outcome_tracker`
- `simulation/execution_simulator`
- `portfolio/portfolio_manager`
- `ml/ranking_model`
- `intelligence/regime`
- `core/monitoring`
- `scanner/opportunity_engine`
- `core/logging`
- `ingestion/bist_universe`
- `learning/integrated_learning`
- `core/audit_log`
- `core/database_dev`
- `risk/position_sizing`
- `features/store`
- `intelligence/signal_fusion`
- `core/decision_engine`
- `core/infrastructure`

