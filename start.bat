@echo off
setlocal enabledelayedexpansion
title ALPHA BIST - Otonom Piyasa Zekasi v2.0
color 0b

echo ==============================================================================
echo       ALPHA BIST -- OTONOM PIYASA ZEKASI VE QUANT PLATFORMU
echo       v2.0 - Resilience-Enhanced Startup
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. .env KONTROLU
echo [1/5] Ortam degiskenleri kontrol ediliyor...
if not exist ".env" (
    if exist ".env.example" (
        echo [!] .env dosyasi bulunamadi, .env.example'dan kopyalaniyor...
        copy .env.example .env >nul
        echo [OK] .env dosyasi olusturuldu. Sifreleri elle girmeniz gerekebilir.
    ) else (
        echo [HATA] .env.example dosyasi bulunamadi!
        pause
        exit /b 1
    )
) else (
    echo [OK] .env dosyasi mevcut.
)

:: 2. DOCKER KONTROLU
echo.
echo [2/5] Docker motoru kontrol ediliyor...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Docker Desktop kapali gorunuyor. Baslatiliyor, lutfen bekleyin...

    if exist "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe" (
        start "" "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
    ) else if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else (
        start "" "Docker Desktop.exe" 2>nul
    )

    set attempt=0
    :wait_docker_loop
    set /a attempt+=1
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo [OK] Docker Desktop aktif hale geldi!
        goto docker_is_ready
    )
    if !attempt! GEQ 25 (
        echo [UYARI] Docker motoru beklenenden uzun suruyor...
        goto docker_is_ready
    )
    echo [*] Docker motorunun acilmasi bekleniyor... (!attempt!/25)
    goto wait_docker_loop
) else (
    echo [OK] Docker motoru calisiyor.
)

:docker_is_ready

:: 3. SERVISLERI AYAĞA KALDIR
echo.
echo [3/5] Mikro-servisler baslatiliyor (Docker Compose --build)...
docker compose up -d --build

if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Docker servisleri baslatilirken bir hata olustu.
    pause
    exit /b 1
)
echo [OK] Tum servisler baslatildi.

:: 4. HEALTH CHECK
echo.
echo [4/5] Servislerin hazir olmasi bekleniyor (maks 180sn)...
set /a health_attempt=0
:health_loop
set /a health_attempt+=1
if !health_attempt! GEQ 36 (
    echo [UYARI] Bazı servisler henüz healthy olmadı (timeout)
    goto health_done
)
timeout /t 5 /nobreak >nul
docker compose ps --format json 2>nul | findstr /C:"healthy" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo [OK] Servisler hazir!
    goto health_done
)
echo [*] Bekleniyor... (!health_attempt!/36)
goto health_loop
:health_done

:: 5. RESILIENCE DOĞRULAMA
echo.
echo [5/5] Resilience bileşenleri doğrulanıyor...
if exist "scripts\backup_alpha.sh" (
    echo   [OK] Backup script mevcut
) else (
    echo   [UYARI] Backup script bulunamadi
)
findstr /C:"stop_grace_period" docker-compose.yml >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo   [OK] stop_grace_period tanimli
) else (
    echo   [UYARI] stop_grace_period bulunamadi
)
findstr /C:"autoheal" docker-compose.yml >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo   [OK] Autoheal container mevcut
) else (
    echo   [UYARI] Autoheal container bulunamadi
)

:: SERVIS DURUMU
echo.
echo ==============================================================================
echo       SERVIS DURUMU
echo ==============================================================================
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

:: ERISIM NOKTALARI
echo.
echo ==============================================================================
echo       ERISIM NOKTALARI
echo ==============================================================================
echo   Web Dashboard : http://localhost:3000
echo   REST API      : http://localhost:8000
echo   API Docs      : http://localhost:8000/docs
echo   Grafana       : http://localhost:3001
echo   Prometheus    : http://localhost:9090
echo   MLflow        : http://localhost:5000
echo   ClickHouse    : http://localhost:8123
echo   PostgreSQL    : localhost:5432
echo   Redis         : localhost:6379
echo   NATS          : localhost:4222
echo   Autoheal      : otomatik unhealthy container restart
echo   Backup        : her gun 02:00 (cron)
echo ==============================================================================

:: BROWSER AC
echo.
echo Web Dashboard aciliyor...
start http://localhost:3000

echo.
echo ==============================================================================
echo       ALPHA BIST BASARIYLA CALISIYOR!
echo ==============================================================================
echo.
echo   Durdurmak icin: docker compose down
echo   Loglar icin:    docker compose logs -f
echo.
pause
