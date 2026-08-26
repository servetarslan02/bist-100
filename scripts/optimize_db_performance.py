"""
ALPHA BIST — Database Performance Optimization Script

PostgreSQL performans optimizasyonları:
- Index analizi ve optimizasyonu
- Table bloat tespiti
- Vacuum/Analyze tetikleme
- Materialized view yenileme
- Sorgu performans analizi
- Bağlantı havuzu kontrolü

Kullanım:
    python scripts/optimize_db_performance.py [--analyze] [--vacuum] [--refresh-views] [--slow-queries]
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.core.database import get_pg_pool, check_db_health
import structlog

logger = structlog.get_logger()


async def analyze_tables():
    """Tüm tabloları ANALYZ et."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        # Kullanıcı tablolarını bul
        tables = await conn.fetch("""
            SELECT schemaname, tablename
            FROM pg_stat_user_tables
            ORDER BY tablename
        """)

        print(f"\n📊 {len(tables)} tablo ANALYZ ediliyor...")
        for table in tables:
            schema = table['schemaname']
            name = table['tablename']
            await conn.execute(f'ANALYZE "{schema}"."{name}"')
            print(f"  ✅ {schema}.{name}")

    print("\n✅ ANALYZE tamamlandı.")


async def vacuum_tables():
    """Kritik tabloları VACUUM et."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        # Dead row oranı yüksek tabloları bul
        tables = await conn.fetch("""
            SELECT
                schemaname,
                relname as tablename,
                n_dead_tup,
                n_live_tup,
                CASE WHEN n_live_tup > 0
                     THEN ROUND(n_dead_tup::numeric / n_live_tup * 100, 2)
                     ELSE 0
                END as dead_pct
            FROM pg_stat_user_tables
            WHERE n_dead_tup > 1000
            ORDER BY n_dead_tup DESC
            LIMIT 20
        """)

        print(f"\n🧹 {len(tables)} tablo VACUUM ediliyor (dead rows > 1000)...")
        for table in tables:
            schema = table['schemaname']
            name = table['tablename']
            dead = table['n_dead_tup']
            pct = table['dead_pct']
            print(f"  🔄 {schema}.{name}: {dead} dead rows ({pct}%)")
            await conn.execute(f'VACUUM ANALYZE "{schema}"."{name}"')
            print(f"  ✅ {schema}.{name} tamamlandı")

    print("\n✅ VACUUM tamamlandı.")


async def refresh_materialized_views():
    """Materialized view'ları yenile."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        views = await conn.fetch("""
            SELECT schemaname, matviewname
            FROM pg_matviews
            WHERE schemaname = 'public'
            ORDER BY matviewname
        """)

        print(f"\n🔄 {len(views)} materialized view yenileniyor...")
        for view in views:
            schema = view['schemaname']
            name = view['matviewname']
            print(f"  🔄 {schema}.{name}...")
            await conn.execute(f'REFRESH MATERIALIZED VIEW CONCURRENTLY "{schema}"."{name}"')
            print(f"  ✅ {schema}.{name} tamamlandı")

    print("\n✅ Materialized views yenilendi.")


async def show_slow_queries(limit: int = 20):
    """Yavaş sorguları göster."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        try:
            queries = await conn.fetch("""
                SELECT
                    query,
                    calls,
                    ROUND(total_exec_time::numeric, 2) as total_time_ms,
                    ROUND(mean_exec_time::numeric, 2) as mean_time_ms,
                    ROUND(stddev_exec_time::numeric, 2) as stddev_ms,
                    rows,
                    ROUND(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0), 2) as cache_hit_pct
                FROM pg_stat_statements
                WHERE calls > 5
                ORDER BY mean_exec_time DESC
                LIMIT $1
            """, limit)

            print(f"\n🐌 En Yavaş {limit} Sorgu:")
            print("-" * 100)
            print(f"{'Ort. Süre':>10} {'Toplam':>10} {'Çağrı':>6} {'Satır':>8} {'Cache%':>7}  Sorgu")
            print("-" * 100)

            for q in queries:
                query_short = q['query'][:60].replace('\n', ' ')
                print(f"{q['mean_time_ms']:>9.1f}ms {q['total_time_ms']:>9.1f}ms {q['calls']:>6} {q['rows']:>8} {q['cache_hit_pct'] or 0:>6.1f}%  {query_short}")

        except Exception as e:
            print(f"\n⚠️ pg_stat_statements extension bulunamadı: {e}")
            print("   Docker-compose'da shared_preload_libraries'a pg_stat_statements ekleyin.")


