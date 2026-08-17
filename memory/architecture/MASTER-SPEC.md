# ALPHA — MASTER SYSTEM SPEC

## Status
Bu belge ALPHA'nın ana ürün/sistem vizyonudur. Eski roadmap, mimari veya düzeltme belgeleri bu dosyayla çelişirse SYSTEM-CONSTITUTION.md aksi bir kural koymadığı sürece bu belge geçerlidir.

## Mission
ALPHA bir hisse seçme botu değildir ve BIST 100 ile sınırlı değildir. Erişilebilir tüm Borsa İstanbul evreni ve onun global bilgi bağlamı üzerinde çalışan, otonom fakat yönetilen bir finansal araştırma, piyasa zekâsı, sıralama, simülasyon ve sanal-portföy işletim sistemidir.

Amaç; piyasaları ve bilgi ortamını sürekli gözlemlemek, dünya/ülke/sektör/şirket/varlık state'lerini temsil etmek, hipotezler üretip test etmek, fırsatları olasılıksal ve göreli olarak sıralamak, belirsizlik ve riski yönetmek, kalıcı paper portföy işletmek, sonuçları ölçmek, hataları teşhis etmek ve kontrollü araştırma yoluyla gelişmektir.

## Scope Principle: No Fixed Coverage Cap
ALPHA ürün seviyesinde `ilk 50 hisse`, `ilk 100`, `BIST100 only`, `ilk N haber`, `maksimum 800 varlık` veya sabit global kaynak sayısı gibi kapsam sınırları içeremez.

Hedef kapsam:
- erişilebilen tüm güncel Borsa İstanbul menkul kıymet evreni;
- bias-safe araştırma için tarihsel üyelikler ve delist/çıkarılmış varlıklar;
- BIST endeksleri, sektörler, peer grupları ve ilgili Türkiye finansal değişkenleri;
- KAP bildirimleri ve şirket olayları;
- Türkiye makroekonomik, düzenleyici ve politika verileri;
- global makroekonomi;
- global hisse/endeks/faiz/FX/emtia/kredi-risk değişkenleri;
- şirket, sektör, müşteri, tedarikçi, rakip, ortaklık ve sahiplik ilişkileri;
- hukuken ve teknik olarak erişilebilen açık web/haber/kamusal bilgi kaynakları;
- mevcut olduğunda lisanslı veya sözleşmeli veri akışları;
- research/validation için yapılandırılmış ve yapılandırılmamış tarihsel veri.

Kapsam sınırı olmaması her kaynağa her an eşit compute ayrılması anlamına gelmez. ALPHA HOT/WARM/COLD gibi dinamik önceliklendirme, incremental computation ve compute bütçeleri kullanır; ancak bu katmanlar eligibility filtresi değildir.

## Core Question
ALPHA'nın temel sorusu `X hissesi yarın yükselir mi?` değildir.

Temel soru:

> Mevcut world state, Türkiye state, piyasa rejimi, sektör state, şirket/asset state, bilgi state, likidite, execution koşulları ve belirsizlik altında, ilgili zaman ufkunda erişilebilir evrene göre en güçlü risk-adjusted fırsatlar hangileridir?

## Three Brains
### 1. Operating Brain
Canlı gözlem, state update, ranking, calibration, uncertainty, risk, paper execution, portfolio, reconciliation, performance ve safe-mode yönetir.

### 2. Research Brain
Yeni araştırma soruları, hipotezler, feature/factor discovery, modeller, event ilişkileri, causal/counterfactual çalışmalar, robustness ve challenger üretir.

### 3. Governance Brain
Sistemin kendisini kandırmasını engeller. Point-in-time, leakage, data lineage, reproducibility, OOS, cost/execution realism, multiple-testing, promotion, audit ve constitutional rule kontrollerini bağımsız yürütür.

Research Brain kendisini production'a terfi ettiremez. Operating Brain governance kurallarını değiştiremez.

## Information Universe
İnternet ve piyasa veri ekosistemi küçük bir RSS listesi değil, sürekli değişen bir bilgi grafiğidir.

Sistem desteklemelidir:
- source registry ve provenance;
- source reliability history;
- raw immutable capture;
- multilingual extraction;
- deduplication ve canonical event formation;
- entity resolution;
- novelty ve contradiction detection;
- source/event/effective/ingest timestamp ayrımı;
- information decay;
- affected-asset inference;
- global-to-local propagation;
- evidence linking ve replay.

Kararı etkileyen her dış olgu kaynak ve zaman damgasına kadar izlenebilir olmalıdır.

## World Model
Dinamik state katmanları:
- WorldState;
- TurkeyState;
- MarketState;
- SectorState;
- Company/AssetState;
- PortfolioState;
- Model/ResearchState;
- DataQualityState.

Olaylar evidence-supported, versioned ve öğrenilebilir graph üzerinden yayılabilir:
`EVENT -> ENTITY -> GLOBAL/MACRO FACTOR -> COUNTRY -> SECTOR -> COMPANY -> ASSET -> PORTFOLIO`.

