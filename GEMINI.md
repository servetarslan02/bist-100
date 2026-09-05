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
  - Web/API: `FastAPI`, `uvicorn`, `pydantic v2` (`pydantic-settings`).
  - Serileştirme: **`orjson` ZORUNLUDUR** (Standart `json` kütüphanesi YASAKTIR; yüksek hız ve tip güvenliği için `orjson.dumps()`, `orjson.loads()` kullanılır).
  - Yerel Veritabanı: **`duckdb` ZORUNLUDUR** (`sqlite3` YASAKTIR; yerel durum, DLQ, backtest sonuçları ve önbellek için `duckdb>=1.3.0` kullanılır).
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
5. **Standart `json` ve `sqlite3` Yasağı (`orjson` ve `duckdb` Zorunludur):**
   - Standart `json` modülü yerine daima `orjson` (`orjson.dumps()`, `orjson.loads()`) kullanılır.
   - `sqlite3` tamamen terkedilmiştir; yerel veritabanı, durum yönetimi, önbellek ve analitik için daima `duckdb` kullanılır. Hiçbir bileşende SQLite kullanılmaz.

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
   - Hatalar `structlog` veya modül standart loglayıcısı ile yapısal olarak loglanmalı, uygun istisna fırlatılmalı veya sistem güvenli moda geçmelidir.
4. **Doğrulama Refleksi:**
   - Düzenleme tamamlandığında dosyanın sentaksı, import doğruluğu ve ruff kurallarına uyumu teyit edilmelidir.

## 4. 🔍 KOD VE SERVİS DENETİM STANDARTLARI (AUDIT RULES)

> Tüm servislerde (`services/*/AUDIT_REPORT.md`) ve kod tabanında geçerli olan bağlayıcı denetim kuralları:

1. **Mock / Sahte / Placeholder Veri Yasağı:**
   - Test verisi, hardcoded değer, statik mock JSON veya placeholder data production/service kodunda kesinlikle yer alamaz.
   - `"Otomatik eklendi."` gibi anlamsız docstring'ler yasaktır; her docstring açıklayıcı, amacını belirten, Args/Returns/Raises içeren ve **Türkçe** olmalıdır.
   - `pass` ile boş bırakılmış fonksiyon/metot gövdeleri yasaktır.
2. **Kapsamlı Hata, Eşzamanlılık ve Sınır Kontrolleri:**
   - Boundary hataları, dead code (ölü kod), sessiz exception yutma, bypass mekanizmaları ve tutarsızlıklar derhal düzeltilmelidir.
   - Polars null değerleri (`np.isnan(None)` vb. TypeError riski), sıfıra bölme (`ZeroDivisionError`) ve `NaN`, `Inf` sayısal taşmaları guard altına alınmalıdır.
   - Paylaşılan state veya veritabanı bağlantısı yöneten singleton sınıflarda eşzamanlı erişim güvenliği (`threading.Lock` / `asyncio.Lock`) zorunludur.
3. **Eksiksiz Fonksiyonellik ve Fail-Closed İlkesi:**
   - Eksik parametreler, eksik validasyonlar ve eksik fallback mekanizmaları tamamlanmalıdır.
   - Hatalar asla sessizce yutulamaz (`except: pass` yasaktır). Hata loglandıktan sonra durumuna göre uygun istisna (`raise ... from e`) fırlatılarak sistem güvenli duruma geçmelidir.
   - Metot ve fonksiyon parametrelerinde ve dönüşlerinde eksiksiz `type annotation` (`None`, `Tuple[...]`, `Any` yerine spesifik tipler) belirtilmelidir.
4. **Profesyonel Kod, Temizlik ve Loglama Standartları:**
   - Her veri modeli / dataclass / çekirdek sınıfta mutlaka açıklayıcı bir `__repr__` metodu bulunmalıdır.
   - Fonksiyon içi gereksiz `import`'lar dosya başına taşınmalı, kullanılmayan import'lar temizlenmelidir.
   - **Loglama Mimarisi:**
     - Sistem genelinde (Web, API, Backtest, Quant, ML, Core, Risk vb.) birincil loglayıcı olarak **`structlog`** (`logger = structlog.get_logger(__name__)`) kullanılır.
     - Yapılandırılmış anahtar-değer parametreleri (`ticker=...`, `fold=...`, `hata=...`) veya biçimlendirilmiş metinler desteklenir.
     - Log mesajları ve hata metinleri tutarlı ve **Türkçe** olmalıdır.
     - Magic number'lar (`100000`, `0.10` vb.) yerine açık isimlendirilmiş sabitler (`DEFAULT_*`) kullanılmalıdır.
5. **Düzeltme Sonrası Canlı Doğrulama (Smoke/Execution Test):**
   - Yalnızca sözdizimi (`syntax`) veya dosya `import`'u ile yetinilmez.
   - Düzenlenen dosyanın temel fonksiyonlarını (CRUD, model tahmini, hesaplama vb.) fiilen çalıştıran mikro bir yürütme testi (`uv run python -c "..."` veya pytest) ve `ruff check` çalıştırılarak doğruluk kanıtlanmalıdır.
6. **Geliştirme Önerileri ve Proaktif İyileştirme:**
   - Hata veya eksik olmasa dahi performans, bellek, Polars vektörizasyonu veya mimari açıdan sistemi iyileştirebilecek potansiyel alanlar tespit edilip dürüstçe raporlanmalı ve sisteme fayda sağlayanlar hayata geçirilmelidir.
7. **Mimari Tutarlılık, Modül Dışa Aktarımı ve Göç (Migration) Takibi:**
   - Modül seviyesinde `__all__` listesi eksiksiz, güncel ve açık olmalıdır.
   - Yeniden adlandırılan veya imzası değiştirilen sınıf/fonksiyonlar için tüm repo (`grep`) taranmalı, çağıran tüm noktalar güncellenmeli ve audit raporuna "Migration" olarak kaydedilmelidir.



