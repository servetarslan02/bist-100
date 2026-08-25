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

# --- PostgreSQL ---
log "Backing up PostgreSQL..."
if docker exec alpha-postgres pg_dump -U alpha alpha_bist > "$BACKUP_DIR/postgres.sql" 2>/dev/null; then
    log "PostgreSQL backup OK ($(du -h "$BACKUP_DIR/postgres.sql" | cut -f1))"
else
    log "WARNING: PostgreSQL backup failed (container may be down)"
fi

# --- SQLite databases ---
log "Backing up SQLite databases..."
for db_file in data/central_state.db data/offline_queue.db data/downtime.db data/paper_trading_state.db data/dlq.db; do
    if [ -f "$db_file" ]; then
        db_name=$(basename "$db_file")
        # WAL checkpoint + safe copy
        sqlite3 "$db_file" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
        cp "$db_file" "$BACKUP_DIR/$db_name"
        # WAL ve SHM dosyalarını da kopyala
        [ -f "${db_file}-wal" ] && cp "${db_file}-wal" "$BACKUP_DIR/${db_name}-wal"
        [ -f "${db_file}-shm" ] && cp "${db_file}-shm" "$BACKUP_DIR/${db_name}-shm"
        log "SQLite $db_name backup OK"
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

# --- Cleanup old backups (keep 30 days) ---
log "Cleaning up backups older than 30 days..."
find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" -mtime +30 -exec rm -rf {} \; 2>/dev/null
CLEANED=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "20*" | wc -l)
log "Remaining backups: $CLEANED"

# --- Summary ---
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log "Backup completed: $BACKUP_DIR ($TOTAL_SIZE)"
log "=== Backup finished ==="
