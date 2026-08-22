# ALPHA BIST — Memory Index

**Son güncelleme:** 2026-08-23

## 📁 Dizin Yapısı

```
memory/
├── VISION.md                        ← Nihai hayal ve sistem vizyonu
├── CURRENT-STATE.md                 ← Mevcut denetim durumu
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
│   └── bolumler/                    ← 32 bölüm detaylı doküman
│       ├── bolum-01 ... bolum-32
│
└── modules/                         ← 24 servis katmanı modül dokümantasyonu
    │
    ├── Genel Rehberler (3 dosya)
    │   ├── BIST-RULES.md            ← BIST piyasa kuralları (13 kategori)
    │   ├── DEPENDENCY-ORDER.md      ← Modül bağımlılık sırası (15 seviye)
    │   └── TEST-EXPECTATIONS.md     ← Test gereksinimleri
    │
    ├── core/MODULE.md               ← Temel altyapı: orchestrator, decision engine, data quality, event bus, security
    ├── data/MODULE.md               ← Veri kaynakları: historical adapter, fundamental provider, persistent repository
    ├── events/MODULE.md             ← Olay altyapısı: event schema, event bus, infrastructure
    ├── labels/MODULE.md             ← Etiket üretimi: cross-sectional rank, forward return, purge/embargo
    │
    ├── ingestion/MODULE.md          ← Veri toplama: providers (yfinance, KAP, BIST, macro), PIT store, pipeline
    ├── features/MODULE.md           ← Feature üretimi: 7 motor, cross-sectional, panel engine, drift detector
    │
    ├── intelligence/MODULE.md       ← Analiz ve tahmin: regime detection, forecasting, Monte Carlo, LLM agent, KAP extraction
    ├── market_state/MODULE.md       ← Piyasa durumu: breadth engine, ensemble regime, risk appetite, transition tracker
    ├── macro/MODULE.md              ← Makro ekonomi: TCMB, inflation, FX, CDS, surprise model, stress test
    │
    ├── ml/MODULE.md                 ← Makine öğrenmesi: LightGBM, ranking model, ensemble, champion/challenger, calibration
    ├── learning/MODULE.md           ← Öğrenme sistemi: drift detection, calibration, attribution, continuous learning
    │
    ├── risk/MODULE.md               ← Risk yönetimi: position sizing, VaR/CVaR, stress test, tail hedge, risk parity
    ├── portfolio/MODULE.md          ← Portföy yönetimi: portfolio manager, PnL, reconciliation
    ├── paper_trading/MODULE.md      ← Sanal işlem: execution simulator, virtual portfolio, risk gate, performance tracker
    ├── simulation/MODULE.md         ← Simülasyon: Monte Carlo, execution simulator, order book, stress test
    │
    ├── backtest/MODULE.md           ← Backtest motoru: walk-forward, deflated Sharpe, bias detector, survivorship
    ├── scanner/MODULE.md            ← Tarama motoru: opportunity engine, alpha scanner, dynamic scanner, event scanner
    ├── factors/MODULE.md            ← Factor investing: Fama-French, Piotroski, Altman, Beneish, factor rotation
    ├── event_study/MODULE.md        ← Event study: abnormal return, CAR, KAP event, statistical test
    │
    ├── agents/MODULE.md             ← AI Agent sistemi: agent pipeline, debate engine, synthesis, self-evaluator
    ├── alternative/MODULE.md        ← Alternatif veri: Google Trends, sosyal medya, uydu, LLM sentiment, web scraping
    ├── viop/MODULE.md               ← VIOP ve opsiyonlar: Greeks, options pricing, hedging, strategies
    ├── api/MODULE.md                ← API ve Dashboard: FastAPI, v1 endpoints, auth, rate limiter
    ├── scheduler/MODULE.md          ← Zamanlayıcı: unified scheduler, daily workflow, learning scheduler
    │
    ├── techstack/                   ← Teknoloji stack araştırması (6 dosya)
    │   ├── BEST-TECH-STACK-2026.md
    │   ├── BREAKING-CHANGES-ANALYSIS.md
    │   ├── CURRENT-STATE.md
    │   ├── INTEGRATION-STATUS.md
    │   ├── ML-BENCHMARK-RESULTS.md
    │   └── ATTENTION-ITEMS-RESOLVED.md
    │
    └── dashboard/README.md          ← Dashboard modülü
```

## 📊 Özet

| Kategori | Dosya | Satır |
|----------|-------|-------|
| Dokümantasyon (01-11) | 12 | ~3,000 |
| Sistem tanımı + bölümler | 35 | ~5,000 |
| Genel rehber | 3 | ~500 |
| Modül MODULE.md (24) | 24 | ~4,500 |
| Modül README (24) | 24 | ~1,200 |
| Modül CURRENT-STATE (6) | 6 | ~300 |
| Techstack araştırması | 6 | ~800 |
| Vizyon + durum | 2 | ~400 |
| **TOPLAM** | **~112** | **~15,700** |

## 🏷️ Otorite Sırası

1. `documentation/01-VIZYON-VE-MANIFESTO.md` — Vizyon ve kırmızı çizgiler
2. `BIST-RULES.md` — BIST kuralları
3. `DEPENDENCY-ORDER.md` — Modül bağımlılıkları
4. `TEST-EXPECTATIONS.md` — Test gereksinimleri
5. `modules/*/MODULE.md` — Modül detaylı spesifikasyonları
6. `documentation/*` — Proje dokümantasyonu
7. `system/*` — Sistem tanımı ve bölümler
8. `VISION.md` — Nihai hayal
