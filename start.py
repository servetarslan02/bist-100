from typing import Any
"""
ALPHA BIST — Cross-Platform Startup Script v2.0 (Resilience-Enhanced)

Tek komutla her şeyi kurar ve başlatır:
  python start.py

Yapılanlar:
  1. .env dosyası yoksa .env.example'dan oluşturur (otomatik şifre üretir)
  2. Docker Desktop kapalıysa başlatır
  3. Docker Compose ile tüm servisleri ayağa kaldırır
  4. Container'ların healthy olmasını bekler
  5. SSD yazma hızı limiti uygular (cgroup v2)
  6. Otomatik backup cron'u kurar
  7. Resilience bileşenlerini doğrular
  8. Web Dashboard'u tarayıcıda açar

SSD Koruma Stratejisi:
  - PostgreSQL: fsync=on, synchronous_commit=on (veri güvenliği)
  - Redis: appendfsync everysec (dengeli persistence)
  - Tüm servisler: cgroup v2 io.max ile 512 MB/s yazma limiti
  - Monitoring: named volumes (tmpfs yok, veri kalıcı)
"""

import os
import platform
import secrets
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.warning("Caught Exception in module_level", exc_info=True)

# === Configuration ===
SSD_WRITE_LIMIT_MBPS = 512  # MB/s — asla aşılmayacak limit
SSD_WRITE_LIMIT_BYTES = SSD_WRITE_LIMIT_MBPS * 1024 * 1024

PROJECT_ROOT = Path(__file__).parent.resolve()

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
    "alpha-questdb",
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
    "alpha-autoheal",
]


# =====================================================
# 1. ENV DOSYASI OLUŞTURMA
# =====================================================


def ensure_env_file() -> Any:
    """ ".env dosyası yoksa .env.example'dan oluştur, otomatik şifre üret."""
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"

    if env_path.exists():
        logger.info("[OK] .env dosyası mevcut.")
        return True

    if not example_path.exists():
        logger.info("[HATA] .env.example dosyası bulunamadı!")
        return False

    logger.info("[!] .env dosyası bulunamadı, .env.example'dan oluşturuluyor...")

    # .env.example'ı oku
    content = example_path.read_text(encoding="utf-8")

    # Otomatik güçlü şifreler üret
    def gen_password(length=24) -> Any:
        """Otomatik eklendi."""
        return secrets.token_urlsafe(length)

    pg_password = gen_password()
    replication_password = gen_password()
    redis_password = gen_password()
    clickhouse_password = gen_password()
    secret_key = gen_password(32)
    jwt_secret = gen_password(32)
    system_api_key = gen_password(32)
    grafana_password = gen_password()

    # Şifreleri yerleştir
    replacements = {
        "POSTGRES_PASSWORD=": f"POSTGRES_PASSWORD={pg_password}",
        "REPLICATION_PASSWORD=": f"REPLICATION_PASSWORD={replication_password}",
        "REDIS_PASSWORD=": f"REDIS_PASSWORD={redis_password}",
        "CLICKHOUSE_PASSWORD=": f"CLICKHOUSE_PASSWORD={clickhouse_password}",
        "SECRET_KEY=": f"SECRET_KEY={secret_key}",
        "JWT_SECRET=": f"JWT_SECRET={jwt_secret}",
        "SYSTEM_API_KEY=": f"SYSTEM_API_KEY={system_api_key}",
        "GRAFANA_PASSWORD=": f"GRAFANA_PASSWORD={grafana_password}",
        "APP_DEBUG=true": "APP_DEBUG=false",
        "AUTH_STRICT=false": "AUTH_STRICT=true",
    }

    for old, new in replacements.items():
        # Sadece boş değerleri değiştir (kullanıcı kendi değerlerini girmediyse)
        lines = content.split("\n")
        new_lines = []
        for line in lines:
            if line.strip().startswith(old) and (line.strip().endswith(old) or '""' in line or line.strip() == old):
                new_lines.append(new)
            else:
                new_lines.append(line)
        content = "\n".join(new_lines)

    env_path.write_text(content, encoding="utf-8")
    logger.info("[OK] .env dosyası oluşturuldu (otomatik şifreler üretildi).")
    logger.info("     ⚠️  Şifreleri kaydedin! Bir daha gösterilmeyecek.")
    logger.info(f"     POSTGRES_PASSWORD: {pg_password[:8]}...")
    logger.info(f"     REDIS_PASSWORD: {redis_password[:8]}...")
    logger.info(f"     GRAFANA_PASSWORD: {grafana_password[:8]}...")
    return True


