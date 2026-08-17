# ingestion/bist_universe

**Dosya:** `services/ingestion/bist_universe.py`
**Satır:** 309

## Açıklama

ALPHA BIST — BIST Universe v4.0 (Auto-Discovery)

TÜM BIST hisseleri + sektör bilgileri — OTOMATIK KEŞIF.
BIST 100, BIST 30, BIST 50, BIST TUM (tum hisseler).

v4.0 Degisiklikler:
- KAP + yfinance + Borsa Istanbul web'den otomatik hisse keşfi
- Endeks kompozisyonlari otomatik guncelleme
- Sektör haritasi otomatik eslestirme
- Cache + periyodik refresh

## Sınıflar (2)

- `TickerInfo`
- `BISTUniverse`

## Fonksiyonlar (15)

- `__init__()`
- `_refresh_dynamic()`
- `BIST_100_TICKERS()`
- `BIST_30_TICKERS()`
- `BIST_50_TICKERS()`
- `BIST_ALL_TICKERS()`
- `SECTOR_MAP()`
- `get_ticker_sector()`
- `get_tickers_by_sector()`
- `get_index_members()`
- `is_active()`
- `get_all_sectors()`
- `get_sector_stats()`
- `refresh()`
- `get_ticker_info()`

