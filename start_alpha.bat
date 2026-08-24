@echo off
title ALPHA BIST 3.0 - Autonomous Quant & Trading Engine
echo =====================================================================
echo    ALPHA BIST 3.0 - Otomotiv ve Kurumsal Borsa Zeka Motoru
echo =====================================================================
echo.
echo [1/3] Docker ve WSL Bellek Kontrolu Yapiliyor...
wsl.exe -u root -e sh -c "sync; echo 3 > /proc/sys/vm/drop_caches" >nul 2>&1

echo [2/3] Tum 17 Mikroservis Baslatiliyor (Arka Planda)...
docker compose up -d

echo [3/3] Servis Saglik Kontrolu ve Web Arayuzu Aciliyor...
timeout /t 3 >nul

start http://localhost:3000

echo.
echo =====================================================================
echo    SISTEM BASARIYLA DEVREDE!
echo    - Web Dashboard: http://localhost:3000
echo    - REST API Docs: http://localhost:8000/docs
echo    - Grafana Panel: http://localhost:3001
echo =====================================================================
pause
