#!/usr/bin/env python3
import structlog
logger = structlog.get_logger(__name__)
from typing import Any
"""ALPHA BIST — PostgreSQL Query Performance Auditor

Ağır sorguları tespit eder, EXPLAIN ANALYZE ile analiz eder.
Crontab: 0 6 * * 1 (Haftalık Pazartesi 06:00)

Kullanım:
    python scripts/audit_query_performance.py
    python scripts/audit_query_performance.py --threshold 500  # ms
    python scripts/audit_query_performance.py --output report.md
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

from services.core.config import settings

# =====================================================
# CONFIGURATION
# =====================================================

DEFAULT_SLOW_QUERY_THRESHOLD_MS = 500
TOP_N_QUERIES = 20

# Kritik tablolar ve beklenen index'ler
CRITICAL_TABLES = {
    "model_predictions": ["instrument_id", "prediction_date", "created_at"],
    "daily_performance": ["date", "strategy_id"],
    "signals": ["instrument_id", "strategy_id", "status", "created_at"],
    "positions": ["portfolio_id", "instrument_id", "status"],
    "orders": ["portfolio_id", "status", "created_at"],
    "alerts": ["alert_type", "severity", "created_at"],
    "scan_results": ["scan_id", "created_at"],
    "audit_logs": ["entity_type", "entity_id", "created_at"],
    "companies": ["ticker", "sector_id"],
    "instruments": ["symbol", "company_id"],
}


async def get_connection() -> Any:
    """PostgreSQL bağlantısı."""
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


async def check_pg_stat_statements(conn) -> Any:
    """pg_stat_statements extension kontrolü."""
    ext = await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
    if not ext:
        logger.info("⚠️  pg_stat_statements extension aktif değil!")
        logger.info("   Aktif etmek için: CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")
        return False
    return True


async def get_slow_queries(conn, threshold_ms: int) -> Any:
    """Yavaş sorguları pg_stat_statements'den çek."""
    try:
        rows = await conn.fetch(
            """
            SELECT
                queryid,
                query,
                calls,
                total_exec_time / calls as avg_time_ms,
                max_exec_time as max_time_ms,
                mean_exec_time as mean_time_ms,
                rows / NULLIF(calls, 0) as avg_rows,
                shared_blks_hit,
                shared_blks_read,
                CASE
                    WHEN shared_blks_hit + shared_blks_read > 0
                    THEN round(shared_blks_hit::numeric / (shared_blks_hit + shared_blks_read) * 100, 2)
                    ELSE 100
                END as cache_hit_ratio
            FROM pg_stat_statements
            WHERE calls > 0
                AND total_exec_time / calls > $1
            ORDER BY total_exec_time / calls DESC
            LIMIT $2
            """,
            threshold_ms,
            TOP_N_QUERIES,
        )
        return rows
    except Exception as e:
        logger.info(f"⚠️  pg_stat_statements sorgulanamadı: {e}")
        return []


async def get_table_stats(conn) -> Any:
    """Tablo istatistikleri."""
    rows = await conn.fetch(
        """
        SELECT
            schemaname,
            relname as table_name,
            n_live_tup as row_count,
            n_dead_tup as dead_rows,
            CASE
                WHEN n_live_tup > 0
                THEN round(n_dead_tup::numeric / n_live_tup * 100, 2)
                ELSE 0
            END as dead_ratio,
            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze
        FROM pg_stat_user_tables
        ORDER BY n_dead_tup DESC
        LIMIT 30
        """
    )
    return rows


async def get_index_usage(conn) -> Any:
    """Index kullanım istatistikleri."""
    rows = await conn.fetch(
        """
        SELECT
            schemaname,
            relname as table_name,
            indexrelname as index_name,
            idx_scan as index_scans,
            idx_tup_read as tuples_read,
            idx_tup_fetch as tuples_fetched,
            pg_size_pretty(pg_relation_size(indexrelid)) as index_size
        FROM pg_stat_user_indexes
        ORDER BY idx_scan ASC
        LIMIT 30
        """
    )
    return rows


