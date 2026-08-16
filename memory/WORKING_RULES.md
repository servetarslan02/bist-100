# ALPHA — WORKING RULES

**STATUS:** ACTIVE
**VERSION:** 2.0
**UPDATED_AT:** 2026-08-16
**DEPENDS_ON:** MEMORY-INDEX.md, SYSTEM-CONSTITUTION.md, MASTER-SPEC.md, TARGET-ARCHITECTURE.md, ROADMAP-v4.md

Bu dosya ALPHA üzerinde kod, research, data, ML, event intelligence ve infrastructure değişikliği yaparken uygulanacak geliştirme disiplinidir.

## 1. Her Çalışmanın Başında Okuma Sırası
1. `memory/MEMORY-INDEX.md`
2. `memory/SYSTEM-CONSTITUTION.md`
3. `memory/MASTER-SPEC.md`
4. ilgili domain spec (`TARGET-ARCHITECTURE`, `EVENT-INTELLIGENCE`, ileride contract specs)
5. `memory/ROADMAP-v4.md`
6. mevcut kod ve testler

Eski roadmap/mimari dosyaları yalnız history/reference olarak kullanılır.

## 2. Önce Gerçeği Bul
Kod değişikliğinden önce GAP ANALYSIS:
- current implementation ne yapıyor?
- docs ne iddia ediyor?
- runtime gerçekten hangi dosyayı kullanıyor?
- data gerçekten nereden geliyor?
- state persistent mı?
- test gerçekten behavior doğruluyor mu?
- hard-coded/mock/fake fallback var mı?

## 3. Architecture Theater Yasak
Şunlar completion değildir:
- dosya/class oluşturmak;
- `TODO` bırakmak;
- endpoint var ama fake data dönüyor;
- test içinde `or True` gibi anlamsız assertion;
- test scriptinin ekrana `passed` yazması;
- LLM'nin `production-ready` demesi;
- modülün import edilmemesi veya runtime'a bağlanmaması.

## 4. Fake / Placeholder Politikası
Production veya paper path'te:
- fabricated market data;
- hard-coded live-looking values;
- silently substituted constants;
- unlabelled mock;
- `except: pass`;
- unexplained `return None`;
- fake confidence
yasaktır.

Test fixture ve research mock kullanılabilir ama açıkça TEST/RESEARCH scope olmalıdır.

## 5. No Fixed Coverage Cap
Business logic içinde `[:50]`, `[:100]`, `first N stocks`, `BIST100 only` benzeri kalıcı kapsam sınırı konamaz.

Compute kontrolü gerekiyorsa:
- HOT/WARM/COLD tier;
- explicit batch size;
- rate limit;
- queue priority;
- resource budget
kullanılır ve bunlar observable/reversible olur.

## 6. Point-in-Time Önceliği
Her market/fundamental/event feature için `ne zaman biliniyordu?` sorusu zorunludur. Current/final/revised bilgi geçmiş timestamp'e sızdırılamaz.

## 7. Mask-First
Invalid/untradable/stale/not-yet-known observation dependent feature'dan önce dışlanır. Sonradan feature'ı None yapmak yeterli değildir.

## 8. Event Intelligence Kuralı
KAP/haber için tek sentiment/news score mantığı kurulamaz. Event'in:
- source/evidence;
- entity;
- lifecycle;
- materiality;
- binding/conditionality;
- expectation/surprise;
- affected entities;
- time horizon;
- reaction;
- uncertainty
boyutları mümkün olduğunda ayrılır.

## 9. Research ≠ Production
Yeni feature/model/agent/prompt/strategy/kod önce research artifact'tır. Doğrudan champion veya production olamaz.

## 10. Test Kapsamı
En az gerekenler:
- happy path;
- edge case;
- invalid/missing/stale data;
- provider timeout/failure;
- DB/cache/event-bus failure;
- duplicate/corrected/late event;
- concurrency/idempotency;
- temporal integrity;
- leakage;
- restart/persistence;
- realistic execution where relevant.

## 11. Test Assertion Kalitesi
Assertion gerçekten yanlış davranışta fail etmelidir. Vacuous assertion (`x or True`) yasaktır.

## 12. Completion Gate
Bir feature/faz ancak:
1. code implemented;
2. canonical runtime'a bağlı;
3. contract uyumlu;
4. input validation;
5. structured error handling;
6. logging/observability;
7. unit tests;
8. edge/failure tests;
9. integration tests;
10. representative gerçek/controlled data validation;
11. security review where relevant;
12. performance/resource review;
13. docs;
14. audit/reproducibility evidence;
15. regression check;
16. critical placeholder/fake path yok
şartlarını sağlıyorsa COMPLETE olabilir.

## 13. ML / Backtest Ek Kuralları
- walk-forward her fold içinde gerçek retraining/calibration yapar;
- OOS metric bağımsız recompute edilir;
- survivorship ve historical universe kontrol edilir;
- costs/execution assumptions açık olur;
- model score probability sayılmaz;
- experiment count/multiple testing takip edilir;
- `Champion` etiketi governance artifact olmadan kullanılamaz.

## 14. Data / Source Ek Kuralları
- provenance zorunlu;
- source timestamp / ingest timestamp / effective timestamp ayrılır;
- corrections versioned olur;
- source disagreement kaybolmaz;
- source failure state olarak ölçülür.

## 15. Büyük Değişiklikler
Major architecture değişiklikleri önce isolated branch/research scope'ta yapılmalı; sonra integration/governance ile main'e alınmalıdır.

## 16. Destructive İşlemler
Silme yerine önce ARCHIVE/LEGACY sınıflandırması tercih edilir. Ancak yanlış dosya production path'i zehirliyorsa kaldırılabilir; karar audit'e yazılır.

## 17. Raporlama
Her önemli çalışma sonunda mümkün olduğunda:
- inspected files;
- changed files;
- confirmed bugs;
- fixed bugs;
- tests run/pass/fail;
- assumptions;
- unverified areas;
- remaining risks;
- next gate
raporlanır.

## 18. Nerede Dur / Fail Closed
Aşağıdaki durumlarda varsayım üretip devam etmek yerine açık UNKNOWN/blocked state üret:
- credential eksik;
- destructive irreversible operation;
- security-critical ambiguity;
- conflicting constitutional requirement;
- data lineage bilinmiyor;
- leakage şüphesi çözülmedi;
- model artifact yeniden üretilemiyor.

Diğer teknik ayrıntılarda best-effort karar verilebilir; ancak karar kaydı tutulur.

## 19. Ana Döngü
`ANALYZE -> CONTRACT -> PLAN -> IMPLEMENT -> TEST -> INTEGRATE -> VERIFY -> AUDIT -> EVIDENCE -> COMPLETE`

Evidence olmadan COMPLETE yoktur.
