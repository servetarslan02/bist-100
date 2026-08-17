# ALPHA BIST — Memory Index

**Son güncelleme:** 2026-08-18

## 📁 Dizin Yapısı

```
memory/
├── VISION.md                        ← Nihai hayal ve sistem vizyonu
├── INDEX.md                         ← Bu dosya
│
├── documentation/                   ← Proje dokümantasyonu (12 dosya)
│   ├── 00-INDEX.md                  ← Doküman indeksi
│   ├── 01-VIZYON-VE-MANIFESTO.md    ← Vizyon ve manifesto
│   ├── 02-SISTEM-MIMARISI.md        ← Sistem mimarisi
│   ├── 03-VERI-VE-BILGI-EVRENI.md   ← Veri ve bilgi evreni
│   ├── 04-FEATURE-MOTORLARI-VE-SINYAL-URETIMI.md
│   ├── 05-MODEL-OGRENME-VE-ARASTIRMA-DONGUSU.md
│   ├── 06-RISK-PORTFOY-VE-EXECUTION.md
│   ├── 07-DEGERLENDIRME-VE-BASARI-KRITERLERI.md
│   ├── 08-YOL-HARITASI-VE-FAZLAR.md
│   ├── 09-MEVCUT-DURUM-VE-ACIK-ANALIZI.md
│   ├── 10-YONETISIM-GUVENLIK-VE-UYUM.md
│   └── 11-SOZLUK.md
│
├── system/                          ← Sistem tanımı ve çalışma mantıkları
│   ├── Sistem tanımı                ← Detaylı sistem tanımı (71KB)
│   ├── Çalışma şekli                ← Çalışma şekli (12KB)
│   ├── Hatalar                      ← Hata raporu (17KB)
│   ├── bolumler/                    ← 32 bölüm detaylı doküman
│   │   ├── bolum-01 ... bolum-32
│   └── planlar/                     ← Uygulama planları
│       ├── IMPLEMENTATION-PLAN-v4.md
│       ├── IMPLEMENTATION-PLAN-v4-BOLUM9-16.md
│       ├── IMPLEMENTATION-PLAN-v4-BOLUM17-22.md
│       ├── IMPLEMENTATION-PLAN-v4-BOLUM23-32.md
│       └── ARCHITECTURE-MAP-v1.md
│
└── modules/                         ← 20 katman modül dokümantasyonu
    │
    ├── Genel Rehberler (3 dosya)
    │   ├── BIST-RULES.md            ← BIST piyasa kuralları (13 kategori)
    │   ├── DEPENDENCY-ORDER.md      ← Modül bağımlılık sırası (15 seviye)
    │   └── TEST-EXPECTATIONS.md     ← Test gereksinimleri
    │
    ├── agents/                      ← AI Agent Sistemi
    │   ├── README.md
    │   └── AGENT-SYSTEM-NIHAI-SPEC.md
    ├── alternative/                 ← Alternatif Veri
    │   ├── README.md
    │   └── ALTERNATIVE-DATA-NIHAI-SPEC.md
    ├── api/                         ← API & Dashboard
    │   ├── README.md
    │   └── API-NIHAI-SPEC.md
    ├── backtest/                    ← Backtest Motoru
    │   ├── README.md
    │   └── BACKTEST-NIHAI-SPEC.md
    ├── core/                        ← Temel Altyapı
    │   ├── README.md
    │   └── CORE-NIHAI-SPEC.md
    ├── event_study/                 ← Event Study
    │   ├── README.md
    │   └── EVENT-STUDY-NIHAI-SPEC.md
    ├── factors/                     ← Factor Investing
    │   ├── README.md
    │   └── FACTORS-NIHAI-SPEC.md
    ├── features/                    ← Feature Engineering
    │   ├── README.md
    │   └── FEATURES-NIHAI-SPEC.md
    ├── ingestion/                   ← Veri Toplama
    │   ├── README.md
    │   └── INGESTION-NIHAI-SPEC.md
    ├── intelligence/                ← Analiz & Tahmin
    │   ├── README.md
    │   └── INTELLIGENCE-NIHAI-SPEC.md
    ├── learning/                    ← Öğrenme Sistemi
    │   ├── README.md
    │   └── LEARNING-NIHAI-SPEC.md
    ├── macro/                       ← Makro Ekonomi
    │   ├── README.md
    │   └── MACRO-NIHAI-SPEC.md
    ├── market_state/                ← Piyasa Durumu
    │   ├── README.md
    │   └── MARKET-STATE-NIHAI-SPEC.md
    ├── ml/                          ← Makine Öğrenmesi
    │   ├── README.md
    │   └── ML-NIHAI-SPEC.md
    ├── portfolio/                   ← Portföy Yönetimi
    │   ├── README.md
    │   └── PORTFOLIO-NIHAI-SPEC.md
    ├── risk/                        ← Risk Yönetimi
    │   ├── README.md
    │   └── RISK-NIHAI-SPEC.md
    ├── scanner/                     ← Tarama Motoru
    │   ├── README.md
    │   └── SCANNER-NIHAI-SPEC.md
    ├── scheduler/                   ← Zamanlayıcı
    │   ├── README.md
    │   └── SCHEDULER-NIHAI-SPEC.md
    ├── simulation/                  ← Simülasyon
    │   ├── README.md
    │   └── SIMULATION-NIHAI-SPEC.md
    └── viop/                        ← VIOP & Opsiyon
        ├── README.md
        └── VIOP-NIHAI-SPEC.md
```

## 📊 Özet

| Kategori | Dosya |
|----------|-------|
| Dokümantasyon | 12 |
| Sistem tanımı + bölümler + planlar | 39 |
| Genel rehber | 3 |
| Modül dokümanı (20 × 2) | 40 |
| Vizyon | 1 |
| **TOPLAM** | **95 dosya** |

## 🏷️ Otorite Sırası

1. `BIST-RULES.md` — BIST kuralları
2. `DEPENDENCY-ORDER.md` — Modül bağımlılıkları
3. `TEST-EXPECTATIONS.md` — Test gereksinimleri
4. `modules/*/NIHAI-SPEC.md` — Modül nihai spesifikasyonları
5. `documentation/*` — Proje dokümantasyonu
6. `system/*` — Sistem tanımı ve bölümler
7. `VISION.md` — Nihai hayal
