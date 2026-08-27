#!/usr/bin/env python3
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


async def main():
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

    print(f"📦 Parquet Export başlıyor... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"   Çıktı dizini: {args.output}")
    print()

    if args.table:
        # Tek tablo
        result = await research_engine.export_timescaledb_to_parquet(
            table=args.table,
            parquet_path=f"{args.output}/{args.table}.parquet",
            where=args.where,
        )
        print(f"✅ {args.table}: {result.get('rows_exported', 0)} satır export edildi")
    else:
        # Tüm tablolar
        results = await research_engine.export_all_timescaledb(args.output)

        print()
        print("=" * 50)
        print("📊 EXPORT ÖZETİ")
        print("=" * 50)

        success = 0
        failed = 0
        for r in results:
            if "error" in r:
                print(f"❌ {r['table']}: {r['error']}")
                failed += 1
            else:
                print(f"✅ {r['table']}: {r['rows_exported']} satır, {r.get('file_size_bytes', 0) / 1024:.1f} KB")
                success += 1

        print()
        print(f"   Başarılı: {success}")
        print(f"   Başarısız: {failed}")

    research_engine.close()


if __name__ == "__main__":
    asyncio.run(main())
