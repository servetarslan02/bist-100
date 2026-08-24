#!/bin/bash
# ALPHA BIST — İlk Kurulum Scripti
# .env.example'dan .env oluşturur ve gerekli değişkenleri ayarlar.

set -e

echo "=========================================="
echo "  ALPHA BIST — İlk Kurulum"
echo "=========================================="

# .env kontrolü
if [ -f .env ]; then
    echo "⚠️  .env dosyası zaten mevcut."
    read -p "Üzerine yazmak ister misiniz? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Kurulum iptal edildi."
        exit 0
    fi
fi

# .env.example'dan kopyala
cp .env.example .env

# Rastgele şifreler oluştur
generate_password() {
    openssl rand -base64 24 | tr -d '/+=' | head -c 24
}

POSTGRES_PASS=$(generate_password)
REDIS_PASS=$(generate_password)
CLICKHOUSE_PASS=$(generate_password)
CLICKHOUSE_USER="alpha"
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
REPLICATION_PASS=$(generate_password)
GRAFANA_PASS=$(generate_password)

# .env dosyasını güncelle
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASS}/" .env
sed -i "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=${REDIS_PASS}/" .env
sed -i "s/^CLICKHOUSE_PASSWORD=.*/CLICKHOUSE_PASSWORD=${CLICKHOUSE_PASS}/" .env
sed -i "s/^CLICKHOUSE_USER=.*/CLICKHOUSE_USER=${CLICKHOUSE_USER}/" .env
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=${SECRET_KEY}/" .env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET}/" .env
sed -i "s/^REPLICATION_PASSWORD=.*/REPLICATION_PASSWORD=${REPLICATION_PASS}/" .env
sed -i "s/^GRAFANA_PASSWORD=.*/GRAFANA_PASSWORD=${GRAFANA_PASS}/" .env

echo ""
echo "✅ .env dosyası oluşturuldu."
echo ""
echo "📋 Oluşturulan şifreler (kaydedin!):"
echo "  PostgreSQL:    ${POSTGRES_PASS}"
echo "  Redis:         ${REDIS_PASS}"
echo "  ClickHouse:    ${CLICKHOUSE_PASS}"
echo "  Grafana:       ${GRAFANA_PASS}"
echo "  Replication:   ${REPLICATION_PASS}"
echo ""
echo "🚀 Başlatmak için:"
echo "  docker-compose up -d"
echo ""
echo "📊 Dashboard: http://localhost:3000"
echo "📊 Grafana:   http://localhost:3001"
echo "📊 API Docs:  http://localhost:8000/docs"
echo "📊 Traefik:   http://localhost:8080"
