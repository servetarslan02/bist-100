Evet. Mimo Claw'a vereceğimiz şey basit bir “bug fix promptu” değil; sistemin teknik şartnamesi + mimarisi + çalışma akışı + geliştirme fazları olacak.

Aşağıdaki tasarım, şimdiye kadar belirlediğimiz hedefleri birleştiriyor: 800+ BIST evrenini tarayan fırsat keşif motoru, AI destekli araştırma/karar sistemi, risk kontrollü sanal portföy, senaryo analizi, öğrenme katmanı ve kurumsal terminal tarzı web dashboard. Gerçek para işlemleri bu sistemden ayrı ve kontrollü kalacak.

Mimo Claw'a anlatılacak sistem

1. Sistemin amacı

Sistem yalnızca birkaç hisseyi analiz eden bir uygulama olmayacak.

Ana amaç:

> BIST'teki tüm erişilebilir varlıkları sürekli izleyen, piyasa rejimini anlayan, haber/makro/teknik/fundamental/AI verilerini birleştiren, fırsatları sıralayan, risklerini hesaplayan ve bunları sanal portföy üzerinde test eden otonom bir yatırım araştırma ve simülasyon platformu oluşturmak.



Sistem kendi kendine:

1. BIST evrenini tarayacak.


2. Verileri toplayacak.


3. Verilerin kalitesini kontrol edecek.


4. Piyasa rejimini çıkaracak.


5. Hisseleri/fonları/varlıkları analiz edecek.


6. Fırsatları keşfedecek.


7. Riskleri hesaplayacak.


8. Fırsatları puanlayacak.


9. Sanal portföyde işlemleri simüle edecek.


10. Sonuçları izleyecek.


11. Hatalı kararları analiz edecek.


12. Modellerin performansını ölçecek.


13. Dashboard'da tüm süreci görünür hale getirecek.




---

2. En önemli prensip

Sistem:

“AI → BUY”

şeklinde çalışmayacak.

Doğru mimari:

DATA
 ↓
DATA QUALITY
 ↓
FEATURES
 ↓
MARKET STATE
 ↓
ASSET ANALYSIS
 ↓
OPPORTUNITY ENGINE
 ↓
DECISION ENGINE
 ↓
RISK ENGINE
 ↓
PORTFOLIO SIMULATOR
 ↓
OUTCOME
 ↓
LEARNING

AI bu sistemin bir bileşeni olacak.

Sistemin sahibi AI değil, kurallar + veri + risk motoru + state machine olacak.


---

3. BIST Universe Engine

İlk büyük motor bu.

Sistem:

BIST
 ├── BIST 100
 ├── BIST 30
 ├── BIST 50
 ├── sektörler
 ├── diğer hisseler
 ├── ETF/Fon
 └── desteklenen diğer varlıklar

evrenini tanıyacak.

Kullanıcı yalnızca 3–5 hisse girmeyecek.

Sistem mümkün olan 800+ BIST varlığını tarayabilecek.

Her varlığın:

symbol
name
sector
industry
market
currency
listing_status
liquidity
market_cap

bilgisi olacak.

Universe değiştiğinde otomatik güncellenecek.


---

4. Data Ingestion Layer

Birden fazla veri kaynağı olacak.

Örneğin:

Market Data
 ├── OHLCV
 ├── bid/ask
 ├── volume
 └── market depth (destekleniyorsa)

Fundamental
 ├── revenue
 ├── EBITDA
 ├── net income
 ├── debt
 ├── cash
 ├── FCF
 ├── EPS
 └── ratios

News
 ├── KAP
 ├── financial news
 └── company news

Macro
 ├── USDTRY
 ├── EURTRY
 ├── rates
 ├── inflation
 ├── VIX
 ├── commodities
 └── global indices

Social/Sentiment
 ├── supported social sources
 └── sentiment signals

Her veri kaynağının reliability score'u olacak.


---

5. Data Quality Engine

Veri geldikten sonra doğrudan sisteme sokulmayacak.

Her veri:

VALID
INVALID
STALE
DUPLICATE
OUT_OF_ORDER
MISSING
SUSPICIOUS

durumlarından geçirilecek.

Örneğin:

price = -10

→ reject.

volume = None

→ missing.

timestamp = 3 hours old

→ stale.

same tick twice

→ duplicate.

Veri hatalıysa:

> Hatalı veriyle karar üretme.




---

6. Feature Engine

Ham verilerden özellikler üretilecek.

Teknik

SMA

EMA

RSI

MACD

ATR

Bollinger Bands

volatility

momentum

relative strength

volume acceleration

breakout

trend strength


Fundamental

P/E

P/B

EV/EBITDA

ROE

ROIC

debt/equity

FCF yield

earnings growth

revenue growth

margin trends


Market-relative

Örneğin:

hisse getirisi
vs BIST100
vs sektör
vs benchmark

Macro

USDTRY değişimi

faiz

enflasyon

VIX

petrol

altın

global risk appetite



---

7. World State Engine

Sistem piyasayı tek tek hisselerden ibaret görmeyecek.

Örneğin:

Market Regime:
RISK_ON

Volatility:
MEDIUM

Liquidity:
GOOD

USDTRY:
STRESSING

Rates:
RESTRICTIVE

Global:
RISK_OFF

gibi bir World State oluşturacak.

Bu state sürekli güncellenecek.


---

8. Regime Engine

Piyasa rejimleri örneğin:

BULL
BEAR
SIDEWAYS
HIGH_VOLATILITY
LOW_VOLATILITY
RISK_ON
RISK_OFF
CRISIS
RECOVERY

olabilir.

Ancak bunlar rastgele thresholdlarla değil, ölçülebilir feature'larla çıkarılmalı.

Regime değiştiğinde karar motorunun ağırlıkları da gerektiğinde değişebilmeli.


---

9. Intelligence Engine

Burada AI devreye girecek.

AI:

haberleri okuyacak,

KAP açıklamalarını analiz edecek,

şirket açıklamalarını yorumlayacak,

sentiment çıkaracak,

olayın etkisini değerlendirecek,

şirketler arasındaki ilişkileri bulacak,

makro olayları yorumlayacak.


Ama AI'nın verdiği:

BUY

tek başına emir olmayacak.

AI sonucu:

evidence
confidence
reasoning
source
timestamp
model_version

şeklinde sisteme girecek.


---

10. Event Impact Engine

Örneğin:

> TCMB faiz artırdı.



Sistem bunu sadece “negative” diye işaretlemeyecek.

Şunu hesaplayacak:

event
 ↓
magnitude
 ↓
surprise
 ↓
market regime
 ↓
sector sensitivity
 ↓
asset sensitivity
 ↓
expected impact
 ↓
decay

Örneğin bankalar ile ihracatçı şirketler aynı etkilenmeyebilir.


---

11. Opportunity Discovery Engine

Sistemin en önemli parçalarından biri.

Her tarama sonunda:

BIST 800+
 ↓
candidate filtering
 ↓
liquidity filter
 ↓
data quality filter
 ↓
technical filter
 ↓
fundamental filter
 ↓
macro compatibility
 ↓
sentiment
 ↓
AI evidence
 ↓
risk
 ↓
opportunity score

oluşacak.

Sonuç:

#1 ABC
Opportunity Score: 91
Risk: Medium
Confidence: 87%
Expected Return: ...
Expected Holding Period: ...

gibi olacak.

Ama sadece yüksek skor değil:

risk-adjusted opportunity esas alınacak.


---

12. Decision Engine

Decision Engine:

LONG
SHORT
HOLD
NO_TRADE

üretebilir.

Önemli:

score < threshold → SHORT

gibi hatalı mantık olmayacak.

HOLD gerçekten HOLD olacak.


---

13. Risk Engine

Decision'dan önce veya decision ile birlikte risk gate çalışacak.

Kontroller:

position limit
portfolio exposure
sector exposure
correlation
liquidity
volatility
drawdown
daily loss
max risk
concentration

olacak.

Örneğin AI:

BUY

dedi.

Ama:

sector exposure > limit

ise:

RISK REJECT

olacak.

AI bunu bypass edemeyecek.


---

14. Position Sizing

“BUY” demek yeterli değil.

Sistem:

capital
risk budget
stop distance
volatility
confidence
portfolio exposure
correlation

kullanarak:

position size

hesaplayacak.

Örneğin:

Portfolio:
100,000 TL

Risk budget:
0.75%

Maximum loss:
750 TL

Sonra stop mesafesine göre pozisyon büyüklüğü hesaplanacak.


---

15. Order Engine

Gerçek para ile işlem yapmak yerine ilk aşamada:

SIMULATED ORDER

üretilecek.

Order state:

CREATED
VALIDATED
RISK_APPROVED
SUBMITTED
FILLED
PARTIALLY_FILLED
CANCELLED
REJECTED

olacak.


---

16. Execution Simulator

Gerçek broker yerine simülasyon.

Spread:

bid/ask

slippage:

market volatility
liquidity
order size

ile simüle edilecek.

Commission/fees de gerçekçi modele göre uygulanacak.


---

17. Virtual Portfolio

Kullanıcı sermayesini girecek:

100.000 TL

ve sistem sanal portföy oluşturacak.

Portfolio:

cash
positions
average cost
market value
realized P&L
unrealized P&L
fees
drawdown
exposure
risk

tutacak.


---

18. Portfolio Ledger

Her fill immutable ledger'a yazılacak.

Örneğin:

BUY
THYAO
100 shares
320 TL
commission ...
timestamp ...
decision_id ...
risk_id ...
order_id ...
fill_id ...

Böylece sonradan:

> “Bu THYAO alımını neden yaptın?”



sorusunun cevabı bulunabilecek.


---

19. Learning Engine

Sistem “öğreniyor” demek:

> Her şeyi kendi kendine değiştiriyor



anlamına gelmeyecek.

Önce outcome kaydedilecek.

Örneğin:

Prediction:
+8%

Actual:
-3%

Sistem:

prediction error

hesaplayacak.

Sonra:

hangi feature?
hangi regime?
hangi model?
hangi source?
hangi strategy?

daha çok hata yapıyor analiz edilecek.


---

20. Model Evaluation

Her AI/model için:

accuracy
precision
recall
calibration
profit factor
Sharpe
Sortino
max drawdown
hit rate
false positive
false negative

ölçülebilecek.

Model iyi görünmüyorsa sistem bunu gösterecek.


---

21. Scenario Engine

Kullanıcı:

> USDTRY %10 artarsa?



diyebilecek.

Sistem:

USDTRY shock
 ↓
macro state
 ↓
