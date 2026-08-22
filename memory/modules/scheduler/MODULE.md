# SCH — Scheduler System

## Giriş

Scheduler modülü, ALPHA BIST sisteminin tüm zamanlanmış görevlerini yönetir. BIST piyasa saatlerine (9 faz) duyarlı, config-driven, priority-based, DB-backed bir scheduler mimarisi kullanır. Günlük workflow otomasyonu, öğrenme döngüsü zamanlaması, job monitoring ve alerting sağlar. SIGTERM/SIGINT handler ile graceful shutdown destekler.

## Katman Haritası

```
┌─────────────────────────────────────────────────────────────┐
│                    UnifiedScheduler                           │
│                    (unified_scheduler.py)                     │
│  Market-aware · Config-driven · Priority-based · DB-backed   │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│ Market   │ Job      │ DB Job   │ Manual   │ Signal          │
│ Session  │ Config   │ Tracker  │ Trigger  │ Handler         │
│ Manager  │ (17 job) │ (PG+mem) │ Queue    │ (SIGTERM/INT)   │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                    DailyWorkflow                              │
│                    (daily_workflow.py)                         │
│  8 faz: pre_market → seans_1 → break → seans_2 → closing    │
│         → post_market → after_hours → night                  │
├─────────────────────────────────────────────────────────────┤
│                    LearningScheduler                          │
│                    (learning_scheduler.py)                    │
│  Günlük: learning_cycle, drift_detection                     │
│  Haftalık: model_retrain, backtest                           │
│  Aylık: calibration_update                                   │
├─────────────────────────────────────────────────────────────┤
│                    JobMonitor                                 │
│                    (job_monitor.py)                           │
│  Status tracking · Duration · Failure rate · Slow detection  │
│  Consecutive failure alerts · Percentile (p50/p95/p99)       │
├─────────────────────────────────────────────────────────────┤
│                    SchedulerAPI                               │
│                    (scheduler_api.py)                         │
│  GET /status · /jobs · /monitor · /workflow · /learning      │
│  GET /market · /history · /dashboard                         │
│  POST /trigger/{job} · /interval · /enable                   │
├─────────────────────────────────────────────────────────────┤
│                    DailyReport                                │
│                    (daily_report.py)                          │
│  Günlük rapor üretici · Sinyal bildirimleri · Anomali alert │
└─────────────────────────────────────────────────────────────┘
```

## Neden Bu Tasarım Seçimi?

| Karar | Neden |
|-------|-------|
| Market session-aware (9 faz) | BIST saatleri sabit; gece trading job çalıştırmak kaynak israfı, seans içinde risk monitoring atlamak tehlikeli |
| Priority-based execution | p=1 (market_data) her zaman önce çalışmalı; p=10 (backup) en son. Kritik job'lar排队 olmaz |
| Config-driven intervals | 17 job tipi, her biri farklı interval (60 sn → 30 gün). Runtime'da değiştirilebilir |
| DB-backed job tracking | system_jobs tablosuna persist; restart sonrası geçmiş kaybolmaz. DB yoksa in-memory fallback |
| Exponential backoff retry | 1s → 2s → 4s; transient hatalarda otomatik kurtarma. Max 3 deneme |
| Dinamik tatil takvimi | DB/config dosyası → hardcoded fallback öncelik sırası. Ramazan/Kurban tarihleri yıllık değişir |
| SIGTERM/SIGINT handler | Docker/K8s graceful shutdown; devam eden job'lar tamamlanır |
| Manuel tetikleme queue | API'den `POST /trigger/{job}` ile anında çalıştırma; rate limited (10/dk) |
| Learning scheduler ayrı | ML job'ları (drift, retrain, backtest) trading job'larından farklı lifecycle'a sahip |

## Uçtan Uca Veri Akışı

```
1. UnifiedScheduler.start()
   a. Signal handler kaydet (SIGTERM/SIGINT)
   b. Startup sequence: market session, holiday calendar, handler'lar, config'ler
   c. Ana döngü: _main_loop() + _trigger_consumer() paralel

2. Her tick (_tick):
   a. MarketSessionManager.current_phase() → mevcut faz
   b. Faza göre sleep süresi belirle:
      - ACTIVE (seans): 30s
      - BREAK: 60s
      - NIGHT: 300s (veya sonraki faza kadar)
   c. _run_jobs_for_phase(phase_name):
      - Eligible job'ları filtrele (enabled + trading_only kontrolü)
      - Priority'ye göre sırala (1→10)
      - Her job için _maybe_run_job(): interval kontrolü → _execute_with_retry()

3. Job çalıştırma (_execute_with_retry):
   a. asyncio.wait_for(handler(), timeout=config.timeout_seconds)
   b. Başarılı → JobResult(status=SUCCESS) → DB + memory kayıt
   c. Timeout/Exception → exponential backoff bekle → tekrar dene (max 3)
   d. Tüm retry'lar başarısız → JobResult(status=FAILED) → DB + memory + alert

4. Manuel tetikleme:
   a. POST /api/scheduler/trigger/{job} → SchedulerAPI.trigger_job()
   b. Rate limit kontrolü (10/dk)
   c. _trigger_queue'ya ekle → _trigger_consumer() tarafından alınır
   d. _execute_with_retry(triggered_by="manual")

5. DailyWorkflow.execute_phase(phase_name):
   a. Phase handler çalıştır (varsa)
   b. Fazdaki job'ları sırayla çalıştır
   c. Sayaçları güncelle (jobs_run_today, jobs_failed_today)

6. LearningScheduler.run_pending_jobs():
   a. Her learning job için interval kontrolü
   b. Zamanı gelenleri çalıştır
   c. last_run güncelle

7. JobMonitor.record_job():
   a. JobRecord oluştur → history'ye ekle
   b. Consecutive failure tracking → 3 ardışık failure → CRITICAL alert
   c. Slow job detection → threshold aşımı → WARNING alert
   d. Alert callback'lerini tetikle
```

