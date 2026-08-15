# Bölüm 12 — Denetim ve İzleme

## Amaç

Her kararın izlenebilirliğini sağlamak. "Bu karar neden alındı?" sorusunun cevabı.

## Çalışma Mantığı

```
Karar → Audit log → Lineage → Snapshot → Recovery → Denetim
```

## Temel Prensip

Her kararın veri kaynağına kadar izlenebilirliği zorunlu.

---

## 1. Audit Log

**Amaç:** Her önemli olayı immutable olarak kaydeder.

**Kaydedilen olaylar:**
- Karar (DECISION)
- Risk kontrolü (RISK_CHECK)
- Sipariş (ORDER)
- Dolum (FILL)
- State değişikliği (STATE_CHANGE)
- Config değişikliği (CONFIG_CHANGE)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/audit_log.py`

---

## 2. Lineage

**Amaç:** Bir kararın tüm zincirini takip eder.

**Zincir:**
```
RAW_DATA → FEATURE → SIGNAL → DECISION → RISK → ORDER → FILL
```

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/audit_log.py`

---

## 3. Snapshot System

**Amaç:** Sistem durumunu periyodik olarak kaydeder.

**Kaydedilen:**
- Portföy durumu
- Pozisyonlar
- Nakit
- Karar geçmişi
- Model versiyonları
- Config versiyonu
- World state

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/infrastructure.py`

---

## 4. Recovery

**Amaç:** Sistem restart sonrası kaldığı yerden devam eder.

**Yöntem:**
1. Son snapshot'ı yükle
2. Snapshot'tan sonraki event'leri replay et
3. State doğrula
4. Devam et

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/state_recovery.py`

---

## 5. Observability

**Metrikler:**
- Events total/failed/duplicate
- Data quality failures
- LLM requests/failures/latency
- Decisions total
- Risk rejections
- Portfolio equity/drawdown

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/observability.py`

---

## 6. Alert System

**Kategoriler:**
- Opportunity (yeni fırsat)
- Risk (limit aşıldı)
- News (kritik haber)
- KAP (önemli bildirim)
- Regime (rejim değişikliği)
- Portfolio (P&L değişikliği)
- Model (model drift)
- System (servis hatası)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/infrastructure.py`

---

## 7. Çıktı

```
AUDIT LOG
──────────────────────────────
10:00:01  DECISION    THYAO  BUY    confidence=0.78
10:00:02  RISK_CHECK  THYAO  PASS   position_limit OK
10:00:03  ORDER       THYAO  BUY    150 lot @ ₺305.25
10:00:04  FILL        THYAO  BUY    150 lot @ ₺305.40
──────────────────────────────
Lineage: RAW → FEATURE → SIGNAL → DECISION → RISK → ORDER → FILL
```
