#!/bin/bash
# PostgreSQL Streaming Replica — Entrypoint
# Primary'den basebackup alır ve replica olarak başlatır.
# Her container restart'ta çalışır.

set -e

PRIMARY_HOST="${PRIMARY_HOST:-alpha-postgres}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
REPL_USER="${REPL_USER:-replicator}"
PGDATA="/var/lib/postgresql/data"

# Data dizini boşsa (ilk çalıştırma), primary'den basebackup al
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "Replica: İlk çalıştırma — primary'den basebackup alınıyor..."

    # Primary'nin hazır olmasını bekle (max 60 saniye)
    WAIT=0
    until pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U alpha 2>/dev/null; do
        WAIT=$((WAIT + 2))
        if [ $WAIT -ge 60 ]; then
            echo "Replica HATA: Primary 60 saniyede hazır olmadı!"
            exit 1
        fi
        echo "Replica: Primary bekleniyor... ($WAIT/60)"
        sleep 2
    done

    # Replication password'ü al (environment veya file)
    if [ -n "$REPLICATION_PASSWORD" ]; then
        REPL_PASS="$REPLICATION_PASSWORD"
    elif [ -f /run/secrets/replication_password ]; then
        REPL_PASS=$(cat /run/secrets/replication_password)
    else
        echo "Replica HATA: REPLICATION_PASSWORD tanımlı değil!"
        exit 1
    fi

    # Basebackup al
    echo "Replica: pg_basebackup çalıştırılıyor..."
    PGPASSWORD="$REPL_PASS" pg_basebackup \
        -h "$PRIMARY_HOST" \
        -p "$PRIMARY_PORT" \
        -U "$REPL_USER" \
        -D "$PGDATA" \
        -Fp -Xs -P -R \
        --checkpoint=fast

    # Replica connection bilgilerini yaz
    cat > "$PGDATA/postgresql.auto.conf" <<EOF
primary_conninfo = 'host=$PRIMARY_HOST port=$PRIMARY_PORT user=$REPL_USER password=$REPL_PASS application_name=replica1'
primary_slot_name = 'replica1_slot'
EOF

    # Standby signal oluştur
    touch "$PGDATA/standby.signal"

    # Data dizinini sahiplendir
    chown -R postgres:postgres "$PGDATA"

    echo "Replica: Basebackup tamamlandı. Replica olarak başlatılıyor."
else
    echo "Replica: Mevcut data bulundu. Replica olarak devam ediliyor."
fi

chmod 0700 "$PGDATA"

# PostgreSQL'i başlat (postgres kullanıcısı olarak)
exec gosu postgres postgres \
    -D "$PGDATA" \
    -c hot_standby=on \
    -c max_connections=100 \
    -c shared_buffers=64MB \
    -c work_mem=2MB \
    -c effective_cache_size=128MB
