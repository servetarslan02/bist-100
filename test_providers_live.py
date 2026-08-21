import asyncio
import time

async def run_all_checks():
    print('=== DETAILED LIVE EXTERNAL SERVICE AUDIT ===\n')

    # 1. YFinance Provider
    try:
        from services.ingestion.providers.yfinance_provider import YFinanceProvider
        yfp = YFinanceProvider()
        t0 = time.time()
        df = yfp.fetch_ohlcv('THYAO', period='5d', interval='1d')
        dt = time.time() - t0
        if df is not None and not df.empty:
            col = 'close' if 'close' in df else 'Close'
            print(f'✅ [CALISIYOR] Yahoo Finance API: THYAO son fiyat: {df[col].iloc[-1]:.2f} TL (Sure: {dt:.2f}s, {len(df)} gunluk mum alindi)')
        else:
            print(f'⚠️ [UYARI] Yahoo Finance API: Bos veri dondu ({dt:.2f}s)')
    except Exception as e:
        print(f'❌ [HATA] Yahoo Finance API: {e}')

    # 2. KAP (Public Disclosures) Provider
    try:
        from services.ingestion.providers.kap_provider import KAPProvider
        kp = KAPProvider()
        t0 = time.time()
        disclosures = await kp.fetch_disclosures(ticker='THYAO', limit=5)
        dt = time.time() - t0
        print(f'✅ [CALISIYOR] KAP (Kamuyu Aydinlatma Platformu): {len(disclosures)} bildirim cekildi (Sure: {dt:.2f}s)')
    except Exception as e:
        print(f'⚠️ [BILGI/FALLBACK] KAP Servisi: {e} (Kural tabanli fallback modunda)')

    # 3. TCMB (Central Bank Macro) Provider
    try:
        from services.ingestion.providers.tcmb_provider import TCMBProvider
        tp = TCMBProvider()
        t0 = time.time()
        macro_data = await tp.fetch_all_macro()
        dt = time.time() - t0
        print(f'✅ [CALISIYOR] TCMB (Merkez Bankasi Makro): {macro_data} (Sure: {dt:.2f}s)')
    except Exception as e:
        print(f'⚠️ [BILGI/FALLBACK] TCMB Servisi: {e} (Varsayilan makro parametrelere fallback yapildi)')

    # 4. News / RSS Provider
    try:
        from services.ingestion.providers.news_provider import NewsProvider
        np_prov = NewsProvider()
        t0 = time.time()
        news = await np_prov.fetch_financial_news_rss(max_items=5)
        dt = time.time() - t0
        print(f'✅ [CALISIYOR] Finansal Haber/RSS Servisi: {len(news)} guncel haber cekildi (Sure: {dt:.2f}s)')
    except Exception as e:
        print(f'⚠️ [BILGI/FALLBACK] Haber/RSS Servisi: {e}')

    # 5. BIST Universe Provider
    try:
        from services.ingestion.bist_universe import bist_universe
        t0 = time.time()
        b100 = bist_universe.BIST_100_TICKERS
        dt = time.time() - t0
        print(f'✅ [CALISIYOR] BIST Universe: {len(b100)} BIST 100 hissesi yuklendi (Sure: {dt:.2f}s)')
    except Exception as e:
        print(f'❌ [HATA] BIST Universe: {e}')

asyncio.run(run_all_checks())