async def show_table_sizes():
    """Tablo boyutlarını göster."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        tables = await conn.fetch("""
            SELECT
                tablename,
                pg_size_pretty(pg_total_relation_size('public.'||tablename)) as total_size,
                pg_size_pretty(pg_relation_size('public.'||tablename)) as table_size,
                pg_size_pretty(pg_indexes_size('public.'||tablename)) as index_size,
                n_live_tup as row_count,
                n_dead_tup as dead_rows
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size('public.'||tablename) DESC
            LIMIT 30
        """)

        print("\n📦 Tablo Boyutları (Top 30):")
        print("-" * 90)
        print(f"{'Tablo':<30} {'Toplam':>10} {'Veri':>10} {'Index':>10} {'Satır':>10} {'Dead':>10}")
        print("-" * 90)

        for t in tables:
            print(f"{t['tablename']:<30} {t['total_size']:>10} {t['table_size']:>10} {t['index_size']:>10} {t['row_count']:>10} {t['dead_rows']:>10}")


async def show_index_usage():
    """Index kullanım istatistiklerini göster."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        indexes = await conn.fetch("""
            SELECT
                tablename,
                indexname,
                idx_scan as scans,
                idx_tup_read as tuples_read,
                pg_size_pretty(pg_relation_size(indexrelid)) as size
            FROM pg_stat_user_indexes
            ORDER BY idx_scan ASC
            LIMIT 30
        """)

        print("\n📉 En Az Kullanılan Indexler (Top 30):")
        print("-" * 80)
        print(f"{'Tablo':<25} {'Index':<30} {'Tarama':>8} {'Boyut':>10}")
        print("-" * 80)

        for idx in indexes:
            print(f"{idx['tablename']:<25} {idx['indexname']:<30} {idx['scans']:>8} {idx['size']:>10}")


async def show_connection_stats():
    """Bağlantı istatistiklerini göster."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        stats = await conn.fetchrow("""
            SELECT
                (SELECT count(*) FROM pg_stat_activity) as total_connections,
                (SELECT count(*) FROM pg_stat_activity WHERE state = 'active') as active,
                (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle') as idle,
                (SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction') as idle_in_tx,
                (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_connections
        """)

        print("\n🔌 Bağlantı İstatistikleri:")
        print("-" * 40)
        print(f"  Toplam bağlantı: {stats['total_connections']}/{stats['max_connections']}")
        print(f"  Aktif:           {stats['active']}")
        print(f"  Boşta:           {stats['idle']}")
        print(f"  Idle in TX:      {stats['idle_in_tx']}")

        if stats['idle_in_tx'] > 5:
            print(f"\n  ⚠️ Uyarı: {stats['idle_in_tx']} bağlantı idle in transaction durumunda!")


async def show_cache_hit_ratio():
    """Cache hit ratio göster."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        ratio = await conn.fetchrow("""
            SELECT
                ROUND(
                    100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0),
                    2
                ) as cache_hit_pct
            FROM pg_stat_database
            WHERE datname = current_database()
        """)

        pct = ratio['cache_hit_pct'] or 0
        print(f"\n💾 Cache Hit Ratio: {pct}%")

        if pct < 95:
            print("  ⚠️ Uyarı: Cache hit ratio düşük! shared_buffers artırılmalı.")
        elif pct < 99:
            print("  ℹ️ İyi, ama daha iyi olabilir.")
        else:
            print("  ✅ Mükemmel!")


async def main():
    parser = argparse.ArgumentParser(description="ALPHA BIST DB Performance Optimization")
    parser.add_argument("--analyze", action="store_true", help="Tüm tabloları ANALYZ et")
    parser.add_argument("--vacuum", action="store_true", help="Dead row'ları VACUUM et")
    parser.add_argument("--refresh-views", action="store_true", help="Materialized view'ları yenile")
    parser.add_argument("--slow-queries", action="store_true", help="Yavaş sorguları göster")
    parser.add_argument("--table-sizes", action="store_true", help="Tablo boyutlarını göster")
    parser.add_argument("--index-usage", action="store_true", help="Index kullanımını göster")
    parser.add_argument("--connections", action="store_true", help="Bağlantı istatistiklerini göster")
    parser.add_argument("--cache", action="store_true", help="Cache hit ratio göster")
    parser.add_argument("--all", action="store_true", help="Tüm analizleri çalıştır")

    args = parser.parse_args()

    # Sağlık kontrolü
    health = await check_db_health()
    if health.get("postgres") != "healthy":
        print("❌ PostgreSQL bağlantısı kurulamadı!")
        sys.exit(1)

    print("✅ PostgreSQL bağlantısı sağlıklı.")

    if args.all or args.analyze:
        await analyze_tables()

    if args.all or args.vacuum:
        await vacuum_tables()

    if args.all or args.refresh_views:
        await refresh_materialized_views()

    if args.all or args.slow_queries:
        await show_slow_queries()

    if args.all or args.table_sizes:
        await show_table_sizes()

    if args.all or args.index_usage:
        await show_index_usage()

    if args.all or args.connections:
        await show_connection_stats()

    if args.all or args.cache:
        await show_cache_hit_ratio()

    if not any([args.analyze, args.vacuum, args.refresh_views, args.slow_queries,
                args.table_sizes, args.index_usage, args.connections, args.cache, args.all]):
        print("\nKullanım: python scripts/optimize_db_performance.py --all")
        print("  --analyze        ANALYZE tüm tablolar")
        print("  --vacuum         VACUUM dead rows")
        print("  --refresh-views  Materialized view yenile")
        print("  --slow-queries   Yavaş sorguları göster")
        print("  --table-sizes    Tablo boyutları")
        print("  --index-usage    Index kullanımı")
        print("  --connections    Bağlantı istatistikleri")
        print("  --cache          Cache hit ratio")
        print("  --all            Tüm analizler")


if __name__ == "__main__":
    asyncio.run(main())
