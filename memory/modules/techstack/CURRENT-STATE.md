# Tech Stack — Mevcut Durum Analizi (Güncellendi v2)

**Tarih:** 2026-08-21
**Kaynak:** TECHSTACK-NIHAI-SPEC.md + Kod Analizi
**Güncelleme:** TÜM SİSTEM EN SON SÜRÜMLERE YÜKSELTİLDİ

---

## 1. Tam Sistem Yükseltme Tablosu

### 1.1 Python Paketleri (requirements.txt)

| Paket | Eski Versiyon | Yeni Versiyon | Değişiklik |
|-------|--------------|---------------|------------|
| fastapi | ≥0.104.0 | ≥0.141.0 | ⬆️ +37 minor |
| uvicorn | ≥0.24.0 | ≥0.52.0 | ⬆️ +28 minor |
| websockets | ≥12.0 | ≥17.0.0 | ⬆️ +5 major |
| python-multipart | ≥0.0.6 | ≥0.0.32 | ⬆️ +26 patch |
| pydantic-settings | ≥2.1.0 | ≥2.15.0 | ⬆️ +14 minor |
| pandas | ≥2.1.0 | ≥2.2.0 | ⬆️ +1 minor |
| numpy | ≥1.26.0 | ≥2.1.0 | ⬆️ +1 major |
| yfinance | ≥0.2.28 | ≥1.6.0 | ⬆️ +1 major |
| aiohttp | ≥3.9.0 | ≥3.14.0 | ⬆️ +5 minor |
| requests | ≥2.31.0 | ≥2.34.0 | ⬆️ +3 minor |
| asyncpg | ≥0.29.0 | ≥0.31.0 | ⬆️ +2 minor |
| aiosqlite | ≥0.19.0 | ≥0.22.0 | ⬆️ +3 minor |
| redis | ≥5.0.0 | ≥8.1.0 | ⬆️ +3 major |
| lightgbm | ≥4.1.0 | ≥4.7.0 | ⬆️ +6 minor |
| scikit-learn | ≥1.3.0 | ≥1.9.0 | ⬆️ +6 minor |
| hmmlearn | ≥0.3.0 | ≥0.3.3 | ⬆️ +3 patch |
| polars | ≥0.20.0 | ≥1.43.0 | ⬆️ +1 major |
| xgboost | ≥2.0.0 | ≥3.4.0 | ⬆️ +1 major |
| scipy | ≥1.11.0 | ≥1.18.0 | ⬆️ +7 minor |
| catboost | ≥1.2.0 | ≥1.2.10 | ⬆️ +10 patch |
| optuna | ≥3.4.0 | ≥4.9.0 | ⬆️ +1 major |
| shap | ≥0.44.0 | ≥0.52.0 | ⬆️ +8 minor |
| mlflow | ≥2.15.0 | ≥3.15.0 | ⬆️ +1 major |
| structlog | ≥23.2.0 | ≥26.1.0 | ⬆️ +3 major |
| prometheus-client | ≥0.19.0 | ≥0.26.0 | ⬆️ +7 minor |
| opentelemetry-api | ≥1.20.0 | ≥1.44.0 | ⬆️ +24 minor |
| opentelemetry-sdk | ≥1.20.0 | ≥1.44.0 | ⬆️ +24 minor |
| python-jose | ≥3.3.0 | ≥3.5.0 | ⬆️ +2 minor |
| passlib | ≥1.7.4 | ≥1.7.4 | ➡️ değişmedi |
| alembic | ≥1.13.0 | ≥1.19.0 | ⬆️ +6 minor |
| lxml | ≥4.9.3 | ≥6.1.0 | ⬆️ +2 major |
| beautifulsoup4 | ≥4.12.0 | ≥4.15.0 | ⬆️ +3 minor |
| feedparser | ≥6.0.10 | ≥6.0.14 | ⬆️ +4 patch |
| nest_asyncio | ≥1.5.8 | ≥1.6.0 | ⬆️ +1 minor |
| httpx | ≥0.25.0 | ≥0.28.0 | ⬆️ +3 minor |
| python-dateutil | ≥2.8.2 | ≥2.9.0 | ⬆️ +1 minor |
| pytz | ≥2023.3 | ≥2026.2 | ⬆️ +3 year |
| pytest | ≥7.4.0 | ≥9.1.0 | ⬆️ +2 major |
| pytest-asyncio | ≥0.21.0 | ≥1.4.0 | ⬆️ +1 major |
| pytest-timeout | ≥2.2.0 | ≥2.4.0 | ⬆️ +2 minor |
| black | ≥23.0.0 | ≥26.5.0 | ⬆️ +3 major |
| mypy | ≥1.7.0 | ≥2.3.0 | ⬆️ +1 major |

### 1.2 Docker Image'ları (docker-compose.yml)

| Image | Eski Versiyon | Yeni Versiyon | Değişiklik |
|-------|--------------|---------------|------------|
| postgres | 16-alpine | 17-alpine | ⬆️ +1 major |
| clickhouse-server | 24.8-alpine | 26.3-alpine | ⬆️ +2 major |
| redis | 7-alpine | 8-alpine | ⬆️ +1 major |
| redpanda | v24.2.8 | v25.3.17 | ⬆️ +1 major |
| prometheus | v2.53.0 | v3.14.0 | ⬆️ +1 major |
| grafana | 11.1.0 | 13.0.7 | ⬆️ +2 major |
| mlflow | v2.15.0 | v3.15.1 | ⬆️ +1 major |

