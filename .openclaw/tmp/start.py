#!/usr/bin/env python3
"""ALPHA BIST — Start Script (`./alpha start` tarafından çağrılır).

.. deprecated:: 4.1
    Bu dosya yerine ``python main.py`` kullanın.
    ``main.py`` canonical entry point olarak belirlenmiştir.
    Bu dosya geriye uyumluluk için tutulmaktadır ve gelecekte kaldırılabilir.
"""
import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    import warnings
    warnings.warn(
        "start.py is deprecated. Use 'python main.py' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="daily", choices=["daily", "scan", "scheduler"])
    args = parser.parse_args()

    if args.mode == "scan":
        from main import run_daily_pipeline
        from datetime import datetime
        run_daily_pipeline(datetime.now().strftime("%Y-%m-%d"))
    elif args.mode == "scheduler":
        from main import run_live_scheduler
        run_live_scheduler()
    else:
        from main import run_daily_pipeline, run_live_scheduler
        from datetime import datetime
        now = datetime.now()
        if 9 <= now.hour < 18:
            run_live_scheduler()
        else:
            run_daily_pipeline(now.strftime("%Y-%m-%d"))

if __name__ == "__main__":
    main()
