import asyncio
from services.core.alpha_engine import AlphaEngine
import datetime
import pandas as pd

engine = AlphaEngine()
today = datetime.date.today()
start_date = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
end_date = today.strftime("%Y-%m-%d")

print("Fetching data...")
try:
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
    print(f"Data fetched! Keys: {len(market_data)}, bm_df: {len(bm_df)}")
except Exception as e:
    import traceback
    traceback.print_exc()
