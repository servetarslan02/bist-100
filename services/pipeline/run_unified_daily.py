"""
GRAND UNIFICATION: PHASE 18 (BEYIN) + PORTFOLIO MANAGER (ELLER)
==============================================================
Bu betik, Phase 18'in %51.86 CAGR gosteren backtest stratejisini,
mevcut kurumsal altyapiyla (PortfolioManager) birlestirir.

Kurallar:
1. Sinyal: Sadece Phase 18 AlphaEngine'den alinir.
2. Agirlik: Top 10 hisseye %10 Esit Agirlik (Equal Weight).
3. Vade: 63 Gunluk sabit tutma suresi (Holding Period). Her gun al/sat YAPILMAZ!
4. RiskManager: Sadece Shadow modunda, mudahale etmez.
5. LearningPipeline: Sadece kaydeder, mudahale etmez.
"""

import asyncio
import json
import logging
from datetime import datetime, date
import pandas as pd
from typing import Dict, List, Any

# Sistemin ana bilesenleri
from services.core.database import pg_fetch, pg_execute, init_databases
from services.core.alpha_engine import AlphaEngine
from services.portfolio.portfolio_manager import PortfolioManager

logger = logging.getLogger("unified_daily")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

# Backtest ile birebir ayni holding suresi
HOLDING_PERIOD_DAYS = 63 

async def get_last_rebalance_date() -> date:
    """Veritabanindan son gercek rebalance (al-sat yapilan) tarihi doner."""
    query = """
        SELECT created_at 
        FROM paper_trade_portfolio 
        WHERE is_rebalance = TRUE
        ORDER BY created_at DESC 
        LIMIT 1
    """
    try:
        rows = await pg_fetch(query)
        if rows:
            return rows[0]["created_at"].date()
    except Exception:
        pass
    return None

