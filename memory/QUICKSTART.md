# ALPHA — QUICKSTART / CURRENT RUNTIME STATUS

**STATUS:** MIGRATION / NOT YET CANONICAL
**UPDATED_AT:** 2026-08-16

Bu dosyanın eski sürümü `start.bat` ile tüm sistemi başlatabildiğini ve otomatik taramanın çalışacağını söylüyordu. Mevcut repository incelemesinde `start.bat` bulunmadı ve birden fazla runtime/API neslinin aynı anda var olduğu görüldü. Bu nedenle eski quickstart talimatları güvenilir kabul edilmez.

## Şu Anki Kural
Canonical runtime kurulana kadar:

- `memory/MEMORY-INDEX.md` ile geçerli belgeleri belirle;
- `memory/SYSTEM-CONSTITUTION.md` kurallarını uygula;
- `memory/ROADMAP-v4.md` FAZ 0/1 migration planını takip et;
- README veya eski roadmap'teki `start`, `scan`, `production-ready` iddialarını doğrulamadan kullanma;
- hard-coded/fake market değerlerini canlı veri sayma;
- mevcut backtest/ML sonuçlarını bağımsız reproducibility kanıtı olmadan Champion/OOS kanıtı sayma.

## Hedef Quickstart
FAZ 1 tamamlandığında bu dosya yalnız doğrulanmış tek bir bootstrap yolu içerecek. Hedef akış:

```text
1. prerequisites check
2. secure .env / secret setup
3. dependency/environment bootstrap
4. storage/services health validation
5. canonical migrations/schema checks
6. canonical runtime start
7. ingestion/source freshness check
8. state/feature health check
9. paper-mode health check
10. explicit ready/degraded/no-trade status
```

## Production/Paper Readiness İlkesi
Bir HTTP endpoint'in açılması sistemin hazır olduğu anlamına gelmez. Ready state en az şu health gate'lerden oluşmalıdır:

- source/data freshness;
- point-in-time integrity;
- storage availability;
- event/state pipeline;
- feature contract health;
- model artifact health;
- risk engine;
- portfolio persistence;
- audit ledger;
- no critical governance failure.

Herhangi kritik gate başarısızsa status açıkça `DEGRADED`, `NO_TRADE` veya `HALT` olmalıdır.

## Geçici Geliştirici Notu
Mevcut Docker/Next.js/FastAPI dosyaları migration sırasında incelenebilir; ancak canonical bootstrap olarak ilan edilmeyecek. FAZ 1 sonunda gerçek komutlar test edilip bu dosyaya yazılacaktır.
