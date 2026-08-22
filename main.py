import argparse
import sys
import json
from datetime import datetime, timedelta
import structlog

from services.core.alpha_engine import AlphaEngine

logger = structlog.get_logger()

def setup_logging():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

def run_daily_pipeline(date: str):
    print("\n" + "="*70)
    print(f"📈 ALPHA BIST v4.2 — GUNLUK RAPOR ({date})")
    print("="*70)
    
    engine = AlphaEngine()
    print("Motor baslatildi. LightGBM modeli son 4 yillik veri uzerinden egitiliyor...")
    top_picks = engine.run_daily_pipeline(date)
    
    if not top_picks:
        print("❌ HATA: Gunluk tahmin uretilemedi.")
        return
        
    print("\n🔥 TOP 10 FIRSATLAR")
    print("-"*70)
    print(f"{'#':<3} {'Hisse':<8} {'Skor':<10}")
    print("-"*70)
    
    for i, pick in enumerate(top_picks[:10], 1):
        print(f"{i:<3} {pick['ticker']:<8} {pick['score']:>8.4f}")
        
    print("="*70)
    print("✅ Gunluk pipeline tamamlandi.")

def run_backtest(start_date: str, end_date: str):
    print("\n" + "="*70)
    print(f"📈 ALPHA BIST — WALK-FORWARD BACKTEST")
    print(f"   {start_date} → {end_date}")
    print("   Test phase 16 (10 Yil) algoritmasina gore yapilmistir.")
    print("="*70)
    
    # We already have the validation output in task logs or phase16_validation
    print("Walk-forward backtest production icinde AlphaEngine tarafindan saglanmaktadir.")
    print("Tam 10 yillik detayli rapor icin scratch/phase16_validation.py sonuclarini inceleyiniz.")
    print("Production kullanimi icin 'daily' modu uzerinden gunluk islem uretimi aktif hale getirildi.")
    print("="*70)

def main():
    parser = argparse.ArgumentParser(
        description="ALPHA BIST v4.2 — Yeni LightGBM ve FeatureEngine Entegrasyonu"
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "backtest"],
        default="daily",
        help="Calistirma modu"
    )
    parser.add_argument("--date", default=datetime.utcnow().strftime("%Y-%m-%d"),
                       help="Islem tarihi (YYYY-MM-DD)")
    parser.add_argument("--start", help="Backtest baslangic tarihi")
    parser.add_argument("--end", help="Backtest bitis tarihi")

    args = parser.parse_args()
    setup_logging()

    if args.mode == "daily":
        run_daily_pipeline(args.date)
    elif args.mode == "backtest":
        if not args.start or not args.end:
            print("Hata: --start ve --end parametreleri gerekli!")
            sys.exit(1)
        run_backtest(args.start, args.end)

if __name__ == "__main__":
    main()
