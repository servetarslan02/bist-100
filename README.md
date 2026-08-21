# ALPHA BIST — Market Intelligence & Quant Engine

> BIST'teki 400+ hisseyi 7/24 tarayan, otonom piyasa zekâsı platformu.

## Hızlı Başlangıç

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# Sistemi başlat (arka plan)
./alpha start

# Tek tarama yap
python3 run_system.py --scan-once

# Durum kontrolü
./alpha status

# Durdur
./alpha stop
```

## Mimari

```
Veri (yfinance, KAP, RSS) → Feature'lar (100+) → 7 Motor → Ranking Model
→ Karar (BUY/SELL/HOLD) → Risk Gate → Execution Simulator → Portfolio → Learning
```

## Dosya Yapısı

```
bist-100/
├── alpha                    # Yönetim scripti (start/stop/status)
├── start.py                 # Ana çalıştırıcı
├── run_system.py            # Sistem runner
├── requirements.txt         # Python bağımlılıkları
├── apps/web/                # Dashboard (Next.js)
├── services/                # Backend servisleri
│   ├── core/                # Temel (config, DB, event, quality, security)
│   ├── ingestion/           # Veri çekme (yfinance, KAP, RSS, fundamental)
│   ├── features/            # Feature hesaplama (teknik, fundamental, macro, sentiment)
│   ├── intelligence/        # Analiz motorları (regime, SPEC, valuation, MC, scenario)
│   ├── scanner/             # Tarama ve sıralama
│   ├── ml/                  # ML modelleri (LightGBM ranking)
│   ├── risk/                # Risk yönetimi
│   ├── portfolio/           # Portföy ve muhasebe
│   ├── simulation/          # Execution simulator
│   ├── backtest/            # Backtest ve walk-forward
│   ├── learning/            # Öğrenme sistemi
│   ├── agents/              # AI agent'lar
│   ├── scheduler/           # Zamanlama
│   └── api/                 # REST API + WebSocket
├── tests/                   # Testler
├── data/                    # Veri dosyaları
├── ml/                      # ML model dosyaları
├── memory/                  # Araştırma notları ve dokümanlar
└── sistem ve calisma mantiklari/  # Sistem tanımı ve çalışma kuralları
```

## Motorlar

| # | Motor | Özellik |
|---|-------|---------|
| 1 | Relatif Güç | 1d/5d/20d/60d/120d vs BIST + sektör |
| 2 | Momentum + Trend | Eğim, ivme, değişim yönü |
| 3 | Hacim + Mikroyapı | Tick rule, VWAP, hacim-fiyat ilişkisi |
| 4 | Fundamental | Sektörel normalize, FCF, bilanço kalitesi |
| 5 | KAP + Haber | Yapılandırılmış extraction |
| 6 | Katalizör | Yaklaşan olaylar |
| 7 | Neden Düşüyor? | Market/sector/company/liquidity/panic |

## Test

```bash
python3 tests/test_phase1.py      # Data Ingestion
python3 tests/test_phase2.py      # Feature Engine
python3 tests/test_faz2_motors.py # 7 Motor
python3 tests/test_faz3_ranking.py # Ranking Model
# ... (22 test dosyası, 424+ test)
```