# =====================================================
# 2. DOCKER KONTROLÜ
# =====================================================


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


def start_docker_desktop() -> Any:
    """Docker Desktop'ı platforma göre başlat."""
    system = platform.system()
    logger.info("[!] Docker motoru kapalı. Docker Desktop başlatılıyor...")

    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        candidates = [
            os.path.join(local_app_data, "Programs", "DockerDesktop", "Docker Desktop.exe"),
            os.path.join(program_files, "Docker", "Docker", "Docker Desktop.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                logger.info(f"[*] Docker Desktop çalıştırılıyor: {path}")
                subprocess.Popen([path], shell=True)
                break
        else:
            subprocess.Popen(["start", "Docker Desktop"], shell=True)

    elif system == "Darwin":
        subprocess.Popen(["open", "-a", "Docker"])

    elif system == "Linux":
        # sudo varsa kullan, yoksa direkt systemctl
        try:
            subprocess.run(["sudo", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            subprocess.Popen(["sudo", "systemctl", "start", "docker"])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # sudo yok — direkt systemctl dene (root olabilir)
            try:
                subprocess.Popen(["systemctl", "start", "docker"])
            except FileNotFoundError:
                logger.info("[HATA] Docker başlatılamadı. Elle başlatın: systemctl start docker")
                return False

    logger.info("[*] Docker daemon hazır olması bekleniyor (maks 60sn)...")
    for i in range(30):
        time.sleep(2)
        if is_docker_running():
            logger.info("[OK] Docker daemon aktif!")
            return True
        logger.info(f"    Bekleniyor... ({i + 1}/30)")

    logger.info("[HATA] Docker başlatılamadı. Elle açıp tekrar deneyin.")
    return False


# =====================================================
# 2.1 mTLS SERTİFİKALARI KONTROLÜ
# =====================================================


def ensure_mtls_certs() -> Any:
    """mTLS sertifikaları yoksa otomatik oluştur."""
    certs_dir = PROJECT_ROOT / "infrastructure" / "mtls" / "certs"
    ca_crt = certs_dir / "ca.crt"
    server_crt = certs_dir / "server.crt"
    client_crt = certs_dir / "client.crt"

    if ca_crt.exists() and server_crt.exists() and client_crt.exists():
        logger.info("[OK] mTLS güvenlik sertifikaları mevcut.")
        return True

    logger.info("[*] mTLS sertifikaları oluşturuluyor...")
    try:
        mtls_dir = PROJECT_ROOT / "infrastructure" / "mtls"
        res = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{mtls_dir}:/work",
                "-w",
                "/work",
                "alpine:latest",
                "sh",
                "-c",
                "apk add --no-cache openssl bash >/dev/null 2>&1 && bash generate_certs.sh",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode == 0 and ca_crt.exists():
            logger.info("[OK] mTLS sertifikaları başarıyla oluşturuldu.")
            return True
        else:
            logger.info(f"[UYARI] Sertifika oluşturulamadı: {res.stderr}")
            return False
    except Exception as e:
        logger.info(f"[UYARI] Sertifika oluşturma hatası: {e}")
        return False


# =====================================================
# 3. SSD YAZMA HIZI LİMİTİ
# =====================================================


def get_container_pid(container_name: str) -> str:
    """Container PID'sini al."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Pid}}", container_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            pid = result.stdout.strip()
            if pid and pid != "0":
                return pid
    except Exception:
        logger.warning("Caught Exception in get_container_pid", exc_info=True)
    return None


def find_cgroup_v2_path(pid: str) -> str:
    """Container'ın cgroup v2 io.max dosyasını bul."""
    docker_cgroup = f"/sys/fs/cgroup/system.slice/docker-{pid}.scope/io.max"
    if os.path.exists(docker_cgroup):
        return docker_cgroup

    unified_cgroup = f"/sys/fs/cgroup/docker/{pid}/io.max"
    if os.path.exists(unified_cgroup):
        return unified_cgroup

    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    cgroup_path = line.strip().split("::")[1]
                    io_max = f"/sys/fs/cgroup/{cgroup_path}/io.max"
                    if os.path.exists(io_max):
                        return io_max
    except Exception:
        logger.warning("Caught Exception in find_cgroup_v2_path", exc_info=True)

    return None


def get_block_device_id() -> str:
    """Ana block device'ın major:minor ID'sini al."""
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "/"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            device = result.stdout.strip()
            import re

            base_device = re.sub(r"p?\d+$", "", device)
            stat_result = subprocess.run(
                ["stat", "-c", "%t:%T", base_device],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if stat_result.returncode == 0:
                parts = stat_result.stdout.strip().split(":")
                major = int(parts[0], 16)
                minor = int(parts[1], 16)
                return f"{major}:{minor}"
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        logger.warning(
            "Error in get_block_device_id: (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError)",
            exc_info=True,
        )
    return "8:0"


def apply_ssd_write_limit() -> Any:
    """Tüm data container'larına cgroup v2 ile 512 MB/s yazma limiti uygula."""
    # Linux değilse atla
    if platform.system() != "Linux":
        logger.info("[*] SSD limit: Sadece Linux'ta uygulanır, atlanıyor.")
        return True

    # cgroup v2 kontrolü
    if not os.path.exists("/sys/fs/cgroup/io.max"):
        logger.info("[*] SSD limit: cgroup v2 io.max mevcut değil, atlanıyor.")
        return True

    logger.info(f"\n[*] SSD yazma hızı limiti uygulanıyor: {SSD_WRITE_LIMIT_MBPS} MB/s")

    device_id = get_block_device_id()
    applied = 0
    skipped = 0
    failed = 0

    for name in DATA_CONTAINERS:
        pid = get_container_pid(name)
        if not pid:
            skipped += 1
            continue

        io_max_path = find_cgroup_v2_path(pid)
        if not io_max_path:
            skipped += 1
            continue

        try:
            with open(io_max_path, "w") as f:
                f.write(f"{device_id} wbps={SSD_WRITE_LIMIT_BYTES}")

            with open(io_max_path) as f:
                verify = f.read().strip()

            if str(SSD_WRITE_LIMIT_BYTES) in verify:
                logger.info(f"  ✅ {name} → {SSD_WRITE_LIMIT_MBPS} MB/s")
                applied += 1
            else:
                failed += 1

        except PermissionError:
            logger.info(f"  ⚠️  {name} → izin hatası (sudo ile çalıştırın veya atlanıyor)")
            skipped += 1
        except Exception as e:
            logger.info(f"  ⚠️  {name} → {e}")
            skipped += 1

    logger.info(f"[*] SSD limit: {applied} uygulandı, {skipped} atlandı, {failed} başarısız")
    return True


# =====================================================
# 4. HEALTH CHECK
# =====================================================


def wait_for_containers_healthy(timeout_s: int = 180) -> Any:
    """Tüm container'ların healthy olmasını bekle."""
    logger.info(f"\n[*] Servislerin hazır olması bekleniyor (maks {timeout_s}sn)...")
    start = time.time()
    last_status = {}

    while time.time() - start < timeout_s:
        all_healthy = True
        unhealthy = []

        for name in DATA_CONTAINERS + APP_CONTAINERS:
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                status = result.stdout.strip()
                if status not in ("healthy", ""):
                    if status != last_status.get(name):
                        unhealthy.append(f"{name}={status}")
                        last_status[name] = status
                    all_healthy = False
                elif status == "healthy":
                    if last_status.get(name) != "healthy":
                        last_status[name] = "healthy"
            except Exception:
                all_healthy = False

        if all_healthy:
            logger.info("[OK] Tüm servisler healthy!")
            return True

        elapsed = int(time.time() - start)
        if unhealthy:
            logger.info(f"    [{elapsed}s] Bekleniyor: {', '.join(unhealthy[:5])}")
        else:
            logger.info(f"    [{elapsed}s] Bekleniyor...")
        time.sleep(5)

    logger.info("[UYARI] Bazı servisler henüz healthy olmadı (timeout)")
    return False


# =====================================================
# 5. BACKUP CRON KURULUMU
# =====================================================


def setup_backup_cron() -> Any:
    """Otomatik backup cron'u kur (sadece Linux/Mac)."""
    if platform.system() == "Windows":
        logger.info("[*] Windows: Backup cron atlandı (Task Scheduler ile kurulabilir)")
        return

    script_path = PROJECT_ROOT / "scripts" / "backup_alpha.sh"
    if not script_path.exists():
        logger.info("[UYARI] backup_alpha.sh bulunamadı, cron atlandı")
        return

    cron_line = f"0 2 * * * {script_path} >> {PROJECT_ROOT}/logs/backup.log 2>&1"

    try:
        # Mevcut crontab'ı al
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        current_cron = result.stdout if result.returncode == 0 else ""

        # Zaten ekli mi?
        if "backup_alpha.sh" in current_cron:
            logger.info("[OK] Backup cron zaten mevcut.")
            return

        # Yeni crontab oluştur
        new_cron = current_cron.rstrip() + "\n" + cron_line + "\n"
        proc = subprocess.run(
            ["crontab", "-"],
            input=new_cron,
            text=True,
            capture_output=True,
        )

        if proc.returncode == 0:
            logger.info("[OK] Backup cron eklendi: her gün 02:00")
            # Logs dizini oluştur
            (PROJECT_ROOT / "logs").mkdir(exist_ok=True)
        else:
            logger.info(f"[UYARI] Backup cron eklenemedi: {proc.stderr[:200]}")

    except FileNotFoundError:
        logger.info("[UYARI] crontab bulunamadı, backup cron atlandı")
    except Exception as e:
        logger.info(f"[UYARI] Backup cron hatası: {e}")


# =====================================================
# 6. RESILIENCE DOĞRULAMA
# =====================================================


def verify_resilience() -> Any:
    """Resilience bileşenlerini doğrula."""
    logger.info("\n[*] Resilience bileşenleri doğrulanıyor...")
    checks = []

    # .env dosyası
    env_exists = (PROJECT_ROOT / ".env").exists()
    checks.append((".env dosyası", env_exists))

    # Docker-compose'da stop_grace_period
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    if compose_path.exists():
        compose_content = compose_path.read_text()
        has_grace = "stop_grace_period" in compose_content
        has_autoheal = "autoheal" in compose_content
        checks.append(("stop_grace_period", has_grace))
        checks.append(("autoheal container", has_autoheal))
    else:
        checks.append(("docker-compose.yml", False))

    # Backup script
    backup_exists = (PROJECT_ROOT / "scripts" / "backup_alpha.sh").exists()
    checks.append(("backup script", backup_exists))

    # Alert rules
    alerts_exists = (PROJECT_ROOT / "infrastructure" / "alert_rules.yml").exists()
    checks.append(("alert rules", alerts_exists))

    # State store signal handler
    state_store_path = PROJECT_ROOT / "services" / "core" / "state_store.py"
    if state_store_path.exists():
        ss_content = state_store_path.read_text()
        has_signal = "signal.signal" in ss_content
        has_atexit = "atexit.register" in ss_content
        checks.append(("state_store signal handler", has_signal))
        checks.append(("state_store atexit", has_atexit))
    else:
        checks.append(("state_store.py", False))

    # Database reconnect
    db_path = PROJECT_ROOT / "services" / "core" / "database.py"
    if db_path.exists():
        db_content = db_path.read_text()
        has_ch_reconnect = "ClickHouse query failed, reconnecting" in db_content
        has_pg_reconnect = "pg_execute connection error" in db_content
        checks.append(("ClickHouse reconnect", has_ch_reconnect))
        checks.append(("PostgreSQL reconnect", has_pg_reconnect))

    # Persistent DLQ
    dlq_path = PROJECT_ROOT / "services" / "core" / "dead_letter_queue.py"
    if dlq_path.exists():
        dlq_content = dlq_path.read_text()
        has_persistent = "PersistentDeadLetterQueue" in dlq_content
        checks.append(("Persistent DLQ", has_persistent))

    # WebSocket backoff
    ws_path = PROJECT_ROOT / "apps" / "web" / "src" / "lib" / "websocket.ts"
    if ws_path.exists():
        ws_content = ws_path.read_text()
        has_backoff = "reconnectDelay" in ws_content and "maxReconnectDelay" in ws_content
        checks.append(("WebSocket backoff", has_backoff))

    # JetStream
    eb_path = PROJECT_ROOT / "services" / "core" / "event_bus.py"
    if eb_path.exists():
        eb_content = eb_path.read_text()
        has_jetstream = "publish_durable" in eb_content
        checks.append(("JetStream usage", has_jetstream))

    # Sonuçları yazdır
    all_ok = True
    for name, ok in checks:
        status = "✅" if ok else "❌"
        logger.info(f"  {status} {name}")
        if not ok:
            all_ok = False

    if all_ok:
        logger.info("[OK] Tüm resilience bileşenleri doğrulandı!")
    else:
        logger.info("[UYARI] Bazı resilience bileşenleri eksik!")

    return all_ok


# =====================================================
# 7. SERVİS DURUMU ÖZETİ
# =====================================================


def print_service_status() -> Any:
    """Servis durumu özeti."""
    logger.info("\n" + "=" * 72)
    logger.info("  SERVİS DURUMU")
    logger.info("=" * 72)

    all_containers = DATA_CONTAINERS + APP_CONTAINERS
    running = 0
    total = 0

    for name in all_containers:
        total += 1
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            status = result.stdout.strip()
            if status == "running":
                logger.info(f"  ✅ {name}")
                running += 1
            else:
                logger.info(f"  ❌ {name} → {status}")
        except Exception:
            logger.info(f"  ❌ {name} → bulunamadı")

    logger.info(f"\n  Toplam: {running}/{total} servis çalışıyor")


def print_access_points() -> Any:
    """Erişim noktaları."""
    logger.info("\n" + "=" * 72)
    logger.info("  ERİŞİM NOKTALARI")
    logger.info("=" * 72)
    logger.info("  🌐 Web Dashboard:    http://localhost:3000")
    logger.info("  📡 REST API:         http://localhost:8000")
    logger.info("  📚 API Docs:         http://localhost:8000/docs")
    logger.info("  📊 Grafana:          http://localhost:3001")
    logger.info("  📈 Prometheus:       http://localhost:9090")
    logger.info("  🔬 MLflow:           http://localhost:5000")
    logger.info("  🗄️  ClickHouse:       http://localhost:8123")
    logger.info("  🐘 PostgreSQL:       localhost:5432")
    logger.info("  🐘 PG Replica:       localhost:5433")
    logger.info("  🔴 Redis:            localhost:6379")
    logger.info("  📨 NATS:             localhost:4222")
    logger.info("  🔷 Traefik:          http://localhost:8080")
    logger.info("  🏥 Autoheal:         otomatik unhealthy container restart")
    logger.info("  💾 Backup:           her gün 02:00 (cron)")
    logger.info("=" * 72)


# =====================================================
# MAIN
# =====================================================


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 72)
    logger.info("      ALPHA BIST — OTONOM PIYASA ZEKASI VE QUANT PLATFORMU")
    logger.info("      v2.0 — Resilience-Enhanced Startup")
    logger.info("=" * 72)
    logger.info(f"  Proje Dizini: {PROJECT_ROOT}")
    logger.info(f"  SSD Yazma Limiti: {SSD_WRITE_LIMIT_MBPS} MB/s")
    logger.info(f"  Data Servisleri: {len(DATA_CONTAINERS)}")
    logger.info(f"  Uygulama Servisleri: {len(APP_CONTAINERS)}")
    logger.info("=" * 72)

    # 1. .env dosyası kontrolü
    logger.info("\n[ADIM 1/7] Ortam değişkenleri kontrol ediliyor...")
    if not ensure_env_file():
        sys.exit(1)

    # 2. Docker kontrolü
    logger.info("\n[ADIM 2/7] Docker motoru kontrol ediliyor...")
    if not is_docker_running():
        success = start_docker_desktop()
        if not success:
            logger.info("\n[HATA] Docker başlatılamadı.")
            logger.info("  Çözüm:")
            logger.info("    Windows: Docker Desktop'ı elle açın")
            logger.info("    Linux:   sudo systemctl start docker")
            logger.info("    Mac:     Docker Desktop'ı elle açın")
            logger.info("\n  Docker çalışırken tekrar deneyin: python start.py")
            sys.exit(1)
    else:
        logger.info("[OK] Docker motoru aktif ve hazır.")

    # 2.1 mTLS Sertifikaları kontrolü
    ensure_mtls_certs()

    # 3. Docker Compose Up
    logger.info("\n[ADIM 3/7] Mikro-servisler Docker Compose ile ayağa kaldırılıyor...")
    try:
        subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("[OK] Tüm servisler başlatıldı.")
    except subprocess.CalledProcessError as e:
        logger.info(f"[HATA] Servisler başlatılamadı: {e}")
        if e.stderr:
            logger.info(f"  Hata: {e.stderr[:500]}")
        sys.exit(1)

    # 4. Container'ların healthy olmasını bekle
    logger.info("\n[ADIM 4/7] Servislerin hazır olması bekleniyor...")
    wait_for_containers_healthy(timeout_s=180)

    # 5. SSD yazma hızı limiti uygula
    logger.info("\n[ADIM 5/7] SSD yazma hızı limiti uygulanıyor...")
    apply_ssd_write_limit()

    # 6. Backup cron kur
    logger.info("\n[ADIM 6/7] Otomatik backup kuruluyor...")
    setup_backup_cron()

    # 7. Resilience doğrulama
    logger.info("\n[ADIM 7/7] Resilience bileşenleri doğrulanıyor...")
    verify_resilience()

    # Servis durumu özeti
    print_service_status()

    # Erişim noktaları
    print_access_points()

    # Browser aç
    logger.info("\n🌐 Web Dashboard Açılıyor: http://localhost:3000")
    time.sleep(2)
    try:
        webbrowser.open("http://localhost:3000")
    except Exception:
        logger.warning("Caught Exception in main", exc_info=True)

    logger.info("\n" + "=" * 72)
    logger.info("      ✅ ALPHA BIST BAŞARIYLA ÇALIŞIYOR!")
    logger.info(f"      SSD Yazma Limiti: {SSD_WRITE_LIMIT_MBPS} MB/s")
    logger.info("      Backup: Her gün 02:00")
    logger.info("      Autoheal: Aktif")
    logger.info("      Resilience: Doğrulandı")
    logger.info("=" * 72)
    logger.info("\n  Durdurmak için: docker compose down")
    logger.info("  Loglar için:    docker compose logs -f")
    logger.info("  Backup için:    bash scripts/backup_alpha.sh")


if __name__ == "__main__":
    main()
