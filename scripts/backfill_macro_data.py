"""
ALPHA BIST — Macro Data Backfill Script

TCMB EVDS ve Yahoo Finance'ten tarihsel makro veri çeker ve historical_store'a kaydet.

Kullanım:
    python3 scripts/backfill_macro_data.py
    python3 scripts/backfill_macro_data.py --years 3
    python3 scripts/backfill_macro_data.py --indicators USDTRY,CPI
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def backfill_from_yahoo(years: int = 5):
    """Yahoo Finance'ten tarihsel veri çek."""
    from services.macro.historical_store import macro_historical_store

    try:
        import yfinance as yf
    except ImportError:
        print("yfinance yüklü değil: pip install yfinance")
        return

    indicators = {
        "USDTRY": "TRY=X",
        "EURTRY": "EURTRY=X",
        "GOLD": "GC=F",
        "OIL": "CL=F",
        "VIX": "^VIX",
        "SP500": "^GSPC",
        "NASDAQ": "^IXIC",
    }

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365)

    for name, symbol in indicators.items():
        print(f"Backfilling {name} ({symbol})...")
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start_date, end=end_date)

            count = 0
            for date, row in hist.iterrows():
                date_str = date.strftime("%Y-%m-%d")
                macro_historical_store.save(
                    date=date_str,
                    indicator=name,
                    value=float(row["Close"]),
                    source="yahoo_finance",
                )
                count += 1

            print(f"  {name}: {count} veri noktası kaydedildi")

        except Exception as e:
            print(f"  {name} hatası: {e}")


def backfill_from_tcmb(years: int = 5):
    """TCMB EVDS'ten tarihsel veri çek."""
    from services.macro.historical_store import macro_historical_store

    try:
        from services.ingestion.providers.tcmb_provider import tcmb_provider
    except ImportError:
        print("TCMB provider bulunamadı")
        return

    print("TCMB EVDS backfill...")
    try:
        # TCMB provider'dan tarihsel veri çek
        data = tcmb_provider.fetch_historical(years=years)
        if data:
            for indicator, values in data.items():
                count = 0
                for date_str, value in values.items():
                    macro_historical_store.save(
                        date=date_str,
                        indicator=f"TCMB_{indicator}",
                        value=float(value),
                        source="tcmb_evds",
                    )
                    count += 1
                print(f"  TCMB_{indicator}: {count} veri noktası")
    except Exception as e:
        print(f"  TCMB hatası: {e}")


def main():
    parser = argparse.ArgumentParser(description="Macro Data Backfill")
    parser.add_argument("--years", type=int, default=5, help="Kaç yıllık veri")
    parser.add_argument("--indicators", type=str, default="all", help="İndikatörler (virgülle ayrılmış veya 'all')")
    args = parser.parse_args()

    print(f"=== Macro Data Backfill ({args.years} yıl) ===\n")

    # Yahoo Finance
    backfill_from_yahoo(years=args.years)

    # TCMB
    backfill_from_tcmb(years=args.years)

    # Rapor
    from services.macro.historical_store import macro_historical_store

    report = macro_historical_store.get_report()
    print("\n=== Backfill Tamamlandı ===")
    print(f"Toplam gösterge: {report['indicators']}")
    print(f"Toplam veri noktası: {report['total_data_points']}")


if __name__ == "__main__":
    main()
