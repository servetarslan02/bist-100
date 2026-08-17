# ALPHA BIST — Memory Index

**Son güncelleme:** 2026-08-18

## 📁 Dizin Yapısı

```
memory/
├── VISION.md              ← Nihai hayal ve sistem vizyonu
├── INDEX.md               ← Bu dosya
│
├── specs/                 ← Teknik spesifikasyonlar
│   ├── SYSTEM-CONSTITUTION.md    ← Sistem anayasası (en üst otorite)
│   ├── MASTER-SPEC.md            ← Ana spesifikasyon
│   ├── TARGET-ARCHITECTURE.md    ← Hedef mimari
│   ├── ALPHA-ARCHITECTURE-v1.1.md ← Mimari v1.1
│   ├── EVENT-INTELLIGENCE-SPEC.md ← KAP/haber olay zekâsı
│   ├── QUICKSTART.md             ← Hızlı başlangıç
│   └── WORKING_RULES.md          ← Geliştirme disiplini
│
├── plans/                 ← Uygulama planları
│   ├── BOLUM23-32-PLAN.md        ← Bölüm 23-32 planı (✅ tamamlandı)
│   └── SYSTEM-WIRING-PLAN.md     ← Sistem bağlantı planı (✅ tamamlandı)
│
├── reports/               ← Analiz ve durum raporları
│   ├── ANALIZ_RAPORU.md
│   ├── CURRENT-STATE.md
│   ├── DOGULAMA_RAPORU.md
│   ├── DUZELTME_RAPORU.md
│   ├── GAP_AUDIT.md
│   └── MIMARI_GAP_ANALIZ.md
│
├── research/              ← Araştırma notları
│   ├── Hisse-bulma-mantığı
│   ├── Sistemler-mantığı
│   ├── bist100.md
│   └── İnceleme-test
│
└── roadmaps/              ← Yol haritaları
    └── ROADMAP-v4.md             ← Aktif yol haritası
```

## 📦 modules/ — Modül Dokümantasyonu (207 dosya)

```
memory/modules/
├── core/              ← 53 modül (temel altyapı)
├── ingestion/         ← 7 modül (veri toplama)
├── features/          ← 18 modül (özellik hesaplama)
├── intelligence/      ← 23 modül (analiz ve tahmin)
├── risk/              ← 7 modül (risk yönetimi)
├── portfolio/         ← 4 modül (portföy yönetimi)
├── learning/          ← 8 modül (öğrenme sistemi)
├── ml/                ← 17 modül (makine öğrenmesi)
├── backtest/          ← 9 modül (geriye dönük test)
├── agents/            ← 2 modül (AI agent)
├── scanner/           ← 9 modül (tarama motoru)
├── scheduler/         ← 4 modül (zamanlayıcı)
├── simulation/        ← 3 modül (simülasyon)
├── api/               ← 4 modül (arayüz)
├── market_state/      ← 2 modül (piyasa durumu)
├── alternative/       ← 6 modül (alternatif veri)
├── macro/             ← 8 modül (makro ekonomi)
├── factors/           ← 8 modül (faktör investing)
├── event_study/       ← 8 modül (olay analizi)
└── viop/              ← 7 modül (vadeli işlem)
```
Her modül için ayrı .md dosyası: sınıf, fonksiyon, bağlantı bilgileri.

## 📐 system/ — Sistem Tanımı ve Çalışma Mantıkları

```
memory/system/
├── Sistem tanımı          ← Sistem tanımı (5631 satır)
├── Çalışma şekli          ← Çalışma şekli (865 satır)
├── Hatalar                ← Hata raporu (1237 satır)
├── bolumler/              ← 32 bölüm detaylı doküman
│   ├── bolum-01 ... bolum-32
└── planlar/               ← Uygulama planları
    ├── IMPLEMENTATION-PLAN-v4.md
    ├── IMPLEMENTATION-PLAN-v4-BOLUM9-16.md
    ├── IMPLEMENTATION-PLAN-v4-BOLUM17-22.md
    ├── IMPLEMENTATION-PLAN-v4-BOLUM23-32.md
    └── ARCHITECTURE-MAP-v1.md
```

## 🏷️ Otorite Sırası

Çelişki olduğunda:
1. `SYSTEM-CONSTITUTION.md` — governance kuralları
2. `MASTER-SPEC.md` — sistem vizyonu
3. `TARGET-ARCHITECTURE.md` — hedef mimari
4. `sistem ve calisma mantiklari/Sistem tanımı` — detaylı tanım
5. `ROADMAP-v4.md` — uygulama planı
6. `VISION.md` — nihai hayal