async def get_missing_indexes(conn) -> Any:
    """Eksik index tespiti — sequential scan yapan büyük tablolar."""
    rows = await conn.fetch(
        """
        SELECT
            relname as table_name,
            seq_scan,
            seq_tup_read,
            idx_scan,
            n_live_tup as row_count,
            CASE
                WHEN seq_scan + idx_scan > 0
                THEN round(seq_scan::numeric / (seq_scan + idx_scan) * 100, 2)
                ELSE 0
            END as seq_scan_ratio
        FROM pg_stat_user_tables
        WHERE n_live_tup > 10000
            AND seq_scan > 100
        ORDER BY seq_tup_read DESC
        LIMIT 20
        """
    )
    return rows


async def get_index_bloat(conn) -> Any:
    """Index şişmesi kontrolü."""
    rows = await conn.fetch(
        """
        SELECT
            schemaname,
            tablename,
            indexname,
            pg_size_pretty(pg_relation_size(indexname::regclass)) as index_size,
            pg_size_pretty(pg_relation_size(tablename::regclass)) as table_size
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY pg_relation_size(indexname::regclass) DESC
        LIMIT 20
        """
    )
    return rows


async def get_locks(conn) -> Any:
    """Aktif lock'lar."""
    rows = await conn.fetch(
        """
        SELECT
            pid,
            wait_event_type,
            wait_event,
            state,
            query,
            now() - query_start as duration
        FROM pg_stat_activity
        WHERE state != 'idle'
            AND pid != pg_backend_pid()
        ORDER BY query_start
        LIMIT 10
        """
    )
    return rows


async def get_replication_lag(conn) -> Any:
    """Replikasyon lag kontrolü."""
    try:
        rows = await conn.fetch(
            """
            SELECT
                client_addr,
                state,
                sent_lsn,
                write_lsn,
                flush_lsn,
                replay_lsn,
                pg_wal_lsn_diff(sent_lsn, replay_lsn) as replay_lag_bytes
            FROM pg_stat_replication
            """
        )
        return rows
    except Exception:
        return []


async def explain_analyze(conn, query: str, params=None) -> Any:
    """EXPLAIN ANALYZE çalıştır."""
    try:
        explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"
        if params:
            result = await conn.fetchval(explain_query, *params)
        else:
            result = await conn.fetchval(explain_query)
        return json.loads(result)
    except Exception as e:
        return {"error": str(e)}


async def check_table_indexes(conn, table_name: str) -> Any:
    """Belirli bir tablonun index'lerini kontrol et."""
    rows = await conn.fetch(
        """
        SELECT
            indexname,
            indexdef
        FROM pg_indexes
        WHERE tablename = $1
            AND schemaname = 'public'
        ORDER BY indexname
        """,
        table_name,
    )
    return rows


async def check_composite_indexes(conn) -> Any:
    """Composite index ihtiyacı analizi."""
    findings = []

    for table, expected_cols in CRITICAL_TABLES.items():
        # Mevcut index'leri al
        indexes = await check_table_indexes(conn, table)
        indexed_cols = set()
        for idx in indexes:
            # Index definition'dan column'ları çıkar
            idxdef = idx["indexdef"]
            for col in expected_cols:
                if col in idxdef:
                    indexed_cols.add(col)

        missing = set(expected_cols) - indexed_cols
        if missing:
            findings.append(
                {
                    "table": table,
                    "missing_indexed_columns": list(missing),
                    "existing_indexes": [idx["indexname"] for idx in indexes],
                }
            )

    return findings


def generate_report(
    slow_queries,
    table_stats,
    index_usage,
    missing_indexes,
    index_bloat,
    locks,
    replication_lag,
    composite_findings,
    threshold_ms,
) -> Any:
    """Markdown rapor oluştur."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = f"""# 🔍 PostgreSQL Query Performance Raporu

> **Oluşturulma:** {now}
> **Eşik:** {threshold_ms}ms
> **Kapsam:** pg_stat_statements, tablo istatistikleri, index analizi

---

## 📊 Yavaş Sorgular (>{threshold_ms}ms ortalama)

