# ALPHA BIST — Memory Index

**Son güncelleme:** 2026-08-18

## 📁 Dizin Yapısı

```
memory/
├── VISION.md                    ← Nihai hayal ve sistem vizyonu
├── INDEX.md                     ← Bu dosya
│
└── modules/                     ← Tüm modül dokümantasyonları
    ├── BIST-RULES.md            ← BIST piyasa kuralları (13 kategori)
    ├── DEPENDENCY-ORDER.md      ← Modül bağımlılık sırası (15 seviye)
    ├── TEST-EXPECTATIONS.md     ← Test gereksinimleri (15 seviye)
    │
    ├── agents/                  ← AI Agent Sistemi
    │   ├── README.md
    │   └── AGENT-SYSTEM-NIHAI-SPEC.md
    ├── alternative/             ← Alternatif Veri
    │   ├── README.md
    │   └── ALTERNATIVE-DATA-NIHAI-SPEC.md
    ├── api/                     ← API & Dashboard
    │   ├── README.md
    │   └── API-NIHAI-SPEC.md
    ├── backtest/                ← Backtest Motoru
    │   ├── README.md
    │   └── BACKTEST-NIHAI-SPEC.md
    ├── core/                    ← Temel Altyapı
    │   ├── README.md
    │   └── CORE-NIHAI-SPEC.md
    ├── event_study/             ← Event Study
    │   ├── README.md
    │   └── EVENT-STUDY-NIHAI-SPEC.md
    ├── factors/                 ← Factor Investing
    │   ├── README.md
    │   └── FACTORS-NIHAI-SPEC.md
    ├── features/                ← Feature Engineering
    │   ├── README.md
    │   └── FEATURES-NIHAI-SPEC.md
    ├── ingestion/               ← Veri Toplama
    │   ├── README.md
    │   └── INGESTION-NIHAI-SPEC.md
    ├── intelligence/            ← Analiz & Tahmin
    │   ├── README.md
    │   └── INTELLIGENCE-NIHAI-SPEC.md
    ├── learning/                ← Öğrenme Sistemi
    │   ├── README.md
    │   └── LEARNING-NIHAI-SPEC.md
    ├── macro/                   ← Makro Ekonomi
    │   ├── README.md
    │   └── MACRO-NIHAI-SPEC.md
    ├── market_state/            ← Piyasa Durumu
    │   ├── README.md
    │   └── MARKET-STATE-NIHAI-SPEC.md
    ├── ml/                      ← Makine Öğrenmesi
    │   ├── README.md
    │   └── ML-NIHAI-SPEC.md
    ├── portfolio/               ← Portföy Yönetimi
    │   ├── README.md
    │   └── PORTFOLIO-NIHAI-SPEC.md
    ├── risk/                    ← Risk Yönetimi
    │   ├── README.md
    │   └── RISK-NIHAI-SPEC.md
    ├── scanner/                 ← Tarama Motoru
    │   ├── README.md
    │   └── SCANNER-NIHAI-SPEC.md
    ├── scheduler/               ← Zamanlayıcı
    │   ├── README.md
    │   └── SCHEDULER-NIHAI-SPEC.md
    ├── simulation/              ← Simülasyon
    │   ├── README.md
    │   └── SIMULATION-NIHAI-SPEC.md
    └── viop/                    ← VIOP & Opsiyon
        ├── README.md
        └── VIOP-NIHAI-SPEC.md
```

## 📊 Özet

| Kategori | Dosya |
|----------|-------|
| Genel rehber | 3 (BIST-RULES, DEPENDENCY-ORDER, TEST-EXPECTATIONS) |
| Modül dokümanı | 40 (20 README + 20 NIHAI-SPEC) |
| Vizyon | 1 (VISION.md) |
| **TOPLAM** | **44 dosya** |

## 🏷️ Otorite Sırası

1. `BIST-RULES.md` — BIST kuralları
2. `DEPENDENCY-ORDER.md` — Modül bağımlılıkları
3. `TEST-EXPECTATIONS.md` — Test gereksinimleri
4. `modules/*/NIHAI-SPEC.md` — Modül nihai spesifikasyonları
5. `VISION.md` — Nihai hayal
