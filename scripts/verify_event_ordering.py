import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — Temizlenmiş & Alakalı Makro Olay Doğrulama Testi
"""

import os
import sys

import requests

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def test_events() -> Any:
    """Otomatik eklendi."""
    r = requests.get("http://localhost:8000/api/v1/event-study/events").json()
    events = r.get("events", [])
    logger.info("=" * 110)
    logger.info(f"{'SIRA':<5} | {'ZAMAN':<12} | {'TİP':<6} | {'DUYGU':<8} | {'KAYNAK':<26} | {'BAŞLIK'}")
    logger.info("=" * 110)
    for e in events[:12]:
        sent_str = f"{int(e['sentiment'] * 100):+d}%"
        logger.info(
            f"{e['id']:<5} | {e['timestamp']:<12} | {e['type']:<6} | {sent_str:<8} | {e['source'][:24]:<26} | {e['title'][:55]}"
        )


if __name__ == "__main__":
    test_events()
