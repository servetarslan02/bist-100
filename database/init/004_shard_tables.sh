#!/bin/bash
# =====================================================
# ALPHA BIST — Shard Table Initialization
# NOT: Sharding devre dışı (SHARDING_ENABLED=false)
# Bu script sadece ileride sharding aktif edilirse kullanılır.
# =====================================================

echo "ℹ️  Sharding devre dışı — shard tabloları oluşturulmadı."
echo "   Sharding aktif etmek için: SHARDING_ENABLED=true"

# Sharding aktif edilmek istenirse aşağıdaki komutları çalıştırın:
# set -e
# PSQL="psql -v ON_ERROR_STOP=1"
# create_tables() {
#     local db=$1
#     $PSQL -d "$db" <<-EOSQL
#         CREATE TABLE IF NOT EXISTS prices (...);
#         CREATE TABLE IF NOT EXISTS signals (...);
#         CREATE TABLE IF NOT EXISTS portfolio_positions (...);
#     EOSQL
# }
# create_tables "alpha_bist_af"
# create_tables "alpha_bist_gm"
# create_tables "alpha_bist_nz"