sector impacts
 ↓
asset impacts
 ↓
portfolio impacts

simüle edecek.

Diğer senaryolar:

TCMB faiz +500bp
BIST -10%
VIX +50%
petrol +20%
USDTRY +10%
global risk-off

olabilir.


---

22. Backtest Engine

Geçmiş veriler üzerinde:

strategy
 ↓
historical market
 ↓
decision
 ↓
risk
 ↓
simulated execution
 ↓
portfolio

çalıştırılacak.

Backtest ile live simulator aynı domain logic'i mümkün olduğunca kullanacak.


---

23. Recovery

Sistem kapanırsa:

snapshot
+
event log

ile aynı state'e geri dönebilecek.

Örneğin kapanmadan önce:

Cash: 54,321
Positions: 7
Equity: 108,542

ise restart sonrası aynı state yeniden üretilecek.


---

24. Event Replay

Belirli bir günü yeniden çalıştırabilmelisin:

2026-08-01

eventleri:

replay

edilip aynı kararlar tekrar üretilebilmeli.

Bu özellikle debugging ve backtest için çok önemli.


---

25. Dashboard

Kullanıcı tarafında basit admin paneli değil, kurumsal yatırım terminali olacak.

Ana workspace'ler:

Overview
Market Radar
Market Map
Events
Opportunities
Asset Research
World State
AI Research
Portfolio
Risk
Scenarios
Backtest
Models
System Health
Audit

Dashboard tarayıcıda çalışacak.

EXE yalnızca opsiyonel launcher olabilir.


---

26. Overview

Ana ekran:

BIST
Market Regime
Risk Regime
Top Opportunities
Top Risks
Portfolio
P&L
AI Confidence
Recent Events
System Health

gösterecek.


---

27. Market Radar

800+ varlığı tarayacak.

Filtreler:

sector
score
risk
momentum
valuation
volume
volatility
AI confidence
market cap

olacak.


---

28. Opportunity Terminal

Sıralama:

Opportunity
Risk-adjusted return
Confidence
Risk
Liquidity
Holding period

üzerinden olacak.

Kullanıcı bir hisseye tıklayınca:

Why?
Evidence
Risks
Catalysts
Technical
Fundamental
Macro
AI analysis
Decision

görecek.


---

29. Asset Research

Bir varlığın tam araştırma ekranı:

Price
Chart
Technical
Fundamental
News
KAP
Sentiment
AI
Macro sensitivity
Risk
Historical behavior
Current signal
Decision history


---

30. Portfolio Terminal

Şunları gösterecek:

Total Equity
Cash
Invested
Daily P&L
Total P&L
Drawdown
Positions
Sector Exposure
Risk
Open Orders
Trade History


---

31. Risk Dashboard

Örneğin:

Portfolio Risk       LOW
Concentration        MEDIUM
Liquidity             GOOD
Correlation           LOW
Drawdown               2.1%
Daily Risk Budget      0.8%

gibi.

Risk neden yükseldiği de açıklanacak.


---

32. AI Research

AI'nın ne yaptığını gizleme.

Her karar için:

Model
Version
Input
Evidence
Confidence
Reasoning
Decision
Risk Decision
Outcome

görülebilmeli.


---

33. Audit

Kullanıcı:

> “Bugün neden 15 numaralı işlemi yaptın?”



dediğinde sistem:

Order
↓
Risk approval
↓
Decision
↓
Signal
↓
Features
↓
Events
↓
Raw data

zincirini göstermeli.


---

34. System Health

Canlı olarak:

API
Database
Redis/Event Bus
Data Providers
LLM
Decision Engine
Risk Engine
Portfolio
Execution Simulator

durumları:

HEALTHY
DEGRADED
FAILED

olarak gösterilmeli.


---

35. Gerçek para güvenliği

İlk ve ana sistem:

Sanal portföy.

Gerçek para execution'ı:

SIMULATION

katmanından tamamen ayrılmalı.

Gerçek broker bağlantısı daha sonra ayrı:

LIVE EXECUTION

olarak ele alınmalı.

Risk motoru olmadan canlı emir gönderilmemeli.


---

36. Teknoloji mimarisi

Mevcut proje yapısı korunarak ihtiyaç halinde şu ayrım hedeflenmeli:

apps/
  web/

services/
  ingestion/
  intelligence/
  risk/
  portfolio/
  decision/
  order/
  execution/
  core/

infra/
  postgres/
  redis/
  event-bus/

tests/
  unit/
  integration/
  e2e/
  replay/
  failure/

Backend domain logic ile UI birbirinden ayrılmalı.


---

37. Geliştirme sırası

Mimo Claw'a hepsini aynı anda yaptırma.

Sıra:

PHASE 0
Repository audit
        ↓
PHASE 1
Core + Config + Database
        ↓
PHASE 2
Data ingestion + Quality
        ↓
PHASE 3
Event infrastructure
        ↓
PHASE 4
World State + Intelligence
        ↓
PHASE 5
Opportunity Engine
        ↓
PHASE 6
Decision Engine
        ↓
PHASE 7
Risk Engine
        ↓
PHASE 8
Order + Execution Simulator
        ↓
PHASE 9
Portfolio Ledger
        ↓
PHASE 10
Learning + Backtest + Scenario
        ↓
PHASE 11
Dashboard
        ↓
PHASE 12
Recovery + Replay
        ↓
PHASE 13
Full E2E + Failure Testing
        ↓
PHASE 14
Production Hardening


---

38. Her fazın çalışma yöntemi

Mimo Claw her fazda:

1. Repository'yi oku
2. Mevcut mimariyi çıkar
3. Gereksinimleri eşleştir
4. Kodla
5. Unit test
6. Integration test
7. Failure test
8. Regression test
9. Security check
10. State invariant check
11. Git diff incele
12. Sonraki faza geç

yapmalı.

Test geçmeden sonraki faza geçmemeli.


---

39. Son kabul testi

Sistem ancak aşağıdaki uçtan uca akış başarıyla çalışırsa tamamlanmış kabul edilecek:

BIST Universe
      ↓
Market Data
      ↓
Data Quality
      ↓
Features
      ↓
World State
      ↓
AI Intelligence
      ↓
Opportunity Discovery
      ↓
Decision
      ↓
Risk Gate
      ↓
Simulated Order
      ↓
Execution
      ↓
Fill
      ↓
Portfolio Ledger
      ↓
P&L
      ↓
Learning
      ↓
Audit
      ↓
Snapshot
      ↓
Restart
      ↓
Recovery
      ↓
SAME STATE

Ve aynı sistem:

duplicate event
invalid data
DB failure
Redis failure
LLM failure
execution failure
partial fill
restart
concurrent orders

durumlarında da güvenli davranmalı.

En önemli hedef

Ortaya çıkacak sistem bir “hisse tahmin botu” değil.

BIST'in tamamını izleyen, fırsat keşfeden, piyasa rejimini anlayan, AI destekli araştırma yapan, risk kontrollü karar üreten, gerçekçi sanal işlemler gerçekleştiren, sonuçlarını ölçen ve geçmiş kararlarını denetlenebilir şekilde saklayan bir AI yatırım araştırma/simülasyon terminali olacak.

Mimo Claw'ın görevi de bunu faz faz, test ederek ve mevcut sistemi bozmadan gerçekleştirmek.

Evet. Kalan kısmı da tamamlayalım. Önceki metnin devamı olarak aşağıdakileri Mimo Claw'a ver. Bu bölüm sistemi uygulanabilir teknik spesifikasyon seviyesine tamamlar.

MASTER SPEC — EK TEKNİK ŞARTNAME

FAZ 21 — SERVICE CONTRACTLARI

Her servis bağımsız çalışabilmeli ve açık contract'a sahip olmalı.

Ingestion

POST /internal/market-data
GET  /internal/market-data/{symbol}

Output:

symbol
timestamp
open
high
low
close
volume
bid
ask
source
quality

Universe

GET /api/universe
GET /api/universe/{symbol}
GET /api/sectors

Intelligence

GET /api/assets/{symbol}/analysis
GET /api/assets/{symbol}/signals
GET /api/assets/{symbol}/events

Opportunity

GET /api/opportunities
GET /api/opportunities/{symbol}

Decision

GET /api/decisions
GET /api/decisions/{decision_id}

Risk

GET /api/risk
GET /api/risk/portfolio
GET /api/risk/{decision_id}

Portfolio

GET /api/portfolio
GET /api/portfolio/positions
GET /api/portfolio/trades
GET /api/portfolio/pnl

Scenario

POST /api/scenarios
GET  /api/scenarios/{scenario_id}

Backtest

POST /api/backtests
GET  /api/backtests/{backtest_id}

---

FAZ 22 — DATABASE SCHEMA

PostgreSQL canonical persistence katmanı olacak.

Minimum tablolar:

assets
asset_prices
market_snapshots
fundamentals
fundamental_snapshots

events
event_consumers
event_dead_letters

features
world_states
regime_states

signals
decisions
risk_decisions

portfolios
positions
portfolio_ledger
orders
fills

scenarios
scenario_results

backtests
backtest_trades
backtest_metrics

model_versions
model_predictions
prediction_outcomes

audit_log
state_snapshots
system_health

Her ana entity

En az:

id
created_at
updated_at
version

taşımalı.

Financial transaction tablolarında mümkünse immutable kayıt yaklaşımı kullanılmalı.

---

FAZ 23 — DATABASE CONSTRAINTS

Database yalnızca uygulamaya güvenmemeli.

Örneğin:

quantity >= 0
price > 0
confidence >= 0
confidence <= 1
quality >= 0
quality <= 1

constraint'leri mümkün olduğunda DB seviyesinde de korunmalı.

Unique:

event_id
fill_id
broker_execution_id
order_external_id

için unique constraint kullanılmalı.

Foreign key'ler gerçek ilişkileri korumalı.

---

FAZ 24 — EVENT SCHEMAS

Event türleri açıkça tanımlanmalı.

Örneğin:

MARKET_TICK
MARKET_BAR
FUNDAMENTAL_UPDATE
NEWS_EVENT
MACRO_EVENT

FEATURE_UPDATE
WORLD_STATE_UPDATED
REGIME_CHANGED

SIGNAL_CREATED
DECISION_CREATED
RISK_APPROVED
RISK_REJECTED

ORDER_CREATED
ORDER_SUBMITTED
ORDER_ACCEPTED
ORDER_REJECTED

FILL_CREATED
ORDER_CANCELLED

POSITION_UPDATED
PORTFOLIO_UPDATED

PREDICTION_CREATED
PREDICTION_RESOLVED

