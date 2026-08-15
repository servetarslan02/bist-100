"""
ALPHA BIST — Full System Runner v1.0

Tüm sistemi tek komutla başlatır:
- Data pipeline
- Feature engine
- Opportunity scanner
- Decision engine
- Risk engine
- Portfolio
- API server
- WebSocket server
- Dashboard

Kullanım:
  python3 start.py                # Her şeyi başlat
  python3 start.py --scan-once    # Tek tarama
  python3 start.py --api-only     # Sadece API
"""

import asyncio
import sys
import os
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

import structlog
from services.core.logging import setup_logging

logger = structlog.get_logger()


async def run_full_system(scan_once: bool = False, api_port: int = 8000, ws_port: int = 8765):
    """Tam sistem çalıştır."""
    setup_logging("INFO")

    print("=" * 70)
    print("  ⚡ ALPHA BIST — Market Intelligence & Quant Engine")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    # 1. System runner
    from run_system import AlphaSystem
    system = AlphaSystem(scan_once=scan_once, api_port=api_port)

    # 2. API server (background thread)
    if not scan_once:
        from services.api.server import run_api_server
        api_thread = threading.Thread(
            target=run_api_server,
            args=(api_port, system),
            daemon=True,
        )
        api_thread.start()
        print(f"  🌐 API: http://localhost:{api_port}")
        print(f"  📊 Dashboard: http://localhost:{api_port}/")
        print()

    # 3. Start system
    await system.start()


def main():
    parser = argparse.ArgumentParser(description="ALPHA BIST Full System")
    parser.add_argument("--scan-once", action="store_true", help="Tek tarama yap ve çık")
    parser.add_argument("--api-port", type=int, default=8000, help="API portu")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket portu")
    args = parser.parse_args()

    asyncio.run(run_full_system(
        scan_once=args.scan_once,
        api_port=args.api_port,
        ws_port=args.ws_port,
    ))


if __name__ == "__main__":
    main()
