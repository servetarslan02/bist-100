@echo off
echo ============================================================
echo ALPHA BIST - Market Intelligence ^& Quant Engine
echo ============================================================
echo.

REM Check Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo HATA: Docker yuklu degil!
    echo Docker Desktop'i indirin: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo HATA: Docker Compose yuklu degil!
    pause
    exit /b 1
)

echo [1/5] Docker kontrol edildi... OK
echo.

REM Check .env
if not exist .env (
    echo [2/5] .env dosyasi olusturuluyor...
    copy .env.example .env >nul
    echo .env dosyasi olusturuldu. Lutfen API anahtarlarinizi girin.
) else (
    echo [2/5] .env dosyasi mevcut... OK
)
echo.

REM Build
echo [3/5] Docker image'lari build ediliyor...
docker-compose build --no-cache
if errorlevel 1 (
    echo HATA: Build basarisiz!
    pause
    exit /b 1
)
echo Build tamamlandi.
echo.

REM Start databases first
echo [4/5] Veritabanlari baslatiliyor...
docker-compose up -d postgres clickhouse redis redpanda
echo Veritabanlari baslatildi. Saglik kontrolu yapiliyor...
timeout /t 10 /nobreak >nul

REM Health check
echo.
echo Saglik kontrolu:
docker-compose ps
echo.

REM Start all services
echo [5/5] Tum servisler baslatiliyor...
docker-compose up -d
echo.
echo ============================================================
echo ALPHA BIST baslatildi!
echo ============================================================
echo.
echo Servisler:
echo   API:        http://localhost:8000
echo   Dashboard:  http://localhost:3000
echo   Grafana:    http://localhost:3001
echo   MLflow:     http://localhost:5000
echo   Prometheus: http://localhost:9090
echo   ClickHouse: http://localhost:8123
echo.
echo Loglar icin: docker-compose logs -f
echo Durdurmak icin: docker-compose down
echo.
pause
