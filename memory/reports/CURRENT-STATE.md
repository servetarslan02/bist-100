# ALPHA — CURRENT REPOSITORY STATE

**STATUS:** ACTIVE FACTUAL SNAPSHOT
**SNAPSHOT_DATE:** 2026-08-16
**PURPOSE:** Hedef mimari ile mevcut implementation'ın karıştırılmasını engellemek.

Bu dosya `MASTER-SPEC.md` veya `TARGET-ARCHITECTURE.md` gibi hedefi tanımlamaz. Mevcut repository üzerinde doğrulanmış önemli gap'leri kaydeder. Kod değiştikçe yeniden audit edilmelidir.

## 1. Genel Sonuç
Repository'de çok sayıda değerli fikir ve modül bulunuyor; ancak kod tabanı farklı LLM geliştirme nesillerinin üst üste binmiş hali. Dosyanın/class'ın varlığı, özelliğin gerçek runtime'a entegre veya production-ready olduğu anlamına gelmiyor.

`DUZELTME_RAPORU.md`, eski roadmap'ler ve README içindeki tamamlanma/production-ready iddiaları bağımsız kanıt değildir.

## 2. Canonical Runtime Gap
- README/eski yönetim akışlarında `start.py` ve/veya `run_system.py` referansları bulunuyor ancak audit sırasında main branch'te bu canonical entry point'ler doğrulanamadı.
- `alpha` yönetim scriptinin eski akışı var olmayan/uyumsuz entry point'lere dayanabiliyor.
- `memory/QUICKSTART.md` eski sürümünde `start.bat` iddia ediyordu; repository search'te `start.bat` bulunmadı.
- Tek, doğrulanmış canonical runtime henüz oluşturulmamış durumda.

## 3. API Nesilleri Birbiriyle Çakışıyor
- `services/api/main.py` ve `services/api/server.py` ayrı API nesilleri içeriyor.
- Docker image `services.api.main:app` çalıştırırken başka belgeler `server.py`yi production server olarak tanımlıyor.
- Bu ikilik kaldırılmadan API davranışı tek source-of-truth değildir.

## 4. Fake / Hard-Coded Live-Looking Data
`services/api/server.py` içinde market endpoint'lerinde sabit BIST değeri/change/breadth/volatility benzeri live-looking değerler bulundu. Bunlar canlı observation gibi kullanılamaz.

## 5. Universe Hard Caps
Bazı API/runtime kodlarında `BIST_STOCKS[:50]`, `[:30]` veya benzeri ilk-N taramalar bulunuyor. Bunlar yeni constitution'a aykırıdır. Compute optimization HOT/WARM/COLD veya explicit scheduler policy ile yeniden tasarlanmalıdır.

## 6. Regime Logic Bug Example
`services/api/main.py` içindeki bir fallback breadth logic'inde `breadth > 65` koşulu, sonraki `breadth > 70` koşulunu erişilemez yapabiliyor. Regime logic yeniden test edilmelidir.

## 7. Fabricated Context Values
Bazı instrument analysis yollarında gerçek veriden gelmeyen sabit `correlation_to_index`, `amihud`, `regime`, `kap_sentiment` vb. değerlerin downstream SPEC/context'e verildiği görüldü. Bu davranış production path'te yasaktır.

## 8. Ranking / ML Gap
Mevcut `services/ml/ranking_model.py` gelişmiş isimler ve yorumlar taşısa da audit sırasında:
- gerçek date × ticker panel contract net değil;
- grouping ile X ordering arasında mismatch riski var;
- açıklamada Adjusted-MSE denmesine rağmen gerçek training objective ile uyumsuzluklar bulunuyor;
- rule-based score direction ile final ascending sort semantics çakışabiliyor;
- confidence rank percentile'dan keyfi biçimde üretilebiliyor.

Bu nedenle mevcut ranking model `Champion` veya validated LambdaRank olarak kabul edilmez.

## 9. Test Quality Gap
`tests/test_faz3_ranking.py` audit örneğinde:
- mevcut implementation ile uyuşmayan class/API import beklentileri;
- `assert ... or True` gibi her durumda geçen assertion
bulundu.

Dolayısıyla test sayısı/`passed` metni coverage veya correctness kanıtı değildir.

