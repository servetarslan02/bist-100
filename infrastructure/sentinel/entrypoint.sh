#!/bin/sh
# Redis Sentinel entrypoint — environment variable'ları config'e inject eder
set -e

CONFIG_TEMPLATE="/etc/sentinel/sentinel.conf.template"
CONFIG="/tmp/sentinel.conf"

# Template'den gerçek config oluştur
# '#' delimiter kullan (şifrede '/' veya '&' olabilir)
sed "s#\${REDIS_PASSWORD}#${REDIS_PASSWORD}#g" "$CONFIG_TEMPLATE" > "$CONFIG"

# Sentinel'i başlat
exec redis-sentinel "$CONFIG"
