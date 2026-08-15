# Bölüm 2 — Veri Kalitesi ve Gerçeklik

## Amaç

Bölüm 1'in topladığı verilerin gerçekten kullanılabilir olup olmadığını belirlemek.

---

## Kullanılacak sistemler

- Data Validation
- Data Quality Engine
- Source Reliability
- Duplicate Detection
- Point-in-Time Data
- Look-Ahead Bias Protection
- Survivorship Bias Protection
- Data Reconciliation
- Data Lineage
- Anomaly Detection

---

## Çalışma mantığı

```
Bölüm 1 verileri
    ↓
Format / tip kontrolü
    ↓
Eksik veri kontrolü
    ↓
Kaynak karşılaştırması
    ↓
Tarih-zaman kontrolü
    ↓
Duplicate kontrolü
    ↓
Anomali kontrolü
    ↓
Bias kontrolü
    ↓
Güvenilirlik skoru
    ↓
ANALİZE HAZIR VERİ
```

---

## Nasıl kullanılacak?

Örneğin bir hissenin kapanışı bir kaynaktan 100 TL, diğerinden 105 TL gelirse sistem doğrudan birini seçmeyecek.

Kaynak güvenilirliği, zaman damgası ve diğer veriler kontrol edilerek uyuşmazlığı tespit edecek.

Aynı şekilde:

- Veri eksikse → eksik olarak işaretleyecek
- Şüpheli değerse → kalite skorunu düşürecek
- Geleceğe ait bilgi varsa → analizden çıkaracak
- Aynı event iki kez geldiyse → tekilleştirecek
- Sonradan düzeltilmiş veri geçmiş analize sızıyorsa → point-in-time versiyonu kullanacak

---

## Çıktısı

Her veri için kabaca:

- Değer
- Kaynak
- Zaman
- Güncellik
- Güvenilirlik
- Kalite

oluşacak.

Örneğin:

```
Hisse fiyatı: 125.40
Kaynak:       X
Güncellik:    2 dk
Kalite:       %98
Güven:        Yüksek
```

---

## Kritik prensip

Bu bölüm **analiz yapmaz** ve **hisse seçmez**.

Sadece sonraki motorlara:

> "Bu veri güvenilir, bu veri şüpheli, bu veri kullanılamaz."

şeklinde temiz ve ölçülebilir bir veri zemini sağlar.

Böylece sonraki Piyasa Analizi bölümü yanlış veya geleceğe ait verilerle karar vermez.
