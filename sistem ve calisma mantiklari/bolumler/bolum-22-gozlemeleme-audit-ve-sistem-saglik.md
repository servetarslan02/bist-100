# Bölüm 22 — Gözlemleme, Audit ve Sistem Sağlık Kontrolü

## Amaç

Sistemin sadece çalışıyor görünmesini değil, gerçekte doğru çalışıp çalışmadığını sürekli ölçmek.

---

## Kullanılacak sistemler

- Monitoring
- Observability
- Metrics
- Structured Logging
- Distributed Tracing
- Alerting
- Audit Log
- Data Quality Dashboard
- Model Monitoring
- Agent Monitoring
- Cost Monitoring

---

## Çalışma mantığı

```
Tüm Sistemler
    ↓
Logs + Metrics + Traces
    ↓
Monitoring Engine
    ↓
Anomaly Detection
    ↓
Health Score
    ↓
Alert / Incident
    ↓
Audit
```

---

## Neler izlenecek?

### Veri:
- Veri gecikmesi
- Eksik veri
- Kaynak hataları
- Veri kalitesi

### AI / Model:
- Tahmin doğruluğu
- Confidence calibration
- Model drift
- Anormal sonuçlar

### Agent:
- Hangi agent çalıştı?
- Hangi araçları kullandı?
- Ne kadar sürdü?
- Hata verdi mi?
- Gereksiz döngüye girdi mi?

### Altyapı:
- CPU/RAM
- API gecikmesi
- Queue
- Database
- Worker durumu

### Maliyet:
- API kullanımı
- Token tüketimi
- Model maliyeti
- Veri sağlayıcı maliyeti

---

## Audit

Kritik bir karar için sonradan şu zincir görülebilmeli:

```
Karar
    ↓
Hangi model?
    ↓
Hangi agent?
    ↓
Hangi veriler?
    ↓
Hangi kaynaklar?
    ↓
Hangi hesaplamalar?
    ↓
Hangi risk kontrolü?
    ↓
Sonuç
```

**Yani sistemin kararları black-box olmamalı.**

---

## Health Score

Örneğin:

```
Data Health:          96%
Model Health:         91%
Agent Health:         98%
Infrastructure:       99%
Overall Health:       95%
```

Kritik bir bileşen bozulduğunda sistem bunu karar motoruna da bildirecek.

Örneğin:

> **Risk Engine sağlıksız → yeni BUY kararlarını engelle.**

---

## Temel prensip

Monitoring sadece "sunucu ayakta mı?" diye bakmayacak.

Asıl soru:

> **"Sistem doğru veriyle, doğru modeli, doğru zamanda, doğru şekilde çalıştırıyor mu?"**

olacak.
