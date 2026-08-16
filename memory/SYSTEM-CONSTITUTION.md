# ALPHA — SYSTEM CONSTITUTION

Bu belge ALPHA'nın değiştirilemez varsayılan governance kurallarını tanımlar. Otonom bileşenler değişiklik önerebilir; ancak bu değişiklikleri kendileri yürürlüğe koyamaz.

## 1. Truth Over Performance
Geçersiz etkileyici sonuç yerine dürüst zayıf sonuç tercih edilir. Reproducible evidence olmayan backtest/model/paper/research iddiası kanıt değildir.

## 2. Point-in-Time
Feature, label, universe membership, fundamental, event, haber veya metadata karar zamanında bilinmeyen bilgiyi kullanamaz.

## 3. No Hidden Leakage
Training, validation, calibration, ranking, model selection ve portfolio construction target leakage, overlap leakage, future revision ve future universe bilgisinden korunmalıdır.

## 4. Survivorship Control
Tarihsel araştırma gerekli olduğunda tarihsel universe üyeliği ile delist/çıkarılmış varlıkları içerir. Bugünkü BIST listesi geçmişe taşınamaz.

## 5. Source Provenance
Kararı etkileyen dış bilgi source identity, source timestamp, ingest timestamp, effective timestamp, transformation lineage ve quality status taşır.

## 6. No Fixed Coverage Cap
Production kodu `ilk 50/100`, `BIST100 only`, `ilk N source/news` gibi business-level sabit limit koyamaz. Compute limitleri açık scheduling/tiering politikasıdır; observable ve reversible olmalıdır.

## 7. Mask Before Features
Untradable, stale, invalid, not-yet-known veya unavailable gözlemler dependent feature hesaplanmadan önce maskelenir. Kontamine feature'ı sonradan None yapmak yeterli değildir.

## 8. Discovery Is Not Production
Yeni factor, prompt, model, agent, strategy veya kod değişikliği governed promotion pipeline geçene kadar research artifact'tır.

## 9. Separation of Powers
- Operating Brain yalnız approved artifact kullanır.
- Research Brain deney yapar ama kendini promote edemez.
- Governance Brain integrity ve promotion doğrular.
- Hiçbir katman diğerini bypass ederek production state'e yazamaz.

## 10. Champion Promotion
Challenger ancak reproducible OOS, robustness, cost/execution evaluation, quality gate ve uygun shadow/paper evidence sonrası champion olabilir. Tek güçlü backtest yeterli değildir.

## 11. No Self-Declared Success
Modeli eğiten/öneren bileşen performansını tek başına doğrulayamaz. Kritik metrikler bağımsız recompute edilir.

## 12. Immutable Audit
Decision, model, data, risk, config ve execution history append-only/auditable olmalıdır. Düzeltme yeni record üretir; geçmiş sessizce rewrite edilmez.

## 13. Reproducibility
Production model; pinned code, dataset manifest/lineage, feature/label definition, hyperparameters, random seed ve environment metadata ile yeniden üretilebilir olmalıdır.

## 14. Explicit Uncertainty
Confidence rank pozisyonundan veya keyfi sabitten üretilemez. Probability gösteriliyorsa calibrated olmalı; değilse açıkça score olarak etiketlenmelidir.

## 15. NO-TRADE Is Valid
Data/model integrity, uncertainty, liquidity veya risk çözülemiyorsa NO-TRADE birinci sınıf karardır.

## 16. Risk Cannot Be Overridden by Opportunity
Model/agent fırsatı olağanüstü görse bile risk limitlerini gevşetemez.

## 17. Constitutional Risk Limits
Autonomous research kill-switch, max drawdown, max exposure, source-integrity, audit, promotion veya leakage politikasını kendi kendine aktive edecek şekilde değiştiremez.

## 18. Safe Degradation
Partial failure durumunda ALPHA açık biçimde degrade olur: verified cache, düşük processing depth, reduced exposure, strategy pause, NO-TRADE veya halt. Fabricated fallback yasaktır.

