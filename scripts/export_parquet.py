#!/usr/bin/env python3
import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""ALPHA BIST — Parquet Export Scheduler

TimescaleDB tablolarını Parquet formatına aktarır.
DuckDB araştırma motoru için veri hazırlar.

Kullanım:
    python scripts/export_parquet.py                    # Tüm tablolar
    python scripts/export_parquet.py --table model_predictions  # Tek tablo
    python scripts/export_parquet.py --output data/parquet  # Özel çıktı dizini
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.core.duckdb_research import research_engine


async def main() -> Any:
    """Otomatik eklendi."""
    parser = argparse.ArgumentParser(description="TimescaleDB → Parquet Export")
    parser.add_argument(
        "--table",
        type=str,
        help="Tek tablo export et (varsayılan: tümü)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/parquet",
        help="Çıktı dizini (varsayılan: data/parquet)",
    )
    parser.add_argument(
        "--where",
        type=str,
        default="",
        help="Filtre koşulu",
    )
    args = parser.parse_args()

    logger.info(f"📦 Parquet Export başlıyor... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    logger.info(f"   Çıktı dizini: {args.output}")
    logger.info()

    if args.table:
        # Tek tablo
        result = await research_engine.export_timescaledb_to_parquet(
            table=args.table,
            parquet_path=f"{args.output}/{args.table}.parquet",
            where=args.where,
        )
        logger.info(f"✅ {args.table}: {result.get('rows_exported', 0)} satır export edildi")
    else:
        # Tüm tablolar
        results = await research_engine.export_all_timescaledb(args.output)

        logger.info()
        logger.info("=" * 50)
        logger.info("📊 EXPORT ÖZETİ")
        logger.info("=" * 50)

        success = 0
        failed = 0
        for r in results:
            if "error" in r:
                logger.info(f"❌ {r['table']}: {r['error']}")
                failed += 1
            else:
                logger.info(f"✅ {r['table']}: {r['rows_exported']} satır, {r.get('file_size_bytes', 0) / 1024:.1f} KB")
                success += 1

        logger.info()
        logger.info(f"   Başarılı: {success}")
        logger.info(f"   Başarısız: {failed}")

    research_engine.close()


if __name__ == "__main__":
    asyncio.run(main())
