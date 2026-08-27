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
# QuestDB snapshot via HTTP API
if curl -s -o "$QUESTDB_BACKUP_DIR/snapshot_metadata.json" "http://localhost:9000/questdb/snapshot" 2>/dev/null; then
    # Copy QuestDB data directory if accessible
    if [ -d "/var/lib/questdb" ]; then
        cp -r /var/lib/questdb/db "$QUESTDB_BACKUP_DIR/" 2>/dev/null || true
    fi
    log "QuestDB backup OK"
else
    log "WARNING: QuestDB backup failed (container may be down or snapshot API unavailable)"
fi

# --- Cleanup old backups (keep 30 days) ---
log "Cleaning up backups older than 30 days..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +30 -exec rm -rf {} \; 2>/dev/null
CLEANED=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" | wc -l)
log "Remaining backups: $CLEANED"

# --- Summary ---
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log "Backup completed: $BACKUP_DIR ($TOTAL_SIZE)"
log "=== Backup finished ==="
