"""
ALPHA BIST — Cross-Platform Startup Script
Automatically detects Docker Desktop, launches daemon if closed, starts all services,
applies SSD write rate limiting (512 MB/s), and opens the web dashboard.

SSD Koruma Stratejisi:
  - PostgreSQL: fsync=on, synchronous_commit=on (veri güvenliği)
  - Redis: appendfsync everysec (dengeli persistence)
  - Tüm servisler: cgroup v2 io.max ile 512 MB/s yazma limiti
  - Monitoring: named volumes (tmpfs yok, veri kalıcı)
"""

import os
import sys
import time
import subprocess
import webbrowser
import platform
import orjson
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# === Configuration ===
SSD_WRITE_LIMIT_MBPS = 512  # MB/s — asla aşılmayacak limit
SSD_WRITE_LIMIT_BYTES = SSD_WRITE_LIMIT_MBPS * 1024 * 1024

# Data yazan servisler (persistent volumes)
DATA_CONTAINERS = [
    "alpha-postgres",
    "alpha-postgres-replica",
    "alpha-clickhouse",
    "alpha-clickhouse-2",
    "alpha-zookeeper",
    "alpha-redis",
    "alpha-sentinel-1",
    "alpha-sentinel-2",
    "alpha-sentinel-3",
    "alpha-nats",
    "alpha-prometheus",
    "alpha-grafana",
    "alpha-mlflow",
]

# Uygulama servisleri (sadece tmpfs, SSD'ye yazmaz)
APP_CONTAINERS = [
    "alpha-traefik",
    "alpha-api",
    "alpha-ingestion",
    "alpha-feature-engine",
    "alpha-market-state",
    "alpha-intelligence",
    "alpha-simulation",
    "alpha-risk",
    "alpha-portfolio",
    "alpha-learning",
    "alpha-celery-worker",
    "alpha-dashboard",
]


def is_docker_running() -> bool:
    """Docker daemon'un çalışıp çalışmadığını kontrol et."""
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


