# ALPHA — EVENT INTELLIGENCE SPEC

## Amaç
ALPHA'nın KAP/haber/web katmanı sentiment veya basit `news_score` motoru değildir. Amaç olayın gerçekten ne olduğunu, şirkete/sektöre/dünyaya ne anlam ifade ettiğini, ne kadar maddi olduğunu, ne kadar kesin olduğunu, piyasanın bunu bekleyip beklemediğini ve gerçek piyasa tepkisinin ne olduğunu anlayan bağlamsal bir Event Intelligence sistemidir.

## 1. Temel Kural
Bir haberin varlığı sinyal değildir. Sistem en az şu soruları cevaplamaya çalışır:
- olay ne?
- gerçekten yeni mi?
- hangi kaynak söylüyor ve güvenilirliği ne?
- rumor, intention, MoU, tender win, signed contract, approval veya execution aşamasında mı?
- hangi entity/company/sector/country etkileniyor?
- şirket ölçeğine göre materiality ne?
- revenue, margin, EBITDA, FCF, debt, cash, capacity veya backlog ne yönde etkilenebilir?
- one-off mu recurring mi?
- hangi horizonlarda etkili?
- piyasa bunu bekliyor muydu?
- olaydan önce fiyatlama olmuş muydu?
- olay sonrası raw/relative/abnormal reaction ne?
- evidence eksik veya çelişkili mi?

LLM doğrudan BUY/SELL authority değildir. Structured event + evidence üretir; Quant/ML/Risk downstream değerlendirir.

## 2. Pipeline
`RAW SOURCE -> SOURCE VALIDATION -> DEDUP -> ENTITY RESOLUTION -> EVENT EXTRACTION -> FINANCIAL/CONTRACT TERM EXTRACTION -> CONDITIONALITY -> NOVELTY/EXPECTATION -> COMPANY MATERIALITY -> PROPAGATION -> MARKET REACTION -> HISTORICAL ANALOGUES -> UNCERTAINTY -> CANONICAL EVENT STATE`

## 3. Event Ontology
Ontoloji genişleyebilir. Başlangıç sınıfları:
financial_results, guidance, profit_warning, contract_award, contract_cancellation, tender, investment, capacity_expansion, acquisition, merger, divestiture, partnership, JV, licensing, regulatory_approval, regulatory_penalty, litigation, tax, debt_issue, refinancing, credit_rating, capital_increase, buyback, insider_transaction, dividend, management_change, supply_disruption, production_halt, product_launch, export_order, government_incentive, geopolitical_exposure, commodity_exposure, currency_exposure, macro_event, sector_event.

## 4. Contract/Agreement Intelligence
`1 milyar TL sözleşme` otomatik pozitif değildir.

Mümkün olduğunda:
- contract_value / TTM revenue;
- contract_value / annual revenue;
- contract_value / market cap;
- contract_value / existing backlog;
- company share of contract;
- expected gross profit / EBITDA;
- expected cashflow / FCF;
- capex required / cash;
- financing need / liquidity;
- currency and cost exposure;
- duration and revenue-recognition schedule;
- advance/payment schedule;
- guarantees, termination conditions;
- recurring vs one-off;
- customer concentration;
- execution capacity
hesaplanır veya structured unknown olarak tutulur.

## 5. Binding / Certainty Ladder
Aynı kabul edilmez:
`rumor < intention < MoU < preliminary agreement < tender winner < signed contract < regulatory approved < execution started < cash/revenue realized`.

Her event `binding_status`, `conditionality`, `execution_probability` ve unknowns taşır.

## 6. Counterparty Intelligence
Counterparty için mümkün olduğunda:
identity, public/private, country, credit/reliability, payment history, strategic importance, customer concentration effect, new-market entry ve relationship history tutulur.

## 7. Expectation / Surprise
`iyi haber = pozitif return` varsayımı yasaktır.

