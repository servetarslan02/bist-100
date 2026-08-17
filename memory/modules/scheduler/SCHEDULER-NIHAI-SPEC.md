# Scheduler Nihai Sistem Dokümanı — Kod Analizi + Araştırma Bazlı

**Tarih:** 2026-08-18
**Kaynaklar:** arXiv Agentic Trading (2026), Borsa İstanbul resmi, Mevcut kod analizi

---

## 1. Sektörde En İyi Uygulama Nedir?

### 1.1 Trading System Scheduler (En İyi Uygulama)

**Temel prensip:** Scheduler piyasa saatlerine göre çalışmalı — piyasa açıkken aktif, kapalıyken duraklamalı.

```
SCHEDULER ARCHITECTURE (En İyi Uygulama)

┌─────────────────────────────────────────────────┐
│              MARKET SESSION MANAGER              │
│  - BIST işlem saatleri                           │
│  - Tatil takvimi                                 │
│  - Faz belirleme (PRE/ACTIVE/POST/CLOSED)        │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────┼──────────────────────────┐
│              JOB SCHEDULER                        │
│  - Market-aware job scheduling                   │
│  - Config-driven intervals                       │
│  - Priority-based execution                      │
│  - DB-backed job tracking                        │
│  - SIGTERM/SIGINT handler                        │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────┼──────────────────────────┐
│              DAILY WORKFLOW                       │
│                                                   │
│  PRE-MARKET (09:50-10:00)                        │
│  - Market data update                            │
│  - Feature calculation                           │
│  - Universe refresh                              │
│                                                   │
│  ACTIVE TRADING (10:00-18:00)                    │
│  - Live scanning (continuous)                    │
│  - Batch scanning (her saat)                     │
│  - Signal generation                             │
│  - Risk monitoring                               │
│  - Health check                                  │
│                                                   │
│  POST-MARKET (18:00-18:30)                       │
│  - Persistence                                   │
│  - Daily report                                  │
│  - Performance attribution                       │
│                                                   │
│  AFTER-HOURS (18:30-09:50)                       │
│  - Learning cycle                                │
│  - Model retraining                              │
│  - Backtest                                      │
│  - Health check (düşük sıklık)                   │
└──────────────────────────────────────────────────┘
```

### 1.2 BIST İşlem Saatleri

| Seans | Saat | Açıklama |
|-------|------|----------|
| **Pre-market** | 09:40-09:55 | Emir toplama |
| **Seans 1** | 09:55-12:30 | Tek fiyat yöntemi |
| **Seans 2** | 14:00-17:40 | Sürekli müzayede |
| **Kapanış** | 17:40-18:00 | Kapanış fiyatları |
| **After-hours** | 18:00+ | Piyasa kapalı |

### 1.3 Job Types (En İyi Uygulama)

| Job | Frekans | Piyasa Durumu | Öncelik |
|-----|---------|---------------|---------|
| **market_data_update** | 2 dakika | Aktif | Yüksek |
| **feature_calculation** | 5 dakika | Aktif | Yüksek |
| **live_inference** | 5 dakika | Aktif | Yüksek |
| **ranking** | 10 dakika | Aktif | Orta |
| **signal_generation** | 10 dakika | Aktif | Orta |
| **health_check** | 1 dakika | Her zaman | Düşük |
| **persistence** | 15 dakika | Aktif + Post | Orta |
| **daily_report** | 1 kez/gün | Post-market | Düşük |
| **learning_cycle** | 1 kez/gün | After-hours | Düşük |
| **model_retrain** | Haftalık | After-hours | Düşük |

---

## 2. Bizde Şu An Ne Var?

### 2.1 Modül Özeti (3 dosya, 468 satır)

| Modül | Satır | Ne Yapıyor | Durum |
|-------|-------|------------|-------|
| `production_scheduler.py` | 199 | Market session-aware scheduler, config-driven intervals, DB-backed, SIGTERM handler | ✅ En kapsamlı |
| `main.py` (scheduler) | 152 | Alpha scheduler, 3 katmanlı tarama (pre/batch/post) | ⚠️ Basit |
| `daily_report.py` | 117 | Günlük rapor üretici, sinyal/anomali/portföy raporu | ✅ İyi |

