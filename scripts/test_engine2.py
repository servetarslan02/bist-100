import structlog

logger = structlog.get_logger(__name__)
import datetime

from services.core.alpha_engine import AlphaEngine

engine = AlphaEngine()
today = datetime.date.today()
start_date = (today - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
end_date = today.strftime("%Y-%m-%d")

logger.info("Fetching data...")
try:
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
    logger.info(f"Data fetched! Keys: {len(market_data)}, bm_df: {len(bm_df)}")
except Exception:
    import traceback

    traceback.print_exc()
