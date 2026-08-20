# ALPHA BIST — Teknoloji Stack (2026)

**Tarih:** 2026-08-21
**Prensip:** "Gerektiğinde kanıtlanmış teknoloji" — fazla bağımlılık, fazla karmaşıklık yok

---

## 1. Çekirdek Stack (Şimdi)

Bu teknolojiler sisteme dahildir, kanıtlanmış ve gereklidir.

### Backend
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **FastAPI** | Async, performant, OpenAPI docs | ✅ Çekirdek |
| **Uvicorn** | En iyi ASGI server | ✅ Çekirdek |
| **ORJSON** | Hızlı JSON serializer (Rust tabanlı) | ✅ Çekirdek |
| **WebSockets** | Gerçek zamanlı iletişim | ✅ Çekirdek |

### Database
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **PostgreSQL** | ACID, JSON support, güvenilir OLTP | ✅ Çekirdek |
| **ClickHouse** | Time-series analytics, columnar storage | ✅ Çekirdek |
| **Redis** | Cache, event bus, sub-ms latency | ✅ Çekirdek |
| **SQLAlchemy** | ORM, Alembic ile uyumlu | ✅ Çekirdek |
| **Alembic** | Schema migration | ✅ Çekirdek |

### Data Processing
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **Polars** | Hızlı DataFrame, Rust tabanlı | ✅ Çekirdek |
| **PyArrow** | Columnar format, Polars ile uyumlu | ✅ Çekirdek |
| **Pandas** | Legacy desteği (eski kod uyumluluğu) | ✅ Çekirdek |
| **NumPy** | Temel numerik hesaplama | ✅ Çekirdek |

### ML — Gradient Boosting
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **LightGBM** | Hızlı, leaf-wise growth | ✅ Çekirdek |
| **CatBoost** | Kategorik feature handling (BIST sektör/pazar) | ✅ Çekirdek |
| **XGBoost** | Esnek, regularization güçlü | ✅ Çekirdek |
| **scikit-learn** | Preprocessing, metrics, calibration | ✅ Çekirdek |

### ML — Deep Learning
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **PyTorch** | Deep learning framework | ✅ Çekirdek |

### ML — Tuning & Explainability
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **Optuna** | Hyperparameter tuning, mevcut ölçek için yeterli | ✅ Çekirdek |
| **SHAP** | Model explainability, endüstri standardı | ✅ Çekirdek |

### Monitoring & Observability
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **structlog** | Structured logging | ✅ Çekirdek |
| **Prometheus** | Metrics toplama | ✅ Çekirdek |
| **Grafana** | Monitoring dashboard | ✅ Çekirdek |
| **OpenTelemetry** | Distributed tracing | ✅ Çekirdek |

### Security
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **python-jose** | JWT token | ✅ Çekirdek |
| **passlib** | Password hashing (bcrypt) | ✅ Çekirdek |
| **cryptography** | Encryption utilities | ✅ Çekirdek |

### Frontend
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **Next.js** | React SSR, API routes | ✅ Çekirdek |
| **React** | UI component | ✅ Çekirdek |
| **Lightweight Charts** | TradingView'ın finansal grafik kütüphanesi | ✅ Çekirdek |
| **AG Grid** | Data table (sortable, filterable, virtual scroll) | ✅ Çekirdek |
| **Zustand** | Lightweight state management | ✅ Çekirdek |
| **Recharts** | Genel amaçlı grafik | ✅ Çekirdek |

### Dev & Test
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **Ruff** | Hızlı linter (black+isort+flake8 birleşimi) | ✅ Çekirdek |
| **Pytest** | Test framework | ✅ Çekirdek |
| **Black** | Formatter | ✅ Çekirdek |
| **mypy** | Type checker | ✅ Çekirdek |

### Infrastructure
| Teknoloji | Neden Seçildi | Durum |
|-----------|--------------|-------|
| **Docker** | Containerization | ✅ Çekirdek |
| **Redpanda** | Kafka alternatifi, event streaming | ✅ Çekirdek |

---

## 2. Sonra İhtiyaç Kanıtlanırsa

Bu teknolojiler henüz eklenmedi. İhtiyaç kanıtlandığında değerlendirilecek.

