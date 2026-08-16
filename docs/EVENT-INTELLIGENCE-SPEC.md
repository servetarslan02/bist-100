# ALPHA EVENT INTELLIGENCE SPEC

## Amaç

ALPHA'nın haber/KAP katmanı bir sentiment veya basit skor motoru değildir. Amaç, olayın ne olduğunu, kime ne ölçüde maddi etkisi olabileceğini, hangi koşullara bağlı olduğunu, piyasanın bunu zaten fiyatlayıp fiyatlamadığını ve sonrasında gerçek fiyat tepkisinin ne olduğunu anlayan bağlamsal bir Event Intelligence sistemi kurmaktır.

## 1. Temel prensip

Bir haberin varlığı tek başına sinyal değildir.

ALPHA şu ayrımı yapmalıdır:

- haber nedir?
- olay gerçekten yeni mi?
- bilgi güvenilir mi?
- kesinleşmiş mi, niyet/mutabakat/ön anlaşma mı?
- şirkete maddi etkisi var mı?
- etkinin büyüklüğü şirket ölçeğine göre ne?
- gelir mi, kâr mı, nakit akışı mı, kapasite mi, borç mu etkilenir?
- etki tek seferlik mi, tekrarlayan mı?
- hangi zaman ufkunda etkili olabilir?
- piyasa bunu bekliyor muydu?
- fiyat olaydan önce hareket etmiş miydi?
- açıklama sonrası fiyat/hacim/spread/relative strength nasıl tepki verdi?
- tepki beklenenden farklıysa neden?

LLM doğrudan AL/SAT kararı vermez. LLM ve diğer NLP modelleri structured event üretir; Quant/ML/Risk katmanları bu bilgiyi bağlam içinde kullanır.

## 2. Event Understanding Pipeline

```text
RAW SOURCE
  -> source validation
  -> deduplication
  -> entity resolution
  -> event extraction
  -> contract/financial term extraction
  -> conditionality analysis
  -> novelty / expectation analysis
  -> company materiality analysis
  -> sector / peer propagation
  -> market reaction analysis
  -> historical analogue retrieval
  -> uncertainty decomposition
  -> canonical event state
  -> downstream research/ranking
```

## 3. Olay sınıfları

Sistem sabit birkaç etikete sıkışmayacaktır. Ontoloji genişleyebilir. Başlangıçta en az:

- financial_results
- revenue_guidance
- profit_warning
- contract_award
- contract_cancellation
- tender
- investment
- capacity_expansion
- acquisition
- merger
- divestiture
- partnership
- joint_venture
- licensing
- regulatory_approval
- regulatory_penalty
- litigation
- tax
- debt_issue
- refinancing
- credit_rating
- capital_increase
- buyback
- insider_transaction
- dividend
- management_change
- supply_disruption
- production_halt
- product_launch
- export_order
- government_incentive
- geopolitical_exposure
- commodity_exposure
- currency_exposure
- macro_event
- sector_event

## 4. Anlaşma/kontrat zekâsı

Bir şirket '1 milyar TL sözleşme imzaladı' dediğinde ALPHA rakama bakıp pozitif skor vermeyecektir.

Aşağıdaki bağlam kurulacaktır:

### 4.1 Şirket ölçeğine göre materiality

Mümkün olduğunda hesaplanır:

- contract_value / trailing_12m_revenue
- contract_value / annual_revenue
- contract_value / market_cap
- contract_value / order_backlog
- expected_gross_profit / EBITDA
- expected_cash_flow / FCF
- capex_required / cash
- financing_need / available_liquidity

1 milyar TL anlaşma küçük bir şirket için dönüştürücü, çok büyük bir şirket için sıradan olabilir.

### 4.2 Muhasebe ve ekonomik etki

Sistem yalnız headline tutarını kullanmayacaktır. Şunları ayırmalıdır:

- toplam kontrat değeri
- şirket payına düşen tutar
- gelir olarak tanınacak dönem
- brüt marj tahmini
- kur riski
- maliyet pass-through maddesi
- avans
- ödeme takvimi
- garanti/teminat
- iptal maddeleri
- kapasite ihtiyacı
- yeni borçlanma gereksinimi
- backlog etkisi
- recurring vs one-off gelir

### 4.3 Kesinlik seviyesi

Aynı anlamda kabul edilmeyecek:

```text
rumor
< intention
< memorandum of understanding
< preliminary agreement
< tender winner announcement
< signed contract
< regulatory approved
< cash received / execution started
```

Her event için `execution_probability` ve `conditionality` tutulacaktır.

### 4.4 Counterparty intelligence

- karşı taraf kim?
- kamu/özel?
- kredi riski?
- geçmiş ödeme davranışı?
- stratejik önemi?
- tek müşteri konsantrasyonu artıyor mu?
- yeni ülke/pazar açıyor mu?

## 5. Beklenti ve sürpriz

Haberin yönü kadar `expected vs unexpected` farkı önemlidir.

Örnek:

- çok güçlü bilanço ama piyasa daha güçlüsünü bekliyorsa negatif tepki olabilir
- kötü bilanço ama korkulandan iyi ise pozitif tepki olabilir
- büyük kontrat daha önce ihale sonucu olarak biliniyorsa KAP imzası yeni bilgi olmayabilir

Sistem mümkün olduğunda şunları üretir:

- expected_state
- observed_event
- surprise_direction
- surprise_magnitude
- pre_event_probability
- information_novelty

## 6. Price Reaction Intelligence

ALPHA 'haber pozitif/negatif' demekle yetinmeyecektir. Olaydan sonra piyasayı okuyacaktır.

