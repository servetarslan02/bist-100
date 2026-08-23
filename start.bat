@echo off
setlocal enabledelayedexpansion
title ALPHA BIST - Otonom Piyasa Zekasi
color 0b

echo ==============================================================================
echo       ALPHA BIST -- OTONOM PIYASA ZEKASI VE QUANT PLATFORMU
echo ==============================================================================
echo.

cd /d "%~dp0"

:: 1. DOCKER KONTROLU
echo [1/3] Docker motoru kontrol ediliyor...
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
        echo [UYARI] Docker motoru beklenenden uzun suruyor. Servisler baslatilmaya calisilacak...
        goto docker_is_ready
    )
    echo [*] Docker motorunun acilmasi bekleniyor... (!attempt!/25)
    goto wait_docker_loop
) else (
    echo [OK] Docker motoru calisiyor.
)

:docker_is_ready
echo.

:: 2. SERVISLERI AYAĞA KALDIR
echo [2/3] Mikro-servisler baslatiliyor (Docker Compose)...
docker compose up -d

if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Docker servisleri baslatilirken bir hata olustu.
    echo Lutfen Docker Desktop uygulamasinin acik oldugundan emin olun.
    echo.
    pause
    exit /b 1
)

echo.
echo [3/3] Servisler baslatildi!
echo ==============================================================================
echo       ALPHA BIST BASARIYLA CALISIYOR!
echo ==============================================================================
echo.
echo   Web Dashboard : http://localhost:3000
echo   REST API      : http://localhost:8000
echo   API Docs      : http://localhost:8000/docs
echo.
echo   Tarayici aciliyor...
start http://localhost:3000

echo.
echo Kapatmak istediginizde 'docker compose down' yapabilirsiniz.
echo.
pause
