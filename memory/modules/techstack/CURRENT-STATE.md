# Tech Stack — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** requirements.txt ve pyproject.toml karşılaştırması

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Python paketi | 30+ |
| Database | 3 (PostgreSQL, ClickHouse, SQLite) |
| ML framework | 4 (LightGBM, XGBoost, scikit-learn, PyTorch) |
| Frontend | Next.js + React |
| Container | Docker + docker-compose |
| Monitoring | Prometheus + structlog |
| LLM | Ollama (local) |

---

## Teknoloji Olgunluk Durumu

| Katman | Teknoloji | Durum | Not |
|--------|-----------|-------|-----|
| Backend | Python 3.12 | ✅ TAM | Ana dil |
| Web Framework | FastAPI ≥0.104.0 | ✅ TAM | REST API |
| ASGI Server | Uvicorn ≥0.24.0 | ✅ TAM | HTTP server |
| WebSocket | websockets ≥12.0 | ✅ TAM | Gerçek zamanlı |
| Dashboard | Next.js 14.2.0 | ✅ TAM | Web arayüzü |
| Database | PostgreSQL 16 | ✅ TAM | Ana veritabanı |
| Time-series DB | ClickHouse 24.8 | ✅ TAM | OHLCV, analytics |
| Cache | Redis 7.x | ✅ TAM | Cache, event bus |
| Dev Database | SQLite | ✅ TAM | Geliştirme ortamı |
| ML | LightGBM ≥4.1.0 | ✅ TAM | Primary model |
| ML | XGBoost ≥2.0.0 | ✅ TAM | Secondary model |
| ML | scikit-learn ≥1.3.0 | ✅ TAM | Preprocessing, metrics |
| ML (opsiyonel) | PyTorch ≥2.0.0 | ✅ TAM | LSTM, Transformer |
| Data | pandas ≥2.1.0 | ✅ TAM | DataFrame |
| Data | numpy ≥1.26.0 | ✅ TAM | Numerik hesaplama |
| Data | polars ≥0.20.0 | ✅ TAM | Hızlı DataFrame |
| Data | scipy ≥1.11.0 | ✅ TAM | İstatistik |
| Data Source | yfinance ≥0.2.28 | ✅ TAM | OHLCV verisi |
| HTTP Client | aiohttp ≥3.9.0 | ✅ TAM | Async HTTP |
| Web Scraping | BeautifulSoup4 ≥4.12.0 | ✅ TAM | HTML parsing |
| RSS | feedparser ≥6.0.10 | ✅ TAM | RSS feed |
| Logging | structlog ≥23.2.0 | ✅ TAM | Structured logging |
| Monitoring | prometheus-client ≥0.19.0 | ✅ TAM | Metrics |
| Config | pydantic-settings ≥2.1.0 | ✅ TAM | Config yönetimi |
| LLM | Ollama | ✅ TAM | Local LLM |
| LLM Model | gemma4:12b-q4_0 | ✅ TAM | Default model |

---

## Çözülen Sorunlar (2026-08-20)

1. **Eksik bağımlılıklar** — `polars`, `httpx`, `pytest-timeout` requirements.txt'e eklendi
2. **Breaking changes** — `regex=` parametresi deprecated, güncellendi

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| PyTorch opsiyonel | P2 | LSTM/Transformer deneysel |
| stable-baselines3 opsiyonel | P2 | RL agent deneysel |
| ClickHouse opsiyonel | P2 | Yoksa bazı modüller çalışamaz |
| Ollama bağımlılığı | P2 | LLM yoksa agent pipeline devre dışı |