## Dosya Bazlı Sorumluluk Tablosu

| Dosya | Sorumluluk |
|-------|-----------|
| `unified_scheduler.py` | **Ana scheduler** — UnifiedScheduler (market-aware, config-driven, priority-based, DB-backed), MarketSessionManager (9 BIST fazı, phase transition callback), HolidayProvider (dinamik + fallback tatil takvimi), JobType enum (17 job tipi), JobConfig (interval, priority, timeout, retry), JobResult, DBJobTracker (PostgreSQL + in-memory fallback), DEFAULT_JOB_CONFIGS (varsayılan konfigürasyonlar) |
| `daily_workflow.py` | DailyWorkflow — 8 faz tanımı (pre_market, seans_1, break, seans_2, closing, post_market, after_hours, night), her faz için job listesi, phase handler desteği, WorkflowStatus, günlük sayaçlar (jobs_run_today, jobs_failed_today), daily report tracking |
| `learning_scheduler.py` | LearningScheduler — 5 learning job (learning_cycle 24h, model_drift_detection 24h, model_retrain 168h, backtest 168h, calibration_update 720h), async handler doğrulama (sync → async wrapper), interval güncelleme, pending job listesi |
| `job_monitor.py` | JobMonitor — JobRecord/JobStatus/JobAlert dataclass'ları, status tracking, duration monitoring (p50/p95/p99 percentile), failure rate tracking, slow job detection (30s eşik), consecutive failure alerts (3 ardışık → CRITICAL), callback-based alerting |
| `scheduler_api.py` | SchedulerAPI — 11 endpoint handler (get_status, get_jobs, get_monitor, get_workflow, get_learning, get_market_session, get_job_history, trigger_job, update_interval, enable_job, update_priority, get_full_dashboard), trigger rate limiter (10/dk) |
| `daily_report.py` | generate_daily_report() — piyasa durumu, dünya durumu, sinyaller, trade planları, anomaliler, portföy özeti; generate_alert_message() — sinyal bildirimleri; generate_anomaly_alert() — anomali bildirimleri |

## Tasarım İlkeleri ve Kırmızı Çizgiler

1. **Trading-only job'lar sadece seans açıkken** — `config.trading_only=True` → piyasa kapalıyken otomatik atlanır.
2. **Priority sıralaması zorunlu** — Her fazda job'lar p=1 (en yüksek) → p=10 (en düşük) sırasıyla çalıştırılır.
3. **Timeout zorunlu** — Her job `config.timeout_seconds` ile sınırlı; aşarsa TIMEOUT olarak kaydedilir.
4. **Retry exponential backoff** — 1s → 2s → 4s; max `config.max_retries` deneme.
5. **DB kayıt zorunlu** — Her job sonucu DB'ye persist edilir; DB yoksa in-memory fallback.
6. **Graceful shutdown** — SIGTERM/SIGINT → `_running=False` → devam eden job'lar tamamlanır.
7. **Tatil takvimi dinamik** — DB/config dosyasından yüklenir; hardcoded fallback sadece son çare.
8. **Manuel tetikleme rate limited** — Dakikada max 10 tetikleme; spam önlenir.

## Bilinen Sınırlamalar

- **In-memory job history** — DB yoksa restart sonrası geçmiş kaybolur (max 1000 kayıt).
- **Tatil takvimi hardcoded** — 2026-2027 yılları için sabit; yeni yıl eklenmesi gerekir.
- **Tek process** — Tüm job'lar tek process içinde çalışır; bir job CPU'yu tüketirse diğerleri etkilenir.
- **Learning scheduler bağımsız** — UnifiedScheduler'dan ayrı çalışır; entegrasyon manuel.
- **Daily report basit** — Text formatında; PDF/HTML dashboard yok.
- **Job dependency yok** — Job'lar bağımsız çalışır; bir job'ın başka bir job'a bağımlılığı desteklenmez.
- **No distributed scheduling** — Tek instance; multi-instance deployment'da çakışma olabilir.

## Cross-Reference

- **API** → `scheduler_api.py` → scheduler durumu ve manuel tetikleme endpoint'leri
- **Agent System** → `learning_cycle` job'u → agent self-evaluation tetikler
- **Alternative Data** → `feature_calculation` job'u → periyodik feature hesaplama
- **Scanner** → `batch_scan` ve `live_scanning` job'ları → opportunity engine tarama
- **Portfolio** → `risk_monitoring` job'u → portföy risk kontrolü
- **ML Models** → `model_drift_detection` ve `model_retrain` job'ları → model bakım
- **Database** → `persistence` job'u → veri saklama; `backup` job'u → DB yedekleme
