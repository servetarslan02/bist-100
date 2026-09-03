# services/simulation/ — Denetim Raporu

---

## SAYFA 1 — Denetim Kuralları

Bu klasördeki tüm `.py` dosyaları aşağıdaki kurallara göre denetlenir.

### K1 — Placeholder Docstring
Aşağıdaki ifadeler placeholder kabul edilir ve düzeltilir:
- `"metod metodu"`, `"__init__ metodu"`, `"X metodu"`
- `"Otomatik eklendi"`
- Sınıf docstring'i ile aynı olan metod docstring'leri
- Anlamsız tek cümlelik docstring'ler

**Kural:** Her docstring, o metodun/sınıfın ne yaptığını açıkça tanımlar.

### K2 — Kritik Mantık Hataları
- Boundary hataları (eşik değerlerde yanlış sonuç)
- Yanlış veri kaynağı
- Eksik filtreleme
- Dead code (hiç çalışmayan kod parçaları)

### K3 — Eksik Fonksiyonellik
- Eksik parametreler
- Eksik loglama (veto, error, warning)
- Eksik fallback mekanizmaları

### K4 — Güvenlik ve Dayanıklılık
- Güvensiz dict erişimi (`data["key"]` yerine `data.get("key")`)
- Exception handling eksikliği
- Regex sınırlamaları

### K5 — Kod Kalitesi
- `__repr__` eksik (dataclass'lar için zorunlu)
- Gereksiz import'lar
- Return type annotation eksik
- Değişken gölgeleme

### Düzeltme Standartları
- Tüm docstring'ler Türkçe ve açıklayıcı
- Mock/statik veri kabul edilmez — production-grade
- `__repr__` tüm dataclass'lara eklenir
- Return type'lar doğru (`Any` yerine gerçek tip)
- Gereksiz import'lar kaldırılır
- Düzeltme sonrası syntax kontrolü yapılır

---

## SAYFA 2 — Genel Bakış

**Tarih:** —  
**Kapsam:** `services/simulation/` — ? dosya  
**Denetim Sonucu:** — sorun tespit edildi, — düzeltildi

### Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | — | — | ⏳ Bekliyor |

### Kategori Dağılımı

| Kategori | Sayı |
|----------|------|
| Placeholder docstring | — |
| Kritik mantık hatası | — |
| Eksik fonksiyonellik | — |
| Güvenlik ve dayanıklılık | — |
| Kod kalitesi | — |
| **Toplam** | **—** |

---

## SAYFA 3 — Kritik Mantık Hataları

| # | Dosya | Hata | Etki | Düzeltme |
|---|-------|------|------|----------|
| — | — | — | — | — |

---

## SAYFA 4 — Eksik Fonksiyonellik

| # | Dosya | Eksik | Eklenen |
|---|-------|-------|---------|
| — | — | — | — |

---

## SAYFA 5 — Güvenlik ve Dayanıklılık

| # | Dosya | Sorun | Düzeltme |
|---|-------|-------|----------|
| — | — | — | — |

---

## SAYFA 6 — Kod Kalitesi

| # | Dosya | Sorun | Düzeltme |
|---|-------|-------|----------|
| — | — | — | — |

---

## SAYFA 7 — İyileştirmeler

_Denetim sırasında yapılan geliştirmeler buraya yazılır._

---

## SAYFA 8 — Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| — | — | — |

---

## SAYFA 9 — Dosya Bazlı Detaylar

_Her dosya için kısa özet buraya yazılır._
