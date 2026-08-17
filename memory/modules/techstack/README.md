# Tech Stack — Teknoloji Altyapısı

**Amaç:** Kullandığımız tüm teknolojiler, versiyonlar ve bağımlılıklar.

## Mevcut Teknoloji Stack

| Katman | Teknoloji | Versiyon | Amaç |
|--------|-----------|----------|------|
| **Backend** | Python | 3.12 | Ana dil |
| **Web Framework** | FastAPI | ≥0.104.0 | REST API |
| **ASGI Server** | Uvicorn | ≥0.24.0 | HTTP server |
| **WebSocket** | websockets | ≥12.0 | Gerçek zamanlı iletişim |
| **Dashboard** | Next.js | 14.2.0 | Web arayüzü |
| **Frontend** | React | 18.3.1 | UI component |
| **Database** | PostgreSQL | 16 | Ana veritabanı |
| **Time-series DB** | ClickHouse | 24.8 | OHLCV, analytics |
| **Cache** | Redis | 7.x | Cache, event bus |
| **Dev Database** | SQLite | — | Geliştirme ortamı |
| **ML** | LightGBM | ≥4.1.0 | Primary model |
| **ML** | XGBoost | ≥2.0.0 | Secondary model |
| **ML** | scikit-learn | ≥1.3.0 | Preprocessing, metrics |
| **ML (opsiyonel)** | PyTorch | ≥2.0.0 | LSTM, Transformer |
| **ML (opsiyonel)** | stable-baselines3 | ≥2.1.0 | RL agent |
| **Data** | pandas | ≥2.1.0 | DataFrame |
| **Data** | numpy | ≥1.26.0 | Numerik hesaplama |
| **Data** | polars | ≥0.20.0 | Hızlı DataFrame |
| **Data** | scipy | ≥1.11.0 | İstatistik |
| **Data Source** | yfinance | ≥0.2.28 | OHLCV verisi |
| **HTTP Client** | aiohttp | ≥3.9.0 | Async HTTP |
| **HTTP Client** | requests | ≥2.31.0 | Sync HTTP |
| **Web Scraping** | BeautifulSoup4 | ≥4.12.0 | HTML parsing |
| **Web Scraping** | lxml | ≥4.9.3 | XML/HTML |
| **RSS** | feedparser | ≥6.0.10 | RSS feed |
| **Logging** | structlog | ≥23.2.0 | Structured logging |
| **Monitoring** | prometheus-client | ≥0.19.0 | Metrics |
| **Config** | pydantic-settings | ≥2.1.0 | Config yönetimi |
| **Serialization** | pydantic | ≥2.0.0 | Data validation |
| **Async** | asyncio | built-in | Async programming |
| **Date** | python-dateutil | ≥2.8.2 | Tarih işlemleri |
| **Timezone** | pytz | ≥2023.3 | Zaman dilimi |
| **LLM** | Ollama | — | Local LLM |
| **LLM Model** | gemma4:12b-q4_0 | — | Default model |
| **Container** | Docker | — | Containerization |
| **Container** | docker-compose | — | Multi-container |
| **Test** | pytest | ≥7.4.0 | Test framework |
| **Test** | pytest-asyncio | ≥0.21.0 | Async test |
| **HTTP Test** | httpx | ≥0.25.0 | API test |
| **Code Quality** | black | ≥23.0.0 | Formatter |
| **Code Quality** | mypy | ≥1.7.0 | Type checker |

## Toplam

| Kategori | Sayı |
|----------|------|
| Python paketi | 30+ |
| Database | 3 (PostgreSQL, ClickHouse, SQLite) |
| ML framework | 4 (LightGBM, XGBoost, scikit-learn, PyTorch) |
| Frontend | Next.js + React |
| Container | Docker + docker-compose |
| Monitoring | Prometheus + structlog |
| LLM | Ollama (local) |
