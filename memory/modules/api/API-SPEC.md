# API Sistem Dokümanı — Endpoint ve Entegrasyon Rehberi

**Tarih:** 2026-08-18

---

## 1. Mevcut Durum

### API Dosyaları
```
services/api/
├── main.py        (716 satır) — Ana API server (FastAPI)
├── server.py      (871 satır) — Dashboard server (HTML + API)
└── websocket.py   (242 satır) — WebSocket server
```

### İki Ayrı Server Var
- `main.py` → Backend API (port 8001)
- `server.py` → Dashboard + API (port 8000)

---

## 2. Endpoint Listesi

### 2.1 main.py Endpoint'leri (Backend API)

| Method | Endpoint | Açıklama | Servis Bağlantısı |
|--------|----------|----------|-------------------|
| GET | `/api/health` | Sağlık kontrolü | core/infrastructure |
| GET | `/api/status` | Sistem durumu | Tüm servisler |
| GET | `/api/market/state` | Piyasa durumu | market_state, features |
| GET | `/api/market/instruments` | Tüm hisseler | ingestion/bist_universe |
| GET | `/api/market/instrument/{ticker}/ohlcv` | OHLCV verisi | ingestion/yfinance |
| GET | `/api/market/instrument/{ticker}/full` | Tam analiz | intelligence/main |
| GET | `/api/market/instrument/{ticker}` | Hisse detay | intelligence, features |
| GET | `/api/signals` | Sinyaller | intelligence/signal_fusion |
| GET | `/api/portfolio` | Portföy | portfolio/main |
| GET | `/api/world/state` | World state | intelligence/world_state |
| GET | `/api/features/{ticker}` | Feature'lar | features/calculator |
| GET | `/api/events` | Event'ler | core/event_bus |
| GET | `/api/models` | ML modelleri | ml/ranking_model |
| GET | `/api/alerts` | Alarmlar | core/alerting |
| WS | `/ws/{channel}` | WebSocket kanalı | websocket |
| WS | `/ws/live` | Canlı veri | websocket |
| GET | `/api/stream/events` | Event stream | core/event_bus |

### 2.2 server.py Endpoint'leri (Dashboard)

| Method | Endpoint | Açıklama | Servis Bağlantısı |
|--------|----------|----------|-------------------|
| GET | `/` | Dashboard HTML | frontend |
| GET | `/health` | Sağlık | core/infrastructure |
| GET | `/api/market` | Piyasa verisi | market_state |
| GET | `/api/opportunities` | Fırsatlar | scanner/opportunity_engine |
| GET | `/api/portfolio` | Portföy | portfolio/main |
| GET | `/api/decisions` | Kararlar | core/decision_engine |
| GET | `/api/learning` | Öğrenme istatistikleri | learning/main |
| GET | `/api/learning/predictions` | Tahminler | learning/outcome_tracker |
| GET | `/api/signals` | Sinyaller | intelligence/signal_fusion |
| GET | `/api/features/{ticker}` | Feature'lar | features/calculator |
| GET | `/api/regime` | Rejim | intelligence/regime |
| GET | `/api/risk` | Risk | risk/main |
| GET | `/api/notifications` | Bildirimler | core/alerting |
| GET | `/api/audit` | Audit log | core/audit_log |
| GET | `/api/stats` | İstatistikler | core/observability |
| GET | `/api/tickers` | Hisse listesi | ingestion/bist_universe |
| WS | `/ws` | WebSocket | websocket |
| GET | `/health/detailed` | Detaylı sağlık | core/infrastructure |
| GET | `/metrics` | Prometheus metrics | core/production_metrics |
| GET | `/admin/lock-metrics` | Lock metrikleri | core/db_lock |

---

## 3. Eksik Endpoint'ler

### Plan'da Var Ama Kodda Yok

