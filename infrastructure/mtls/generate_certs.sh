#!/bin/bash
# =====================================================
# ALPHA BIST — mTLS Certificate Generator
# Self-signed CA + Server + Client sertifikaları
# =====================================================
# Kullanım:
#   bash infrastructure/mtls/generate_certs.sh
#   # veya
#   bash infrastructure/mtls/generate_certs.sh --force  (var olanları yeniden oluştur)
#
# Çıktı:
#   infrastructure/mtls/certs/ca.crt        — CA sertifikası
#   infrastructure/mtls/certs/ca.key        — CA private key
#   infrastructure/mtls/certs/server.crt    — Sunucu sertifikası
#   infrastructure/mtls/certs/server.key    — Sunucu private key
#   infrastructure/mtls/certs/client.crt    — İstemci sertifikası
#   infrastructure/mtls/certs/client.key    — İstemci private key
#   infrastructure/mtls/certs/dhparam.pem   — DH parametreleri
# =====================================================

set -euo pipefail

CERTS_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
DAYS_CA=3650       # CA: 10 yıl
DAYS_SERVER=365    # Server: 1 yıl
DAYS_CLIENT=365    # Client: 1 yıl
KEY_SIZE=4096
FORCE=false

# Argüman kontrolü
if [[ "${1:-}" == "--force" ]]; then
    FORCE=true
fi

# Dizin oluştur
mkdir -p "$CERTS_DIR"

# Varsa ve --force değilse atla
if [[ -f "$CERTS_DIR/ca.crt" && "$FORCE" != "true" ]]; then
    echo "✅ Sertifikalar zaten mevcut. Yeniden oluşturmak için --force kullanın."
    exit 0
fi

echo "🔐 ALPHA BIST — mTLS Sertifikaları oluşturuluyor..."
echo "   Dizin: $CERTS_DIR"
echo ""

# =====================================================
# 1. CA (Certificate Authority)
# =====================================================
echo "📜 [1/4] CA sertifikası oluşturuluyor..."

# CA private key
openssl genrsa -out "$CERTS_DIR/ca.key" $KEY_SIZE 2>/dev/null

# CA sertifikası
openssl req -new -x509 \
    -key "$CERTS_DIR/ca.key" \
    -out "$CERTS_DIR/ca.crt" \
    -days $DAYS_CA \
    -subj "/C=TR/ST=Istanbul/L=Istanbul/O=ALPHA BIST/OU=Security/CN=ALPHA BIST CA" \
    -sha256 2>/dev/null

echo "   ✅ CA sertifikası: $DAYS_CA gün geçerli"

# =====================================================
# 2. Server Sertifikası
# =====================================================
echo "🖥️  [2/4] Server sertifikası oluşturuluyor..."

# Server private key
openssl genrsa -out "$CERTS_DIR/server.key" $KEY_SIZE 2>/dev/null

# Server CSR (Certificate Signing Request)
cat > "$CERTS_DIR/server.cnf" <<EOF
[req]
default_bits = $KEY_SIZE
prompt = no
distinguished_name = dn
req_extensions = v3_req

[dn]
C = TR
ST = Istanbul
L = Istanbul
O = ALPHA BIST
OU = API
CN = alpha-api

[v3_req]
subjectAltName = @alt_names
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = alpha-api
DNS.2 = alpha-dashboard
DNS.3 = alpha-ingestion
DNS.4 = alpha-feature-engine
DNS.5 = alpha-market-state
DNS.6 = alpha-intelligence
DNS.7 = alpha-simulation
DNS.8 = alpha-risk
DNS.9 = alpha-portfolio
DNS.10 = alpha-learning
DNS.11 = alpha-celery-worker
DNS.12 = localhost
DNS.13 = *.alpha-bist.local
IP.1 = 127.0.0.1
IP.2 = 0.0.0.0
EOF

openssl req -new \
    -key "$CERTS_DIR/server.key" \
    -out "$CERTS_DIR/server.csr" \
    -config "$CERTS_DIR/server.cnf" 2>/dev/null

