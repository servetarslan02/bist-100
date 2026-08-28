#!/bin/bash
# =====================================================
# ALPHA BIST — Otomatik Recovery Drill Script
# Backup'lardan restore testi yaparak disaster recovery
# hazırlığını doğrular.
# Crontab: 0 4 * * 0 (her Pazar sabah 4'te)
# =====================================================

set -euo pipefail

DRILL_DIR="/tmp/alpha_recovery_drill_$(date +%Y%m%d_%H%M%S)"
LOG_FILE="/home/work/backups/recovery_drill.log"
BACKUP_ROOT="/home/work/backups"

mkdir -p "$DRILL_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Recovery Drill started ==="
log "Drill directory: $DRILL_DIR"

DRILL_PASSED=0
DRILL_FAILED=0
DRILL_SKIPPED=0

# =====================================================
# 1. EN GÜNCEL BACKUP'I BUL
# =====================================================
log "Finding latest backup..."
LATEST_BACKUP=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" | sort -r | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    log "ERROR: No backup found in $BACKUP_ROOT"
    exit 1
fi

log "Using backup: $LATEST_BACKUP"

# =====================================================
# 2. POSTGRESQL RESTORE TEST
# =====================================================
log "--- PostgreSQL Restore Test ---"

if [ -f "$LATEST_BACKUP/postgres.sql" ] && [ -s "$LATEST_BACKUP/postgres.sql" ]; then
    # SQL header kontrolü
    if head -5 "$LATEST_BACKUP/postgres.sql" | grep -q "PostgreSQL database dump"; then
        # Geçici veritabanına restore et
        DRILL_DB="alpha_drill_$(date +%s)"
        log "Creating temporary database: $DRILL_DB"

        if docker exec alpha-postgres psql -U alpha -c "CREATE DATABASE $DRILL_DB;" 2>/dev/null; then
            # Restore dene
            if docker exec -i alpha-postgres psql -U alpha -d "$DRILL_DB" < "$LATEST_BACKUP/postgres.sql" >/dev/null 2>&1; then
                # Tablo sayısını kontrol et
                TABLE_COUNT=$(docker exec alpha-postgres psql -U alpha -d "$DRILL_DB" -t -c \
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d ' ')

                if [ "$TABLE_COUNT" -gt 0 ]; then
                    log "PostgreSQL restore PASSED ($TABLE_COUNT tables restored)"
                    DRILL_PASSED=$((DRILL_PASSED + 1))
                else
                    log "WARNING: PostgreSQL restore — 0 tables found after restore"
                    DRILL_FAILED=$((DRILL_FAILED + 1))
                fi
            else
                log "WARNING: PostgreSQL restore command failed"
                DRILL_FAILED=$((DRILL_FAILED + 1))
            fi

            # Geçici veritabanını temizle
            docker exec alpha-postgres psql -U alpha -c "DROP DATABASE IF EXISTS $DRILL_DB;" 2>/dev/null || true
        else
            log "WARNING: Could not create temporary database"
            DRILL_FAILED=$((DRILL_FAILED + 1))
        fi
    else
        log "WARNING: PostgreSQL backup header check failed"
        DRILL_FAILED=$((DRILL_FAILED + 1))
    fi
else
    log "SKIP: PostgreSQL backup not found"
    DRILL_SKIPPED=$((DRILL_SKIPPED + 1))
fi

# =====================================================
# 3. DUCKDB RESTORE TEST
# =====================================================
log "--- DuckDB Restore Test ---"

for db_file in central_state.db offline_queue.db downtime.db paper_trading_state.db dlq.db; do
    if [ -f "$LATEST_BACKUP/$db_file" ] && [ -s "$LATEST_BACKUP/$db_file" ]; then
        # Geçici kopya oluştur
        DRILL_DUCKDB="$DRILL_DIR/$db_file"
        cp "$LATEST_BACKUP/$db_file" "$DRILL_DUCKDB"

        # Integrity check
        if duckdb "$DRILL_DUCKDB" "SELECT 1;" >/dev/null 2>&1; then
            # Tablo sayısını kontrol et
            DUCKDB_TABLES=$(duckdb "$DRILL_DUCKDB" "SELECT count(*) FROM information_schema.tables;" 2>/dev/null | tr -d ' ')
            log "DuckDB $db_file restore PASSED ($DUCKDB_TABLES tables)"
            DRILL_PASSED=$((DRILL_PASSED + 1))
        else
            log "WARNING: DuckDB $db_file restore FAILED (integrity check)"
            DRILL_FAILED=$((DRILL_FAILED + 1))
        fi
    else
        log "SKIP: DuckDB $db_file backup not found"
        DRILL_SKIPPED=$((DRILL_SKIPPED + 1))
    fi
done

# =====================================================
# 4. QUESTDB RESTORE TEST
# =====================================================
log "--- QuestDB Restore Test ---"