"""
    if slow_queries:
        report += "| # | Ortalama (ms) | Max (ms) | Çağrı | Cache Hit % | Sorgu (kısaltılmış) |\n"
        report += "|---|---|---|---|---|---|\n"
        for i, q in enumerate(slow_queries, 1):
            query_short = q["query"][:80].replace("|", "\\|").replace("\n", " ")
            report += f"| {i} | {q['avg_time_ms']:.1f} | {q['max_time_ms']:.1f} | {q['calls']} | {q['cache_hit_ratio']}% | `{query_short}` |\n"
    else:
        report += "✅ Yavaş sorgu tespit edilmedi.\n"

    report += "\n---\n\n## 📋 Tablo İstatistikleri\n\n"
    report += "| Tablo | Satır | Dead | Dead % | Son Vacuum | Son Analyze |\n"
    report += "|---|---|---|---|---|---|\n"
    for t in table_stats[:15]:
        vacuum = t["last_autovacuum"] or t["last_vacuum"] or "Yok"
        analyze = t["last_autoanalyze"] or t["last_analyze"] or "Yok"
        if isinstance(vacuum, datetime):
            vacuum = vacuum.strftime("%Y-%m-%d %H:%M")
        if isinstance(analyze, datetime):
            analyze = analyze.strftime("%Y-%m-%d %H:%M")
        report += f"| {t['table_name']} | {t['row_count']:,} | {t['dead_rows']:,} | {t['dead_ratio']}% | {vacuum} | {analyze} |\n"

    report += "\n---\n\n## 📉 Kullanılmayan Index'ler\n\n"
    unused = [idx for idx in index_usage if idx["index_scans"] == 0]
    if unused:
        report += "| Tablo | Index | Boyut |\n"
        report += "|---|---|---|\n"
        for idx in unused[:10]:
            report += f"| {idx['table_name']} | {idx['index_name']} | {idx['index_size']} |\n"
        report += "\n⚠️ Bu index'ler hiç kullanılmamış. Gerekli olup olmadığını değerlendirin.\n"
    else:
        report += "✅ Tüm index'ler kullanılıyor.\n"

    report += "\n---\n\n## 🔍 Sequential Scan Oranı Yüksek Tablolar\n\n"
    if missing_indexes:
        report += "| Tablo | Seq Scan | Idx Scan | Seq % | Satır |\n"
        report += "|---|---|---|---|---|\n"
        for m in missing_indexes[:10]:
            report += f"| {m['table_name']} | {m['seq_scan']:,} | {m['idx_scan']:,} | {m['seq_scan_ratio']}% | {m['row_count']:,} |\n"
        report += "\n⚠️ Bu tablolarda index kullanımı düşük. Composite index gerekebilir.\n"
    else:
        report += "✅ Sequential scan oranları normal.\n"

    report += "\n---\n\n## 🏗️ Composite Index Analizi\n\n"
    if composite_findings:
        for f in composite_findings:
            report += f"### {f['table']}\n"
            report += f"- **Eksik index'lenmiş sütunlar:** {', '.join(f['missing_indexed_columns'])}\n"
            report += (
                f"- **Mevcut index'ler:** {', '.join(f['existing_indexes']) if f['existing_indexes'] else 'Yok'}\n\n"
            )
    else:
        report += "✅ Kritik tablolar için index stratejisi yeterli.\n"

    report += "\n---\n\n## 📦 Index Boyutları (En Büyük)\n\n"
    report += "| Tablo | Index | Index Boyut | Tablo Boyut |\n"
    report += "|---|---|---|---|\n"
    for b in index_bloat[:10]:
        report += f"| {b['tablename']} | {b['indexname']} | {b['index_size']} | {b['table_size']} |\n"

    report += "\n---\n\n## 🔒 Aktif Lock'lar\n\n"
    if locks:
        report += "| PID | State | Duration | Sorgu (kısaltılmış) |\n"
        report += "|---|---|---|---|\n"
        for l in locks:
            query_short = l["query"][:60].replace("|", "\\|").replace("\n", " ") if l["query"] else "N/A"
            report += f"| {l['pid']} | {l['state']} | {l['duration']} | `{query_short}` |\n"
    else:
        report += "✅ Aktif lock yok.\n"

    report += "\n---\n\n## 🔄 Replikasyon Lag\n\n"
    if replication_lag:
        for r in replication_lag:
            lag_bytes = r["replay_lag_bytes"] or 0
            lag_mb = lag_bytes / (1024 * 1024)
            report += f"- **Client:** {r['client_addr']} | **State:** {r['state']} | **Lag:** {lag_mb:.2f} MB\n"
    else:
        report += "ℹ️ Replikasyon yok veya tespit edilemedi.\n"

    report += "\n---\n\n## 📌 Öneriler\n\n"

    recommendations = []
    if slow_queries:
        recommendations.append("🔴 Yavaş sorguları optimize edin veya index ekleyin")
    if unused:
        recommendations.append(f"🟠 {len(unused)} kullanılmayan index var — gereksiz yazma yükü")
    if missing_indexes:
        recommendations.append("🔴 Sequential scan oranı yüksek tablolar için composite index ekleyin")
    if composite_findings:
        recommendations.append("🟠 Kritik tablolar için eksik index'leri değerlendirin")
    dead_tables = [t for t in table_stats if t["dead_ratio"] > 10]
    if dead_tables:
        recommendations.append(f"🔴 {len(dead_tables)} tabloda dead row oranı %10'un üstünde — VACUUM ANALYZE gerekli")

    if recommendations:
        for r in recommendations:
            report += f"- {r}\n"
    else:
        report += "✅ Kritik sorun tespit edilmedi.\n"

    return report


async def main() -> Any:
    """Otomatik eklendi."""
    parser = argparse.ArgumentParser(description="PostgreSQL Query Performance Auditor")
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_SLOW_QUERY_THRESHOLD_MS,
        help=f"Yavaş sorgu eşiği (ms), varsayılan: {DEFAULT_SLOW_QUERY_THRESHOLD_MS}",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="reports/query_performance_audit.md",
        help="Çıktı dosyası",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON formatında çıktı",
    )
    args = parser.parse_args()

    logger.info(f"🔍 PostgreSQL Query Performance Audit başlıyor... (eşik: {args.threshold}ms)")

    conn = await get_connection()
    try:
        # pg_stat_statements kontrolü
        has_pss = await check_pg_stat_statements(conn)

        # Veri topla
        slow_queries = await get_slow_queries(conn, args.threshold) if has_pss else []
        table_stats = await get_table_stats(conn)
        index_usage = await get_index_usage(conn)
        missing_indexes = await get_missing_indexes(conn)
        index_bloat = await get_index_bloat(conn)
        locks = await get_locks(conn)
        replication_lag = await get_replication_lag(conn)
        composite_findings = await check_composite_indexes(conn)

        if args.json:
            data = {
                "timestamp": datetime.now().isoformat(),
                "threshold_ms": args.threshold,
                "slow_queries": [dict(q) for q in slow_queries],
                "table_stats": [dict(t) for t in table_stats],
                "index_usage": [dict(i) for i in index_usage],
                "missing_indexes": [dict(m) for m in missing_indexes],
                "composite_findings": composite_findings,
            }
            output = json.dumps(data, indent=2, default=str)
        else:
            output = generate_report(
                slow_queries,
                table_stats,
                index_usage,
                missing_indexes,
                index_bloat,
                locks,
                replication_lag,
                composite_findings,
                args.threshold,
            )

        # Çıktı dosyasına yaz
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        logger.info(f"✅ Rapor kaydedildi: {output_path}")

        # Konsola özet yaz
        logger.info("\n📊 ÖZET:")
        logger.info(f"   Yavaş sorgu: {len(slow_queries)}")
        logger.info(f"   Tablo: {len(table_stats)}")
        logger.info(f"   Kullanılmayan index: {len([i for i in index_usage if i['index_scans'] == 0])}")
        logger.info(f"   Seq scan yüksek tablo: {len(missing_indexes)}")
        logger.info(f"   Eksik composite index: {len(composite_findings)}")
        logger.info(f"   Aktif lock: {len(locks)}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
