#!/usr/bin/env python3
"""ALPHA BIST — TimescaleDB Health & Data Quality Auditor

TimescaleDB hypertable'ları, compression, retention ve veri kalitesini kontrol eder.
Crontab: 0 6 * * * (Günlük 06:00)

Kullanım:
    python scripts/audit_timescaledb_health.py
    python scripts/audit_timescaledb_health.py --output report.md
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg

from services.core.config import settings


# =====================================================
# CONFIGURATION
# =====================================================

HYPERTABLES = [
    "model_predictions",
    "daily_performance",
    "equity_curve",
    "daily_pnl",
    "equity_snapshots",
    "scan_results",
    "alerts",
    "audit_logs",
    "system_events",
    "paper_trades",
    "backtest_runs",
]

# Veri kalitesi kuralları (tablo bazlı)
DATA_QUALITY_RULES = {
    "model_predictions": {
        "null_checks": ["instrument_id", "prediction_date", "confidence"],
        "range_checks": {
            "confidence": {"min": 0, "max": 1},
        },
        "monotonic_checks": ["prediction_date"],
        "duplicate_checks": [("instrument_id", "prediction_date")],
    },
    "daily_performance": {
        "null_checks": ["date", "strategy_id"],
        "range_checks": {
            "total_return": {"min": -1, "max": 10},
            "drawdown": {"min": -1, "max": 0},
        },
        "monotonic_checks": ["date"],
    },
    "signals": {
        "null_checks": ["instrument_id", "strategy_id", "status"],
        "enum_checks": {
            "status": ["active", "expired", "executed", "cancelled"],
        },
    },
    "positions": {
        "null_checks": ["portfolio_id", "instrument_id", "status"],
        "range_checks": {
            "quantity": {"min": 0},
            "entry_price": {"min": 0},
        },
    },
    "orders": {
        "null_checks": ["portfolio_id", "status"],
        "range_checks": {
            "quantity": {"min": 0},
            "price": {"min": 0},
        },
    },
}


async def get_connection():
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )


async def check_hypertables(conn):
    """Hypertable durumlarını kontrol et."""
    results = []
    for table in HYPERTABLES:
        try:
            info = await conn.fetchrow(
                """
                SELECT 
                    hypertable_name,
                    num_chunks,
                    compression_state,
                    is_compressed
                FROM timescaledb_information.hypertables
                WHERE hypertable_name = $1
                """,
                table,
            )
            if info:
                # Chunk bilgisi
                chunks = await conn.fetch(
                    """
                    SELECT 
                        chunk_name,
                        range_start,
                        range_end,
                        is_compressed
                    FROM timescaledb_information.chunks
                    WHERE hypertable_name = $1
                    ORDER BY range_start DESC
                    LIMIT 5
                    """,
                    table,
                )
                results.append(
                    {
                        "table": table,
                        "status": "ok",
                        "num_chunks": info["num_chunks"],
                        "compression_state": info["compression_state"],
                        "is_compressed": info["is_compressed"],
                        "recent_chunks": [
                            {
                                "name": c["chunk_name"],
                                "start": str(c["range_start"]),
                                "end": str(c["range_end"]),
                                "compressed": c["is_compressed"],
                            }
                            for c in chunks
                        ],
                    }
                )
            else:
                results.append({"table": table, "status": "not_hypertable"})
        except Exception as e:
            results.append({"table": table, "status": "error", "error": str(e)})
    return results


async def check_compression_policies(conn):
    """Compression policy'leri kontrol et."""
    try:
        rows = await conn.fetch(
            """
            SELECT 
                hypertable_name,
                config,
                schedule_interval,
                last_run_success,
                last_run_duration
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            ORDER BY hypertable_name
            """
        )
        return [
            {
                "table": r["hypertable_name"],
                "config": dict(r["config"]) if r["config"] else {},
                "schedule": str(r["schedule_interval"]),
                "last_success": r["last_run_success"],
                "last_duration": str(r["last_run_duration"]) if r["last_run_duration"] else None,
            }
            for r in rows
        ]
    except Exception as e:
        return [{"error": str(e)}]


