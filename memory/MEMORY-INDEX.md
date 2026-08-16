# ALPHA — MEMORY INDEX / SOURCE OF TRUTH

**Durum:** ACTIVE / CANONICAL
**Tarih:** 16 Ağustos 2026

Bu dosya `memory/` klasöründeki belgelerin hangi amaçla kullanılacağını ve hangisinin otorite olduğunu tanımlar.

## 1. Otorite Sırası
Çelişki olduğunda aşağıdaki sıra geçerlidir:

1. `SYSTEM-CONSTITUTION.md` — değiştirilemez governance ve integrity kuralları
2. `MASTER-SPEC.md` — ürün/sistem vizyonu ve kapsam
3. `TARGET-ARCHITECTURE.md` — hedef teknik mimari
4. `EVENT-INTELLIGENCE-SPEC.md` — KAP/haber/web olay zekâsı
5. `CURRENT-STATE.md` — mevcut repository hakkında doğrulanmış factual snapshot; hedef değil
6. `ROADMAP-v4.md` — mevcut migration/build planı
7. `WORKING_RULES.md` — geliştirme disiplini ve completion kriterleri
8. Versioned contracts/specs — ileride `contracts/` veya memory altına eklenecek
9. Eski architecture/roadmap dosyaları — yalnız historical/reference
10. Ham konuşma ve scan çıktıları — yalnız raw context/artifact

**Önemli:** `CURRENT-STATE.md` hedef mimariyi değiştirmez. Yalnız bugün gerçekte neyin var/ne kadar güvenilir olduğunu kaydeder.

## 2. CANONICAL / ACTIVE FILES

### `MASTER-SPEC.md`
ALPHA'nın ne olduğunu tanımlar:
- BIST100 ile sınırlı değil;
- tüm erişilebilir BIST evreni;
- global information context;
- Operating / Research / Governance brains;
- self-learning fakat governed autonomy;
- multi-horizon, uncertainty-aware, paper-first.

### `SYSTEM-CONSTITUTION.md`
Sistem kendisini kandıramasın diye zorunlu kurallar:
point-in-time, leakage, survivorship, provenance, no hard coverage cap, mask-first, OOS, independent validation, no fake confidence, NO-TRADE, risk, secrets, immutable audit.

### `TARGET-ARCHITECTURE.md`
Hedef runtime/data/research/governance mimarisi. HOT/WARM/COLD yalnız compute priority'dir; kapsam filtresi değildir.

### `EVENT-INTELLIGENCE-SPEC.md`
Haber/KAP anlayışının ana spec'i. Sentiment-score yaklaşımının yerine event understanding, materiality, expectation/surprise, event threads, company memory, graph propagation ve reaction intelligence kullanılır.

### `CURRENT-STATE.md`
Mevcut kod tabanında doğrulanmış önemli gap ve riskleri kaydeder. Eski LLM belgelerindeki `production ready`, `champion`, `OOS passed` gibi iddiaların evidence olmadan gerçek kabul edilmesini engeller.

### `ROADMAP-v4.md`
Eski LLM tarafından oluşturulmuş kod tabanından hedef ALPHA'ya migration planıdır. Fazlar ancak evidence ile COMPLETE olabilir.

### `WORKING_RULES.md`
Her kod/değişiklik çalışmasında uygulanacak kurallar.

### `QUICKSTART.md`
Şu an migration-state belgesidir. Canonical runtime doğrulanana kadar eski başlatma iddiaları geçersizdir.

## 3. LEGACY / HISTORICAL FILES

Aşağıdakiler silinmemiştir çünkü düşünce tarihini ve eski kararları korurlar; ancak ACTIVE AUTHORITY DEĞİLDİR:

### `ALPHA-ARCHITECTURE.md`
Legacy v1.0. `800+ hisse`, sabit filtreleme hiyerarşisi ve bazı artık geçerli olmayan teknoloji/LLM varsayımları içerir.

### `ALPHA-ARCHITECTURE-v1.1.md`
Legacy v1.1. Canonical event/state/feature fikirlerinin faydalı parçaları vardır ancak yeni full-scope/governance/event intelligence vizyonu karşısında otorite değildir.

### `ROADMAP-v2.md`
Legacy. 7 motor ve eski probabilistic ranking yaklaşımı.

### `ROADMAP-v3.md`
Legacy. Mask-first, learning-to-rank ve walk-forward fikirleri değerlidir; fakat `Adjusted-MSE`, sabit motor sayısı ve bazı araştırma iddiaları canonical kural değildir.

### `ROADMAP.md`
Legacy master roadmap. İçindeki `✅ Çalışıyor/Tamamlandı` tabloları **doğrulanmış gerçek kabul edilmez**. Repository audit, bazı bu iddiaların implementation ile uyuşmadığını göstermiştir. Yalnız eski plan/intent kaynağıdır.

## 4. RAW CONTEXT / ARTIFACTS

### `bist100.md`
Eski konuşmaların/brainstorming'in büyük ham dökümü. Source-of-truth değildir. Yeni gereksinimleri hatırlamak ve fikir provenance'ı için kullanılabilir.

### `scan_results.json`
Bir scan/runtime/research output artifact'ıdır. Architecture veya validation kanıtı değildir. Dataset/scan version, timestamp ve lineage olmadan model başarısı ispatı sayılmaz.

## 5. Hedef ile Gerçeği Ayırma Kuralı
Üç ayrı kavram hiçbir zaman karıştırılamaz:

- **TARGET:** ne inşa etmek istiyoruz? → MASTER/TARGET/EVENT specs
- **CURRENT:** şu an kod gerçekten ne yapıyor? → CURRENT-STATE + yeni audit artifacts
- **PLAN:** current'tan target'a nasıl gideceğiz? → ROADMAP-v4

Bir özellik TARGET'ta yazıyor diye CURRENT'ta var sayılmaz.

## 6. Yeni Bir Belge Eklerken
Her yeni memory belgesi şu metadata'yı açıkça söylemelidir:
- STATUS: CANONICAL / ACTIVE / DRAFT / FACTUAL-SNAPSHOT / LEGACY / RAW-ARTIFACT
- OWNER/DOMAIN
- VERSION
- UPDATED_AT
- SUPERSEDES varsa hangi belgeyi geçtiği
- DEPENDS_ON varsa canonical references

## 7. Completion / Evidence Kuralı
Memory'de `DONE`, `COMPLETE`, `PRODUCTION READY`, `CHAMPION`, `LEAKAGE SAFE`, `OOS PASSED` gibi bir ifade ancak yeniden üretilebilir test/artifact ile destekleniyorsa kullanılabilir.

Örnek kanıt zinciri:
`code commit -> dataset manifest -> test run -> metrics artifact -> independent verification -> audit record`.

## 8. Memory'nin Amacı
`memory/` ALPHA'nın rastgele not klasörü değil; sistemin uzun dönem tasarım hafızasıdır.

Burada dört şey ayrılır:
- **Truth/Policy:** canonical specs
- **Current Reality:** factual snapshots/audits
- **Plan:** active roadmap
- **History:** legacy docs/raw conversations/artifacts

Bu ayrım korunmadan ALPHA'nın otonom araştırma ve self-development katmanı güvenli şekilde kurulamaz.
