# 🚀 Scheduler System Nihai Mimari — Uygulama Planı

**Tarih:** 2026-08-20
**Hazırlayan:** AI Analiz (Kod Analizi + Araştırma)
**Kaynaklar:** arXiv Agentic Trading (2026), BIST resmi, CFA Institute (2026), APScheduler, Mevcut kod analizi

---

## 1. Araştırma Bulguları

### 1.1 Trading System Scheduler — En İyi Uygulama

**Temel prensip:** Scheduler piyasa saatlerine göre çalışmalı — piyasa açıkken aktif, kapalıyken duraklamalı.

| Job | Frekans | Piyasa Durumu | Öncelik |
|-----|---------|---------------|---------|
| market_data_update | 2 dakika | Aktif | Yüksek |
| feature_calculation | 5 dakika | Aktif | Yüksek |
| live_inference | 5 dakika | Aktif | Yüksek |
| ranking | 10 dakika | Aktif | Orta |
| signal_generation | 10 dakika | Aktif | Orta |
| health_check | 1 dakika | Her zaman | Düşük |
| persistence | 15 dakika | Aktif + Post | Orta |
| daily_report | 1 kez/gün | Post-market | Düşük |
| learning_cycle | 1 kez/gün | After-hours | Düşük |
| model_retrain | Haftalık | After-hours | Düşük |

### 1.2 BIST İşlem Saatleri

| Seans | Saat | Açıklama |
|-------|------|----------|
| Pre-market | 09:40-09:55 | Emir toplama |
| Seans 1 | 09:55-12:30 | Tek fiyat yöntemi |
| Seans 2 | 14:00-17:40 | Sürekli müzayede |
| Kapanış | 17:40-18:00 | Kapanış fiyatları |
| After-hours | 18:00+ | Piyasa kapalı |

### 1.3 APScheduler Best Practices

- **Config-driven**: Tüm job'lar config'den tanımlanmalı
- **Job persistence**: DB-backed job tracking
- **Retry policy**: Exponential backoff
- **Job monitoring**: Status, duration, failure tracking
- **Graceful shutdown**: SIGTERM/SIGINT handler

---

## 2. Mevcut Sistem Analizi

### 2.1 Modül Özeti (3 dosya, 468 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `production_scheduler.py` | 199 | Market session-aware, config-driven, DB-backed, SIGTERM | ✅ En kapsamlı |
| `main.py` | 152 | AlphaScheduler, 3 katmanlı tarama (pre/batch/post) | ⚠️ Basit |
| `daily_report.py` | 117 | Günlük rapor üretici | ✅ İyi |

### 2.2 Kritik Eksiklikler

| # | Eksiklik | Etki | Öncelik |
|---|----------|------|---------|
| 1 | **İki ayrı scheduler** | Tutarsız scheduling | 🔴 Kritik |
| 2 | **Job retry policy yok** | Geçici hatalarda iş duruyor | 🔴 Kritik |
| 3 | **Job monitoring yok** | Job failure'lar tespit edilemiyor | 🟡 Yüksek |
| 4 | **Daily workflow eksik** | Tam otomatik günlük akış yok | 🟡 Yüksek |
| 5 | **Learning cycle scheduler'da yok** | Model güncelleme otomatik değil | 🟡 Yüksek |
| 6 | **Backtest scheduling yok** | Strateji doğrulama otomatik değil | 🟠 Orta |
| 7 | **Config-driven zayıf** | Runtime'da scheduling ayarlanamıyor | 🟠 Orta |
| 8 | **Job failure alerts yok** | Kritik job failure'lar bildirilmiyor | 🟡 Yüksek |

---

## 3. Nihai Hedef — Unified Scheduler v2.0