| Endpoint | Açıklama | Gerekli Servis |
|----------|----------|----------------|
| `POST /api/scenarios` | Senaryo çalıştır | intelligence/scenario |
| `GET /api/scenarios/{id}` | Senaryo sonucu | intelligence/scenario |
| `POST /api/backtests` | Backtest başlat | backtest/engine |
| `GET /api/backtests/{id}` | Backtest sonucu | backtest/engine |
| `GET /api/risk/portfolio` | Portföy risk | risk/enhanced_risk |
| `GET /api/risk/{decision_id}` | Karar risk | risk/main |
| `POST /api/decisions` | Karar oluştur | core/decision_engine |
| `GET /api/decisions/{id}` | Karar detay | core/decision_engine |
| `GET /api/universe` | BIST evreni | ingestion/bist_universe |
| `GET /api/universe/{ticker}` | Hisse bilgisi | ingestion/bist_universe |
| `GET /api/sectors` | Sektörler | features/cross_sectional |
| `POST /api/orders` | Emir oluştur | simulation/execution_simulator |
| `GET /api/orders/{id}` | Emir detay | simulation/execution_simulator |
| `GET /api/positions` | Pozisyonlar | portfolio/main |
| `GET /api/trades` | İşlem geçmişi | portfolio/main |
| `GET /api/pnl` | P&L | portfolio/main |
| `GET /api/agents` | Agent durumu | agents/agent_system |
| `GET /api/agents/{role}/results` | Agent sonuçları | agents/agent_system |
| `GET /api/learning/drift` | Drift tespiti | learning (yok) |
| `GET /api/learning/attribution` | Performans attribüsyonu | learning/attribution |
| `GET /api/models/{id}` | Model detay | ml/ranking_model |
| `GET /api/models/performance` | Model performansı | ml/ranking_model |

---

## 4. WebSocket Kanalları

### Mevcut Kanallar

| Kanal | İçerik | Güncelleme |
|-------|--------|------------|
| `/ws/market` | Piyasa verisi | Tick bazlı |
| `/ws/opportunities` | Fırsatlar | Event bazlı |
| `/ws/portfolio` | Portföy | İşlem bazlı |
| `/ws/risk` | Risk | Alert bazlı |
| `/ws/system` | Sistem durumu | Periyodik |
| `/ws/live` | Canlı akış | Gerçek zamanlı |
| `/ws/events` | Event stream | Event bazlı |

---

## 5. Servis Bağlantı Haritası

### main.py Servis Kullanımı

```python
# main.py'de import edilen servisler:
from services.core.config import settings
from services.core.database import init_databases, close_databases, ...
from services.core.event_bus import ensure_topics, publish_event, EventConsumer
from services.core.logging import setup_logging
from services.ingestion.bist_universe import bist_universe
from services.features.calculator import feature_calculator
from services.intelligence.world_state import world_state_manager
from services.intelligence.spec_engine import spec_engine
from services.intelligence.signal_fusion import SignalFusionEngine
from services.intelligence.regime import regime_engine
from services.intelligence.forecasting import ForecastingEngine
from services.intelligence.monte_carlo import MonteCarloEngine
from services.intelligence.knowledge_graph import KnowledgeGraph
from services.intelligence.research_memory import ResearchMemory
from services.intelligence.evidence_engine import EvidenceVerificationEngine
from services.intelligence.factor_engine import FactorEngine
from services.intelligence.impact_engine import ImpactEngine
from services.intelligence.macro_sensitivity import MacroSensitivityEngine
from services.intelligence.trade_planner import TradePlanner
from services.intelligence.analysis_engines import ...
from services.intelligence.news_pipeline import NewsPipeline
from services.core.decision_engine import DecisionEngine
from services.core.risk_gate import RiskGate
from services.risk.position_sizing import PositionSizer
from services.core.compliance import compliance_checker
from services.core.short_selling import short_selling_monitor
from services.core.halt_monitor import halt_monitor
from services.portfolio.portfolio_manager import PortfolioManager, CommissionModel
from services.learning.outcome_tracker import OutcomeTracker
from services.learning.integrated_learning import IntegratedLearningSystem
from services.features.macro import compute_all_macro_features
from services.intelligence.factor_engine import compute_financial_scores
from services.intelligence.impact_engine import analyze_event_impact
```

### server.py Servis Kullanımı

```python
# server.py'de import edilen servisler:
from services.core.config import settings
from services.core.monitoring import monitoring_auth
from services.core.production_metrics import metrics_collector
from services.core.db_lock import get_lock_metrics, get_all_metrics, get_health_report
from services.portfolio.portfolio_manager import PortfolioManager, CommissionModel
from services.portfolio.main import PortfolioService
from services.core.decision_engine import DecisionEngine
from services.intelligence.signal_fusion import SignalFusionEngine
from services.intelligence.regime import regime_engine
from services.intelligence.world_state import world_state_manager
from services.intelligence.knowledge_graph import KnowledgeGraph
from services.intelligence.research_memory import ResearchMemory
from services.intelligence.evidence_engine import EvidenceVerificationEngine
from services.risk.main import RiskEngine
from services.learning.main import LearningService
from services.scanner.opportunity_engine import OpportunityDiscoveryEngine
from services.features.calculator import feature_calculator
from services.features.store import FeatureStore
from services.ingestion.bist_universe import bist_universe
```

