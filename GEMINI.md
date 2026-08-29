# ALPHA BIST — Antigravity Geliştirme & Sistem Manifestosu (GEMINI.md)

> Bu dosya Antigravity AI asistanı için bu projenin birincil ve zorunlu başvuru kaynağıdır.
> Bu projede yapılan tüm dosya düzenlemeleri, hata ayıklama ve kod üretim süreçlerinde aşağıdaki kurallar istisnasız uygulanır.

---

## 1. 🏗️ MEVCUT ALTYAPI VE TEKNOLOJİ YIĞINI

### 🐍 Python & Paket Yönetimi
- **Python Sürümü:** `>= 3.12`
- **Paket Yöneticisi:** `uv` (`uv.lock`, `pyproject.toml`).
  - Asla global `pip install` çalıştırma!
  - Komutlar için `uv run python ...` veya `uv add ...` kullanılmalıdır.
- **Linter & Formatter:** `ruff` (Line length: 120, target: py312).
- **Tip Denetleyicisi:** `mypy` (`strict = true`, python 3.12).
- **Framework & Kütüphaneler:**
  - Web/API: `FastAPI`, `uvicorn`, `pydantic v2` (`pydantic-settings`), `orjson`.
  - Loglama: `structlog` (Windows UTF-8 uyumlu).
  - İletişim: `websockets`, `httpx`, `asyncpg`, `SQLAlchemy 2.0+`.

### 💾 Veritabanı Mimarisi (Database Topology)
| Veritabanı | Sürüm / İmaj | Host Port | Amaç | Bağlantı Sürücüsü |
|---|---|---|---|---|
| **PostgreSQL + TimescaleDB** | `timescale/timescaledb:latest-pg17` | `5432` (primary), `5433` (replica) | İşlemsel + Zaman Serisi (Hypertable) | `asyncpg`, `SQLAlchemy 2.0` |
| **ClickHouse** | `clickhouse/clickhouse-server:26.3-alpine` | `8123` (HTTP), `9002` (Native) | 30 yıllık OLAP analitik | `clickhouse-connect` |
| **QuestDB** | Latest | ILP / HTTP | Tick & Orderbook verisi | `questdb` (ILP) |
| **DuckDB** | `duckdb>=1.3.0` | Embedded (In-process / File) | Offline research & local state | `duckdb` |
| **Redis 8 + Sentinel** | `redis:8-alpine` | `6379` (Redis), `26379` (Sentinel) | Cache, Pub/Sub, Streams | `redis-py >= 8.1.0` |

### 🐳 Docker & Servis Ağı
- Proje Docker Compose ile yönetilir: Proje adı `bist-100-main`, network `alpha-net`.
- Gateway / Reverse Proxy: `Traefik v3.7` (`alpha-traefik`, portlar 80, 443, 8080).
- Mesajlaşma / Olay Hattı: `NATS` / `Redis Streams`.
- Başlatma Betiği: `start.py` ve `start.bat` (Docker kontrolleri, SSD koruma limiti cgroup 512 MB/s, health check'ler).
- Host İşletim Sistemi: **Windows 11 (PowerShell)**. Bash spesifik komutlar (`&&`, `export`, `/dev/null`) host terminalinde çalıştırılamaz.

---

## 2. 🧠 QUANT & ML KURALLARI (KIRMIZI ÇİZGİLER)

1. **Sıfır Veri Sızıntısı (Zero Data Leakage / Point-In-Time):**
   - Geleceği gören hiçbir feature veya model eğitime/canlıya dahil edilemez.
   - Feature hesaplaması ile etiketleme (labeling) arasında mutlaka **purge + embargo** uygulanmalıdır.
   - **Mask-First İlkesi:** Filtreleme/maskeleme, feature hesaplamasından **önce** uygulanır, sonra değil.
2. **Polars Zorunludur (Pandas Yasak):**
   - Yeni yazılan yüksek hacimli veri işleme ve feature motorlarında `polars>=1.30.0` kullanılmalıdır.
   - `pandas` yalnızca geriye dönük uyumluluk gerektiren legacy kısımlarda tolere edilir; yeni kodda kullanılmaz.
3. **ML Modelleri Hiyerarşisi:**
   - **LightGBM:** Ana şampiyon (champion) model.
   - **XGBoost & CatBoost:** Challenger modeller.
   - Ensemble default değildir; gerçek ve kanıtlanmış fayda olmadan eklenemez.
4. **Sahte Veri Yasağı:**
   - Sabit (hard-coded) piyasa verisi canlı gözlem gibi sunulamaz. Veri yoksa "eksik/bilinmiyor" olarak işaretlenir.
   - `assert ... or True` gibi sahte test assertion'ları kesinlikle yasaktır.

---

## 3. 🛠️ DOSYA DÜZENLEME VE HATA DÜZELTME KURALLARI

Bana iletilen görevlerde **eksik veya yanlış iş yapılmasını önleyen bağlayıcı kurallar**:

1. **Eksiksiz Kod (No Placeholders / No TODOs):**
   - Düzenlenen fonksiyonlar, modeller veya endpoint'ler eksiksiz yazılmalıdır.
   - Kod ortasında `// TODO`, `# logic buraya gelecek`, veya gövdesi boş bırakılmış fonksiyonlar bırakılamaz.
2. **Bağlamı Önceden İnceleme Zorunluluğu:**
   - Bir dosyada değişiklik yapmadan önce, o dosyanın import'ları, veri modelleri (Pydantic / SQLAlchemy) ve o fonksiyonu çağıran diğer servisler taranmalıdır.
   - Parametre tipleri veya dönüş değerleri değiştiriliyorsa, çağıran tüm yerler (`services/` altında) güncellenmelidir.
3. **Fail-Closed Hata Yönetimi:**
   - `except: pass` veya hatayı sessizce yok sayan `try-except` blokları YASAKTIR.
   - Hatalar `structlog` ile yapısal olarak loglanmalı, uygun istisna fırlatılmalı veya sistem güvenli moda geçmelidir.
4. **Doğrulama Refleksi:**
   - Düzenleme tamamlandığında dosyanın sentaksı, import doğruluğu ve ruff kurallarına uyumu teyit edilmelidir.