async def check_retention_policies(conn):
    """Retention policy'leri kontrol et."""
    try:
        rows = await conn.fetch(
            """
            SELECT 
                hypertable_name,
                config,
                schedule_interval,
                last_run_success
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_retention'
            ORDER BY hypertable_name
            """
        )
        return [
            {
                "table": r["hypertable_name"],
                "config": dict(r["config"]) if r["config"] else {},
                "schedule": str(r["schedule_interval"]),
                "last_success": r["last_run_success"],
            }
            for r in rows
        ]
    except Exception as e:
        return [{"error": str(e)}]


async def check_continuous_aggregates(conn):
    """Continuous aggregate'leri kontrol et."""
    try:
        rows = await conn.fetch(
            """
            SELECT 
                view_name,
                compression_state,
                materialization_hypertable_name
            FROM timescaledb_information.continuous_aggregates
            ORDER BY view_name
            """
        )
        return [
            {
                "view": r["view_name"],
                "compression": r["compression_state"],
                "materialization_table": r["materialization_hypertable_name"],
            }
            for r in rows
        ]
    except Exception as e:
        return [{"error": str(e)}]


async def check_data_quality(conn, table: str, rules: dict):
    """Veri kalitesi kontrolü."""
    issues = []

    # Null checks
    for col in rules.get("null_checks", []):
        try:
            count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"
            )
            if count > 0:
                issues.append(
                    {"type": "null", "column": col, "count": count, "severity": "high"}
                )
        except Exception:
            pass

    # Range checks
    for col, bounds in rules.get("range_checks", {}).items():
        try:
            if "min" in bounds:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} < $1", bounds["min"]
                )
                if count > 0:
                    issues.append(
                        {
                            "type": "range_below_min",
                            "column": col,
                            "min": bounds["min"],
                            "count": count,
                            "severity": "high",
                        }
                    )
            if "max" in bounds:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} > $1", bounds["max"]
                )
                if count > 0:
                    issues.append(
                        {
                            "type": "range_above_max",
                            "column": col,
                            "max": bounds["max"],
                            "count": count,
                            "severity": "high",
                        }
                    )
        except Exception:
            pass

    # Duplicate checks
    for cols in rules.get("duplicate_checks", []):
        if isinstance(cols, tuple):
            col_str = ", ".join(cols)
            try:
                count = await conn.fetchval(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT {col_str}, COUNT(*) as cnt 
                        FROM {table} 
                        GROUP BY {col_str} 
                        HAVING COUNT(*) > 1
                    ) t
                    """
                )
                if count > 0:
                    issues.append(
                        {
                            "type": "duplicate",
                            "columns": list(cols),
                            "count": count,
                            "severity": "medium",
                        }
                    )
            except Exception:
                pass

    # Enum checks
    for col, allowed in rules.get("enum_checks", {}).items():
        try:
            allowed_str = ", ".join(f"'{v}'" for v in allowed)
            count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE {col} NOT IN ({allowed_str})"
            )
            if count > 0:
                issues.append(
                    {
                        "type": "invalid_enum",
                        "column": col,
                        "allowed": allowed,
                        "count": count,
                        "severity": "high",
                    }
                )
        except Exception:
            pass

    # Future timestamp check
    try:
        time_cols = {
            "model_predictions": "prediction_date",
            "daily_performance": "date",
            "signals": "created_at",
            "orders": "created_at",
            "alerts": "created_at",
        }
        if table in time_cols:
            col = time_cols[table]
            count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE {col} > NOW() + INTERVAL '1 day'"
            )
            if count > 0:
                issues.append(
                    {
                        "type": "future_timestamp",
                        "column": col,
                        "count": count,
                        "severity": "critical",
                    }
                )
    except Exception:
        pass

    return issues


async def check_chunk_health(conn):
    """Chunk sağlık kontrolü."""
    try:
        # Compressed olmayan eski chunk'lar
        uncompressed_old = await conn.fetch(
            """
            SELECT 
                hypertable_name,
                chunk_name,
                range_start,
                range_end,
                pg_size_pretty(
                    pg_relation_size(format('%I.%I', chunk_schema, chunk_name)::regclass)
                ) as size
            FROM timescaledb_information.chunks
            WHERE is_compressed = false
                AND range_end < NOW() - INTERVAL '30 days'
            ORDER BY range_start
            LIMIT 20
            """
        )

        # Chunk sayısı yüksek hypertable'lar
        chunk_counts = await conn.fetch(
            """
            SELECT 
                hypertable_name,
                COUNT(*) as chunk_count
            FROM timescaledb_information.chunks
            GROUP BY hypertable_name
            HAVING COUNT(*) > 100
            ORDER BY chunk_count DESC
            """
        )

        return {
            "uncompressed_old": [
                {
                    "table": r["hypertable_name"],
                    "chunk": r["chunk_name"],
                    "start": str(r["range_start"]),
                    "end": str(r["range_end"]),
                    "size": r["size"],
                }
                for r in uncompressed_old
            ],
            "high_chunk_count": [
                {"table": r["hypertable_name"], "count": r["chunk_count"]}
                for r in chunk_counts
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def generate_report(
    hypertables,
    compression_policies,
    retention_policies,
    continuous_aggregates,
    data_quality_results,
    chunk_health,
):
    """Markdown rapor oluştur."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = f"""# 🏥 TimescaleDB Health & Data Quality Raporu