### 2.2 production_scheduler.py (199 satır) — Detaylı

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `ProductionScheduler` | 43-199 | Ana scheduler sınıfı | ✅ |
| `DEFAULT_INTERVALS` | 45-54 | Varsayılan job aralıkları | ✅ İyi |
| `register_handler()` | 68-71 | Job handler kaydetme | ✅ |
| `update_interval()` | 73-76 | Runtime interval güncelleme | ✅ İyi |
| `start()` | 78-94 | Scheduler başlatma (SIGTERM handler) | ✅ İyi |
| `stop()` | 96-100 | Graceful shutdown | ✅ |
| `_signal_handler()` | 102-105 | SIGTERM/SIGINT callback | ✅ İyi |
| `_startup_sequence()` | 107-130 | Startup kontrolleri (config, DB, market session) | ✅ İyi |
| `_tick()` | 132-165 | Ana scheduler döngüsü (market phase bazlı) | ✅ İyi |
| `_maybe_run()` | 167-198 | Job çalıştırma kontrolü (interval, trading_only) | ✅ İyi |

### 2.3 main.py (152 satır) — AlphaScheduler

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `AlphaScheduler` | 22-152 | 3 katmanlı tarama scheduler | ⚠️ Basit |
| `start()` | 28-78 | Ana döngü (saat bazlı) | ⚠️ Basit |
| `_pre_market()` | 80-88 | Piyasa öncesi hazırlık | ✅ |
| `_batch_scan()` | 90-109 | Batch tarama | ✅ |
| `_post_market()` | 111-119 | Piyasa sonrası rapor | ✅ |
| `_daily_summary()` | 121-124 | Günlük özet | ⚠️ Boş |

### 2.4 daily_report.py (117 satır)

| Fonksiyon | Satır | Ne Yapıyor | Durum |
|-----------|-------|------------|-------|
| `generate_daily_report()` | 20-97 | Günlük rapor (piyasa, dünya, sinyaller, trade planları, anomaliler, portföy) | ✅ İyi |
| `generate_alert_message()` | 100-114 | Sinyal bildirimi | ✅ |
| `generate_anomaly_alert()` | 117-127 | Anomali bildirimi | ✅ |

---

## 3. Eksikler (Kritik)

### 3.1 AlphaScheduler ile ProductionScheduler Ayrı

**Sorun:** İki ayrı scheduler var — AlphaScheduler (main.py) ve ProductionScheduler (production_scheduler.py). İkisi de farklı işler yapıyor ama birbirine bağlı değil.
**Etki:** Tutarsız scheduling, duplicate iş
**Çözüm:** Tek canonical scheduler

### 3.2 Daily Workflow Otomasyonu Eksik

**Sorun:** AlphaScheduler saat bazlı çalışıyor ama production_scheduler phase bazlı. İkisi de eksik.
**Etki:** Günlük workflow tam otomatik değil
**Çözüm:** Tam günlük workflow otomasyonu

### 3.3 Learning Cycle Scheduler'da Yok

**Sorun:** Learning cycle (model retrain, drift detection) scheduler'da tanımlı değil
**Etki:** Model güncelleme otomatik değil
**Çözüm:** Learning cycle job'ları ekle

### 3.4 Backtest Scheduler'da Yok

**Sorun:** Otomatik backtest scheduler'da yok
**Etki:** Strateji doğrulama otomatik değil
**Çözüm:** Scheduled backtest job'ları

### 3.5 Alert Scheduling Yok

**Sorun:** Alert'ler scheduler ile entegre değil
**Etki:** Kritik durumlar zamanında bildirilmiyor
**Çözüm:** Scheduled alert checks

### 3.6 Job Retry Policy Yok

**Sorun:** Job başarısız olursa retry yok
**Etki:** Geçici hatalarda iş duruyor
**Çözüm:** Exponential backoff retry

### 3.7 Job Monitoring Yok