| Teknoloji | Ne Zaman Eklenir | Kanıtlanması Gereken |
|-----------|-----------------|---------------------|
| **Ray Tune** | Tuning darboğaz olduğunda | Optuna'nın yetmediği durum |
| **Weights & Biases** | Tracking ihtiyacı olduğunda | MLflow'nun yetmediği durum |
| **TabNet** | DL tabular'da LightGBM'yi geçerse | OOS benchmark ile kanıt |
| **FT-Transformer** | DL tabular'da LightGBM'yi geçerse | OOS benchmark ile kanıt |
| **Featuretools** | Feature engineering ihtiyacı olduğunda | Leakage olmadan değer kattığı kanıt |
| **tsfresh** | Time-series feature ihtiyacı olduğunda | Mevcut feature'ların yetmediği durum |
| **LIME** | SHAP'ın yetmediği durum | SHAP'ın yetersiz olduğu spesifik vaka |
| **PyTorch Lightning** | DL pipeline karmaşıklaştığında | Raw PyTorch'un yetmediği durum |

---

## 3. Neden Bu Teknolojiler Seçilmedi?

### Ray Tune
- Şu an distributed tuning ihtiyacımız yok
- Optuna mevcut ölçeğimiz için yeterli
- Ray ek karmaşıklık ve bağımlılık getiriyor
- **Geçiş kriteri:** Optuna 100+ trial'da darboğaz olursa

### Weights & Biases
- Dış servis bağımlılığı getiriyor
- Mevcut Model Registry + DB altyapımız var
- MLflow zaten docker-compose'da mevcut
- **Geçiş kriteri:** Tracking ihtiyacı MLflow'yu aşarsa

### TabNet + FT-Transformer
- BIST tabular verimizde LightGBM'yi geçip geçmedikleri kanıtlanmadı
- OOS benchmark olmadan eklemek gereksiz bağımlılık
- **Geçiş kriteri:** OOS benchmark ile LightGBM'yi geçerlerse

### Featuretools + tsfresh
- Otomatik feature üretimi finansal sistemde riskli:
  - Feature explosion
  - Data leakage
  - Gereksiz korelasyon
- **Geçiş kriteri:** Mevcut feature'ların yetmediği kanıtlanırsa

### LIME
- SHAP zaten mevcut
- İki explainability sistemi gereksiz karmaşıklık
- **Geçiş kriteri:** SHAP'ın yetersiz olduğu spesifik vaka

### PyTorch Lightning
- Mevcut DL pipeline basit
- Ekstra abstraction gereksiz
- **Geçiş kriteri:** DL pipeline karmaşıklaştığında

---

## 4. Performans İddiaları — Düzeltme

Önceki dokümandaki performans iddiaları kanıtlanmamıştı. İşte düzeltme:

| İddia | Durum | Düzeltme |
|-------|-------|----------|
| "Polars 10-100x hızlı" | Genel benchmark | Bizim sorgularımızda ölçülmedi |
| "Ray Tune 4x hızlı" | Genel benchmark | Bizim ölçeğimizde ölçülmedi |
| "Ensemble accuracy 0.91" | Kanıtlanmamış | Bizim verimizde ölçülmedi |
| "Stacking %8-12 daha iyi" | Kanıtlanmamış | Bizim verimizde ölçülmedi |

**Doğru yaklaşım:** Her teknolojinin değerini bizim BIST verimizde OOS benchmark ile kanıtlamak.

---

## 5. Bağımlılık Sayısı

| Kategori | Eski | Yeni | Fark |
|----------|------|------|------|
| Python paketi | 50+ | 38 | -12 (gereksiz paketler çıkarıldı) |
| Frontend paketi | 15 | 10 | -5 (gereksiz paketler çıkarıldı) |
| Docker image | 7 | 7 | 0 |
| **TOPLAM** | **72+** | **55** | **-17** |

---

## 6. Sonuç

**Prensip:** "Gerektiğinde kanıtlanmış teknoloji"

- ✅ 38 Python paketi (kanıtlanmış, gerekli)
- ✅ 10 Frontend paketi (kanıtlanmış, gerekli)
- ✅ 7 Docker image (kanıtlanmış, gerekli)
- ⏳ 8 teknoloji "sonra ihtiyaç kanıtlanırsa" listesinde

**Daha az bağımlılık, daha az karmaşıklık, daha az bakım = aynı hedef.**