RECOVERY_STARTED
RECOVERY_COMPLETED

Her event:

event_id
event_type
schema_version
timestamp
source
correlation_id
causation_id
entity_id
payload

içermeli.

---

FAZ 25 — EVENT STREAM

Event stream'ler domain'e göre ayrılmalı.

Örneğin:

market.events
fundamental.events
news.events
macro.events

feature.events
worldstate.events
signal.events
decision.events

risk.events
order.events
execution.events
portfolio.events

learning.events
system.events

Consumer group kullanılmalı.

Aynı event iki consumer tarafından yanlışlıkla iki kez uygulanmamalı.

---

FAZ 26 — AI MODEL MİMARİSİ

AI görevleri tek modele yüklenmemeli.

Önerilen routing:

Qwen3-Coder
→ code / technical agent tasks

DeepSeek-R1
→ deep reasoning / complex analysis

Gemma 3
→ lightweight classification / summarization

Ancak modellerin rolü config üzerinden değiştirilebilir olmalı.

Model registry:

model_id
provider
version
task
context_limit
temperature
status
created_at

tutmalı.

---

FAZ 27 — AI FALLBACK

LLM çalışmazsa bütün sistem durmamalı.

Örneğin:

Primary LLM
↓ failure
Secondary LLM
↓ failure
Rule-based fallback
↓ failure
NO_TRADE / DEGRADED

olmalı.

AI unavailable durumunda risk motoru bypass edilmemeli.

---

FAZ 28 — AI OUTPUT VALIDATION

LLM'den gelen JSON/schema doğrudan güvenilmemeli.

Pipeline:

LLM
↓
parse
↓
schema validation
↓
range validation
↓
source validation
↓
confidence validation
↓
domain validation
↓
accept/reject

LLM:

price = -500
confidence = 4.8

döndürürse reject edilmeli.

---

FAZ 29 — PROMPT VERSIONING

Her AI prediction:

model_version
prompt_version
input_hash
feature_version
timestamp

saklamalı.

Böylece:

«“Bu karar hangi prompt/model ile üretildi?”»

cevaplanabilmeli.

---

FAZ 30 — FEATURE VERSIONING

Feature hesaplamaları versioned olmalı.

Örneğin:

technical_features_v1
technical_features_v2
fundamental_features_v1
macro_features_v1

Backtest eski feature version'ı ile yeniden üretilebilmeli.

Live ile backtest arasındaki feature leakage engellenmeli.

---

FAZ 31 — NO LOOK-AHEAD BIAS

Backtest'te gelecekteki veri kesinlikle kullanılmamalı.

Örneğin:

2025-05-01 decision

hesaplanırken:

2025-05-02

verisi hiçbir şekilde erişilebilir olmamalı.

Fundamental data için:

publication timestamp kullanılmalı.

Sadece fiscal period kullanmak yeterli değil.

---

FAZ 32 — MARKET CALENDAR

Sistem:

- BIST trading hours,
- hafta sonları,
- resmi tatiller,
- half-day,
- suspension,
- trading halt

durumlarını bilmeli.

Market kapalıyken normal tick beklenmemeli.

---

FAZ 33 — DATA PROVIDER FAILOVER

Her veri tipi için provider priority:

Primary
↓
Secondary
↓
Cached
↓
Unavailable

şeklinde olmalı.

Provider failure:

system crash

olmamalı.

Ancak kritik veri yoksa:

NO_TRADE

olabilir.

---

FAZ 34 — RATE LIMIT

Her external provider için:

timeout
retry
backoff
rate_limit
circuit_breaker

uygula.

Retry exponential backoff kullanmalı.

Örneğin:

1s
2s
4s
8s

gibi.

Sonsuz retry yok.

---

FAZ 35 — CIRCUIT BREAKER

Provider sürekli hata veriyorsa:

CLOSED
→ OPEN
→ HALF_OPEN
→ CLOSED

state machine kullanılmalı.

Bu mekanizma:

- market provider,
- news provider,
- LLM provider,
- broker simulator

için kullanılabilir.

---

FAZ 36 — API SECURITY

API:

- authentication,
- authorization,
- rate limiting,
- input validation,
- request size limits,
- timeout

kullanmalı.

Admin endpointleri kullanıcı endpointlerinden ayrılmalı.

Internal servisler public internetten erişilebilir olmamalı.

---

FAZ 37 — AUTHORIZATION

Roller:

VIEWER
ANALYST
OPERATOR
ADMIN
SYSTEM

olabilir.

Örneğin:

VIEWER
→ dashboard okuyabilir

ANALYST
→ scenario/backtest çalıştırabilir

OPERATOR
→ simulator kontrol edebilir

ADMIN
→ config/model yönetebilir

SYSTEM
→ internal event operations

---

FAZ 38 — WEBSOCKET / REAL-TIME

Dashboard gerçek zamanlı güncellenebilmeli.

Örneğin:

/ws/market
/ws/opportunities
/ws/portfolio
/ws/risk
/ws/system

olabilir.

Backend event → WebSocket update.

Frontend polling'e bağımlı olmamalı.

---

FAZ 39 — FRONTEND STATE

Frontend'de server state ile UI state ayrılmalı.

Server state:

- market,
- portfolio,
- risk,
- opportunities.

UI state:

- selected symbol,
- filters,
- tabs,
- chart range.

Server state cache/revalidation mekanizması kullanılmalı.

---

FAZ 40 — DASHBOARD UX

Ana navigation:

Overview
Markets
Opportunities
Research
Portfolio
Risk
Scenarios
Backtests
AI
Models
Events
System
Audit

olmalı.

Her ekran bağımsız route olmalı.

URL üzerinden doğrudan erişilebilir olmalı.

---

FAZ 41 — MARKET MAP

Heatmap:

sector
market cap
daily return
volume

gösterebilmeli.

Örneğin:

Banking
Industrial
Energy
Technology
Retail

ayrılmalı.

---

FAZ 42 — OPPORTUNITY RANKING

Opportunity ranking tek score'dan oluşmamalı.

Ayrı metrikler:

Opportunity Score
Risk Score
Confidence
Expected Return
Expected Loss
Liquidity Score
Regime Compatibility
Fundamental Score
Technical Score
Macro Score
Sentiment Score

gösterilmeli.

---

FAZ 43 — SCORE EXPLAINABILITY

Örneğin:

Opportunity Score: 87

yanında:

Technical       +18
Fundamental     +21
Macro           +14
Momentum        +16
Sentiment       +9
Risk            -7
Liquidity       +4

gibi decomposition göster.

Kullanıcı score'un nereden geldiğini görebilmeli.

---

FAZ 44 — RISK EXPLAINABILITY

Risk:

Risk Score: 72

ise:

Volatility       +18
Concentration    +15
Correlation      +12
Liquidity         +8
Drawdown          +7
Event Risk       +12

gibi açıklanmalı.

---

FAZ 45 — SCENARIO ENGINE

Scenario input generic olmalı.

Örneğin:

{
  "usdtry_change": 0.10,
  "interest_rate_change": 0.05,
  "bist_change": -0.10,
  "vix_change": 0.50
}

Scenario engine:

scenario
↓
macro shock
↓
sector response
↓
asset response
↓
portfolio response

üretmeli.

Sonuç:

expected_equity
expected_drawdown
sector_impacts
asset_impacts
risk_change

---

FAZ 46 — BACKTEST METRICS

Backtest sonucu:

Total Return
CAGR
Sharpe
Sortino
Calmar
Max Drawdown
Win Rate
Profit Factor
Average Win
Average Loss
Expectancy
Turnover
Fees
Slippage
Exposure

hesaplanmalı.

Ayrıca benchmark:

BIST100

ile karşılaştırılmalı.

---

FAZ 47 — WALK-FORWARD TEST

Model/strategy yalnızca tek historical backtest ile değerlendirilmemeli.

Örneğin:

Train
→ Validate
→ Test
→ Move window
→ Repeat

walk-forward yapılmalı.

---

FAZ 48 — MODEL CALIBRATION

Prediction:

confidence = 90%

diyorsa gerçekleşme oranları gerçekten yaklaşık %90 civarında mı kontrol edilmeli.

Calibration curve / Brier score gibi metrikler kullanılabilir.

Overconfident model tespit edilmeli.

---

FAZ 49 — DRIFT DETECTION

Model zamanla bozulabilir.

İzlenecek:

feature drift
prediction drift
outcome drift
data distribution drift
regime drift

Drift aşırı yükselirse:

MODEL_DEGRADED

durumuna geç.

---

FAZ 50 — MODEL PROMOTION

Yeni model doğrudan production'a geçmemeli.

Pipeline:

TRAIN
↓
VALIDATE
↓
BACKTEST
↓
WALK-FORWARD
↓
PAPER TEST
↓
SHADOW
↓
PROMOTE

olmalı.

Rollback desteklenmeli.

---

FAZ 51 — SHADOW MODE

Yeni model eski modelle aynı veriyi görür ama gerçek karar sistemini değiştirmez.

Karşılaştır:

old_model
vs
new_model

Sonuçları ölç.

Yeni model ancak üstünlüğü kanıtlanırsa promote edilir.

---

FAZ 52 — AUDIT IMMUTABILITY

Audit kayıtları mümkün olduğunca immutable olmalı.

Bir karar sonradan sessizce değiştirilmemeli.

Correction gerekiyorsa:

old_record
+
correction_event

oluştur.

---

FAZ 53 — SYSTEM DEGRADATION MODES

Sistem sadece:

UP
DOWN

olmamalı.

Örneğin:

FULL
DEGRADED_DATA
DEGRADED_AI
DEGRADED_EVENT
DEGRADED_DATABASE
READ_ONLY
NO_TRADE
RECOVERY

durumları olabilir.

Örneğin LLM yoksa:

DEGRADED_AI

ama market monitoring devam edebilir.

Risk sistemi yoksa:

NO_TRADE

olmalı.

---

FAZ 54 — HEALTH CHECK

Her servis:

/live
/ready
/health

endpointlerine sahip olabilir.

Health:

database
redis
event bus
providers
model
worker

durumlarını kontrol etmeli.

---

FAZ 55 — METRICS

Prometheus/OpenTelemetry uyumlu metric sistemi kurulabilir.

Minimum:

events_total
events_failed_total
events_duplicate_total
data_quality_failures_total

llm_requests_total
llm_failures_total
llm_latency

decisions_total
risk_rejections_total

orders_total
fills_total

portfolio_equity
portfolio_drawdown

provider_errors
recovery_failures

---

FAZ 56 — ALERTING

Critical:

