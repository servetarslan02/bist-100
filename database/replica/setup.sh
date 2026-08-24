#!/bin/bash
# PostgreSQL Streaming Replica Setup
# Primary'den basebackup alır ve replica olarak başlatır

set -e

PRIMARY_HOST="alpha-postgres"
PRIMARY_PORT=5432
REPL_USER="replicator"
REPL_PASSWORD="${REPLICATION_PASSWORD}"
PGDATA="/var/lib/postgresql/data"

# Eğer data dizini boşsa (ilk çalıştırma), primary'den basebackup al
if [ -z "$(ls -A $PGDATA 2>/dev/null)" ]; then
    echo "Replica: Primary'den basebackup alınıyor..."

    # Primary'nin hazır olmasını bekle
    until pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U alpha; do
        echo "Replica: Primary bekleniyor..."
        sleep 2
    done

    # Basebackup al
    PGPASSWORD="$REPL_PASSWORD" pg_basebackup \
        -h "$PRIMARY_HOST" \
        -p "$PRIMARY_PORT" \
        -U "$REPL_USER" \
        -D "$PGDATA" \
        -Fp -Xs -P -R

    # Replica ayarları
    cat > "$PGDATA/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=$PRIMARY_HOST port=$PRIMARY_PORT user=$REPL_USER password=$REPL_PASSWORD application_name=replica1'
primary_slot_name = 'replica1_slot'
EOF

    # Standby signal
    touch "$PGDATA/standby.signal"

    echo "Replica: Basebackup tamamlandı."
fi

# Replica'yı başlat
exec postgres \
    -c hot_standby=on \
    -c max_connections=20 \
    -c shared_buffers=64MB \
    -c work_mem=2MB \
    -c effective_cache_size=128MB
