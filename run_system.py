#!/usr/bin/env python3
"""
ALPHA BIST — System Runner

.. deprecated:: 4.1
    Bu dosya yerine ``python main.py`` kullanın.
    ``main.py`` canonical entry point olarak belirlenmiştir.
    Bu dosya geriye uyumluluk için tutulmaktadır ve gelecekte kaldırılabilir.

Sistem çalıştırıcı — tek tarama veya sürekli çalışma modu.

Kullanım (deprecated):
    python3 run_system.py --scan-once    # Tek tarama yap ve çık
    python3 run_system.py --continuous   # Sürekli çalışma
    python3 run_system.py --health       # Sağlık kontrolü

Kullanım (canonical):
    python main.py --mode daily
    python main.py --mode live
    python main.py --mode health
"""

import sys
import argparse
from pathlib import Path

# Proje kökünü Python path'e ekle
sys.path.insert(0, str(Path(__file__).parent))


def main():
    import warnings
    warnings.warn(
        "run_system.py is deprecated. Use 'python main.py' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    parser = argparse.ArgumentParser(description="ALPHA BIST System Runner (deprecated, use main.py)")
    parser.add_argument("--scan-once", action="store_true", help="Tek tarama yap ve çık")
    parser.add_argument("--continuous", action="store_true", help="Sürekli çalışma modu")
    parser.add_argument("--health", action="store_true", help="Sistem sağlık kontrolü")
    parser.add_argument("--date", default=None, help="Tarih (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.health:
        from main import run_health_check
        run_health_check()
    elif args.scan_once:
        from main import run_daily_pipeline
        from datetime import datetime
        date = args.date or datetime.now().strftime("%Y-%m-%d")
        run_daily_pipeline(date)
    elif args.continuous:
        from main import run_live_scheduler
        run_live_scheduler()
    else:
        # Varsayılan: tek tarama
        from main import run_daily_pipeline
        from datetime import datetime
        date = args.date or datetime.now().strftime("%Y-%m-%d")
        run_daily_pipeline(date)


if __name__ == "__main__":
    main()