Hard-coded propagation kuralları yalnız bootstrap olabilir; kalıcı gerçek sayılmaz.

## Intelligence Families
Başlangıç evidence aileleri, bunlarla sınırlı olmamak üzere:
1. Relative Strength
2. Momentum + Trend
3. Volume + Microstructure
4. Fundamental / FCF / Quality / Growth / Value
5. KAP + Event/News Intelligence
6. Catalyst
7. Why Is It Falling?
8. Mean Reversion
9. Seasonality

Yeni motor/factor keşfedilebilir; ancak governed validation olmadan production'a giremez.

## Event Intelligence
ALPHA haberleri tek bir sentiment/news score'a indirgemez. Event Intelligence olayın anlamını, maddi önemini, kesinliğini, beklenti/sürpriz boyutunu, zaman ufkunu, şirket ölçeğine göre etkisini, ilişkili şirket/sektörleri ve olay sonrası gerçek piyasa tepkisini modellemelidir.

## Cross-Sectional First
Varlıklar eligible evren ve uygun peer setleri içinde değerlendirilir. Universe membership, features, ranks, dispersion, labels ve relative performance point-in-time olmalıdır.

## Multi-Horizon
Intraday veri destekliyorsa intraday, ayrıca 1-5D, 1-4W, 1-6M ve daha uzun araştırma horizonları ayrı model/target/decision mantıklarına sahip olabilir. Tek skor farklı horizonları gizlice karıştıramaz.

## Model Philosophy
Ranking ana mekanizmalardan biridir fakat dogma değildir. Learning-to-rank, calibrated classification, regression, anomaly, state-space, causal/event-impact, volatility/risk, execution/liquidity, ensemble ve specialist modeller yalnız OOS kanıtıyla değer kazanır.

Hiçbir model adı, karmaşıklığı veya LLM tarafından yazılmış olması nedeniyle güvenilir sayılmaz.

## Research Lifecycle
`IDEA -> RATIONALE -> DATA CONTRACT -> POINT-IN-TIME DATASET -> TRAIN -> PURGED/EMBARGOED OOS -> ROBUSTNESS -> COST/EXECUTION TEST -> QUALITY GATE -> SHADOW -> CHALLENGER -> PAPER EVIDENCE -> PROMOTE / REJECT / RETIRE`

Discovery production değildir.

## Self-Learning
ALPHA prediction/ranking outcome, portfolio ve execution outcome, regime-conditioned performance, source reliability, drift, residual, failed prediction ve experiment history'den öğrenir.

Self-learning = kontrollü data/model/research evrimi. Constitutional risk ve governance kurallarını keyfi değiştirmek değildir.

## Uncertainty
Mümkün olduğunca ayrı tutulur:
- data uncertainty;
- model uncertainty;
- regime uncertainty;
- event interpretation uncertainty;
- execution uncertainty;
- portfolio uncertainty.

Yetersiz/çelişkili evidence `UNKNOWN` veya `NO-TRADE` üretebilir.

## Paper-First Operating Model
Mevcut hedef gerçek para execution değildir. Hedef; live-data üzerinde yıllarca çalışan, komisyon, spread, slippage, liquidity, timing, turnover, partial fills ve mümkün olduğunda market-impact gerçekçiliği bulunan persistent paper trading sistemidir.

## Persistent Audit and Reproducibility
Her karar en az şu versioned artifact/lineage ile yeniden üretilebilir olmalıdır:
- source/event IDs ve timestamps;
- universe snapshot;
- masks/data-quality state;
- feature definition/version;
- label contract;
- model artifact/version;
- code commit;
- config hash;
- regime/state snapshot;
- score/rank/calibration/uncertainty;
- risk decision;
- paper order/fill;
- outcome/attribution.

## Failure-Aware Autonomy
Sistem source outage/staleness, contradictory data, distribution shift, feature/model drift, regime mismatch, execution anomaly, portfolio drawdown, integrity failure, leakage veya reproducibility failure'ı fark edip sınıflandırmalıdır.

Çözülemeyen integrity uncertainty durumunda varsayılan davranış sahte confidence değil; degrade, exposure reduction veya NO-TRADE'dir.

## Success Definition
ALPHA başarılı sayılırsa yıllarca minimum günlük insan müdahalesiyle çalışırken bağımsız doğrulanabilir biçimde şunları kanıtlayabilmelidir:
- data point-in-time ve traceable;
- research reproducible;
- OOS dürüst;
- paper sonuçları realistic cost/execution sonrası ölçülüyor;
- promotion governed;
- failure ve risk durumunda kendini koruyor;
- yeni araştırma sadece kanıt sonrası production'a geçiyor;
- sistem ne bildiğini, ne bilmediğini ve neden hareket ettiğini açıklayabiliyor.