database failure
event loss
portfolio inconsistency
recovery failure
risk engine failure
unexpected negative cash
duplicate fills

alert üretmeli.

---

FAZ 57 — LOGGING

JSON structured logs:

{
  "timestamp": "...",
  "level": "ERROR",
  "service": "risk",
  "event_id": "...",
  "correlation_id": "...",
  "message": "Risk check failed"
}

kullan.

Secret loglama.

---

FAZ 58 — DOCKER

Her servis:

- deterministic build,
- healthcheck,
- non-root user,
- environment-based configuration,
- graceful shutdown

desteklemeli.

Development ve production compose ayrılmalı.

---

FAZ 59 — MIGRATIONS

DB schema değişiklikleri migration üzerinden yapılmalı.

Elle production DB değiştirme.

Migration:

up
down
version

kontrolüne sahip olmalı.

Destructive migration dikkatle uygulanmalı.

---

FAZ 60 — CI/CD

Her commit:

lint
typecheck
unit tests
integration tests
security scan
build

çalıştırmalı.

PR merge öncesi başarısız test varsa merge engellenmeli.

---

FAZ 61 — TYPESCRIPT

Frontend:

- strict TypeScript
- "any" yok
- API contract types
- runtime validation
- error boundaries

kullanmalı.

Backend Python ise:

- strict typing
- mypy/pyright
- Ruff
- Pydantic

kullanılabilir.

---

FAZ 62 — ERROR HANDLING

Generic:

except Exception:
    pass

kullanma.

Her hata:

expected
recoverable
retryable
fatal

olarak sınıflandırılmalı.

---

FAZ 63 — TRANSACTION BOUNDARIES

Financial state değiştiren işlemler transaction içinde olmalı.

Özellikle:

fill
cash
position
ledger
P&L

tek atomic operation olmalı.

---

FAZ 64 — IDEMPOTENCY KEY

Her mutating request:

idempotency_key

alabilmeli.

Aynı request tekrar gelirse:

same result

döndürülmeli.

---

FAZ 65 — TIME STANDARD

Tüm backend timestamp'leri:

UTC + timezone-aware

olmalı.

Frontend kullanıcı timezone'una çevirebilir.

Naive datetime kullanma.

---

FAZ 66 — MONEY STANDARD

Para hesaplarında floating point kritik financial calculation için kullanılmamalı.

Uygun:

Decimal

veya DB numeric.

Currency explicit:

TRY
USD
EUR

olmalı.

---

FAZ 67 — NUMERIC PRECISION

Quantity ve price precision asset bazlı tanımlanmalı.

Örneğin:

price_precision
quantity_precision
tick_size
lot_size

tutulmalı.

---

FAZ 68 — MARKET MICROSTRUCTURE

Simülasyonda:

spread
slippage
liquidity
order size
volume participation

dikkate alınmalı.

100 TL'lik emir ile 10 milyon TL'lik emir aynı şekilde execute edilmemeli.

---

FAZ 69 — PORTFOLIO RECONCILIATION

Periyodik:

ledger
vs
positions
vs
cash
vs
equity

karşılaştır.

Fark varsa:

RECONCILIATION_FAILURE

üret.

Sessizce düzeltme.

---

FAZ 70 — FINAL ACCEPTANCE

Sistem tamamlandı kabul edilmesi için:

Data

800+ asset scan
✓

Quality

invalid/stale/duplicate detection
✓

Intelligence

AI + deterministic features
✓

Decision

LONG / SHORT / HOLD / NO_TRADE
✓

Risk

hard veto
✓

Simulation

order → execution → fill
✓

Portfolio

ledger → position → P&L
✓

Learning

prediction → outcome → evaluation
✓

Recovery

restart → replay → same state
✓

Audit

decision → evidence → order → fill
✓

Testing

unit
integration
e2e
failure
replay
concurrency
regression
✓

---

MIMO CLAW İÇİN SON TALİMAT

Bu sistemi tek seferde baştan yazma.

Mevcut repository'yi önce analiz et.

Her fazı mevcut kodla eşleştir.

Mevcut çalışan parçaları mümkün olduğunca koru.

Bir servis zaten doğru implement edilmişse yeniden yazma.

Eksik olanı tamamla.

Hatalı olanı düzelt.

Çakışan iki implementation varsa tek canonical implementation bırak.

Duplicate business logic bırakma.

Her domain için tek source of truth oluştur.

Her faz sonunda:

FILES CHANGED
BUGS FIXED
ARCHITECTURAL CHANGES
TESTS ADDED
TEST RESULTS
REMAINING RISKS

raporu ver.

Test geçmeden sonraki faza geçme.

Final hedef:

«BIST evrenini sürekli tarayan, veri kalitesini denetleyen, piyasa rejimini çıkaran, teknik/fundamental/makro/haber/AI evidence'larını birleştiren, fırsatları risk-adjusted şekilde sıralayan, hard risk gate üzerinden karar veren, gerçekçi sanal emir ve portföy simülasyonu yapan, sonuçlarını öğrenme sistemiyle değerlendiren, tamamen audit edilebilir ve restart sonrası deterministik şekilde recovery yapabilen production-grade AI yatırım araştırma ve simülasyon platformu.»

Evet. O zaman hisse bulma motorunu ayrı tutup, sistemin geri kalan bütün zeka ve analiz katmanlarını ayrı bir master bölüm olarak tanımlayalım.

Aşağıdaki bölüm, önceki spesifikasyona eklenmek üzere hazırlanmıştır.

AI YATIRIM SİSTEMİ

Hisse Keşfi Dışındaki Tüm Analiz, Tahmin, Risk ve Zeka Sistemleri

«NOT: Hisse keşif/ranking motoru bu dokümanın dışında tutulur. Bu doküman, aday bir varlık sisteme girdikten SONRA onun hakkında çalışan bütün analiz ve karar destek sistemini tanımlar.»

---

1. MASTER ANALYSIS PIPELINE

Bir varlık aday olarak sisteme girdikten sonra:

ASSET
 ↓
DATA VALIDATION
 ↓
MARKET CONTEXT
 ↓
FUNDAMENTAL ANALYSIS
 ↓
TECHNICAL ANALYSIS
 ↓
PRICE ACTION
 ↓
VOLUME ANALYSIS
 ↓
VOLATILITY ANALYSIS
 ↓
MACRO ANALYSIS
 ↓
SECTOR ANALYSIS
 ↓
NEWS ANALYSIS
 ↓
KAP ANALYSIS
 ↓
SOCIAL SENTIMENT
 ↓
EVENT ANALYSIS
 ↓
CATALYST ANALYSIS
 ↓
CORRELATION ANALYSIS
 ↓
ANOMALY DETECTION
 ↓
REGIME ANALYSIS
 ↓
FORECASTING
 ↓
PROBABILITY ENGINE
 ↓
MONTE CARLO
 ↓
VALUATION
 ↓
RISK ENGINE
 ↓
SCENARIO ENGINE
 ↓
STRESS TEST
 ↓
PORTFOLIO IMPACT
 ↓
AI SYNTHESIS
 ↓
CONFIDENCE
 ↓
DECISION SUPPORT

Hiçbir tek modül tek başına yatırım kararı vermez.

---

2. DATA VALIDATION ENGINE

Analiz başlamadan önce tüm veriler kontrol edilir.

Kontroller:

missing
stale
duplicate
outlier
timestamp
source reliability
cross-source consistency

Örneğin fiyat kaynağı A:

100.20

kaynak B:

100.25

ise normal fark kabul edilebilir.

Ama:

100.20
vs
145.80

ise veri anomalisi olarak işaretlenir.

Veri kalitesi düşükse model confidence düşürülür.

---

3. FUNDAMENTAL ANALYSIS ENGINE

Şirketin ekonomik ve finansal yapısını analiz eder.

Gelir

Revenue
Revenue Growth
Revenue CAGR
Organic Growth

Kârlılık

Gross Margin
EBIT Margin
EBITDA Margin
Net Margin
ROE
ROA
ROIC

Bilanço

Cash
Debt
Net Debt
Working Capital
Current Ratio
Debt/Equity
Net Debt/EBITDA

Nakit

Operating Cash Flow
Free Cash Flow
FCF Margin
FCF Yield
Cash Conversion

Büyüme kalitesi

Sadece büyüme miktarı değil:

growth
+
margin
+
cash flow
+
debt

birlikte değerlendirilir.

---

4. FUNDAMENTAL TREND ENGINE

Tek bir bilanço yerine zaman serisini analiz eder.

Örneğin:

Revenue:
+12%
+18%
+24%

→ accelerating growth.

Ama:

Revenue:
+25%
+15%
+5%

→ growth deceleration.

Aynı işlem:

- margin
- EPS
- FCF
- debt
- ROIC

için yapılır.

---

5. EARNINGS QUALITY ENGINE

Kârın kalitesini ölçer.

Örneğin:

Net Income ↑
Cash Flow ↓

varsa uyarı.

Ayrıca:

receivables growth
inventory growth
cash flow conversion
one-off gains

incelenir.

Amaç:

«Muhasebe kârı ile ekonomik kâr arasındaki farkı yakalamak.»

---

6. VALUATION ENGINE

Bir şirketin yalnızca ucuz/pahalı olduğunu değil, farklı yöntemlerle değerini tahmin eder.

Multiples

P/E
P/B
EV/EBITDA
EV/EBIT
EV/Sales
FCF Yield
Dividend Yield

Peer comparison

Şirket:

vs sector median
vs sector average
vs historical own valuation

karşılaştırılır.

---

7. DCF ENGINE

Uygun şirketlerde:

Revenue
Margins
Taxes
Capex
Working Capital
FCF
WACC
Terminal Growth

kullanılarak DCF yapılır.

Sonuç:

Intrinsic Value
Current Price
Upside
Downside

olur.

Tek bir DCF sonucu kullanılmaz.

Varsayımlar senaryo halinde tutulur.

---

8. VALUATION SCENARIOS

En az:

Bear
Base
Bull

senaryosu.

Örneğin:

Bear → intrinsic value 85
Base → 110
Bull → 145

Mevcut fiyat:

100

ise sistem sadece:

«“%10 upside”»

demez.

Olasılık ağırlıklı sonuç üretir.

---

9. TECHNICAL ANALYSIS ENGINE

Teknik göstergeler ayrı ayrı hesaplanır.

Trend

SMA20
SMA50
SMA100
SMA200
EMA20
EMA50
EMA200

Momentum

RSI
MACD
ROC
Momentum
Stochastic

Volatility

ATR
Bollinger Band Width
Historical Volatility
Realized Volatility