Structured fields:
- expected_state;
- observed_event;
- surprise_direction;
- surprise_magnitude;
- pre_event_probability;
- information_novelty;
- already_priced_probability.

Büyük ama daha önce bilinen bir contract imzası düşük novelty taşıyabilir. Kötü ama korkulandan iyi bilanço pozitif surprise olabilir.

## 8. Market Reaction Intelligence
Olay pencereleri veri çözünürlüğüne göre örneğin:
- pre-event [-5d,-1d];
- [0,+30m];
- [0,+1d];
- [+1d,+5d];
- [+5d,+20d].

İzlenebilecek ölçüler:
raw return, BIST-relative, sector-relative, abnormal return, volume anomaly, spread, volatility, gap, reversal, follow-through, peer reaction.

Reaction states örnekleri:
- good_news_confirmed_by_market;
- good_news_ignored;
- good_news_sold_the_news;
- bad_news_absorbed;
- bad_news_accelerating;
- likely_already_priced;
- ambiguous_event.

## 9. Event Threads / Lifecycle
Aynı olayın farklı aşamaları bağımsız beş pozitif haber sayılmaz.

`rumor -> tender participation -> tender win -> contract signing -> approval -> execution -> revenue recognition -> margin outcome`

`event_thread_id` ve lifecycle stage ile bağlanır.

## 10. Company Memory
LLM haberi sıfır bağlamla okumaz. CompanyState en az:
business model, segments, customers, suppliers, countries, FX/commodity sensitivity, debt/cash, capacity, backlog, projects/contracts, litigation, management, historical events ve event-reaction profile taşır.

## 11. Knowledge Graph / Propagation
Event etkisi:
`EVENT -> COMPANY -> CUSTOMER/SUPPLIER -> PEERS -> SECTOR -> COMMODITY/CURRENCY/COUNTRY -> BIST ASSETS`.

Bootstrap rules olabilir ama sabit truth değildir. Propagation relationships source/evidence ve tarihsel calibration taşır.

## 12. Historical Event Memory
Her event için context + outcome saklanır:
event type, company size/state, sector, regime, valuation, pre-event momentum, materiality, surprise, source reliability, reaction, 1d/5d/20d relative outcome.

Historical analogue yalnız evidence'tır, otomatik karar değildir.

## 13. Uncertainty Decomposition
Tek confidence yerine mümkün olduğunda:
- extraction_confidence;
- entity_resolution_confidence;
- source_confidence;
- materiality_confidence;
- execution_probability;
- impact_direction_confidence;
- impact_magnitude_uncertainty;
- horizon_uncertainty;
- contradiction_state.

## 14. Evidence Binding
LLM'nin çıkardığı önemli alanlar mümkün olduğunda:
`value + source_id + source_timestamp + evidence_span + extraction_method/model_version + confidence`
ile saklanır.

Kaynaksız finansal rakam üretmek yasaktır.

## 15. No Single News Score
Downstream için numerical features üretilebilir; ancak ana output tek `news_score` değildir.

Örnek alanlar:
event_type, event_thread_id, company, counterparties, amounts/currencies, binding_status, execution_probability, financial materiality vectors, novelty, surprise, prepriced probability, horizon, affected entities, key unknowns, evidence, reaction state, uncertainty.

## 16. Research Questions
Research Brain zamanla şu tür sorular test edebilir:
- Contract announcements hangi company-size/materiality oranlarında gerçekten persistent relative return üretiyor?
- Hangi sektörlerde headline amount yerine margin/backlog daha açıklayıcı?
- Event impact hangi rejimde hızlı decay ediyor?
- `bad_news_absorbed` state'i hangi koşullarda reversal evidence taşıyor?
- Company-specific historical reaction profile genellenebilir mi?

Bu bulgular OOS/governance olmadan production'a geçmez.

## Ana İlke
**ALPHA haberi puanlayan değil, olayı anlayan sistem olacaktır.**