**Sorun:** Job'ların çalışıp çalışmadığı takip edilmiyor
**Etki:** Job failure'lar tespit edilemiyor
**Çözüm:** Job status tracking, failure alerts

### 3.8 Config-Driven Scheduling Zayıf

**Sorun:** Interval'lar hard-coded (production_scheduler'da config var ama alpha_scheduler'da yok)
**Etki:** Runtime'da scheduling ayarlanamıyor
**Çözüm:** Tüm scheduler'lar config-driven

---

## 4. Nihai Scheduler Mimarisi

### 4.1 Scheduler Pipeline (Nihai)

```
┌─────────────────────────────────────────────────────────────┐
│                    SCHEDULER PIPELINE                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              MARKET SESSION MANAGER                  │   │
│  │  - BIST işlem saatleri                              │   │
│  │  - Tatil takvimi                                    │   │
│  │  - Faz belirleme:                                   │   │
│  │    CLOSED → PRE_MARKET → ACTIVE → POST_MARKET →    │   │
│  │    AFTER_HOURS → CLOSED                             │   │
│  │  - Phase transition events                          │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              JOB SCHEDULER                          │   │
│  │  - Market-aware job scheduling                      │   │
│  │  - Config-driven intervals                          │   │
│  │  - Priority-based execution                         │   │
│  │  - DB-backed job tracking ← YENİ                    │   │
│  │  - Job retry policy ← YENİ                          │   │
│  │  - Job monitoring ← YENİ                            │   │
│  └─────────────────────────┬───────────────────────────┘   │
│                            ↓                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DAILY WORKFLOW                          │   │
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

### 4.2 Job Retry Policy (Nihai)

```python
class JobRetryPolicy:
    """Job retry politikası — exponential backoff."""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    async def execute_with_retry(self, handler: Callable, job_type: str,
                                  payload: Dict) -> Any:
        """Retry ile job çalıştır."""
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = await handler(payload)
                if attempt > 0:
                    logger.info("Job succeeded after retry",
                               job_type=job_type, attempt=attempt)
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning("Job failed, retrying",
                                 job_type=job_type, attempt=attempt,
                                 delay=delay, error=str(e))
                    await asyncio.sleep(delay)
                else:
                    logger.error("Job failed after all retries",
                               job_type=job_type, attempts=self.max_retries,
                               error=str(e))
        
        raise last_error
```

### 4.3 Job Monitoring (Nihai)

```python
class JobMonitor:
    """Job çalıştırma takibi."""
    
    def __init__(self):
        self._job_history = []  # {job_type, status, duration, timestamp}
    
    def record_job(self, job_type: str, status: str, duration_ms: float):
        """Job kaydet."""
        self._job_history.append({
            "job_type": job_type,
            "status": status,
            "duration_ms": duration_ms,
            "timestamp": datetime.now().isoformat(),
        })
        # Son 1000 job'ı tut
        if len(self._job_history) > 1000:
            self._job_history = self._job_history[-1000:]
    
    def get_stats(self, job_type: str = None) -> Dict:
        """Job istatistikleri."""
        history = self._job_history
        if job_type:
            history = [h for h in history if h["job_type"] == job_type]
        
        if not history:
            return {"total_jobs": 0}
        
        total = len(history)
        failed = sum(1 for h in history if h["status"] == "FAILED")
        avg_duration = np.mean([h["duration_ms"] for h in history])
        
        return {
            "total_jobs": total,
            "failed_jobs": failed,
            "success_rate": round((total - failed) / total, 4),
            "avg_duration_ms": round(avg_duration, 2),
            "last_failure": next((h for h in reversed(history) if h["status"] == "FAILED"), None),
        }