> **Oluşturulma:** {now}  
> **Kapsam:** {len(HYPERTABLES)} hypertable, compression, retention, data quality

---

## 📊 Hypertable Durumları

| Tablo | Chunk | Compression | Durum |
|---|---|---|---|
"""
    for h in hypertables:
        if h["status"] == "ok":
            status = "✅"
            report += f"| {h['table']} | {h['num_chunks']} | {'✅' if h['is_compressed'] else '❌'} | {status} |\n"
        elif h["status"] == "not_hypertable":
            report += f"| {h['table']} | - | - | ⚠️ Hypertable değil |\n"
        else:
            report += f"| {h['table']} | - | - | ❌ {h.get('error', 'Unknown')} |\n"

    report += "\n---\n\n## 🗜️ Compression Policies\n\n"
    if compression_policies and "error" not in compression_policies[0]:
        report += "| Tablo | Schedule | Son Çalışma |\n"
        report += "|---|---|---|\n"
        for cp in compression_policies:
            last = "✅" if cp.get("last_success") else "❌"
            report += f"| {cp['table']} | {cp['schedule']} | {last} |\n"
    else:
        report += "⚠️ Compression policy bulunamadı.\n"

    report += "\n---\n\n## 🗑️ Retention Policies\n\n"
    if retention_policies and "error" not in retention_policies[0]:
        report += "| Tablo | Schedule | Son Çalışma |\n"
        report += "|---|---|---|\n"
        for rp in retention_policies:
            last = "✅" if rp.get("last_success") else "❌"
            report += f"| {rp['table']} | {rp['schedule']} | {last} |\n"
    else:
        report += "⚠️ Retention policy bulunamadı. `database/init/004_timescaledb_retention.sql` çalıştırılmalı.\n"

    report += "\n---\n\n## 📈 Continuous Aggregates\n\n"
    if continuous_aggregates and "error" not in continuous_aggregates[0]:
        report += "| View | Compression |\n"
        report += "|---|---|\n"
        for ca in continuous_aggregates:
            report += f"| {ca['view']} | {ca['compression']} |\n"
    else:
        report += "⚠️ Continuous aggregate bulunamadı.\n"

    report += "\n---\n\n## 🔍 Veri Kalitesi Kontrolleri\n\n"
    total_issues = 0
    for table, issues in data_quality_results.items():
        if issues:
            report += f"### {table}\n\n"
            report += "| Sorun | Detay | Adet | Önem |\n"
            report += "|---|---|---|---|\n"
            for issue in issues:
                severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(
                    issue["severity"], "⚪"
                )
                detail = ""
                if issue["type"] == "null":
                    detail = f"`{issue['column']}` NULL"
                elif issue["type"] in ("range_below_min", "range_above_max"):
                    detail = f"`{issue['column']}` limit dışı"
                elif issue["type"] == "duplicate":
                    detail = f"`{', '.join(issue['columns'])}` duplike"
                elif issue["type"] == "invalid_enum":
                    detail = f"`{issue['column']}` geçersiz değer"
                elif issue["type"] == "future_timestamp":
                    detail = f"`{issue['column']}` gelecek tarih"
                report += f"| {severity_icon} {issue['type']} | {detail} | {issue['count']} | {issue['severity']} |\n"
                total_issues += 1
            report += "\n"

    if total_issues == 0:
        report += "✅ Veri kalitesi sorunu tespit edilmedi.\n"

    report += "\n---\n\n## 📦 Chunk Sağlık Kontrolü\n\n"
    if "error" not in chunk_health:
        if chunk_health.get("uncompressed_old"):
            report += "### Sıkıştırılmamış Eski Chunk'lar\n\n"
            report += "| Tablo | Chunk | Başlangıç | Bitiş | Boyut |\n"
            report += "|---|---|---|---|---|\n"
            for c in chunk_health["uncompressed_old"]:
                report += f"| {c['table']} | {c['chunk']} | {c['start']} | {c['end']} | {c['size']} |\n"
            report += "\n⚠️ Bu chunk'lar 30 günden eski ama sıkıştırılmamış.\n"
        else:
            report += "✅ Eski uncompressed chunk yok.\n"

        if chunk_health.get("high_chunk_count"):
            report += "\n### Yüksek Chunk Sayısı\n\n"
            report += "| Tablo | Chunk Sayısı |\n"
            report += "|---|---|\n"
            for c in chunk_health["high_chunk_count"]:
                report += f"| {c['table']} | {c['count']} |\n"
            report += "\n⚠️ Chunk sayısı yüksek — retention policy değerlendirin.\n"
    else:
        report += f"⚠️ Chunk kontrolü yapılamadı: {chunk_health['error']}\n"

    report += "\n---\n\n## 📌 Öneriler\n\n"
    recommendations = []

    uncompressed = [h for h in hypertables if h.get("is_compressed") == False]
    if uncompressed:
        recommendations.append(f"🔴 {len(uncompressed)} hypertable sıkıştırılmamış")

    no_retention = []
    if retention_policies and "error" not in retention_policies[0]:
        retained_tables = {r["table"] for r in retention_policies}
        no_retention = [t for t in HYPERTABLES if t not in retained_tables]
    else:
        no_retention = HYPERTABLES
    if no_retention:
        recommendations.append(f"🟠 {len(no_retention)} hypertable retention policy yok")

    if total_issues > 0:
        recommendations.append(f"🔴 {total_issues} veri kalitesi sorunu tespit edildi")

    if chunk_health.get("uncompressed_old"):
        recommendations.append(
            f"🟠 {len(chunk_health['uncompressed_old'])} eski uncompressed chunk"
        )

    if recommendations:
        for r in recommendations:
            report += f"- {r}\n"
    else:
        report += "✅ Kritik sorun tespit edilmedi.\n"

    return report


async def main():
    parser = argparse.ArgumentParser(description="TimescaleDB Health Auditor")
    parser.add_argument(
        "--output",
        type=str,
        default="reports/timescaledb_health.md",
        help="Çıktı dosyası",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON formatında çıktı",
    )
    args = parser.parse_args()

    print("🏥 TimescaleDB Health Audit başlıyor...")

    conn = await get_connection()
    try:
        # Veri topla
        hypertables = await check_hypertables(conn)
        compression_policies = await check_compression_policies(conn)
        retention_policies = await check_retention_policies(conn)
        continuous_aggregates = await check_continuous_aggregates(conn)
        chunk_health = await check_chunk_health(conn)

        # Veri kalitesi kontrolleri
        data_quality_results = {}
        for table, rules in DATA_QUALITY_RULES.items():
            issues = await check_data_quality(conn, table, rules)
            if issues:
                data_quality_results[table] = issues

        if args.json:
            data = {
                "timestamp": datetime.now().isoformat(),
                "hypertables": hypertables,
                "compression_policies": compression_policies,
                "retention_policies": retention_policies,
                "continuous_aggregates": continuous_aggregates,
                "data_quality": data_quality_results,
                "chunk_health": chunk_health,
            }
            output = json.dumps(data, indent=2, default=str)
        else:
            output = generate_report(
                hypertables,
                compression_policies,
                retention_policies,
                continuous_aggregates,
                data_quality_results,
                chunk_health,
            )

        # Çıktı dosyasına yaz
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"✅ Rapor kaydedildi: {output_path}")

        # Konsola özet
        print(f"\n📊 ÖZET:")
        print(f"   Hypertable: {len([h for h in hypertables if h['status'] == 'ok'])}/{len(HYPERTABLES)}")
        print(f"   Compression policy: {len(compression_policies)}")
        print(f"   Retention policy: {len(retention_policies)}")
        print(f"   Continuous aggregate: {len(continuous_aggregates)}")
        print(f"   Veri kalitesi sorunu: {sum(len(v) for v in data_quality_results.values())}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