# CA ile imzala
openssl x509 -req \
    -in "$CERTS_DIR/server.csr" \
    -CA "$CERTS_DIR/ca.crt" \
    -CAkey "$CERTS_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERTS_DIR/server.crt" \
    -days $DAYS_SERVER \
    -sha256 \
    -extensions v3_req \
    -extfile "$CERTS_DIR/server.cnf" 2>/dev/null

echo "   ✅ Server sertifikası: $DAYS_SERVER gün geçerli (SAN: 13 hostname)"

# =====================================================
# 3. Client Sertifikası
# =====================================================
echo "👤 [3/4] Client sertifikası oluşturuluyor..."

# Client private key
openssl genrsa -out "$CERTS_DIR/client.key" $KEY_SIZE 2>/dev/null

# Client CSR
cat > "$CERTS_DIR/client.cnf" <<EOF
[req]
default_bits = $KEY_SIZE
prompt = no
distinguished_name = dn
req_extensions = v3_req

[dn]
C = TR
ST = Istanbul
L = Istanbul
O = ALPHA BIST
OU = Service
CN = alpha-client

[v3_req]
keyUsage = digitalSignature
extendedKeyUsage = clientAuth
EOF

openssl req -new \
    -key "$CERTS_DIR/client.key" \
    -out "$CERTS_DIR/client.csr" \
    -config "$CERTS_DIR/client.cnf" 2>/dev/null

# CA ile imzala
openssl x509 -req \
    -in "$CERTS_DIR/client.csr" \
    -CA "$CERTS_DIR/ca.crt" \
    -CAkey "$CERTS_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERTS_DIR/client.crt" \
    -days $DAYS_CLIENT \
    -sha256 \
    -extensions v3_req \
    -extfile "$CERTS_DIR/client.cnf" 2>/dev/null

echo "   ✅ Client sertifikası: $DAYS_CLIENT gün geçerli"

# =====================================================
# 4. DH Parametreleri (opsiyonel, TLS performansı için)
# =====================================================
echo "🔑 [4/4] DH parametreleri oluşturuluyor..."
openssl dhparam -out "$CERTS_DIR/dhparam.pem" 2048 2>/dev/null
echo "   ✅ DH parametreleri: 2048-bit"

# =====================================================
# Temizlik
# =====================================================
rm -f "$CERTS_DIR"/*.csr "$CERTS_DIR"/*.cnf "$CERTS_DIR"/*.srl

# Dosya izinleri
chmod 600 "$CERTS_DIR"/*.key
chmod 644 "$CERTS_DIR"/*.crt "$CERTS_DIR"/*.pem

echo ""
echo "═══════════════════════════════════════════════════"
echo "✅ mTLS sertifikaları başarıyla oluşturuldu!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "📁 Dosyalar:"
ls -la "$CERTS_DIR/"
echo ""
echo "🔍 CA sertifika doğrulama:"
openssl x509 -in "$CERTS_DIR/ca.crt" -noout -subject -issuer -dates 2>/dev/null
echo ""
echo "🔍 Server sertifika doğrulama:"
openssl x509 -in "$CERTS_DIR/server.crt" -noout -subject -issuer -dates 2>/dev/null
echo ""
echo "🔍 Client sertifika doğrulama:"
openssl x509 -in "$CERTS_DIR/client.crt" -noout -subject -issuer -dates 2>/dev/null
echo ""
echo "📋 Kullanım:"
echo "   export MTLS_CA_CERT=$CERTS_DIR/ca.crt"
echo "   export MTLS_SERVER_CERT=$CERTS_DIR/server.crt"
echo "   export MTLS_SERVER_KEY=$CERTS_DIR/server.key"
echo "   export MTLS_CLIENT_CERT=$CERTS_DIR/client.crt"
echo "   export MTLS_CLIENT_KEY=$CERTS_DIR/client.key"