Trend strength

ADX
Directional Movement

---

10. PRICE ACTION ENGINE

İndikatörlerden bağımsız olarak:

higher high
higher low
lower high
lower low
breakout
breakdown
retest
reversal
consolidation
gap

tespit edilir.

Candlestick pattern'leri yardımcı sinyal olarak kullanılabilir.

---

11. SUPPORT / RESISTANCE ENGINE

Destek ve direnç:

historical price
volume profile
swing points
moving averages
previous highs/lows

kullanılarak çıkarılır.

Her seviye için:

strength
touch_count
recency
volume

hesaplanabilir.

---

12. VOLUME ENGINE

Fiyat hareketinin hacim tarafından desteklenip desteklenmediğini ölçer.

Örneğin:

Price ↑
Volume ↑

→ confirmation.

Ama:

Price ↑
Volume ↓

→ weaker confirmation.

Ayrıca:

volume spike
relative volume
volume acceleration
OBV

hesaplanır.

---

13. VOLATILITY ENGINE

Volatiliteyi tek sayı olarak görmez.

Hesaplar:

realized volatility
historical volatility
ATR
downside volatility
upside volatility
volatility regime
volatility expansion
volatility contraction

Volatility expansion tespit edilirse risk motoruna event gönderilir.

---

14. MARKET MICROSTRUCTURE ENGINE

Veri destekliyorsa:

bid
ask
spread
depth
order imbalance
liquidity

analiz edilir.

Amaç:

«İşlem yapılabilir fiyat ile teorik fiyat arasındaki farkı anlamak.»

---

15. MACRO ENGINE

Şirketi piyasadan bağımsız değerlendirme.

Takip:

TCMB policy rate
inflation
USDTRY
EURTRY
US rates
VIX
gold
oil
global indices
credit conditions

---

16. MACRO SENSITIVITY ENGINE

Her şirket için:

USDTRY sensitivity
interest sensitivity
commodity sensitivity
global market sensitivity

tahmin edilir.

Örneğin:

USDTRY +10%

senaryosunda şirketin:

revenue
cost
margin
debt
valuation

üzerindeki etkisi hesaplanır.

---

17. SECTOR ENGINE

Şirketin bulunduğu sektör analiz edilir.

Ölç:

sector momentum
sector valuation
sector earnings growth
sector relative strength
sector volatility
sector fund flow

Şirketin sektöre göre performansı:

stock return - sector return

gibi relative metrics ile izlenir.

---

18. RELATIVE STRENGTH ENGINE

Varlığı:

BIST100
sector
peer group
global benchmark

ile karşılaştır.

Örneğin:

Stock +15%
BIST +5%
Sector +7%

→ strong relative performance.

---

19. NEWS ENGINE

Haberler:

source
timestamp
company
sector
topic
sentiment
importance
novelty
credibility

ile işlenir.

Haber sadece:

positive / negative

olarak sınıflandırılmaz.

---

20. NEWS IMPACT ENGINE

Her haber için:

impact direction
impact magnitude
confidence
time horizon

çıkarılır.

Örneğin:

New contract

→ positive.

Ama sözleşmenin şirket gelirine etkisi küçükse:

impact = LOW

olabilir.

---

21. KAP ANALYSIS ENGINE

KAP açıklamaları özel önceliğe sahip olur.

Kategoriler:

financial results
capital increase
buyback
dividend
merger
acquisition
contract
investment
management change
legal
regulatory
guidance

Analiz edilir.

---

22. NEWS DUPLICATION ENGINE

Aynı haber:

Reuters
Bloomberg
local media
social media

tarafından tekrar tekrar paylaşılmış olabilir.

Bunları tek event altında birleştir.

Ama kaynakların güvenilirlik bilgilerini kaybetme.

---

23. SOCIAL SENTIMENT ENGINE

Desteklenen sosyal kaynaklardan:

post volume
sentiment
engagement
author reliability
topic
trend

çıkarılır.

---

24. SOCIAL MANIPULATION ENGINE

Sosyal medya sinyali doğrudan güvenilir kabul edilmez.

Tespit:

bot-like activity
spam
duplicate posts
coordinated posting
sudden artificial volume
low-quality accounts

yüksekse sentiment confidence düşürülür.

---

25. SENTIMENT MOMENTUM

Sentiment'in yalnızca seviyesi değil değişimi izlenir.

Örneğin:

Positive sentiment:
20 → 30 → 45 → 70

→ accelerating sentiment.

Ama:

80 → 70 → 55

→ sentiment deterioration.

---

26. EVENT ENGINE

Olayları tek tek değil zaman çizelgesi olarak takip eder.

Örneğin:

KAP
↓
News
↓
Social
↓
Price
↓
Volume

arasındaki ilişki incelenir.

---

27. CATALYST ENGINE

Yaklaşan olayları izler:

earnings
dividend
general assembly
contract
product launch
regulatory decision
central bank
macro data

Her catalyst:

date
importance
expected impact
uncertainty

taşır.

---

28. EVENT DECAY ENGINE

Bir haberin etkisi zamanla azalabilir.

Örneğin:

Day 0 → 100%
Day 1 → 70%
Day 2 → 45%
Day 5 → 15%

Bu değerler sabit olmak zorunda değildir; event türüne göre öğrenilebilir.

---

29. CORRELATION ENGINE

Hisse ile:

other stocks
sector
BIST
USDTRY
gold
oil
VIX
rates

arasındaki korelasyon hesaplanır.

Rolling correlation kullanılmalı.

---

30. ANOMALY ENGINE

Olağandışı durumları yakalar:

price anomaly
volume anomaly
volatility anomaly
news anomaly
sentiment anomaly
fundamental anomaly

Örneğin:

Normal volume: 1M
Current volume: 12M

→ volume anomaly.

---

31. REGIME ENGINE

Piyasanın mevcut rejimini belirler:

BULL
BEAR
SIDEWAYS
HIGH_VOL
LOW_VOL
RISK_ON
RISK_OFF
CRISIS
RECOVERY

Aynı teknik sinyal farklı rejimlerde farklı anlam taşıyabilir.

---

32. SIGNAL FUSION ENGINE

Bütün modüllerin sonuçları burada birleştirilir.

Örneğin:

Technical       +18
Fundamental     +22
Macro           +12
News            +8
Social          +4
Relative        +9
Valuation       +15
Risk            -10

Ancak basit toplama zorunlu değildir.

Ağırlıklar:

market regime
asset type
time horizon
data confidence

ile değişebilir.

---

33. PROBABILITY ENGINE

Sistem:

«“Fiyat kesin yükselecek.”»

demez.

Örneğin:

P(+10% within 20d) = 61%
P(+5% within 20d)  = 73%
P(-5% within 20d)  = 24%
P(-10% within 20d) = 9%

gibi olasılık dağılımları üretir.

---

34. FORECASTING ENGINE

Farklı zaman horizonları:

intraday
1 day
5 day
20 day
60 day
120 day

olarak ayrılabilir.

Her horizon ayrı prediction olarak tutulur.

---

35. ENSEMBLE FORECASTING

Tek model yerine:

technical model
statistical model
time-series model
ML model
LLM analysis
Monte Carlo

sonuçları karşılaştırılabilir.

Modellerin geçmiş performanslarına göre ensemble weighting yapılabilir.

---

36. MONTE CARLO ENGINE

Monte Carlo, tek bir fiyat tahmini üretmek için kullanılmaz.

Binlerce olası gelecek yol simüle edilir.

Örneğin:

Current Price = P
Expected Return = μ
Volatility = σ
Horizon = T

ile çok sayıda fiyat path'i oluşturulur.

Sonuç:

P10
P25
P50
P75
P90

gibi dağılımlar olur.

---

37. MONTE CARLO OUTPUT

Örneğin:

20 gün sonra:

P10 = 82
P25 = 91
P50 = 104
P75 = 119
P90 = 134

Sistem böylece:

downside probability
upside probability
expected value
tail risk

hesaplayabilir.

---

38. MONTE CARLO PORTFOLIO

Tek hisse değil bütün portföy simüle edilebilir.

Correlation matrix kullanılarak:

10,000 portfolio paths

oluşturulur.

Sonuç:

expected return
VaR
CVaR
max drawdown distribution
probability of loss

olur.

---

39. RISK ENGINE

Risk kategorileri:

market risk
volatility risk
liquidity risk
concentration risk
correlation risk
event risk
macro risk
tail risk
model risk
data risk

ayrı hesaplanır.

---

40. VaR / CVaR

Portfolio için:

VaR 95%
VaR 99%
CVaR 95%
CVaR 99%

hesaplanabilir.

CVaR özellikle tail loss'u anlamak için kullanılır.

---

41. DRAWDOWN ENGINE

Takip:

peak equity
current equity
drawdown
max drawdown
drawdown duration
recovery time

yapılır.

---

42. POSITION RISK ENGINE

Her pozisyon için:

position value
portfolio weight
volatility contribution
VaR contribution
sector contribution
correlation contribution

hesaplanır.

---

43. PORTFOLIO OPTIMIZATION

Amaç yalnızca maksimum getiri değildir.

Optimize edilebilecek hedefler:

risk-adjusted return
minimum volatility
maximum Sharpe
maximum diversification
drawdown constraint
sector constraint
position constraint

---

44. SCENARIO ENGINE

Kullanıcı:

USDTRY +10%
BIST -15%
VIX +50%
TCMB +500bp

girdiğinde bütün analiz zinciri yeniden çalıştırılır.

Sonuç:

portfolio impact
asset impact
sector impact
risk change
drawdown estimate

---

45. STRESS TEST ENGINE

Extreme senaryolar:

2008-style crisis
2020-style shock
BIST crash
currency shock
rate shock
liquidity shock

gibi tarihsel veya sentetik senaryolarla test edilir.

---

46. MODEL RISK ENGINE

Modelin kendisinin yanılma ihtimali ölçülür.

Örneğin:

prediction confidence = 90%
model reliability = 62%

ise nihai confidence doğrudan %90 olamaz.

Model reliability confidence'ı sınırlar.

---

47. DATA CONFIDENCE ENGINE

Sonuç:

Confidence = 88%

ise bu:

data quality
+
model reliability
+
source reliability
+
agreement

ile hesaplanmalı.

Veri kalitesi düşerse confidence düşmeli.

---

48. AI SYNTHESIS ENGINE

Son aşamada AI bütün sonuçları okur:

technical
fundamental
macro
news
social
valuation
forecast
Monte Carlo
risk
scenario

ve insan tarafından okunabilir araştırma raporu üretir.

