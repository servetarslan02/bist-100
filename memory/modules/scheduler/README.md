# Scheduler

**Modül sayısı:** 6 | **Toplam satır:** ~1,700

| Modül | Satır | Sınıf | Açıklama |
|-------|-------|-------|----------|
| `unified_scheduler` | ~700 | 5 | Tek canonical scheduler (market-aware, DB-backed, priority-based) |
| `job_monitor` | ~280 | 3 | Job monitoring (status, duration, failure, alerting) |
| `daily_workflow` | ~200 | 3 | Günlük workflow otomasyonu (8 faz) |
| `learning_scheduler` | ~170 | 2 | Learning cycle scheduling (drift, retrain, backtest) |
| `scheduler_api` | ~200 | 1 | Scheduler API endpoints (trigger dahil) |
| `daily_report` | ~120 | 0 | Günlük rapor üretici |

## Temel Özellikler

- ✅ Market session-aware (BIST saatleri, 9 faz)
- ✅ Config-driven intervals (16 job tipi)
- ✅ Priority-based execution (1=en yüksek, 10=en düşük)
- ✅ DB-backed job tracking (system_jobs tablosu, memory fallback)
- ✅ Job retry policy (exponential backoff, timeout)
- ✅ Job monitoring (consecutive failure, slow job alerts)
- ✅ Dinamik tatil takvimi (config/holidays.json + runtime ekleme)
- ✅ Manuel tetikleme (POST /api/scheduler/trigger/{job})
- ✅ SIGTERM/SIGINT handler
- ✅ Graceful shutdown
- ✅ 90 test (tümü geçiyor)
