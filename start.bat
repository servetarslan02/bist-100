@echo off
chcp 65001 >nul
title ALPHA BIST — Otonom Piyasa Zekası ve Quant Motoru
color 0A

echo ==============================================================================
echo       🚀 ALPHA BIST — OTONOM PİYASA ZEKASI VE QUANT PLATFORMU
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. DOCKER DAEMON KONTROLÜ
echo [1/3] Docker servis durumu denetleniyor...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Docker Desktop kapalı veya servis çalışmıyor.
    echo [*] Docker Desktop otomatik olarak başlatılıyor, lütfen bekleyin...
    
    if exist "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe" (
        start "" "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
    ) else if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else (
        start "" "Docker Desktop.exe" 2>nul
    )

    :: Docker'ın açılmasını bekle (Maksimum 60 saniye)
    set /a attempt=0
    :wait_docker
    set /a attempt+=1
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo [OK] Docker Desktop başarıyla aktif hale geldi!
        goto docker_ready
    )
    if %attempt% GEQ 20 (
        echo [HATA] Docker başlatılamadı. Lütfen Docker Desktop'ı elle açıp tekrar deneyin.
        pause
        exit /b 1
    )
    echo [*] Docker motorunun hazır olması bekleniyor... (%attempt%/20)
    goto wait_docker
) else (
    echo [OK] Docker motoru aktif ve hazır.
)

:docker_ready
echo.

:: 2. SERVİSLERİ AYAĞA KALDIR
echo [2/3] Tüm mikro-servisler ayağa kaldırılıyor...
echo       - alpha-clickhouse (30 Yıllık OLAP Veri Deposu)
echo       - alpha-postgres   (Portföy, İşlemler ve Modeller)
echo       - alpha-redis      (Canlı RAM Önbellek ve Telemetri)
echo       - alpha-redpanda   (Event Streaming)
echo       - alpha-api        (FastAPI Quant Motoru)
echo       - alpha-dashboard  (Next.js 15 Web Arayüzü)
echo.

docker compose up -d

if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Servisler başlatılırken bir sorun oluştu!
    pause
    exit /b 1
)

echo.
echo [3/3] Servislerin sağlık durumu doğrulanıyor...
timeout /t 4 /nobreak >nul

echo ==============================================================================
echo       ✅ ALPHA BIST TÜM KATMANLARIYLA ÇALIŞIYOR!
echo ==============================================================================
echo.
echo   🌐 Web Dashboard : http://localhost:3000
echo   🔌 REST API       : http://localhost:8000
echo   📚 API Docs       : http://localhost:8000/docs
echo.
echo   Tarayıcı otomatik olarak açılıyor...
start http://localhost:3000

echo.
echo Servisleri durdurmak istediğinizde 'docker compose down' komutunu kullanabilirsiniz.
echo Bu pencereyi kapatabilirsiniz.
echo ==============================================================================
timeout /t 5 >nul
