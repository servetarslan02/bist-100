def run_alpha_engine_sync():
    """Arka planda (veya scheduler ile) AlphaEngine'i calistirip DB'ye yazar."""
    from services.core.alpha_engine import AlphaEngine
    from services.core.risk_manager import RiskManager
    import asyncio
    import json
    import pandas as pd
    from datetime import datetime
    
    engine = AlphaEngine()
    rm = RiskManager()
    
    # 1. Veri Cek (Son 1 yili alalim yeterli)
    today = datetime.now()
    start_date = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
    
    # Eger piyasa verisi yoksa veya cok eksikse cik
    if bm_df.empty:
        return
        
    # Son 63 gunluk egitim dongusu (Optuna ile)
    common_dates = list(sorted([d.strftime('%Y-%m-%d') for d in bm_df.index]))
    if len(common_dates) < 200:
        return
        
    train_start = common_dates[0]
    train_end = common_dates[-2]
    target_date = common_dates[-1]
    
    # Optuna egitimi
    success = engine.train(
        market_data, bm_df, sector_map,
        train_start, train_end,
        optimize=True
    )
    
    if not success:
        return
        
    # Tahmin (Bugun icin)
    preds = engine.predict(market_data, bm_df, sector_map, target_date)
    top_picks = preds[:10]
    
    # Makro Rejim Kontrolu
    t_date = pd.Timestamp(target_date)
    regime = rm.get_market_regime(bm_df, t_date)
    is_cash = regime < 1.0
    
    # JSON yapisini hazirla
    tickers_json = json.dumps(top_picks)
    
    # DB'ye kaydet
    async def save_to_db():
        from services.core.database import pg_execute
        query = """
            INSERT INTO paper_trade_portfolio (target_date, tickers, is_cash_regime)
            VALUES ($1, $2, $3)
        """
        await pg_execute(query, t_date.date(), tickers_json, is_cash)
        
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(save_to_db())
        else:
            loop.run_until_complete(save_to_db())
    except Exception:
        asyncio.run(save_to_db())

if __name__ == '__main__':
    run_alpha_engine_sync()
