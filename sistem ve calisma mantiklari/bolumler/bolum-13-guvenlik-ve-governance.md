# Bölüm 13 — Güvenlik ve Governance

## Amaç

Sistemi ve verileri korumak. "Ne yapamaz?" sorusunun cevabı.

## Çalışma Mantığı

```
İstek → Kimlik doğrulama → Yetkilendirme → Güvenlik kontrolü → İşlem
```

## Temel Prensip

AI risk bypass edemez. Agent kendi permissions'unu değiştiremez. Audit history değiştirilemez.

---

## 1. Authentication

**Yöntem:** Session/Token tabanlı

**Özellikler:**
- Password hashing (PBKDF2)
- Token expiration (24 saat)
- Session tracking

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/security.py`

---

## 2. Authorization

**Roller:**
- VIEWER: Sadece okuma
- ANALYST: Okuma + backtest + scenario
- OPERATOR: Okuma + backtest + scenario + config
- ADMIN: Tüm izinler
- SYSTEM: Tüm izinler (otomatik)

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/security.py`

---

## 3. Safety Governance

**Yapamayacakları:**
- AI risk bypass edemez
- AI doğrudan portföy değiştiremez
- AI audit geçmişini silemez
- AI kendi kendini production'a alamaz
- Agent kendi permissions'unu değiştiremez

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/security.py`

---

## 4. No-Trade Gate

**Koşullar (herhangi biri → NO_TRADE):**
- Kötü veri
- Risk engine çalışmıyor
- Portföy tutarsız
- Model geçersiz
- Kritik olay belirsizliği
- Sistem degraded

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/security.py`

---

## 5. System State Machine

**Durumlar:**
```
STARTING → INITIALIZING → READY → DEGRADED → RECOVERY → READY
                                       ↓
                                    FAILED
```

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/security.py`

---

## 6. Secret Redaction

**Amaç:** Loglarda hassas bilgi gizler.

**Kapsam:** API key, token, secret, password, Bearer token

**Durum:** ✅ Çalışıyor

**Dosya:** `services/core/security.py`
