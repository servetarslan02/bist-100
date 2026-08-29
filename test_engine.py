import structlog
logger = structlog.get_logger(__name__)
import pandas as pd

from services.core.alpha_engine import AlphaEngine

engine = AlphaEngine()
today = pd.Timestamp.now()
start_date = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
end_date = today.strftime("%Y-%m-%d")

logger.info("Fetching data...")
market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
logger.info(f"Data fetched! Keys: {len(market_data.keys())}, bm_df: {len(bm_df)}")

logger.info("Generating samples...")
X, y, f = engine.generate_training_samples(market_data, bm_df, sector_map, pd.Timestamp(start_date), today)
logger.info(f"Generated X: {len(X)}")
