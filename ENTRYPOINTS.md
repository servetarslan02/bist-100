# ALPHA BIST — Entry Points Rehberi

> **Kural:** Her servisin tek bir canonical entry point'i vardır.

## 📋 Entry Points

| Entry Point | Amaç | Port | Kullanım |
|------------|------|------|----------|
| `main.py` | Ana CLI (daily/backtest/paper/learning) | — | `python main.py --mode daily` |
| `services/api/app.py` | **Canonical** production API | 8000 | `uvicorn services.api.app:app` |
| `apps/api/main.py` | Standalone FastAPI (farklı endpoint'ler) | 8001 | `uvicorn apps.api.main:app` |
| `services/features/main.py` | Feature Engine microservice | — | `python -m services.features.main` |
| `services/ingestion/main.py` | Data Ingestion microservice | — | `python -m services.ingestion.main` |
| `services/intelligence/main.py` | Intelligence microservice | — | `python -m services.intelligence.main` |

## ⚠️ Deprecated

| Entry Point | Durum | Alternatif |
|------------|-------|-----------|
| `services/api/server.py` | DEPRECATED | `services/api/app.py` |
| `start.py` | Silindi | `main.py` |
| `run_system.py` | Silindi | `main.py` |

## 🚀 Hızlı Başlangıç

```bash
# Sistem sağlık kontrolü
python main.py --mode health

# Günlük pipeline
python main.py --mode daily

# Backtest
python main.py --mode backtest --start 2020-01-01 --end 2024-01-01

# API server
uvicorn services.api.app:app --host 0.0.0.0 --port 8000
```
