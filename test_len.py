import pandas as pd
import yfinance as yf
from datetime import datetime

today = datetime.now()
start_date = (today - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
end_date = today.strftime("%Y-%m-%d")

bm = yf.Ticker("XU100.IS").history(start=start_date, end=end_date)
print(f"XU100 length: {len(bm)}")
for offset in [20, 40, 60, 80]:
    t_snap = pd.Timestamp(today) - pd.Timedelta(days=int(offset))
    snap_bm = bm[(bm.index.tz_localize(None) >= pd.Timestamp(start_date)) & (bm.index.tz_localize(None) <= t_snap)]
    print(f"Offset {offset}: snap length: {len(snap_bm)}")
