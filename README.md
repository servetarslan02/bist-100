# ALPHA BIST — Market Intelligence & Quant Engine

> BIST'teki 800+ hisseyi 7/24 tarayan, otonom piyasa zekâsı platformu.

## 📋 Proje Durumu

**Mimari Versiyon:** 1.0 — Kilitli  
**Aşama:** Tasarım tamamlandı, implementasyona geçilebilir.

## 🏗️ Mimari Özet

```
Kaynaklar → Adapterler → Redpanda → Realtime State + ClickHouse + Parquet
                         ↓
              Feature Engine → ML Ensemble → Gemma 4 12B
                         ↓
              Regime → Strategy → Opportunity → Simulation
                         ↓
              Risk Gate → Decision → Paper/Execution
                         ↓
              Outcome → Attribution → Learning → Model Validation
```

## 🛠️ Teknoloji Stack

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python + FastAPI |
| Frontend | Next.js + TypeScript + Tailwind |
| Event Bus | Redpanda |
| OLTP | PostgreSQL |
| OLAP | ClickHouse |
| Cache | Redis |
| Data Lake | Parquet + DuckDB |
| ML | LightGBM + XGBoost + PyTorch |
| LLM | Gemma 4 12B Q4_0 (Ollama) |
| Model Registry | MLflow |
| Monitoring | Prometheus + Grafana |

## 📁 Dosyalar

- `bist100.md` — Orijinal AI konuşma kaydı (269KB)
- `ALPHA-ARCHITECTURE.md` — Nihai teknik mimarî spesifikasyon v1.0

## 🎯 Geliştirme Aşamaları

### MVP (~4-6 hafta)
- BIST delayed data + KAP + TCMB EVDS
- PostgreSQL + ClickHouse + Redis + Redpanda
- Temel feature engine + LightGBM baseline
- Gemma 4 12B reasoning
- Backtest + paper trading
- Dashboard skeleton

### V1 (~3-4 ay)
- 800+ asset coverage
- Tüm finansal motorlar
- World Intelligence + Knowledge Graph
- SPEC Engine + Regime Engine
- Scenario Lab + Walk-forward validation
- Learning Engine

### V2 (~6-12 ay)
- Lisanslı real-time feed
- Broker API entegrasyonu
- Kontrollü otomatik execution
- LLM LoRA fine-tuning

## ⚠️ Yasal Uyarı

Bu sistem yatırım tavsiyesi vermez. Üretilen sinyaller ve tahminler yalnızca araştırma amaçlıdır. Gerçek para ile işlem yapmadan önce kapsamlı test ve doğrulama gereklidir.

---

*Başlangıç: 14 Ağustos 2026*
