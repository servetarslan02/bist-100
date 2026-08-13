@echo off
echo ============================================================
echo ALPHA BIST - Servis Durumu
echo ============================================================
echo.
docker-compose ps
echo.
echo Bellek kullanimi:
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" 2>nul
echo.
pause