Ama AI:

- ham veriyi değiştiremez,
- metrikleri uyduramaz,
- risk veto'sunu geçemez,
- olmayan haberi kaynak gösteremez.

---

49. EXPLAINABILITY ENGINE

Her sonuç için:

WHY?
WHY NOT?
WHAT CHANGED?
WHAT COULD INVALIDATE THIS?
WHAT IS THE MAIN RISK?
WHAT IS THE MAIN CATALYST?

sorularına cevap üretilir.

---

50. DECISION SUPPORT

Nihai çıktı örneği:

ASSET: XYZ

Overall View:
POSITIVE

Confidence:
78%

Expected Return:
+11.4%

Risk:
MEDIUM

Monte Carlo:
P(+10%) = 57%

Valuation:
+18% upside

Technical:
Positive

Fundamental:
Strong

Macro:
Neutral

News:
Positive

Social:
Moderately Positive

Main Catalyst:
Earnings

Main Risk:
Currency sensitivity

Invalidation:
Price < X
Fundamental deterioration
Regime change

Bu çıktı yatırım tavsiyesi olarak değil, sistemin bütün analizlerinin birleşmiş araştırma sonucu olarak saklanır.

---

51. PREDICTION OUTCOME ENGINE

Her tahmin daha sonra gerçekle karşılaştırılır.

Örneğin:

Prediction:
+10% / 20 days

Actual:
+7.2%

kaydedilir.

Sonra:

prediction error
model error
regime
features

analiz edilir.

---

52. LEARNING ENGINE

Sistem şunu öğrenmeye çalışır:

hangi sinyal?
hangi regime?
hangi sektör?
hangi horizon?
hangi model?

hangi koşullarda başarılı.

Örneğin:

RSI breakout
+ high volume
+ bull regime

başarılı olabilirken:

RSI breakout
+ bear regime

başarısız olabilir.

---

53. DRIFT ENGINE

Zaman içinde:

feature distribution
prediction distribution
sentiment distribution
market regime
model performance

değişirse drift tespit edilir.

---

54. MODEL COMPARISON

Her model:

accuracy
calibration
Sharpe contribution
false positives
false negatives
regime performance

ile karşılaştırılır.

---

55. RESEARCH MEMORY

Sistem geçmiş araştırmaları saklar.

Örneğin:

2026-08-01:
Bullish

2026-08-05:
Neutral

2026-08-10:
Bearish

ve neden değiştiğini gösterir.

---

56. DECISION TIMELINE

Bir varlık için:

News
 ↓
Sentiment
 ↓
Technical
 ↓
Fundamental
 ↓
Prediction
 ↓
Monte Carlo
 ↓
Risk
 ↓
Decision
 ↓
Outcome

zaman çizelgesi gösterilir.

---

57. SELF-CHECK ENGINE

Nihai analizden önce sistem kendi sonucunu sorgular:

Is data stale?
Are sources conflicting?
Is confidence too high?
Is there look-ahead?
Is there an anomaly?
Is market regime changing?
Is model degraded?
Is risk underestimated?

Herhangi biri kritikse confidence düşürülür veya:

NO_TRADE

üretilir.

---

58. CONFLICT ENGINE

Örneğin:

Technical: BUY
Fundamental: SELL
News: BUY
Macro: SELL

ise sistem bunu gizlememeli.

Şunu göstermeli:

SIGNAL CONFLICT

ve hangi tarafın neden daha ağır bastığını açıklamalı.

---

59. FINAL RESEARCH OBJECT

Her varlık için bütün sistemlerin çıktısı tek bir canonical research object'te birleşmeli:

AssetResearch
 ├── data_quality
 ├── technical
 ├── price_action
 ├── volume
 ├── volatility
 ├── fundamental
 ├── valuation
 ├── macro
 ├── sector
 ├── relative_strength
 ├── news
 ├── kap
 ├── social
 ├── events
 ├── catalysts
 ├── correlations
 ├── anomalies
 ├── regime
 ├── forecasts
 ├── probabilities
 ├── monte_carlo
 ├── risk
 ├── scenarios
 ├── stress_tests
 ├── model_confidence
 ├── ai_synthesis
 └── audit

Bu object sistemin bütün diğer katmanları tarafından kullanılabilir.

---

60. EN ÖNEMLİ KURAL

Hiçbir sistem:

RSI → BUY
AI → BUY
News → BUY
Monte Carlo → BUY

şeklinde tek başına karar veremez.

Doğru mimari:

MULTIPLE INDEPENDENT EVIDENCE
          ↓
DATA QUALITY
          ↓
CONTEXT
          ↓
SIGNAL FUSION
          ↓
PROBABILITY
          ↓
MONTE CARLO
          ↓
RISK
          ↓
SCENARIO
          ↓
AI SYNTHESIS
          ↓
DECISION SUPPORT

şeklindedir.

Böylece sistem bir indikatör botu değil, çok katmanlı bir quant + fundamental + macro + event + sentiment + AI research platformu olur.

Hisse keşif motoru bunun üzerine ayrıca bağlanır ve yalnızca hangi varlıkların bu araştırma pipeline'ına gireceğini belirler.

Evet. Bunların tamamını da sistemin ana spesifikasyonuna ekleyecek şekilde tanımlıyorum. Böylece analitik motor + veri altyapısı + AI ajanları + hafıza + güvenlik + operasyon + recovery + governance birlikte tamamlanmış olacak.

AI YATIRIM PLATFORMU

Sistem Omurgası, AI Ajanları, Veri Altyapısı, Hafıza, Güvenlik ve Operasyon Master Spec

Bu doküman önceki:

- Hisse keşfi
- Teknik analiz
- Fundamental analiz
- Haber/KAP
- Sosyal medya
- Makro
- Değerleme
- Tahmin
- Monte Carlo
- Risk
- Portföy
- Backtest
- Scenario
- Learning

tanımlarının üzerine eklenir.

Amaç, sistemi sadece analiz yapan bir uygulama olmaktan çıkarıp uçtan uca çalışan, denetlenebilir, hatalara dayanıklı ve sürekli öğrenen AI yatırım araştırma/simülasyon platformu haline getirmektir.

---

1. DATA INGESTION SYSTEM

Sistemin dış dünyayla bağlantı katmanıdır.

Kaynaklar:

Market Data
Fundamentals
KAP
News
Social
Macro
Company Data
Economic Data

Her provider için adapter oluştur.

ProviderAdapter
 ├── authenticate()
 ├── fetch()
 ├── normalize()
 ├── validate()
 └── health_check()

Provider değişince domain kodu değişmemeli.

---

2. ETL / ELT PIPELINE

Veri:

FETCH
 ↓
RAW
 ↓
NORMALIZE
 ↓
VALIDATE
 ↓
ENRICH
 ↓
FEATURE
 ↓
STORE
 ↓
EVENT

şeklinde ilerler.

Raw data mümkün olduğunca korunmalı.

---

3. DATA QUALITY SYSTEM

Her veri kaydına:

quality_score
source
timestamp
freshness
validation_status

eklenir.

Durumlar:

VALID
STALE
INVALID
MISSING
DUPLICATE
SUSPICIOUS
CONFLICTED

---

4. DATA SOURCE RELIABILITY

Provider'ların güvenilirliği ayrıca ölçülür.

Örneğin:

Provider A: 98%
Provider B: 91%
Provider C: 76%

Bu değerler:

- hata oranı
- gecikme
- veri tutarlılığı
- missing data
- geçmiş doğruluk

üzerinden hesaplanabilir.

---

5. DATA RECONCILIATION

Aynı veri birden fazla kaynaktan geldiğinde:

Source A
Source B
Source C
 ↓
Reconciliation

yapılır.

Çelişki varsa:

CONFLICT

oluşturulur.

Sistem sessizce birini seçmemeli.

---

6. FEATURE STORE

Bütün hesaplanmış feature'ların canonical kaynağıdır.

Örneğin:

RSI
ATR
EMA
ROE
FCF Yield
Momentum
Volatility

burada tutulur.

Her feature:

feature_name
value
timestamp
asset
calculation_version
source_version

taşır.

---

7. FEATURE VERSIONING

Formül değişirse eski backtest bozulmamalı.

Örneğin:

RSI_v1
RSI_v2

ayrı tutulabilir.

---

8. REAL-TIME EVENT SYSTEM

Yeni veri geldiğinde ilgili sistemler otomatik tetiklenir.

Örneğin:

NEW_PRICE
 ↓
Technical Update
 ↓
Signal Update
 ↓
Risk Update

Yeni KAP:

NEW_KAP
 ↓
News Analysis
 ↓
Event Analysis
 ↓
Sentiment
 ↓
Forecast
 ↓
Risk

---

9. EVENT PRIORITY

Event'ler önem derecesine sahip olur:

CRITICAL
HIGH
NORMAL
LOW

Örneğin şirket iflas haberi:

CRITICAL

normal sosyal medya postu:

LOW

---

10. EVENT ORCHESTRATOR

Bütün pipeline'ı yönetir.

Görevi:

hangi job?
hangi sırada?
hangi paralel?
hangi dependency?
hangi retry?

belirlemek.

---

11. JOB QUEUE

Ağır işler queue'ya gönderilir:

AI analysis
Monte Carlo
Backtest
Scenario
Large universe scan
Feature recalculation

Web request'i bloklamamalı.

---

12. CACHE SYSTEM

Pahalı hesaplar cache'lenir.

Örneğin:

DCF
Monte Carlo
fundamental analysis
AI summary

aynı input hash ile tekrar gelirse gereksiz hesap yapılmaz.

Cache invalidation event-based olabilir.

---

13. KNOWLEDGE GRAPH

Sistem yalnızca tablo verisi kullanmamalı.

İlişkiler:

Company
 ↕
Sector
 ↕
Supplier
 ↕
Customer
 ↕
Product
 ↕
Person
 ↕
Event
 ↕
News
 ↕
Macro Event

şeklinde tutulabilir.

Örneğin:

«Petrol yükseldi.»

Sistem:

Oil
 ↓
Energy sector
 ↓
Company A
 ↓
Cost impact
 ↓
Margin impact

ilişkisini kurabilmeli.

---

14. RESEARCH MEMORY

Sistem geçmiş araştırmaları unutmamalı.

Her araştırma:

asset
date
thesis
evidence
risk
prediction
outcome
model
prompt

ile saklanır.

---

15. LONG-TERM MEMORY

Sistem zaman içinde:

company behavior
sector behavior
event behavior
model behavior

hakkında tarihsel hafıza oluşturur.

---

