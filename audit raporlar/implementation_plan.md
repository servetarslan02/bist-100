# API & Entegrasyon Testi Düzeltme Planı

Tüm API uç noktalarını (237 adet) kapsayan otomatik entegrasyon testini tamamladım.
Test sonucunda: **150 Başarılı, 76 Atlanan (Parametrik/POST), 11 Hatalı** uç nokta tespit edildi. 

Bu 11 hatalı uç nokta sitenin portföy, strateji ve risk analiz sayfalarının çökmesine neden olmaktadır. Sorunların kaynağını tespit ettim ve aşağıda düzeltme planını sunuyorum.

## User Review Required

> [!IMPORTANT]
> Aşağıdaki değişiklikler FastAPI uç noktalarındaki 500 hatalarını (çökmeleri) ve zaman aşımı (timeout) sorunlarını giderecektir. Planı onaylarsanız düzeltmeleri hemen uygulayacağım.

## Hatalı Uç Noktalar ve Tespit Edilen Nedenler

**1. VirtualPortfolio Eksik Metotları (500 Internal Server Error)**
Etkilenen Uç Noktalar:
- `GET /api/v1/portfolio/position-history` (ve `/strategy/...`)
- `GET /api/v1/portfolio/equity-snapshots` (ve `/strategy/...`)
- `GET /api/v1/portfolio/tax` (ve `/strategy/...`)

*Neden:* `VirtualPortfolio` sınıfında `get_position_history`, `get_equity_snapshots` metotları ve `_commission_total` özelliği tanımlanmamış (veya stub bırakılmış). Bu yüzden endpointler çağrıldığında `AttributeError` fırlatıp çöküyor.

**2. Eksik Import Hatası (500 Internal Server Error)**
Etkilenen Uç Noktalar:
- `GET /api/v1/portfolio/tca` (ve `/strategy/...`)

*Neden:* `/app/services/portfolio/enhancements.py` içinden `tca_analyzer` modülü içe aktarılmaya çalışılıyor ancak böyle bir modül yok.

**3. Zaman Aşımı - Timeout (> 5 saniye)**
Etkilenen Uç Noktalar:
- `GET /api/v1/risk/portfolio`
- `GET /api/v1/risk/liquidity`
- `GET /api/v1/macro/indicators`

*Neden:* Bu uç noktalar harici bir API'ye bağlanmaya çalışıp yanıt alamıyor olabilir veya veritabanında çok ağır, indekslenmemiş bir sorgu çalıştırıyor olabilir.

## Proposed Changes

Aşağıdaki dosyaları güncelleyerek bu sorunları çözeceğim:

### `services/paper_trading/virtual_portfolio.py`

#### [MODIFY] `virtual_portfolio.py`
- `get_position_history(self)` metodu eklenecek (pozisyon geçmişini liste olarak dönecek).
- `get_equity_snapshots(self)` metodu eklenecek (zaman serisi olarak bakiye geçmişini dönecek).
- `__init__` içine `self._commission_total = 0.0` eklenecek ve işlem yapıldıkça güncellenecek.

### `services/portfolio/enhancements.py`

#### [MODIFY] `enhancements.py`
- `tca_analyzer` bağımlılığı ya mock'lanacak ya da sınıf içinde doğru implementasyonu oluşturularak export edilecek.

### `services/api/v1/risk.py` & `services/api/v1/macro.py`

#### [MODIFY] `risk.py`
#### [MODIFY] `macro.py`
- Timeout olan uç noktaların sorguları analiz edilecek. Gerekirse sorgulara asenkron timeout limitleri (ör. `asyncio.wait_for`) eklenecek ve harici servislere (ör. Yahoo Finance/TCMB) gidiliyorsa hata yönetimiyle (fallback data) 500/Timeout düşmesi engellenecek.

## Verification Plan

### Automated Tests
- Düzeltmelerden sonra `api_integration_tester.py` betiği tekrar çalıştırılacak.
- Hatalı olan 11 uç noktanın 200 OK yanıtı döndürdüğü teyit edilecek.

### Manual Verification
- Docker logları üzerinden API isteklerinin çökmediği (Traceback atmadığı) doğrulanacak.