## 10. Backtest Gap
`services/backtest/engine.py` audit sırasında:
- open positions için gerçek mark-to-market eksik/basit;
- `holding_days=1`;
- CAGR = total return şeklinde simplification;
- drawdown duration = 0;
- exposure = 0;
- price_data'nın gerçek kullanımı sınırlı
özellikleri gösterdi.

Bu nedenle mevcut backtest metrics finansal kanıt olarak kullanılamaz.

## 11. Walk-Forward Gap
`services/backtest/enhanced_walk_forward.py` precomputed predictions/actuals üzerinde fold değerlendirmesi yapıyor; fold içinde model training/calibration pipeline'ını yeniden çalıştırdığı kanıtlanmadı. Constitution gereği bu leakage-safe walk-forward sayılmaz.

## 12. Mask-First Gap
`services/core/data_quality.py` bazı feature'ları hesaplandıktan sonra None yapabilen `apply_mask` yaklaşımı içeriyor. Canonical kural mask BEFORE dependent features'dır. Audit sırasında bu post-hoc mask'in repo genelindeki gerçek integration'ı da doğrulanmadı.

## 13. Label Contract Gap
`services/labels/generator.py` içindeki cross-sectional rank fonksiyonunda type/interface tutarsızlığı görüldü: dokümante edilen input shape ile `.get(label_name)` kullanımının beklediği shape uyuşmuyor. Dataset/label platform yeniden contract-driven kurulmalı.

## 14. Agent Intelligence Gap
`services/agents/agent_system.py` çok sayıda AgentRole tanımlıyor; fakat temel agent davranışları önemli ölçüde ortak `BaseAgent` + rule-based fallback'e dayanıyor. Tool registry'nin gerçek enforcement/execution zinciri sınırlı. Bu haliyle full agentic research organization değildir.

## 15. Learning Gap
`services/learning/integrated_learning.py` esas olarak in-memory prediction/outcome kayıtları ve basit accuracy/drift istatistiği tutuyor. Gerçek retraining, feature importance feedback, governed champion/challenger lifecycle bu sınıfta kanıtlanmış değil.

## 16. Event Bus / Failure Handling Gap
`services/core/event_bus.py` içinde önemli yerlerde silent/fail-open davranışlar ve `except: pass` örnekleri bulunuyor. Critical data/event paths structured observable failure'a dönüştürülmeli.

## 17. Dependency / Architecture Mismatch
Eski architecture bazı teknolojileri zorunlu gibi anlatırken mevcut `requirements.txt` bunların bir kısmını içermiyor; bazı kod dosyaları ise bu eksik bağımlılıkları import etmeye çalışıyor. Stack önce ölçülmüş ihtiyaçlara göre sadeleştirilip coherent hale getirilmeli.

## 18. Secrets Gap
`docker-compose.yml` audit sırasında repository içinde hard-coded database/admin password örnekleri taşıyordu. Constitution gereği secrets source control'de tutulmamalı.

## 19. Event Intelligence Current Gap
Event/KAP/news için çeşitli modüller bulunuyor fakat yeni `EVENT-INTELLIGENCE-SPEC.md` seviyesinde:
- materiality;
- expectation/surprise;
- event thread;
- binding/conditionality;
- company memory;
- evidence binding;
- post-event reaction;
- historical reaction profile
uçtan uca canonical runtime'a entegre edilmiş olarak henüz doğrulanmadı.

## 20. Current Trust Rule
Aşağıdaki etiketler audit artifact olmadan kullanılamaz:
- COMPLETE
- PRODUCTION READY
- LEAKAGE SAFE
- OOS PASSED
- CHAMPION
- 85% COVERAGE
- 100/100
- LIVE

## 21. Migration Priority
Mevcut durumdan hedefe sıra:
1. repository truth audit;
2. canonical runtime/contracts;
3. source/universe/entity registry;
4. point-in-time + mask-first data;
5. event intelligence foundation;
6. state + feature platform;
7. dataset/label/validation;
8. honest baseline;
9. governance/model lifecycle;
10. persistent paper OS;
11. autonomous research.

Bu dosya yeni audit sonuçlarıyla güncellenmelidir; target architecture ile karıştırılmamalıdır.
