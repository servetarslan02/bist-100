# ALPHA BIST - Hızlı Başlangıç (Windows)

## Ön Gereksinimler

1. **Docker Desktop** - https://www.docker.com/products/docker-desktop/
   - Windows için indirin ve kurun
   - Kurulumdan sonra bilgisayarınızı yeniden başlatın
   - Docker Desktop'ı açın ve çalıştığını doğrulayın

2. **Git** - https://git-scm.com/download/win

## Kurulum

### 1. Repoyu klonlayın
```cmd
git clone https://github.com/servetarslan02/bist-100.git
cd bist-100
```

### 2. Başlatın
```cmd
start.bat
```

Bu script:
- Docker'ı kontrol eder
- `.env` dosyasını oluşturur
- Tüm image'ları build eder
- Veritabanlarını başlatır
- Tüm servisleri başlatır

### 3. Erişin
- **Dashboard:** http://localhost:3000
- **API:** http://localhost:8000
- **Grafana:** http://localhost:3001
- **MLflow:** http://localhost:5000

## Yönetim

| Komut | Açıklama |
|-------|----------|
| `start.bat` | Tüm servisleri başlat |
| `stop.bat` | Tüm servisleri durdur |
| `status.bat` | Servis durumlarını göster |
| `logs.bat` | Canlı logları göster |

## Manuel Komutlar

```cmd
# Başlat
docker-compose up -d

# Durdur
docker-compose down

# Loglar
docker-compose logs -f

# Tek servis başlat
docker-compose up -d api

# Servis durumu
docker-compose ps

# Yeniden build
docker-compose build --no-cache
```

## Sorun Giderme

### Docker başlamıyor
- Docker Desktop'ı açın
- WSL2 kurulu olduğundan emin olun
- Bilgisayarınızı yeniden başlatın

### Port çakışması
```cmd
# Hangi portun kullanıldığını kontrol edin
netstat -ano | findstr :8000
netstat -ano | findstr :3000
```

### Bellek yetersiz
- Docker Desktop → Settings → Resources → Memory → 8GB+
- Gerekirse servis sayısını azaltın

### Veritabanı bağlantısı yok
```cmd
# Veritabanı sağlık kontrolü
docker-compose exec postgres pg_isready -U alpha
docker-compose exec clickhouse clickhouse-client --query "SELECT 1"
docker-compose exec redis redis-cli ping
```

## API Anahtarları (Opsiyonel)

`.env` dosyasını düzenleyin:

```env
# TCMB EVDS (makro veri için)
TCMB_EVDS_API_KEY=your_key_here

# NewsAPI (haberler için)
NEWS_API_KEY=your_key_here

# Alpha Vantage (global veri için)
ALPHA_VANTAGE_KEY=your_key_here
```

## İlk Çalıştırma

1. `start.bat` çalıştırın
2. http://localhost:3000 adresine gidin
3. Dashboard'da Market Radar'ı kontrol edin
4. İlk tarama otomatik başlayacak (birkaç dakika sürebilir)