---

## 6. Eksik Entegrasyonlar

### API'de Kullanılmayan Servisler

| Servis | Neden Kullanılmalı |
|--------|-------------------|
| `intelligence/monte_carlo.py` | `/api/scenarios` endpoint'inde |
| `intelligence/scenario.py` | `/api/scenarios` endpoint'inde |
| `intelligence/probability.py` | `/api/instrument/{ticker}/forecast` endpoint'inde |
| `intelligence/prediction_layer.py` | `/api/predictions` endpoint'inde |
| `intelligence/kap_llm_extractor.py` | `/api/events` endpoint'inde |
| `intelligence/pipeline.py` | `/api/intelligence` endpoint'inde |
| `risk/enhanced_risk.py` | `/api/risk/portfolio` endpoint'inde |
| `risk/calibration.py` | `/api/models/calibration` endpoint'inde |
| `risk/reconciliation.py` | `/api/portfolio/reconciliation` endpoint'inde |
| `learning/attribution.py` | `/api/learning/attribution` endpoint'inde |
| `learning/continuous_learning.py` | `/api/learning/status` endpoint'inde |
| `learning/super_intelligence.py` | `/api/learning/evolution` endpoint'inde |
| `ml/ranking_model.py` | `/api/models` endpoint'inde detaylı |
| `ml/model_comparator.py` | `/api/models/compare` endpoint'inde |
| `ml/ensemble.py` | `/api/models/ensemble` endpoint'inde |
| `backtest/engine.py` | `/api/backtests` endpoint'inde |
| `backtest/enhanced_walk_forward.py` | `/api/backtests/walk-forward` endpoint'inde |
| `agents/agent_system.py` | `/api/agents` endpoint'inde |
| `scanner/opportunity_engine.py` | `/api/opportunities` endpoint'inde detaylı |
| `scanner/alpha_engine.py` | `/api/scanner/alpha` endpoint'inde |
| `simulation/execution_simulator.py` | `/api/orders` endpoint'inde |
| `alternative/*` | `/api/alternative` endpoint'inde |
| `macro/*` | `/api/macro` endpoint'inde |
| `factors/*` | `/api/factors` endpoint'inde |
| `event_study/*` | `/api/event-study` endpoint'inde |
| `viop/*` | `/api/viop` endpoint'inde |
| `features/technical_features.py` | `/api/features/{ticker}` endpoint'inde |
| `features/feature_selector.py` | `/api/features/select` endpoint'inde |

---

## 7. Uygulama Planı

### Faz 1: Eksik Endpoint'ler (22 yeni endpoint)
```
POST /api/scenarios
GET  /api/scenarios/{id}
POST /api/backtests
GET  /api/backtests/{id}
GET  /api/risk/portfolio
GET  /api/decisions/{id}
GET  /api/universe
GET  /api/sectors
POST /api/orders
GET  /api/positions
GET  /api/trades
GET  /api/pnl
GET  /api/agents
GET  /api/learning/attribution
GET  /api/learning/drift
GET  /api/models/{id}
GET  /api/models/compare
GET  /api/intelligence/{ticker}
GET  /api/macro
GET  /api/factors/{ticker}
GET  /api/event-study/{ticker}
GET  /api/viop
```

### Faz 2: Servis Entegrasyonu
- Tüm servisleri API'ye bağla
- Orchestrator'ı API'de kullan

### Faz 3: WebSocket Genişletme
- Agent sonuçları canlı stream
- Model performansı canlı stream
- Drift alert'leri canlı stream

### Faz 4: Güvenlik
- Rate limiting
- API key authentication
- CORS ayarları
- Input validation

---

## 8. Endpoint Sayıları

| Kategori | Mevcut | Hedef |
|----------|--------|-------|
| Market | 6 | 8 |
| Portfolio | 1 | 5 |
| Risk | 1 | 3 |
| Intelligence | 4 | 8 |
| Learning | 2 | 5 |
| Models | 1 | 4 |
| Scanner | 1 | 3 |
| Agents | 0 | 2 |
| Backtest | 0 | 3 |
| Scenario | 0 | 2 |
| Macro | 0 | 1 |
| Factors | 0 | 1 |
| Event Study | 0 | 1 |
| VIOP | 0 | 1 |
| Alternative | 0 | 1 |
| **TOPLAM** | **16** | **48** |
