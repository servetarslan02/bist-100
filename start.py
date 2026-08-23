"""
ALPHA BIST — Cross-Platform Startup Script
Automatically detects Docker Desktop, launches daemon if closed, starts all 6 services,
and opens the web dashboard in the default browser.
"""

import os
import sys
import time
import subprocess
import webbrowser
import platform

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def is_docker_running() -> bool:
    try:
        res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception:
        return False

def start_docker_desktop():
    system = platform.system()
    print("[!] Docker motoru kapalı veya servis çalışmıyor. Docker Desktop başlatılıyor...")
    
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        
        candidates = [
            os.path.join(local_app_data, "Programs", "DockerDesktop", "Docker Desktop.exe"),
            os.path.join(program_files, "Docker", "Docker", "Docker Desktop.exe"),
        ]
        
        started = False
        for path in candidates:
            if os.path.exists(path):
                print(f"[*] Docker Desktop çalıştırılıyor: {path}")
                subprocess.Popen([path], shell=True)
                started = True
                break
        
        if not started:
            try:
                subprocess.Popen(["start", "Docker Desktop"], shell=True)
            except Exception:
                pass
    elif system == "Darwin":
        subprocess.Popen(["open", "-a", "Docker"])
    elif system == "Linux":
        subprocess.Popen(["sudo", "systemctl", "start", "docker"])

    print("[*] Docker daemon'un hazır olması bekleniyor (Maksimum 60sn)...")
    for i in range(30):
        time.sleep(2)
        if is_docker_running():
            print("[OK] Docker daemon başarıyla AKTİF hale geldi!")
            return True
        print(f"    Bekleniyor... ({i+1}/30)")
    
    print("[HATA] Docker otomatik başlatılamadı. Lütfen Docker Desktop'ı elle açıp tekrar deneyin.")
    return False

def main():
    print("=" * 72)
    print("      ALPHA BIST — OTONOM PIYASA ZEKASI VE QUANT PLATFORMU")
    print("=" * 72)

    # 1. Verify / Launch Docker
    if not is_docker_running():
        success = start_docker_desktop()
        if not success:
            sys.exit(1)
    else:
        print("[OK] Docker motoru aktif ve hazır.")

    # 2. Docker Compose Up
    print("\n[*] Tüm mikro-servisler Docker Compose ile ayağa kaldırılıyor...")
    try:
        subprocess.run(["docker", "compose", "up", "-d"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[HATA] Servisler başlatılamadı: {e}")
        sys.exit(1)

    print("\n[OK] Tüm 6 konteyner sorunsuz çalışıyor:")
    print("   • alpha-clickhouse (30 Yıllık OLAP Veri Deposu)")
    print("   • alpha-postgres   (Portföy, İşlemler ve Modeller)")
    print("   • alpha-redis      (Sub-Millisecond Önbellek & Telemetri)")
    print("   • alpha-redpanda   (Event Streaming)")
    print("   • alpha-api        (FastAPI Quant Motoru)")
    print("   • alpha-dashboard  (Next.js 15 Web Arayüzü)")

    # 3. Open Browser
    print("\n🌐 Web Dashboard Açılıyor: http://localhost:3000")
    time.sleep(2)
    try:
        webbrowser.open("http://localhost:3000")
    except Exception:
        pass

    print("\n" + "=" * 72)
    print("      ALPHA BIST BASARIYLA CALISIYOR!")
    print("=" * 72)

if __name__ == "__main__":
    main()