Event window örnekleri:

- [-5d, -1d] pre-event
- [0, +30m]
- [0, +1d]
- [+1d, +5d]
- [+5d, +20d]

İzlenecekler:

- raw return
- benchmark-relative return
- sector-relative return
- abnormal return
- volume anomaly
- spread change
- volatility change
- gap
- reversal
- follow-through
- peer reaction

Böylece sistem örneğin şu state'leri ayırabilir:

- good_news_confirmed_by_market
- good_news_ignored
- good_news_sold_the_news
- bad_news_absorbed
- bad_news_accelerating
- ambiguous_event
- likely_already_priced

## 7. Haber değil olay zinciri

Tek bir haber tek başına değerlendirilmez.

```text
Rumor
 -> tender participation
 -> tender won
 -> contract signed
 -> regulatory approval
 -> production starts
 -> first revenue recognition
 -> margin outcome
```

Bunlar aynı `event_thread_id` altında birleştirilebilir. Böylece aynı olayın beş farklı haberini beş bağımsız pozitif sinyal sayma hatası engellenir.

## 8. Event Memory ve Historical Analogues

Sistem geçmiş olaylardan öğrenmelidir.

Her event için:

- event type
- company state
- company size
- sector
- regime
- valuation state
- pre-event momentum
- materiality
- surprise
- source reliability
- post-event reaction
- 1d/5d/20d relative outcome

saklanır.

Yeni olay geldiğinde benzer tarihsel olaylar retrieval ile bulunur. Ancak historical analogue doğrudan karar değildir; yalnız evidence sağlar.

## 9. Şirket kimliği ve bağlam hafızası

LLM her haberi sıfırdan okumamalıdır. Her şirket için güncel bir company state bulunmalıdır:

- iş modeli
- gelir segmentleri
- ana müşteriler
- tedarikçiler
- ülkeler
- döviz duyarlılığı
- emtia duyarlılığı
- borç profili
- kapasite
- backlog
- son yatırımlar
- devam eden davalar
- son KAP olayları
- yönetim
- tarihsel event reaction profile

Bu bağlam olmadan haber anlayışı eksik kabul edilir.

## 10. Knowledge Graph ve propagation

Event etkisi yalnız açıklamayı yapan şirkette kalmayabilir.

```text
EVENT
 -> COMPANY
 -> CUSTOMER/SUPPLIER
 -> SECTOR
 -> COMMODITY
 -> COUNTRY
 -> PEERS
 -> BIST ASSETS
```

Propagation etkileri sabit hard-coded skor olarak kabul edilmez. Başlangıç kuralları olabilir fakat zamanla tarihsel evidence ile kalibre edilmelidir.

## 11. Uncertainty

Tek confidence alanı yerine en az:

- extraction_confidence
- entity_resolution_confidence
- source_confidence
- materiality_confidence
- execution_probability
- impact_direction_confidence
- impact_magnitude_uncertainty
- horizon_uncertainty

ayrı tutulmalıdır.

Belirsizlik yüksekse sistem bunu bilgi olarak saklar; sahte kesinlik üretmez.

## 12. LLM güvenlik ve doğrulama

LLM'nin çıkardığı rakamlar kaynak metinden evidence span ile bağlanmalıdır.

Her önemli alan için mümkün olduğunda:

```text
value
source_id
source_timestamp
evidence_span
extraction_method
confidence
```

saklanır.

LLM'nin kaynaksız yeni finansal rakam üretmesi yasaktır.

## 13. Reaction Model

ALPHA zamanla şirketlerin farklı olay türlerine nasıl tepki verdiğini öğrenebilir.

Örnek araştırma soruları:

- Bu şirkette kontrat KAP'ları tarihsel olarak fiyatlanıyor mu?
- Piyasa headline value yerine margin'i mi önemsiyor?
- Aynı kontrat tipi küçük şirketlerde mi daha güçlü etki yaratıyor?
- Event etkisi hangi rejimde daha uzun sürüyor?
- İlk gün reaction ile 20 günlük relative return arasında ilişki var mı?

Bu analiz research katmanında yapılır ve OOS doğrulama olmadan production signal'a dönüşmez.

## 14. Event Materiality bir tek skor değildir

Downstream modeller için bazı sayısal feature'lar üretilebilir; fakat Event Intelligence'ın ana çıktısı tek `news_score` olmayacaktır.

Örnek structured output:

```json
{
  "event_type": "contract_award",
  "company": "XYZ",
  "contract_value": 1250000000,
  "company_share": 0.60,
  "currency": "TRY",
  "duration_months": 24,
  "binding_status": "signed_contract",
  "execution_probability": 0.92,
  "revenue_materiality": 0.18,
  "backlog_materiality": 0.31,
  "estimated_margin": null,
  "novelty": "partially_known",
  "prepriced_probability": 0.55,
  "impact_horizon": ["1-5D", "1-4W", "1-12M"],
  "key_unknowns": ["gross_margin", "payment_schedule"],
  "affected_entities": ["XYZ", "sector:A", "supplier:B"],
  "evidence": []
}
```

Bu structure daha sonra quant/ML modellerinin kullanacağı feature'lara dönüşebilir.

## 15. Ana kural

**ALPHA haberi puanlayan değil, olayı anlayan sistem olacaktır.**

Bir olayın gerçek etkisini belirleyen şey yalnız metnin olumlu/olumsuz tonu değil; şirket ölçeği, finansal materiality, beklenti, kesinlik, zaman ufku, rejim, sektör bağlantıları ve olay sonrası gerçek piyasa davranışıdır.
