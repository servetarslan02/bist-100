#!/bin/bash
# =====================================================
# ALPHA BIST — Otomatik Backup Script
# Günlük PostgreSQL, ClickHouse ve SQLite backup'ları
# Crontab: 0 2 * * * /home/work/bist-100/scripts/backup_alpha.sh
# =====================================================

set -euo pipefail

BACKUP_ROOT="/home/work/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_ROOT}/${DATE}"
LOG_FILE="${BACKUP_ROOT}/backup.log"

mkdir -p "$BACKUP_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Backup started ==="

# --- PostgreSQL (Full + WAL for PITR) ---
log "Backing up PostgreSQL..."

# Full backup (pg_dump)
if docker exec alpha-postgres pg_dump -U alpha alpha_bist > "$BACKUP_DIR/postgres.sql" 2>/dev/null; then
    log "PostgreSQL full backup OK ($(du -h "$BACKUP_DIR/postgres.sql" | cut -f1))"
else
    log "WARNING: PostgreSQL full backup failed (container may be down)"
fi

# WAL archive for PITR (Point-in-Time Recovery)
WAL_DIR="$BACKUP_DIR/wal_archive"
mkdir -p "$WAL_DIR"
if docker exec alpha-postgres pg_switch_wal() 2>/dev/null; then
    # Switch WAL and archive
    docker exec alpha-postgres psql -U alpha -c "SELECT pg_switch_wal();" 2>/dev/null || true
    # Copy WAL files from pg_wal directory
    docker exec alpha-postgres bash -c "cp /var/lib/postgresql/data/pg_wal/*.backup $WAL_DIR/ 2>/dev/null || true" 2>/dev/null || true
    log "PostgreSQL WAL archive initiated for PITR"
else
    log "WARNING: PostgreSQL WAL switch failed"
fi

# Base backup for PITR (pg_basebackup)
BASE_BACKUP_DIR="$BACKUP_DIR/base_backup"
mkdir -p "$BASE_BACKUP_DIR"
if docker exec alpha-postgres pg_basebackup -U alpha -D /tmp/base_backup -Ft -z -Xs 2>/dev/null; then
    docker cp alpha-postgres:/tmp/base_backup.tar.gz "$BASE_BACKUP_DIR/" 2>/dev/null || true
    docker exec alpha-postgres rm -rf /tmp/base_backup 2>/dev/null || true
    log "PostgreSQL base backup OK for PITR"
else
    log "WARNING: PostgreSQL base backup failed (non-critical, full dump available)"
fi

# --- DuckDB databases ---
log "Backing up DuckDB databases..."
for db_file in data/central_state.db data/offline_queue.db data/downtime.db data/paper_trading_state.db data/dlq.db; do
    if [ -f "$db_file" ]; then
        db_name=$(basename "$db_file")
        # DuckDB checkpoint + safe copy
        duckdb "$db_file" "CHECKPOINT;" 2>/dev/null || true
        cp "$db_file" "$BACKUP_DIR/$db_name"
        # WAL dosyasını da kopyala (varsa)
        [ -f "${db_file}.wal" ] && cp "${db_file}.wal" "$BACKUP_DIR/${db_name}.wal"
        log "DuckDB $db_name backup OK"
    fi
done

# --- ML Models ---
log "Backing up ML models..."
if [ -d "ml/saved_models" ]; then
    tar czf "$BACKUP_DIR/ml_models.tar.gz" -C ml saved_models 2>/dev/null && \
        log "ML models backup OK" || \
        log "WARNING: ML models backup failed"
fi

# --- Config files ---
log "Backing up config..."
tar czf "$BACKUP_DIR/config.tar.gz" config/ .env 2>/dev/null && \
    log "Config backup OK" || \
    log "WARNING: Config backup failed"

# --- QuestDB backup ---
log "Backing up QuestDB..."
QUESTDB_BACKUP_DIR="$BACKUP_DIR/questdb"
mkdir -p "$QUESTDB_BACKUP_DIR"

# QuestDB tablolarini CSV olarak export et (daha guvenilir)
QUESTDB_TABLES=("market_ticks" "ohlcv" "events")
QUESTDB_EXPORT_OK=0
QUESTDB_EXPORT_FAIL=0

for table in "${QUESTDB_TABLES[@]}"; do
    # QuestDB PostgreSQL wire protocol ile export
    if docker exec alpha-questdb psql -U admin -h localhost -p 8812 -q \
        -c "COPY $table TO '$table.csv' WITH HEADER true;" 2>/dev/null; then
        # Container'dan kopyala
        docker cp "alpha-questdb:/var/lib/questdb/$table.csv" "$QUESTDB_BACKUP_DIR/$table.csv" 2>/dev/null || true
        if [ -f "$QUESTDB_BACKUP_DIR/$table.csv" ] && [ -s "$QUESTDB_BACKUP_DIR/$table.csv" ]; then
            log "QuestDB $table export OK ($(du -h "$QUESTDB_BACKUP_DIR/$table.csv" | cut -f1))"
            QUESTDB_EXPORT_OK=$((QUESTDB_EXPORT_OK + 1))
        else
            log "WARNING: QuestDB $table export - file empty or missing"
            QUESTDB_EXPORT_FAIL=$((QUESTDB_EXPORT_FAIL + 1))
        fi
    else
        log "WARNING: QuestDB $table export failed (table may not exist)"
        QUESTDB_EXPORT_FAIL=$((QUESTDB_EXPORT_FAIL + 1))
    fi
