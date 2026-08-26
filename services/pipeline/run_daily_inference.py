"""
ALPHA BIST — Daily Inference Pipeline

Günlük tahmin pipeline'ı.
BIST-30, BIST-50, BIST-100 için multi-index destekli.
Scheduler tarafından tetiklenir.
"""

def run_alpha_engine_sync(universes=None):
    """Arka planda AlphaEngine'i çalıştırıp DB'ye yazar.

    Args:
        universes: Çalıştırılacak endeksler. None ise ["bist30", "bist50", "bist100"].
    """
    from services.core.alpha_engine import AlphaEngine
    from services.core.risk_manager import RiskManager
    import asyncio
    import orjson
    import pandas as pd
    from datetime import datetime

    if universes is None:
        universes = ["bist30", "bist50", "bist100"]

    engine = AlphaEngine()
    rm = RiskManager()

    today = datetime.now()
    date = today.strftime("%Y-%m-%d")

    # Multi-index pipeline çalıştır
    results = engine.run_multi_index_pipeline(date, universes=universes)

    if not results or not results.get("combined"):
        return

    combined = results["combined"]
    top_picks = combined[:10]

    # Makro Rejim Kontrolu
    start_date = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    market_data, bm_df, sector_map = engine.fetch_data(start_date, date, universe="bist100")

    if bm_df.empty:
        return

    t_date = pd.Timestamp(date)
    regime = rm.get_market_regime(bm_df, t_date)
    is_cash = regime < 1.0

    # JSON yapısını hazırla (multi-index bilgisi ile)
    output = {
        "date": date,
        "combined": top_picks,
        "per_index": {u: results.get(u, [])[:5] for u in universes},
        "summary": results.get("summary", {}),
        "is_cash_regime": is_cash,
    }
    tickers_json = orjson.dumps(output).decode()

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