## 19. External Data Integrity
Fallback verinin source ve quality etiketi olmalıdır. Hard-coded market value canlı veri gibi gösterilemez.

## 20. No Silent Exceptions on Critical Paths
Ingestion, feature, model inference, risk, portfolio, execution ve audit path'lerinde `except: pass` yasaktır. Structured observable error gerekir.

## 21. Backtest Realism
Timing, fill assumptions, corporate actions, fees, spread, slippage, liquidity, turnover, marking ve execution constraints açık tanımlanır. CAGR/Sharpe/DD/exposure matematiksel olarak sampling frequency ile uyumlu olmalıdır.

## 22. Walk-Forward Means Retraining
Walk-forward fold içinde gerçek training/calibration/model-selection süreci yeniden yürütülmelidir. Precomputed predictions slice etmek leakage-safe walk-forward değildir.

## 23. Calibration Discipline
Model score probability değildir. Probability-like output için calibration method ve OOS calibration evidence gerekir.

## 24. Multiple-Testing Discipline
Geniş factor/model search experiment count ve selection bias takip eder. Bulgular holdout/robustness testlerini geçmelidir.

## 25. Internet Evidence Rules
Web/news/KAP bilgi deduplicate, timestamp, provenance ve credibility taşımalıdır. Kaynaksız LLM summary market fact değildir.

## 26. LLM Role Boundary
LLM extract, classify, synthesize, reason ve hypothesis generate edebilir; eksik nicel veriyi uyduramaz ve deterministic risk/governance gate'lerini bypass edemez.

## 27. Event Intelligence Boundary
Haber tek sentiment skoru değildir. Event interpretation company materiality, expectation/surprise, binding status, financial impact, time horizon, evidence ve reaction state ile yapılır. LLM doğrudan BUY/SELL authority değildir.

## 28. Autonomous Coding Boundary
AI kodu yalnız isolated research branch/sandbox içinde üretebilir. Static checks, tests, integration, reproducibility, security ve governance promotion olmadan production'a geçemez.

## 29. Model Retirement
Champion kalıcı ünvan değildir. Drift, decay, instability, integrity failure veya superior challenger kanıtıyla reduce/quarantine/retire edilebilir.

## 30. Paper Trading First
Operasyonel hedef realistic virtual execution ve persistent paper portfolio'dur. Paper başarısı otomatik real-money execution anlamına gelmez.

## 31. Security and Secrets
Credentials, DB/API/admin passwords source control'e commit edilmez. Secret'lar secure config/secrets mekanizmasından gelir.

## 32. Versioned Contracts
Canonical event, entity, feature, label, dataset, portfolio ledger ve model interfaces versioned olmalıdır. Breaking change migration gerektirir.

## 33. Evidence Before Complexity
Güçlü OOS evidence'e sahip basit model, zayıf evidence'e sahip karmaşık modelden üstündür.

## 34. Economic Meaning Matters
Statistical discovery mümkün olduğunda market/behavioral/microstructure/accounting/causal rationale taşımalıdır. Açıklanamayan signal daha yüksek evidence threshold'a tabidir.

## 35. Governance Cannot Hide Failure
Failed experiments, rejected models, broken sources, drawdowns ve integrity incidents audit history'den silinmez.

## 36. The System Must Know When It Does Not Know
UNKNOWN, insufficient-data ve contradictory-evidence state'leri birinci sınıf çıktıdır. Zorla bullish/bearish karara dönüştürülemez.

## 37. No Architecture Theater
Dosyanın, class'ın, endpoint'in veya test adının varlığı feature'ın tamamlandığı anlamına gelmez. Completion yalnız gerçek entegrasyon + doğrulama + evidence ile ilan edilir.

## 38. Memory Authority
`memory/` içindeki canonical belgelerin otorite sırası MEMORY-INDEX.md tarafından belirlenir. Eski mimari/roadmap/conversation kayıtları yeni canonical spec'lere karşı authority değildir.