async def run_unified_daily_cycle():
    """Her gun saat 18:15'te tetiklenen ana Dongu."""
    await init_databases()
    logger.info("Grand Unification: Otonom Gun Sonu (EOD) dongusu basladi.")
    
    # 1. KONTROL: BUGUN REBALANCE GUNU MU?
    today = date.today()
    last_rebalance = await get_last_rebalance_date()
    
    needs_rebalance = True
    
    if last_rebalance is None:
        logger.info("Hic rebalance kaydi bulunamadi. Ilk portfoy olusturuluyor!")
        needs_rebalance = True
    else:
        # Trading gunu hesabi (Basit yaklasim: hafta sonlari haric say)
        # Daha dogrusu, BIST is gunu sayisidir. 
        # Simdilik takvim gunu uzerinden yaklasik 88 gun (63 is gunu = ~88 takvim gunu) 
        days_passed = (today - last_rebalance).days
        if days_passed >= 88: 
            logger.info(f"{days_passed} takvim gunu gecti. REBALANCE TETIKLENIYOR.")
            needs_rebalance = True
        else:
            logger.info(f"Son rebalance uzerinden {days_passed} gun gecti. Sadece MTM (Mark-to-Market) yapilacak.")
            
    # 2. MOTORLARI AYARLA
    engine = AlphaEngine()
    
    # Guncel Fiyatlari Cek (Mark-to-Market icin sart)
    start_date = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
    
    if bm_df.empty:
        logger.error("Veri cekilemedi! Dongu iptal.")
        return
        
    current_prices = {}
    for ticker, df in market_data.items():
        if not df.empty:
            current_prices[ticker] = float(df['Close'].iloc[-1])
            
    from services.api.v1.portfolio import _get_pm
    pm = _get_pm()
    # (PortfolioManager icinde state yukleme metodu var mi? 
    # Varsa cagirmaliyiz, simdilik baslangic durumu varsayip simule ediyoruz).
    # Normalde PortfolioManager'in redis/db serialize yapisi kullanilmalidir.
    
    if needs_rebalance:
        # 3. BEYIN: PHASE 18 KARAR ALIYOR
        common_dates = list(sorted([d.strftime('%Y-%m-%d') for d in bm_df.index]))
        train_start = common_dates[0]
        train_end = common_dates[-2]
        target_date = common_dates[-1]
        
        logger.info(f"Phase 18 (Optuna) egitimi basliyor: {train_start} -> {train_end}")
        success = engine.train(market_data, bm_df, sector_map, train_start, train_end, optimize=True)
        
        if success:
            preds = engine.predict(market_data, bm_df, sector_map, target_date)
            
            # Redis'e skorlari kaydet ki UI / radar onlari okuyabilsin
            try:
                from services.core.redis_helper import set_cached
                set_cached("phase18:predictions", preds, ttl=86400 * 3) # 3 gun
                set_cached("phase18:last_trained", datetime.now().isoformat(), ttl=86400 * 3)
            except Exception as e:
                logger.warning(f"Redis cache yazilamadi: {e}")
                

            # CHIEF RISK OFFICER: Liquidity Filter (10 Million TL)
            valid_preds = []
            MIN_LIQUIDITY_TL = 10_000_000
            for p in preds:
                tick = p["ticker"]
                if tick in market_data:
                    df = market_data[tick]
                    df_past = df.loc[df.index <= target_date]
                    if len(df_past) >= 20:
                        avg_vol = df_past['Volume'].tail(20).mean()
                        avg_close = df_past['Close'].tail(20).mean()
                        if (avg_vol * avg_close) >= MIN_LIQUIDITY_TL:
                            valid_preds.append(p)
            
            top_10 = valid_preds[:10]

            logger.info(f"YENI TOP 10 (PHASE 18): {top_10}")
            
            # 4. UYGULAMA: Portfolio Manager
            # Hedef agirliklar: %10
            from services.api.v1.portfolio import _get_service
            ps = _get_service()
            if not getattr(ps, "_running", False):
                await ps.start()
                
            target_weights = {item["ticker"]: 0.10 for item in top_10}
            
            # Portfoy yoneticisine hedef veriyoruz (sanal rebalance)
            pm.update_prices(current_prices)
            orders = pm.compute_rebalance_orders(target_weights, turnover_limit=1.0)
            executed_orders = []
            
            # Emirleri uygula
            for order in orders:
                ticker = order["ticker"]
                action = order["action"]
                value = order["value"]
                price = current_prices.get(ticker, 1.0)
                
                if action == "SELL":
                    pos = pm.get_position(ticker)
                    quantity = pos["quantity"] if pos else 0
                else:
                    quantity = int(value / price) if price > 0 else 0
                
                if quantity <= 0:
                    continue
                    
                import hashlib
                instrument_id = int(hashlib.md5(ticker.encode()).hexdigest(), 16) % 1000000
                
                # Insert instrument into SQLite to satisfy FK
                from services.core.database_dev import dev_db
                try:
                    await dev_db.pg_execute("INSERT OR IGNORE INTO instruments (id, symbol, exchange, instrument_type) VALUES (?, ?, 'BIST', 'EQUITY')", instrument_id, ticker)
                except Exception:
                    pass
                    
                if action == "BUY":
                    res = await ps.execute_buy(ticker, quantity, price, instrument_id=instrument_id)
                    executed_orders.append(res)
                elif action == "SELL":
                    res = await ps.execute_sell(ticker, quantity, price, instrument_id=instrument_id)
                    executed_orders.append(res)
                elif action == "REDUCE":
                    res = await ps.execute_sell(ticker, quantity, price, instrument_id=instrument_id)
                    executed_orders.append(res)
                    
            # 5. DB KAYDI
            top_10_tickers = [item["ticker"] for item in top_10]
            tickers_json = json.dumps(top_10_tickers)
            try:
                await pg_execute(
                    "INSERT INTO paper_trade_portfolio (target_date, tickers, is_cash_regime, is_rebalance) VALUES ($1, $2, $3, $4)",
                    today, tickers_json, False, True
                )
            except Exception as e:
                logger.error(f"DB Kayit Hatasi: {e}")
                
            logger.info("Grand Unification Dongusu Tamamlandi.")
            return {"needs_rebalance": True, "executed": executed_orders}
            
    else:
        # SADECE MTM YAPIYORUZ
        pm.update_prices(current_prices)
        logger.info("Mark-to-Market degerlemesi yapildi.")
        return {"needs_rebalance": False, "message": "Sadece MTM yapildi."}

if __name__ == '__main__':
    asyncio.run(run_unified_daily_cycle())