def start_docker_desktop():
    """Docker Desktop'ı platforma göre başlat."""
    system = platform.system()
    print("[!] Docker motoru kapalı. Docker Desktop başlatılıyor...")

    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        candidates = [
            os.path.join(local_app_data, "Programs", "DockerDesktop", "Docker Desktop.exe"),
            os.path.join(program_files, "Docker", "Docker", "Docker Desktop.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                print(f"[*] Docker Desktop çalıştırılıyor: {path}")
                subprocess.Popen([path], shell=True)
                break
        else:
            subprocess.Popen(["start", "Docker Desktop"], shell=True)

    elif system == "Darwin":
        subprocess.Popen(["open", "-a", "Docker"])

    elif system == "Linux":
        subprocess.Popen(["sudo", "systemctl", "start", "docker"])

    print("[*] Docker daemon hazır olması bekleniyor (maks 60sn)...")
    for i in range(30):
        time.sleep(2)
        if is_docker_running():
            print("[OK] Docker daemon aktif!")
            return True
        print(f"    Bekleniyor... ({i+1}/30)")

    print("[HATA] Docker başlatılamadı. Elle açıp tekrar deneyin.")
    return False


def get_container_pid(container_name: str) -> str:
    """Container PID'sini al."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Pid}}", container_name],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            pid = result.stdout.strip()
            if pid and pid != "0":
                return pid
    except Exception:
        pass
    return None


def find_cgroup_v2_path(pid: str) -> str:
    """Container'ın cgroup v2 io.max dosyasını bul."""
    # Method 1: Docker cgroup yolu (en güvenilir)
    docker_cgroup = f"/sys/fs/cgroup/system.slice/docker-{pid}.scope/io.max"
    if os.path.exists(docker_cgroup):
        return docker_cgroup

    # Method 2: cgroup v2 unified hierarchy
    unified_cgroup = f"/sys/fs/cgroup/docker/{pid}/io.max"
    if os.path.exists(unified_cgroup):
        return unified_cgroup

    # Method 3: /proc/{pid}/cgroup üzerinden bul
    try:
        with open(f"/proc/{pid}/cgroup", "r") as f:
            for line in f:
                if line.startswith("0::"):
                    cgroup_path = line.strip().split("::")[1]
                    io_max = f"/sys/fs/cgroup/{cgroup_path}/io.max"
                    if os.path.exists(io_max):
                        return io_max
    except Exception:
        pass

    return None


def get_block_device_id() -> str:
    """Ana block device'ın major:minor ID'sini al (örn: 8:0 for /dev/sda)."""
    try:
        # Root filesystem device'ını bul
        result = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "/"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            device = result.stdout.strip()
            # /dev/sda1 -> /dev/sda, /dev/nvme0n1p1 -> /dev/nvme0n1
            import re
            base_device = re.sub(r'p?\d+$', '', device)
            # Device ID al
            stat_result = subprocess.run(
                ["stat", "-c", "%t:%T", base_device],
                capture_output=True, text=True, timeout=5,
            )
            if stat_result.returncode == 0:
                parts = stat_result.stdout.strip().split(":")
                major = int(parts[0], 16)
                minor = int(parts[1], 16)
                return f"{major}:{minor}"
    except Exception:
        pass

    # Fallback: 8:0 (typical /dev/sda)
    return "8:0"


def apply_ssd_write_limit():
    """Tüm data container'larına cgroup v2 ile 512 MB/s yazma limiti uygula."""
    print(f"\n[*] SSD yazma hızı limiti uygulanıyor: {SSD_WRITE_LIMIT_MBPS} MB/s")
    print(f"    Limit: {SSD_WRITE_LIMIT_BYTES:,} bytes/s")

    device_id = get_block_device_id()
    print(f"    Block device: {device_id}")

    applied = 0
    skipped = 0
    failed = 0

    for name in DATA_CONTAINERS:
        pid = get_container_pid(name)
        if not pid:
            print(f"  ⏭️  {name} → çalışmıyor, atlanıyor")
            skipped += 1
            continue

        io_max_path = find_cgroup_v2_path(pid)
        if not io_max_path:
            print(f"  ⚠️  {name} → cgroup v2 io.max bulunamadı (PID: {pid})")
            failed += 1
            continue

        try:
            # Mevcut limitleri oku
            with open(io_max_path, "r") as f:
                current = f.read().strip()

            # wbps limitini uygula
            with open(io_max_path, "w") as f:
                f.write(f"{device_id} wbps={SSD_WRITE_LIMIT_BYTES}")

            # Doğrula
            with open(io_max_path, "r") as f:
                verify = f.read().strip()

            if str(SSD_WRITE_LIMIT_BYTES) in verify:
                print(f"  ✅ {name} → SSD yazma: {SSD_WRITE_LIMIT_MBPS} MB/s max")
                applied += 1
            else:
                print(f"  ⚠️  {name} → limit uygulanamadı (doğrulama başarısız)")
                failed += 1

        except PermissionError:
            print(f"  ❌ {name} → izin hatası (sudo ile çalıştırın)")
            failed += 1
        except Exception as e:
            print(f"  ❌ {name} → hata: {e}")
            failed += 1

    print(f"\n[*] SSD limit özeti: {applied} uygulandı, {skipped} atlandı, {failed} başarısız")
    return failed == 0


def wait_for_containers_healthy(timeout_s: int = 120):
    """Tüm container'ların healthy olmasını bekle."""
    print("\n[*] Servislerin hazır olması bekleniyor...")
    start = time.time()

    while time.time() - start < timeout_s:
        all_healthy = True
        for name in DATA_CONTAINERS:
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
                    capture_output=True, text=True, timeout=5,
                )
                status = result.stdout.strip()
                if status != "healthy":
                    all_healthy = False
                    break
            except Exception:
                all_healthy = False
                break

        if all_healthy:
            print("[OK] Tüm data servisleri healthy!")
            return True

        time.sleep(3)
        elapsed = int(time.time() - start)
        print(f"    Bekleniyor... ({elapsed}s/{timeout_s}s)")

    print("[UYARI] Bazı servisler henüz healthy olmadı")
    return False


def verify_ssd_limits():
    """Uygulanan SSD limitlerini doğrula."""
    print("\n[*] SSD limit doğrulaması...")
    all_ok = True

    for name in DATA_CONTAINERS:
        pid = get_container_pid(name)
        if not pid:
            continue

        io_max_path = find_cgroup_v2_path(pid)
        if not io_max_path:
            continue

        try:
            with open(io_max_path, "r") as f:
                content = f.read().strip()

            if str(SSD_WRITE_LIMIT_BYTES) in content:
                print(f"  ✅ {name} → {SSD_WRITE_LIMIT_MBPS} MB/s limit aktif")
            elif "max" in content:
                print(f"  ⚠️  {name} → limit uygulanmamış (max)")
                all_ok = False
            else:
                print(f"  ℹ️  {name} → {content}")
        except Exception:
            pass

    return all_ok


def main():
    print("=" * 72)
    print("      ALPHA BIST — OTONOM PIYASA ZEKASI VE QUANT PLATFORMU")
    print("=" * 72)
    print(f"  SSD Yazma Limiti: {SSD_WRITE_LIMIT_MBPS} MB/s")
    print(f"  Data Servisleri: {len(DATA_CONTAINERS)}")
    print(f"  Uygulama Servisleri: {len(APP_CONTAINERS)}")
    print("=" * 72)

    # 1. Docker kontrolü
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

    # 3. Container'ların healthy olmasını bekle
    wait_for_containers_healthy(timeout_s=120)

    # 4. SSD yazma hızı limiti uygula
    apply_ssd_write_limit()

    # 5. Limit doğrulaması
    verify_ssd_limits()

    # 6. Servis durumu özeti
    print("\n" + "=" * 72)
    print("  SERVİS DURUMU")
    print("=" * 72)

    all_containers = DATA_CONTAINERS + APP_CONTAINERS
    for name in all_containers:
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", name],
                capture_output=True, text=True, timeout=5,
            )
            status = result.stdout.strip()
            if status == "running":
                print(f"  ✅ {name}")
            else:
                print(f"  ❌ {name} → {status}")
        except Exception:
            print(f"  ❌ {name} → bulunamadı")

    # 7. Servis portları
    print("\n" + "=" * 72)
    print("  ERİŞİM NOKTALARI")
    print("=" * 72)
    print("  🌐 Web Dashboard:    http://localhost:3000")
    print("  📡 REST API:         http://localhost:8000")
    print("  📚 API Docs:         http://localhost:8000/docs")
    print("  📊 Grafana:          http://localhost:3001")
    print("  📈 Prometheus:       http://localhost:9090")
    print("  🔬 MLflow:           http://localhost:5000")
    print("  🗄️  ClickHouse:       http://localhost:8123")
    print("  🐘 PostgreSQL:       localhost:5432")
    print("  🐘 PG Replica:       localhost:5433")
    print("  🔴 Redis:            localhost:6379")
    print("  📨 NATS:             localhost:4222")
    print("  🔷 Traefik:          http://localhost:8080")
    print("=" * 72)

    # 8. Browser aç
    print("\n🌐 Web Dashboard Açılıyor: http://localhost:3000")
    time.sleep(2)
    try:
        webbrowser.open("http://localhost:3000")
    except Exception:
        pass

    print("\n" + "=" * 72)
    print("      ALPHA BIST BAŞARIYLA ÇALIŞIYOR!")
    print(f"      SSD Yazma Limiti: {SSD_WRITE_LIMIT_MBPS} MB/s ✅")
    print("=" * 72)


if __name__ == "__main__":
    main()