```
┌─────────────────────────────────────────────────────────────┐
│                    UNIFIED SCHEDULER v2.0                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  MARKET SESSION MANAGER                              │   │
│  │  ✅ BIST işlem saatleri                              │   │
│  │  ✅ Faz belirleme (CLOSED→PRE→ACTIVE→POST→AFTER)    │   │
│  │  🆕 Tatil takvimi                                    │   │
│  │  🆕 Phase transition events                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  JOB SCHEDULER                                       │   │
│  │  ✅ Market-aware job scheduling                      │   │
│  │  ✅ Config-driven intervals                          │   │
│  │  🆕 Job retry policy (exponential backoff)           │   │
│  │  🆕 Job monitoring (status, duration, failure)       │   │
│  │  🆕 Job failure alerts                               │   │
│  │  🆕 Priority-based execution                         │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  DAILY WORKFLOW                                      │   │
│  │                                                      │   │
│  │  09:40 — PRE-MARKET                                 │   │
│  │    ├── Market data update                           │   │
│  │    ├── Feature calculation                          │   │
│  │    ├── Universe refresh                             │   │
│  │    └── Regime detection                             │   │
│  │                                                      │   │
│  │  09:55-12:30 — SEANS 1                              │   │
│  │    ├── Live scanning (continuous)                   │   │
│  │    ├── Batch scan (10:00)                           │   │
│  │    ├── Signal generation                            │   │
│  │    └── Risk monitoring                              │   │
│  │                                                      │   │
│  │  12:30-14:00 — ARA                                  │   │
│  │    ├── Feature recalculation                        │   │
│  │    └── Health check                                 │   │
│  │                                                      │   │
│  │  14:00-17:40 — SEANS 2                              │   │
│  │    ├── Live scanning (continuous)                   │   │
│  │    ├── Batch scan (15:00)                           │   │
│  │    ├── Signal generation                            │   │
│  │    └── Risk monitoring                              │   │
│  │                                                      │   │
│  │  17:40-18:00 — KAPANIŞ                              │   │
│  │    ├── Closing price update                         │   │
│  │    └── Daily P&L calculation                        │   │
│  │                                                      │   │
│  │  18:00-18:30 — POST-MARKET                          │   │
│  │    ├── Persistence                                  │   │
│  │    ├── Daily report                                 │   │
│  │    ├── Performance attribution                      │   │
│  │    └── Alert check                                  │   │
│  │                                                      │   │
│  │  18:30-23:00 — AFTER-HOURS                          │   │
│  │    ├── Learning cycle                               │   │
│  │    ├── Model drift detection                        │   │
│  │    ├── Backtest (scheduled)                         │   │
│  │    ├── Model retrain (weekly)                       │   │
│  │    └── Health check (düşük sıklık)                  │   │
│  │                                                      │   │
│  │  23:00-09:40 — NIGHT                                │   │
│  │    ├── Health check (çok düşük sıklık)              │   │
│  │    └── Backup                                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Faz Planı

### FAZ 1: Unified Scheduler (1-2 gün)

**Amaç:** İki scheduler'ı birleştir, tek canonical scheduler oluştur.

```
Dosya: services/scheduler/unified_scheduler.py
```
- [ ] `UnifiedScheduler` sınıfı
  - [ ] `ProductionScheduler`'dan market session awareness
  - [ ] `AlphaScheduler`'dan 3 katmanlı tarama
  - [ ] Config-driven intervals
  - [ ] SIGTERM/SIGINT handler
  - [ ] Graceful shutdown

### FAZ 2: Job Retry & Monitoring (1-2 gün)

**Amaç:** Job failure'ları retry et, job istatistiklerini takip et.

```
Dosya: services/scheduler/job_retry.py
Dosya: services/scheduler/job_monitor.py
```
- [ ] `JobRetryPolicy` sınıfı
  - [ ] Exponential backoff (1s, 2s, 4s)
  - [ ] Max retry sayısı (configurable)
  - [ ] Retry logging
- [ ] `JobMonitor` sınıfı
  - [ ] `record_job(job_type, status, duration_ms)` — job kaydet
  - [ ] `get_stats(job_type)` — istatistikler
  - [ ] `get_failure_rate()` — failure rate
  - [ ] `get_slow_jobs(threshold_ms)` — yavaş job'lar

### FAZ 3: Daily Workflow Automation (1 gün)

**Amaç:** Tam günlük workflow otomasyonu.

```
Dosya: services/scheduler/daily_workflow.py
```
- [ ] `DailyWorkflow` sınıfı
  - [ ] Pre-market jobs (09:40-09:55)
  - [ ] Active trading jobs (09:55-17:40)
  - [ ] Post-market jobs (17:40-18:30)
  - [ ] After-hours jobs (18:30-23:00)
  - [ ] Night jobs (23:00-09:40)
  - [ ] Phase transition callbacks

### FAZ 4: Learning & Backtest Scheduling (1 gün)

**Amaç:** Learning cycle ve backtest'i otomatik zamanla.

```
Dosya: services/scheduler/learning_scheduler.py
```
- [ ] `LearningScheduler` sınıfı
  - [ ] `schedule_learning_cycle()` — günlük
  - [ ] `schedule_model_drift_detection()` — günlük
  - [ ] `schedule_model_retrain()` — haftalık
  - [ ] `schedule_backtest()` — haftalık
  - [ ] `schedule_calibration_update()` — aylık

### FAZ 5: Config Enhancement & API (1 gün)

**Amaç:** Runtime config güncelleme ve scheduler API.

```
Dosya: services/scheduler/scheduler_config.py
Dosya: services/scheduler/scheduler_api.py
```
- [ ] `SchedulerConfig` sınıfı
  - [ ] Config dosyasından yükleme
  - [ ] Runtime interval güncelleme
  - [ ] Job enable/disable
- [ ] `GET /api/scheduler/status` — scheduler durumu
- [ ] `GET /api/scheduler/jobs` — job listesi
- [ ] `GET /api/scheduler/monitor` — job monitoring
- [ ] `POST /api/scheduler/trigger/{job}` — manuel tetikleme

---

## 5. Test Stratejisi

| Faz | Test Dosyası | Min Test | Kritik Test |
|-----|-------------|----------|-------------|
| 1 | test_scheduler_faz1.py | 8 | Unified scheduler lifecycle |
| 2 | test_scheduler_faz2.py | 10 | Retry + monitoring |
| 3 | test_scheduler_faz3.py | 6 | Daily workflow phases |
| 4 | test_scheduler_faz4.py | 6 | Learning scheduling |
| 5 | test_scheduler_faz5.py | 6 | Config + API |

---

## 📊 Zaman Özeti

| Faz | Süre | Teslimat |
|-----|------|----------|
| **Faz 1** | 1-2 gün | Unified scheduler |
| **Faz 2** | 1-2 gün | Job retry + monitoring |
| **Faz 3** | 1 gün | Daily workflow |
| **Faz 4** | 1 gün | Learning scheduling |
| **Faz 5** | 1 gün | Config + API |
| **TOPLAM** | **5-7 gün** | |

---

## 📚 Referanslar

1. arXiv Agentic Trading (2026)
2. BIST resmi işlem saatleri
3. CFA Institute — Trade Strategy & Execution (2026)
4. APScheduler best practices
5. Mevcut kod analizi (3 dosya, 468 satır)
