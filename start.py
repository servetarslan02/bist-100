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

def apply_ssd_write_limit(mbps: int = 500):
    """SSD yazma hızını cgroup v2 ile sınırlar."""
    print(f"\n[*] SSD yazma hızı limiti uygulanıyor: {mbps}MB/s")
    
    limit_bytes = mbps * 1024 * 1024  # 500MB/s = 524288000 bytes
    containers = ["alpha-postgres", "alpha-clickhouse", "alpha-redis", "alpha-redpanda"]
    
    for name in containers:
        try:
            # Container ID al
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.Id}}", name],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"  ⚠️  {name} → bulunamadı")
                continue
            
            container_id = result.stdout.strip()
            cgroup_path = f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/io.max"
            
            if not os.path.exists(cgroup_path):
                print(f"  ⚠️  {name} → cgroup v2 io.max bulunamadı")
                continue
            
            # Mevcut device'ları oku ve wbps limiti ekle
            with open(cgroup_path, "r") as f:
                lines = f.read().strip().split("\n")
            
            applied = False
            for line in lines:
                dev_id = line.split()[0] if line.strip() else ""
                if dev_id and dev_id != "max":
                    try:
                        with open(cgroup_path, "w") as f:
                            f.write(f"{dev_id} wbps={limit_bytes}")
                        print(f"  ✅ {name} → SSD yazma: {mbps}MB/s max")
                        applied = True
                        break
                    except PermissionError:
                        print(f"  ⚠️  {name} → izin hatası (sudo gerekebilir)")
                        break
            
            if not applied:
                print(f"  ⚠️  {name} → limit uygulanamadı")
                
        except Exception as e:
            print(f"  ⚠️  {name} → hata: {e}")


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

    # 3. SSD yazma hızı limiti uygula
    apply_ssd_write_limit(500)

    print("\n[OK] Tüm servisler çalışıyor:")
    print("   • alpha-clickhouse (30 Yıllık OLAP Veri Deposu)")
    print("   • alpha-postgres   (Portföy, İşlemler ve Modeller)")
    print("   • alpha-redis      (Sub-Millisecond Önbellek & Telemetri)")
    print("   • alpha-redpanda   (Event Streaming)")
    print("   • alpha-api        (FastAPI Quant Motoru)")
    print("   • alpha-dashboard  (Next.js 15 Web Arayüzü)")

    # 4. Open Browser
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