16. RESEARCH CONTEXT ENGINE

AI'ya bütün database'i göndermek yerine ilgili context oluşturulur.

Örneğin THYAO analizinde:

company data
recent news
recent KAP
sector
macro
technical
historical decisions

toplanır.

Sonra AI'ya verilir.

---

17. AI AGENT SYSTEM

Ajanlar görev bazlıdır.

Örneğin:

Research Agent
News Agent
Macro Agent
Fundamental Agent
Technical Agent
Risk Agent
Portfolio Agent
Scenario Agent
Backtest Agent
Audit Agent

Her agent kendi domain'inde çalışır.

---

18. AGENT ORCHESTRATOR

Ajanları yöneten üst katmandır.

Örneğin:

Research Request
 ↓
Technical Agent
Fundamental Agent
News Agent
Macro Agent
 ↓
Risk Agent
 ↓
Synthesis Agent

---

19. AGENT TOOL SYSTEM

Agent'ların erişebileceği araçlar açıkça sınırlandırılır.

Örneğin Research Agent:

read_market_data
read_news
read_fundamentals
run_analysis

Risk Agent:

read_portfolio
calculate_risk
approve/reject

Agent'ın ihtiyaç olmayan tool'a erişimi olmamalı.

---

20. AGENT MEMORY

Her agent:

current_context
task_history
tool_results

tutabilir.

Ama kritik state merkezi sistemde tutulmalı.

Agent memory canonical database yerine geçmemeli.

---

21. AGENT COMMUNICATION

Agent'lar birbirine doğrudan rastgele mesaj göndermemeli.

Canonical event/message formatı:

sender
receiver
task_id
correlation_id
payload
timestamp

olmalı.

---

22. AGENT LOOP CONTROL

Ajan:

analyze
→ analyze
→ analyze
→ analyze

şeklinde sonsuz döngüye girmemeli.

Her task:

max_steps
timeout
max_retries

sınırına sahip olmalı.

---

23. AGENT CONFIDENCE

Agent sonucu:

result
confidence
evidence
uncertainty

ile dönmeli.

Confidence uydurulmamalı.

Evidence ile desteklenmeli.

---

24. HUMAN-IN-THE-LOOP

Kritik işlemlerde insan onayı bulunabilir.

Örneğin:

LIVE EXECUTION
MODEL PROMOTION
RISK LIMIT CHANGE
SYSTEM CONFIG CHANGE

için approval gerekebilir.

---

25. NOTIFICATION SYSTEM

Bildirim kategorileri:

Opportunity
Risk
News
KAP
Regime
Portfolio
Model
System
Security

---

26. ALERT ENGINE

Örnek:

Portfolio drawdown > threshold

→ alert.

New critical KAP

→ alert.

Model degradation

→ alert.

---

27. PORTFOLIO ACCOUNTING

Portfolio yalnızca:

price × quantity

değildir.

Hesapla:

cash
fees
slippage
realized P&L
unrealized P&L
average cost
tax model if configured

---

28. ACCOUNTING LEDGER

Her financial state değişimi ledger event'i üretmeli.

Örneğin:

BUY
SELL
FEE
DIVIDEND
DEPOSIT
WITHDRAWAL
SPLIT

---

29. EXECUTION SIMULATOR

Emir:

CREATE
→ VALIDATE
→ RISK
→ EXECUTE
→ FILL

akışından geçer.

---

30. SLIPPAGE MODEL

Slippage:

volatility
spread
liquidity
order size
market condition

ile ilişkilendirilir.

---

31. PARTIAL FILL

Büyük emir tamamen dolmayabilir.

Örneğin:

Order = 10,000
Fill = 6,000
Remaining = 4,000

desteklenmeli.

---

32. RECONCILIATION ENGINE

Şunlar eşit/tutarlı olmalı:

Cash
+
Position Market Value
=
Equity

Ledger ile positions uyuşmalı.

Uyuşmazlık varsa işlem durdurulabilir.

---

33. EXPERIMENT SYSTEM

Her strateji deney olarak kaydedilir:

experiment_id
strategy
parameters
dataset
feature_version
model_version
result

---

34. A/B TEST SYSTEM

Örneğin:

Strategy A
vs
Strategy B

aynı historical period üzerinde karşılaştırılır.

---

35. RESEARCH LAB

Araştırmacı:

strategy
feature
model
threshold

değiştirip deney çalıştırabilir.

Production sistemi değiştirmez.

---

36. MODEL REGISTRY

Her model:

model_id
version
task
metrics
training_data
feature_version
status

ile kayıtlıdır.

Status:

EXPERIMENTAL
VALIDATED
SHADOW
PRODUCTION
RETIRED

---

37. MODEL LIFECYCLE

Model:

TRAIN
 ↓
VALIDATE
 ↓
BACKTEST
 ↓
WALK-FORWARD
 ↓
SHADOW
 ↓
PROMOTE
 ↓
MONITOR
 ↓
ROLLBACK / RETIRE

---

38. MODEL ROLLBACK

Yeni model kötüleşirse:

Model V5
↓ failure
Model V4

otomatik veya approval sonrası geri alınabilir.

---

39. RESEARCH LINEAGE

Bir prediction'ın kaynağı takip edilebilmeli:

Prediction
 ↓
Model
 ↓
Prompt
 ↓
Features
 ↓
Normalized Data
 ↓
Raw Data
 ↓
Provider

---

40. DATA LINEAGE

Her feature için:

raw source
→ transformation
→ feature
→ model
→ prediction

zinciri tutulmalı.

---

41. AUDIT SYSTEM

Audit kayıtları:

WHO
WHAT
WHEN
WHY
INPUT
OUTPUT
VERSION

bilgilerini içermeli.

---

42. SECURITY SYSTEM

Secret'lar:

API keys
DB passwords
JWT secrets
provider credentials

kod içine yazılmamalı.

Environment/secret manager kullanılmalı.

---

43. AUTHENTICATION

Kullanıcı login sistemi.

Session/token güvenliği.

Password hashing.

Token expiration.

---

44. AUTHORIZATION

Permission matrix:

READ_MARKET
READ_PORTFOLIO
RUN_BACKTEST
RUN_SCENARIO
CHANGE_CONFIG
PROMOTE_MODEL
LIVE_EXECUTION

ayrı izinler olabilir.

---

45. NETWORK SECURITY

Public internetten:

database
redis
event bus
internal services

doğrudan erişilememeli.

---

46. SECRET REDACTION

Loglarda:

API key
password
token
secret

asla görünmemeli.

---

47. OBSERVABILITY

Üç temel katman:

Logs
Metrics
Traces

---

48. DISTRIBUTED TRACING

Bir kullanıcı isteği:

API
→ Orchestrator
→ Agent
→ Feature
→ Risk
→ Portfolio

şeklinde ilerliyorsa aynı "correlation_id" korunmalı.

---

49. PERFORMANCE MONITORING

Ölç:

API latency
AI latency
database latency
event latency
queue latency
Monte Carlo duration
backtest duration

---

50. COST MONITORING

AI/API maliyetleri:

tokens
requests
provider
model
cost

bazında takip edilir.

Böylece:

«“Bu sistem bugün neden 20$ harcadı?”»

cevaplanabilir.

---

51. RESOURCE MANAGEMENT

CPU/GPU/RAM kullanımı izlenir.

Ağır işler:

Monte Carlo
Backtest
LLM inference
large scans

resource-aware queue'ya alınabilir.

---

52. CONFIGURATION SYSTEM

Threshold'lar kod içine gömülmemeli.

Örneğin:

RSI threshold
risk limit
position limit
model weight
alert threshold

config üzerinden yönetilmeli.

---

53. CONFIG VERSIONING

Her configuration değişikliği:

old
new
who
when
reason

şeklinde kaydedilmeli.

---

54. SNAPSHOT SYSTEM

Periyodik sistem snapshot:

portfolio
positions
cash
decisions
model versions
config version
world state

saklanır.

---

55. DISASTER RECOVERY

Felaket durumunda:

backup
+
snapshot
+
event log

kullanılarak sistem geri getirilebilir.

---

56. EVENT REPLAY

Belirli timestamp'ten itibaren eventler yeniden oynatılabilir.

Amaç:

- bug reproduction
- recovery
- backtest
- debugging

---

57. DETERMINISTIC RECOVERY

Recovery sonrası:

positions
cash
ledger
equity

aynı sonucu üretmeli.

---

58. FAILURE INJECTION

Test ortamında bilerek:

DB down
Redis down
LLM down
Provider down
Network timeout
Duplicate event
Corrupted data
Partial fill

oluştur.

Sistemin nasıl davrandığını doğrula.

---

59. CHAOS TESTING

Bir servisin kapanması diğer sistemi tamamen çökertmemeli.

Örneğin:

News provider DOWN

iken:

Market monitoring
Technical analysis
Portfolio

çalışmaya devam edebilir.

Ancak confidence düşebilir.

---

60. SAFETY GOVERNANCE

Kesin sınırlar:

AI cannot bypass risk
Agent cannot change its own permissions
Agent cannot modify audit history
Model cannot self-promote
Data provider cannot directly create trades
News cannot directly create orders
Social sentiment cannot directly create orders

---

61. NO-TRADE GATE

Aşağıdaki durumlardan biri kritikse:

bad data
risk engine unavailable
portfolio inconsistent
model invalid
critical event uncertainty
system degraded

sistem:

NO_TRADE

durumuna geçebilir.

---

62. SYSTEM STATE MACHINE

Global state:

STARTING
 ↓
INITIALIZING
 ↓
READY
 ↓
DEGRADED
 ↓
RECOVERY
 ↓
READY

Critical failure:

FAILED

---

63. TESTING PYRAMID

Unit

Her hesaplama.

Integration

Servisler arası iletişim.

E2E

Gerçek pipeline.

Replay

Historical event replay.

Failure

Provider/DB/LLM failure.

Concurrency

Aynı anda event/order işlemleri.

Regression

Eski davranışların bozulmaması.

Security

Unauthorized access.

---

64. GOLDEN DATASETS

Sistem için değişmeyen test datasetleri oluştur.

Örneğin:

known market period
known news
known fundamentals
known outcomes

Yeni kod bunlarla test edilir.

---

65. GOLDEN DECISIONS

Bazı senaryolarda beklenen sonuçlar önceden belirlenebilir.

Örneğin:

critical data missing
→ NO_TRADE

Yeni sürüm farklı davranırsa regression failure.

---

66. CONTRACT TESTING

Servislerin API/event schema'ları değiştiğinde consumer'lar kırılmamalı.