```

### 4.4 Config-Driven Scheduling (Nihai)

```python
SCHEDULER_CONFIG = {
    "pre_market": {
        "start": "09:40",
        "jobs": [
            {"type": "market_data_update", "interval": 120},
            {"type": "feature_calculation", "interval": 300},
            {"type": "universe_refresh", "interval": 86400},
        ],
    },
    "active_trading": {
        "start": "09:55",
        "end": "17:40",
        "jobs": [
            {"type": "live_scanning", "interval": 0},  # Continuous
            {"type": "batch_scan", "interval": 3600},   # Her saat
            {"type": "signal_generation", "interval": 600},
            {"type": "risk_monitoring", "interval": 120},
            {"type": "health_check", "interval": 60},
        ],
    },
    "post_market": {
        "start": "18:00",
        "end": "18:30",
        "jobs": [
            {"type": "persistence", "interval": 0},  # Bir kez
            {"type": "daily_report", "interval": 0},
            {"type": "performance_attribution", "interval": 0},
        ],
    },
    "after_hours": {
        "start": "18:30",
        "end": "23:00",
        "jobs": [
            {"type": "learning_cycle", "interval": 86400},
            {"type": "model_drift_detection", "interval": 86400},
            {"type": "backtest", "interval": 604800},  # Haftalık
            {"type": "health_check", "interval": 300},
        ],
    },
}
```

---

## 5. Rakip Karşılaştırması

### 5.1 ProductionScheduler vs AlphaScheduler

| Özellik | ProductionScheduler | AlphaScheduler | Fark |
|---------|-------------------|----------------|------|
| Market session aware | ✅ | ⚠️ Basit | ✅ |
| Config-driven | ✅ | ❌ | ✅ |
| DB-backed | ✅ | ❌ | ✅ |
| SIGTERM handler | ✅ | ❌ | ✅ |
| Job worker | ✅ | ❌ | ✅ |
| Metrics | ✅ | ❌ | ✅ |
| 3 katmanlı tarama | ❌ | ✅ | ⚠️ |
| Daily workflow | ⚠️ Eksik | ⚠️ Eksik | ⚠️ |

### 5.2 Best Practices Karşılaştırması

| Özellik | Best Practice | Bizim Sistem | Fark |
|---------|---------------|-------------|------|
| Market-aware scheduling | ✅ | ✅ | ✅ Aynı |
| Config-driven intervals | ✅ | ✅ | ✅ Aynı |
| DB-backed job tracking | ✅ | ⚠️ Basit | ⚠️ |
| Job retry policy | ✅ | ❌ | ❌ |
| Job monitoring | ✅ | ❌ | ❌ |
| Graceful shutdown | ✅ | ✅ | ✅ Aynı |
| Daily workflow automation | ✅ | ⚠️ Eksik | ⚠️ |
| Learning cycle scheduling | ✅ | ❌ | ❌ |
| Backtest scheduling | ✅ | ❌ | ❌ |

---

## 6. Uygulama Planı

### Faz 1: Unified Scheduler (Hemen)
1. AlphaScheduler'ı ProductionScheduler'a entegre et
2. Tek canonical scheduler
3. Daily workflow automation

### Faz 2: Job Retry & Monitoring (1 hafta)
1. Job retry policy (exponential backoff)
2. Job monitoring (status, duration, failure tracking)
3. Job failure alerts

### Faz 3: Learning & Backtest Scheduling (1 hafta)
1. Learning cycle job (daily)
2. Model drift detection job (daily)
3. Model retrain job (weekly)
4. Backtest job (weekly)

### Faz 4: Config Enhancement (1 hafta)
1. Tüm scheduler'lar config-driven
2. Runtime interval güncelleme
3. Job priority system

---

## 7. Mevcut Sistem vs Nihai Vizyon

| Özellik | Mevcut | Hedef |
|---------|--------|-------|
| Modül sayısı | 3 | 5 |
| Toplam satır | 468 | ~800 |
| Market-aware scheduling | ✅ | ✅ |
| Config-driven | ⚠️ Kısmen | ✅ Tam |
| DB-backed job tracking | ✅ | ✅ |
| SIGTERM handler | ✅ | ✅ |
| Job retry policy | ❌ | ✅ |
| Job monitoring | ❌ | ✅ |
| Daily workflow automation | ⚠️ Eksik | ✅ Tam |
| Learning cycle scheduling | ❌ | ✅ |
| Backtest scheduling | ❌ | ✅ |
| Unified scheduler | ❌ | ✅ |
