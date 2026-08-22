# Scanner Modülü — Güncel Durum Raporu

**Tarih:** 2026-08-21
**Analiz:** Kod tabanı envanteri

---

## Genel Durum

| Metrik | Değer |
|--------|-------|
| Modül sayısı | 16 |
| Toplam satır | ~4,500 |
| Test sayısı | 20 |
| Katmanlı filtreleme | Tier 0→5 |

---

## Modül Olgunluk Durumu

| Modül | Durum | Not |
|-------|-------|-----|
| alpha_engine.py | ✅ TAM | 3 katmanlı tarama |
| alpha_scanner.py | ✅ TAM | Merkezi pipeline |
| opportunity_engine.py | ✅ TAM | 10 bileşenli skor |
| tiered_scanner.py | ✅ TAM | Tier 0→5 |
| live_scanner.py | ✅ TAM | Tick bazlı |
| event_scanner.py | ✅ TAM | KAP/haber/macro |
| dynamic_opportunity_scanner.py | ✅ TAM | yfinance ile tarama |
| scanner_interface.py | ✅ TAM | ABC, ScanResult |
| backtest_runner.py | ✅ TAM | v3.0 optimize |
| deduplicator.py | ✅ TAM | Cooldown, force scan |
| scan_scheduler.py | ✅ TAM | Adaptif interval |
| event_queue.py | ✅ TAM | Priority queue |
| custom_filters.py | ✅ TAM | BIST filtreleri |
| scan_alerts.py | ✅ TAM | Alert kuralları |
| performance_tracker.py | ✅ TAM | Hit rate, accuracy |
| scan_persistence.py | ✅ TAM | SQLite |

---

## Bilinen Sınırlamalar

| Sınırlama | Öncelik | Açıklama |
|-----------|---------|----------|
| dynamic_scanner gecikmeli veri | P1 | Gerçek zamanlı veri akışı yok |
| ML skor entegrasyonu eksik | P1 | Quant proxy kullanıyor |
| Tier 4-5 implemente edilmemiş | P2 | Sadece kriter filtresi |
| backtest_runner canonical scoring yok | P2 | Legacy skor mantığı |
| event_scanner hard-coded sektör | P2 | Dinamik sektör graph gerekli |