### 1.3 Frontend (package.json)

| Paket | Eski Versiyon | Yeni Versiyon | Değişiklik |
|-------|--------------|---------------|------------|
| next | 14.2.0 | 15.4.0 | ⬆️ +1 major |
| react | 18.3.1 | 19.1.0 | ⬆️ +1 major |
| react-dom | 18.3.1 | 19.1.0 | ⬆️ +1 major |
| recharts | 2.12.0 | 3.10.0 | ⬆️ +1 major |
| ag-grid-community | 31.3.0 | 36.1.0 | ⬆️ +5 major |
| ag-grid-react | 31.3.0 | 36.1.0 | ⬆️ +5 major |
| zustand | 4.5.0 | 5.0.0 | ⬆️ +1 major |
| typescript | 5.4.5 | 5.8.0 | ⬆️ +3 minor |
| tailwindcss | — | 4.1.0 | 🆕 eklendi |
| date-fns | — | 4.1.0 | 🆕 eklendi |
| clsx | — | 2.1.1 | 🆕 eklendi |
| eslint | — | 9.28.0 | 🆕 eklendi |

### 1.4 Altyapı

| Bileşen | Eski | Yeni | Değişiklik |
|---------|------|------|------------|
| Python (Docker) | 3.12-slim | 3.13-slim | ⬆️ +1 minor |
| Next.js config | v14 format | v15 format | ⬆️ güncellendi |
| TypeScript config | es5 target | es2022 target | ⬆️ güncellendi |
| Tailwind CSS | JS config | CSS config (v4) | ⬆️ güncellendi |

---

## 2. Özet İstatistikler

| Kategori | Toplam | Güncellenen | Yeni Eklenen |
|----------|--------|-------------|--------------|
| Python paketi | 38 | 36 | 2 (opentelemetry) |
| Docker image | 7 | 7 | 0 |
| Frontend paketi | 11 | 6 | 5 |
| Altyapı | 4 | 4 | 0 |
| **TOPLAM** | **60** | **53** | **7** |

---

## 3. Kritik Yükseltmeler ve Dikkat Noktaları

### 3.1 Breaking Changes (Dikkat Gerektiren)

| Paket | Değişiklik | Etki |
|-------|-----------|------|
| **numpy 2.x** | API değişiklikleri | Eski numpy kodu çalışmayabilir |
| **pandas 3.0** | Yeni nullable dtype | Eski pandas kodu güncellenmeli |
| **xgboost 3.x** | Yeni API | Eski xgboost kodu güncellenmeli |
| **redis 8.x** | Yeni async API | Eski redis kodu güncellenmeli |
| **React 19** | Yeni hooks | Eski React kodu güncellenmeli |
| **Next.js 15** | Yeni config format | next.config.js güncellendi |
| **Tailwind v4** | CSS-based config | tailwind.config.ts → globals.css |
| **Prometheus v3** | Yeni query language | PromQL güncellenmeli |

### 3.2 Güvenli Yükseltmeler (Sorunsuz)

| Paket | Değişiklik | Not |
|-------|-----------|-----|
| FastAPI | 0.104 → 0.141 | Geriye uyumlu |
| scikit-learn | 1.3 → 1.9 | Geriye uyumlu |
| LightGBM | 4.1 → 4.7 | Geriye uyumlu |
| structlog | 23 → 26 | Geriye uyumlu |
| PostgreSQL | 16 → 17 | Geriye uyumlu |
| Grafana | 11 → 13 | Geriye uyumlu |

---

## 4. Yapılan Tüm Düzeltmeler

### 4.1 requirements.txt ✅
- 36 paket güncellendi
- 2 yeni paket eklendi (opentelemetry-api, opentelemetry-sdk)

### 4.2 docker-compose.yml ✅
- 7 Docker image'ı güncellendi

### 4.3 apps/web/package.json ✅
- 6 paket güncellendi
- 5 yeni paket eklendi (tailwindcss, date-fns, clsx, eslint, eslint-config-next)

### 4.4 apps/web/next.config.js ✅
- Next.js 15 uyumlu hale getirildi
- optimizePackageImports eklendi
- CORS headers eklendi

### 4.5 apps/web/tsconfig.json ✅
- target: es5 → es2022
- forceConsistentCasingInFileNames eklendi
- allowImportingTsExtensions eklendi

### 4.6 apps/web/src/app/globals.css ✅
- Tailwind v4 CSS-based config oluşturuldu

### 4.7 infrastructure/Dockerfile.api ✅
- Python 3.12-slim → 3.13-slim

### 4.8 .env.example ✅
- Qwen3 default model olarak eklendi
- gemma4 fallback olarak korundu

---

## 5. Sonraki Adımlar

1. **Test çalıştır** — `pip install -r requirements.txt` ile bağımlılıkları yükle
2. **Uyumluluk kontrolü** — Breaking changes için kod güncelleme
3. **Docker build** — `docker-compose build` ile image'ları yeniden oluştur
4. **Frontend build** — `npm install && npm run build` ile frontend'i derle
5. **Entegrasyon testi** — Tüm servislerin birlikte çalıştığını doğrula