if [ -d "$LATEST_BACKUP/questdb" ]; then
    # CSV export'ları kontrol et
    QUESTDB_TABLES_RESTORED=0
    for table in market_ticks ohlcv events; do
        if [ -f "$LATEST_BACKUP/questdb/$table.csv" ] && [ -s "$LATEST_BACKUP/questdb/$table.csv" ]; then
            ROW_COUNT=$(wc -l < "$LATEST_BACKUP/questdb/$table.csv")
            if [ "$ROW_COUNT" -gt 1 ]; then
                log "QuestDB $table restore check PASSED ($ROW_COUNT rows in CSV)"
                QUESTDB_TABLES_RESTORED=$((QUESTDB_TABLES_RESTORED + 1))
            else
                log "WARNING: QuestDB $table CSV has only header (no data)"
            fi
        fi
    done

    # Cold snapshot kontrolü
    if [ -f "$LATEST_BACKUP/questdb/questdb_snapshot.tar.gz" ] && [ -s "$LATEST_BACKUP/questdb/questdb_snapshot.tar.gz" ]; then
        # Snapshot'ı geçici dizine aç
        mkdir -p "$DRILL_DIR/questdb_restore"
        if tar xzf "$LATEST_BACKUP/questdb/questdb_snapshot.tar.gz" -C "$DRILL_DIR/questdb_restore" 2>/dev/null; then
            log "QuestDB cold snapshot extract PASSED"
            QUESTDB_TABLES_RESTORED=$((QUESTDB_TABLES_RESTORED + 1))
        else
            log "WARNING: QuestDB cold snapshot extract FAILED"
        fi
    fi

    if [ $QUESTDB_TABLES_RESTORED -gt 0 ]; then
        log "QuestDB restore PASSED ($QUESTDB_TABLES_RESTORED components)"
        DRILL_PASSED=$((DRILL_PASSED + 1))
    else
        log "WARNING: QuestDB restore FAILED (no valid data)"
        DRILL_FAILED=$((DRILL_FAILED + 1))
    fi
else
    log "SKIP: QuestDB backup directory not found"
    DRILL_SKIPPED=$((DRILL_SKIPPED + 1))
fi

# =====================================================
# 5. ML MODELS RESTORE TEST
# =====================================================
log "--- ML Models Restore Test ---"

if [ -f "$LATEST_BACKUP/ml_models.tar.gz" ] && [ -s "$LATEST_BACKUP/ml_models.tar.gz" ]; then
    mkdir -p "$DRILL_DIR/ml_restore"
    if tar xzf "$LATEST_BACKUP/ml_models.tar.gz" -C "$DRILL_DIR/ml_restore" 2>/dev/null; then
        MODEL_COUNT=$(find "$DRILL_DIR/ml_restore" -type f | wc -l)
        if [ "$MODEL_COUNT" -gt 0 ]; then
            log "ML models restore PASSED ($MODEL_COUNT files)"
            DRILL_PASSED=$((DRILL_PASSED + 1))
        else
            log "WARNING: ML models restore — 0 files found"
            DRILL_FAILED=$((DRILL_FAILED + 1))
        fi
    else
        log "WARNING: ML models extract FAILED"
        DRILL_FAILED=$((DRILL_FAILED + 1))
    fi
else
    log "SKIP: ML models backup not found"
    DRILL_SKIPPED=$((DRILL_SKIPPED + 1))
fi

# =====================================================
# 6. CONFIG RESTORE TEST
# =====================================================
log "--- Config Restore Test ---"

if [ -f "$LATEST_BACKUP/config.tar.gz" ] && [ -s "$LATEST_BACKUP/config.tar.gz" ]; then
    mkdir -p "$DRILL_DIR/config_restore"
    if tar xzf "$LATEST_BACKUP/config.tar.gz" -C "$DRILL_DIR/config_restore" 2>/dev/null; then
        CONFIG_FILES=$(find "$DRILL_DIR/config_restore" -type f | wc -l)
        log "Config restore PASSED ($CONFIG_FILES files)"
        DRILL_PASSED=$((DRILL_PASSED + 1))
    else
        log "WARNING: Config extract FAILED"
        DRILL_FAILED=$((DRILL_FAILED + 1))
    fi
else
    log "SKIP: Config backup not found"
    DRILL_SKIPPED=$((DRILL_SKIPPED + 1))
fi

# =====================================================
# 7. RTO (Recovery Time Objective) ÖLÇÜMÜ
# =====================================================
DRILL_END=$(date +%s)
DRILL_START=$(stat -c %Y "$DRILL_DIR" 2>/dev/null || date +%s)
DRILL_DURATION=$((DRILL_END - DRILL_START))

# =====================================================
# 8. TEMİZLİK
# =====================================================
log "Cleaning up drill directory..."
rm -rf "$DRILL_DIR"

# =====================================================
# 9. ÖZET
# =====================================================
log "=== Recovery Drill Summary ==="
log "Duration: ${DRILL_DURATION}s"
log "Passed: $DRILL_PASSED"
log "Failed: $DRILL_FAILED"
log "Skipped: $DRILL_SKIPPED"
log "Backup used: $LATEST_BACKUP"

if [ $DRILL_FAILED -gt 0 ]; then
    log "⚠️  ATTENTION: $DRILL_FAILED restore tests FAILED!"
    log "Review: $LOG_FILE"
    exit 1
else
    log "✅ All restore tests PASSED"
    exit 0
fi