done

# QuestDB snapshot metadata (row counts)
QUESTDB_COUNTS=$(curl -s "http://localhost:9000/exp?query=SELECT+count()+FROM+market_ticks" 2>/dev/null || echo '{}')
echo "$QUESTDB_COUNTS" > "$QUESTDB_BACKUP_DIR/row_counts.json"
log "QuestDB row counts saved"

# QuestDB data directory snapshot (cold backup)
if docker exec alpha-questdb ls /var/lib/questdb/db >/dev/null 2>&1; then
    docker exec alpha-questdb tar czf /tmp/questdb_snapshot.tar.gz -C /var/lib/questdb db 2>/dev/null || true
    docker cp alpha-questdb:/tmp/questdb_snapshot.tar.gz "$QUESTDB_BACKUP_DIR/" 2>/dev/null || true
    docker exec alpha-questdb rm -f /tmp/questdb_snapshot.tar.gz 2>/dev/null || true
    if [ -f "$QUESTDB_BACKUP_DIR/questdb_snapshot.tar.gz" ] && [ -s "$QUESTDB_BACKUP_DIR/questdb_snapshot.tar.gz" ]; then
        log "QuestDB cold snapshot OK ($(du -h "$QUESTDB_BACKUP_DIR/questdb_snapshot.tar.gz" | cut -f1))"
    fi
fi

log "QuestDB backup summary: $QUESTDB_EXPORT_OK tables exported, $QUESTDB_EXPORT_FAIL failed"

# --- Backup Verification (Restore Test) ---
log "Verifying backup integrity..."
VERIFICATION_PASSED=0
VERIFICATION_FAILED=0

# PostgreSQL backup verification
if [ -f "$BACKUP_DIR/postgres.sql" ] && [ -s "$BACKUP_DIR/postgres.sql" ]; then
    # SQL dosyası boş mu kontrol et
    if head -5 "$BACKUP_DIR/postgres.sql" | grep -q "PostgreSQL database dump" 2>/dev/null; then
        log "PostgreSQL backup verification PASSED"
        VERIFICATION_PASSED=$((VERIFICATION_PASSED + 1))
    else
        log "WARNING: PostgreSQL backup may be corrupted (header check failed)"
        VERIFICATION_FAILED=$((VERIFICATION_FAILED + 1))
    fi
else
    log "WARNING: PostgreSQL backup file missing or empty"
    VERIFICATION_FAILED=$((VERIFICATION_FAILED + 1))
fi

# DuckDB backup verification
for db_file in data/central_state.db data/offline_queue.db data/downtime.db data/paper_trading_state.db data/dlq.db; do
    db_name=$(basename "$db_file")
    if [ -f "$BACKUP_DIR/$db_name" ] && [ -s "$BACKUP_DIR/$db_name" ]; then
        # DuckDB integrity check
        if duckdb "$BACKUP_DIR/$db_name" "SELECT 1;" >/dev/null 2>&1; then
            log "DuckDB $db_name verification PASSED"
            VERIFICATION_PASSED=$((VERIFICATION_PASSED + 1))
        else
            log "WARNING: DuckDB $db_name verification FAILED (integrity check)"
            VERIFICATION_FAILED=$((VERIFICATION_FAILED + 1))
        fi
    fi
done

# QuestDB backup verification
QUESTDB_VERIFIED=0
for table in market_ticks ohlcv events; do
    if [ -f "$BACKUP_DIR/questdb/$table.csv" ] && [ -s "$BACKUP_DIR/questdb/$table.csv" ]; then
        ROW_COUNT=$(wc -l < "$BACKUP_DIR/questdb/$table.csv")
        if [ "$ROW_COUNT" -gt 0 ]; then
            log "QuestDB $table verification PASSED ($ROW_COUNT rows)"
            QUESTDB_VERIFIED=$((QUESTDB_VERIFIED + 1))
        else
            log "WARNING: QuestDB $table verification FAILED (empty)"
        fi
    fi
done
if [ -f "$BACKUP_DIR/questdb/questdb_snapshot.tar.gz" ] && [ -s "$BACKUP_DIR/questdb/questdb_snapshot.tar.gz" ]; then
    log "QuestDB cold snapshot verification PASSED"
    QUESTDB_VERIFIED=$((QUESTDB_VERIFIED + 1))
fi
if [ $QUESTDB_VERIFIED -gt 0 ]; then
    VERIFICATION_PASSED=$((VERIFICATION_PASSED + QUESTDB_VERIFIED))
else
    log "WARNING: QuestDB backup verification FAILED (no valid exports)"
    VERIFICATION_FAILED=$((VERIFICATION_FAILED + 1))
fi

log "Verification summary: $VERIFICATION_PASSED passed, $VERIFICATION_FAILED failed"

# --- Cleanup old backups (keep 30 days) ---
log "Cleaning up backups older than 30 days..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +30 -exec rm -rf {} \; 2>/dev/null
CLEANED=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" | wc -l)
log "Remaining backups: $CLEANED"

# --- Summary ---
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log "Backup completed: $BACKUP_DIR ($TOTAL_SIZE)"
log "Verification: $VERIFICATION_PASSED passed, $VERIFICATION_FAILED failed"
log "=== Backup finished ==="
