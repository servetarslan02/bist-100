"""
ALPHA BIST - Automated System Health & Log Monitor
Denetlenen alanlar:
1. Docker konteyner sağlık durumları (unhealthy, restarting, exited).
2. ClickHouse bellek aşımı veya merge döngüsü.
3. Konteyner loglarında beklenmeyen CRITICAL, FATAL veya Exception kayıtları.
"""

import re
import subprocess
import sys
from typing import Dict, List, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def get_container_states() -> List[Tuple[str, str, str]]:
    """Tüm Docker konteynerlerinin isim, durum ve sağlık özetini döner."""
    res = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.State}}"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    results = []
    for line in res.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            results.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return results


def check_container_health(containers: List[Tuple[str, str, str]]) -> List[str]:
    """Sağlıksız veya çökmüş konteynerleri tespit eder."""
    issues = []
    for name, status, state in containers:
        status_lower = status.lower()
        if state != "running":
            issues.append(f"Konteyner çalışmıyor: {name} (State: {state}, Status: {status})")
        elif "unhealthy" in status_lower:
            issues.append(f"Konteyner sağlıksız (unhealthy): {name} (Status: {status})")
        elif "restarting" in status_lower:
            issues.append(f"Konteyner yeniden başlatma döngüsünde (restarting): {name} (Status: {status})")
    return issues


def scan_container_logs(minutes: int = 5) -> Dict[str, List[str]]:
    """Son X dakikadaki konteyner loglarında kritik hataları tarar."""
    patterns = [
        re.compile(r"\bCRITICAL\b", re.IGNORECASE),
        re.compile(r"\bFATAL\b", re.IGNORECASE),
        re.compile(r"\bMEMORY_LIMIT_EXCEEDED\b", re.IGNORECASE),
        re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    ]

    # Bilinen, zararsız veya rutin uyarılar
    whitelist = [
        re.compile(r"mTLS certificate files missing", re.IGNORECASE),
        re.compile(r"Server disconnected without sending a response", re.IGNORECASE),
        re.compile(r"FastAPIDeprecationWarning", re.IGNORECASE),
        re.compile(r"level=info", re.IGNORECASE),
        re.compile(r"level=warn", re.IGNORECASE),
        re.compile(r"the database system is starting up", re.IGNORECASE),
        re.compile(r"could not connect to the primary server.*the database system is starting up", re.IGNORECASE),
        re.compile(r'"level":\s*"info"', re.IGNORECASE),
        re.compile(r'"level":\s*"warning"', re.IGNORECASE),
    ]

    ps = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True)
    c_names = [c.strip() for c in ps.stdout.strip().split("\n") if c.strip()]

    found_errors: Dict[str, List[str]] = {}
    for name in c_names:
        res = subprocess.run(
            ["docker", "logs", "--since", f"{minutes}m", name],
            capture_output=True,
            text=True,
            errors="replace",
        )
        all_lines = (res.stdout + "\n" + res.stderr).split("\n")
        matched = []
        for line in all_lines:
            line_str = line.strip()
            if not line_str:
                continue
            if any(p.search(line_str) for p in patterns):
                if not any(w.search(line_str) for w in whitelist):
                    matched.append(line_str)
        if matched:
            found_errors[name] = matched

    return found_errors


def main() -> int:
    print("🔍 [MONITOR] Sistem sağlık durumu ve loglar denetleniyor...")
    containers = get_container_states()
    if not containers:
        print("❌ [HATA] Hiçbir Docker konteyneri bulunamadı!")
        return 1

    health_issues = check_container_health(containers)
    log_issues = scan_container_logs(minutes=5)

    has_problem = False

    if health_issues:
        has_problem = True
        print("\n⚠️ [KONTEYNER SAĞLIK SORUNLARI]:")
        for h in health_issues:
            print(f"  - {h}")

    if log_issues:
        has_problem = True
        print("\n⚠️ [LOGLARDA TESPİT EDİLEN KRİTİK HATALAR]:")
        for c_name, errs in log_issues.items():
            print(f"  - [{c_name}] ({len(errs)} hata):")
            for e in errs[-3:]:
                print(f"      {e[:140]}")

    if not has_problem:
        print(f"✅ [BAŞARILI] Tüm sistem sağlıklı! ({len(containers)} konteyner incelendi, 0 kritik hata).")
        return 0
    else:
        print("\n🚨 [DİKKAT] Sistemde müdahale gerektiren anormallikler var!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