Schema compatibility kontrolü yapılmalı.

---

67. VERSION COMPATIBILITY

Event:

schema_version = 2

ise consumer gerektiğinde V1/V2 uyumluluğunu yönetmeli.

---

68. GRACEFUL SHUTDOWN

Servis kapanırken:

stop accepting new jobs
finish safe jobs
flush events
persist state
close connections

yapmalı.

---

69. STARTUP RECOVERY

Startup:

load config
load snapshot
verify DB
verify event position
verify portfolio
resume consumers

şeklinde ilerlemeli.

---

70. FINAL SYSTEM MODEL

Bütün sistem artık:

                ┌───────────────┐
                │ DATA SOURCES  │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ DATA INGESTION│
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ DATA QUALITY  │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ FEATURE STORE │
                └───────┬───────┘
                        ↓
        ┌───────────────┴────────────────┐
        ↓                                ↓
 ANALYTICS ENGINE                  EVENT ENGINE
        ↓                                ↓
        └───────────────┬────────────────┘
                        ↓
                ┌───────────────┐
                │ WORLD STATE   │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ AI AGENTS     │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ SIGNAL FUSION │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ FORECAST      │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ MONTE CARLO   │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ RISK ENGINE   │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ SCENARIO      │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ DECISION      │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ SIMULATOR     │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ PORTFOLIO     │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ OUTCOME       │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ LEARNING      │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ MEMORY        │
                └───────┬───────┘
                        ↓
                ┌───────────────┐
                │ AUDIT         │
                └───────────────┘

       SECURITY / OBSERVABILITY / RECOVERY
             ↓        ↓        ↓
          ALL SYSTEM COMPONENTS

71. SYSTEM'S FUNDAMENTAL RULE

Sistemin hiçbir katmanı tek başına otorite değildir.

Doğru yaklaşım:

DATA
+
EVIDENCE
+
CONTEXT
+
MODELS
+
PROBABILITY
+
RISK
+
SCENARIO
+
AUDIT

birlikte değerlendirilir.

AI ise bunların üzerine çalışan zekâ katmanıdır; finansal güvenlik sınırlarının üzerinde değildir.

72. FINAL DEFINITION

Ortaya çıkan sistem:

«Veriyi toplayan, doğrulayan, anlamlandıran; teknik, fundamental, makro, haber, KAP, sosyal medya, event, değerleme ve istatistiksel analizleri birleştiren; farklı AI ajanlarıyla araştırma yapan; olasılıksal tahmin ve Monte Carlo simülasyonları gerçekleştiren; risk ve portföy etkisini hesaplayan; senaryo ve stres testleri uygulayan; sanal emirleri gerçekçi şekilde simüle eden; sonuçları geçmiş performansla karşılaştırarak modellerini değerlendiren; araştırma hafızası oluşturan; bütün kararların veri kaynağına kadar izlenebilmesini sağlayan; hata, veri kaybı, model arızası ve servis kesintilerinde güvenli moda geçebilen; recovery ve event replay destekli, production-grade AI yatırım araştırma ve portföy simülasyon platformudur.»

Bu tanımın dışındaki hiçbir AI ajanı, servis veya modül kendi başına yeni bir yatırım mantığı icat ederek sisteme eklenmemelidir. Yeni bir yetenek eklenirse önce bu mimaride hangi katmana ait olduğu belirlenmeli, contract'ı tanımlanmalı, testleri yazılmalı ve audit/recovery mekanizmasına dahil edilmelidir.

Tabii. Bunları kısa ama Mimo Claw'ın ne yapacağını anlayacağı netlikte özetleyelim:

Son Sistemler — Kısa Teknik Tanımlar

1. Multi-Market / Multi-Asset

Sistem sadece tek borsa veya hisseye bağlı olmamalı. BIST, ABD, Avrupa ve farklı varlık sınıfları aynı temel mimariyle desteklenmeli.

2. FX / Para Birimi

USD, EUR, TRY gibi farklı para birimlerini tanımalı. Portföy değerlerini seçilen ana para birimine çevirmeli ve kur riskini ayrıca hesaplamalı.

3. Trading Calendar

Her piyasanın işlem günlerini, tatillerini, açılış/kapanış saatlerini ve seanslarını bilmeli. Kapalı piyasada veri veya işlem üretmemeli.

4. Corporate Actions

Temettü, bölünme, bedelsiz, sermaye artırımı, birleşme gibi şirket olaylarını fiyat ve portföy geçmişine doğru şekilde yansıtmalı.

5. Survivorship Bias Protection

Geçmiş analizlerde bugün hâlâ var olan şirketleri kullanıp iflas eden/silinmiş şirketleri yok saymamalı.

6. Look-Ahead Bias Protection

Model geçmişte karar verirken gelecekte henüz bilinmeyen hiçbir veriyi kullanamamalı.

7. Point-in-Time Data

Her verinin o tarihte gerçekten bilinen versiyonu saklanmalı. Sonradan düzeltilmiş bilanço/veri geçmiş analize yanlışlıkla girmemeli.

8. Transaction Cost Model

Komisyon, spread, slippage, vergi ve diğer işlem maliyetlerini hesaba katmalı. Kârlılığı brüt değil gerçekçi net sonuçla ölçmeli.

9. Benchmark Engine

Performansı BIST100, sektör endeksi veya uygun benchmark ile karşılaştırmalı.

10. Performance Attribution

Portföy getirisi neden oluştuğunu açıklamalı:

Hisse seçimi
Sektör seçimi
Momentum
Value
Market exposure
FX

gibi katkıları ayırmalı.

11. Factor Engine

Value, Momentum, Quality, Size, Low Volatility gibi faktörleri hesaplamalı.

12. Factor Exposure

Portföyün hangi faktörlere ne kadar maruz kaldığını göstermeli. Örneğin portföy aşırı momentum ağırlıklıysa bunu belirtmeli.

13. Liquidity Analysis

Bir pozisyonun piyasayı ne kadar etkileyebileceğini hesaplamalı. Büyük pozisyonlarda kapasite ve çıkış riskini göstermeli.

14. Privacy / Data Retention

Kullanıcı verileri, portföy bilgileri ve hassas bilgiler güvenli tutulmalı. Hangi verinin ne kadar süre saklanacağı belirlenmeli.

15. Multi-Tenant Isolation

Birden fazla kullanıcı desteklenirse her kullanıcının:

portfolio
data
memory
settings
API keys

birbirinden tamamen izole olmalı.

16. Provider Rate Limit

Veri sağlayıcıların API limitlerini takip etmeli. Limit dolduğunda sistemi bozmak yerine queue/cache/fallback kullanmalı.

17. Idempotency

Aynı event iki kez gelirse işlem iki kez uygulanmamalı.

Örneğin aynı BUY event'i iki kere gelirse iki ayrı işlem oluşmamalı.

18. Distributed Locking

Aynı pozisyon veya veri üzerinde iki worker aynı anda çakışan işlem yapmamalı.

19. Circuit Breaker

Bir servis sürekli hata veriyorsa sistem sürekli tekrar denemek yerine servisi geçici olarak devre dışı bırakıp fallback kullanmalı.

20. Retry / Fallback

Geçici ağ veya provider hatalarında kontrollü retry yapılmalı. Alternatif kaynak varsa fallback kullanılmalı.

21. Database Versioning

Database şeması değişiklikleri migration sistemiyle yapılmalı. Eski veriler kaybolmamalı.

22. Disaster Recovery Testing

Backup'ın gerçekten geri yüklenebildiği düzenli olarak test edilmeli. Sadece backup almak yeterli değil.

23. Reproducibility

Geçmişteki bir analiz aynı:

data version
feature version
model version
config
prompt

ile tekrar çalıştırıldığında aynı sonucu mümkün olduğunca üretmeli.

24. Probability Calibration

Model %70 olasılık verdiğinde uzun vadede bu tahminlerin yaklaşık %70 oranında gerçekleşip gerçekleşmediği ölçülmeli.

25. Uncertainty Decomposition

Belirsizliğin nereden geldiği ayrılmalı:

Data uncertainty
Model uncertainty
Market uncertainty
Event uncertainty

26. Confidence Calibration

Sistem gereğinden fazla özgüvenli olmamalı. Çok belirsiz durumda confidence otomatik düşmeli.

27. Manipulation Detection

Fiyat, hacim, haber veya sosyal medyada manipülasyon ihtimali aranmalı. Şüpheli durumda sinyal güvenilirliği azaltılmalı.

28. AI Hallucination Protection

AI'nın uydurma:

haber
şirket bilgisi
istatistik
kaynak
finansal veri

üretmesi engellenmeli. AI yalnızca doğrulanmış verilere dayanmalı.

29. Citation Verification

AI bir haber/veri/kaynak kullandığında kaynağın gerçekten mevcut ve iddiayı destekliyor olduğu doğrulanmalı.

30. Decision Replay

Geçmişte verilen bir karar bugünkü bilgilerle değil, kararın verildiği andaki verilerle tekrar oluşturulabilmeli.

Örneğin:

«“10 Ağustos'ta neden BUY denmişti?”»

sorusuna sistem o günkü verilerle cevap verebilmeli.

31. Compliance / Audit Retention

Önemli işlemler ve kararlar uzun süre saklanmalı. Kim, ne zaman, hangi veri/model ile ne yaptı sorusu cevaplanabilmeli.

---

SON DURUM

Bütün sistemleri birlikte düşündüğümüzde platformun ana yapısı:

DATA
 ↓
DATA QUALITY
 ↓
FEATURES
 ↓
MARKET / FUNDAMENTAL / TECHNICAL / MACRO
 ↓
NEWS / KAP / SOCIAL / EVENTS
 ↓
VALUATION
 ↓
FORECAST
 ↓
MONTE CARLO
 ↓
RISK
 ↓
SCENARIO / STRESS TEST
 ↓
PORTFOLIO
 ↓
SIMULATION
 ↓
AI AGENTS
 ↓
DECISION SUPPORT
 ↓
EXECUTION SIMULATION
 ↓
OUTCOME
 ↓
LEARNING
 ↓
MEMORY
 ↓
AUDIT

Bunun çevresinde de:

SECURITY
OBSERVABILITY
COST CONTROL
RECOVERY
VERSIONING
DATA LINEAGE
GOVERNANCE

bulunacak.

Bu seviyede sistem tanımı mimari açıdan tamamlanmış kabul edilebilir. Bundan sonraki aşama yeni sistem tanımlamak değil, bunları modüllere, servislerə, API'lere, database tablolarına ve implementasyon görevlerine bölmek olur.
