#!/usr/bin/env python3
"""
ALPHA BIST — Main Entry Point v4.0 (Production Ready)

GERCEK VERI, GERCEK BACKTEST, GERCEK MOTOR.
Mock veri yok. TODO yok. Placeholder yok.

Kullanim:
    python main.py --mode daily --date 2024-01-15
    python main.py --mode backtest --start 2022-01-01 --end 2024-01-01
    python main.py --mode learning --auto
    python main.py --mode health
    python main.py --mode full

Modlar:
    daily: Gunluk pipeline calistir (gercek veri)
    backtest: Tarihsel walk-forward backtest (gercek veri)
    learning: Surekli ogrenme dongusu
    health: Sistem saglik kontrolu
    full: Tum pipeline + backtest + learning
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import structlog

logger = structlog.get_logger()


def setup_logging():
    """Logging yapilandirmasi."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def _get_data_source():
    """Veri kaynagini baslat."""
    from services.data.data_source import data_source
    return data_source


def _get_universe():
    """BIST evrenini baslat."""
    from services.ingestion.bist_universe import bist_universe
    return bist_universe


def run_daily_pipeline(date: str):
    """Gunluk pipeline calistir — GERCEK VERI."""
    logger.info("Starting daily pipeline", date=date)

    data_source = _get_data_source()
    universe = _get_universe()

    # Dinamik hisse listesi
    all_tickers = universe.BIST_ALL_TICKERS
    bist_100 = universe.BIST_100_TICKERS
    logger.info("Universe loaded", total=len(all_tickers), bist_100=len(bist_100))

    # Gercek veri cek — once BIST 100, sonra digerleri
    print(f"📊 Gercek veri cekiliyor: {len(bist_100)} hisse (BIST 100)")

    yf_tickers = [f"{t}.IS" for t in bist_100 if t != "XU100"] + ["XU100.IS"]
    market_data = data_source.get_multiple_stocks(yf_tickers, period="6mo", interval="1d")

    # Ticker isimlerini duzelt (.IS kaldir)
    market_data = {k.replace(".IS", ""): v for k, v in market_data.items()}

    if not market_data:
        print("❌ Veri yuklenemedi! Internet baglantisini kontrol edin.")
        return None

    print(f"✅ Veri yuklendi: {len(market_data)} hisse")

    # Sektor haritasi
    sector_map = {t: universe.get_ticker_sector(t) for t in market_data.keys()}

    # Pipeline calistir
    from services.core.orchestrator import orchestrator

    report = orchestrator.run_full_pipeline(
        date=date,
        market_data=market_data,
        sector_map=sector_map,
    )

    # Raporu yazdir
    print("\n" + "="*70)
    print(f"🚀 ALPHA BIST v4.0 — GUNLUK RAPOR ({date})")
    print("="*70)
    print(f"📊 Rejim: {report.regime}")
    print(f"💻 Sistem Durumu: {report.system_health.get('status', 'UNKNOWN')}")
    print(f"⏱️  Pipeline Suresi: {report.system_health.get('pipeline_duration_ms', 0)}ms")

    print("\n🏆 TOP 10 FIRSATLAR")
    print("-"*70)
    print(f"{'#':<3} {'Hisse':<8} {'Skor':<8} {'Yon':<6} {'Guven':<8} {'Sinyaller'}")
    print("-"*70)
    for opp in report.top_opportunities[:10]:
        signals = []
        if opp.get('direction') == 'LONG':
            signals.append("🟢 AL")
        else:
            signals.append("🔴 SAT")
        print(f"{opp['rank']:<3} {opp['ticker']:<8} {opp['score']:<8.2f} {opp['direction']:<6} {opp['confidence']:<7.1f}% {' '.join(signals)}")

    print("\n💼 PORTFOY ONERISI")
    print("-"*70)
    port = report.portfolio_recommendation
    print(f"  Toplam Pozisyon: {port.get('total_positions', 0)}")
    print(f"  Toplam Agirlik: {port.get('total_weight', 0):.2%}")
    print(f"  {'Hisse':<8} {'Agirlik':<10} {'Tutar (TL)':<12} {'Risk %'}")
    print("-"*70)
    for pos in port.get('positions', [])[:5]:
        print(f"  {pos['ticker']:<8} {pos['weight']:<9.2%} {pos['notional']:<11,.0f} {pos['risk_pct']:<6.2f}%")

    print("\n🧠 OGRENME DURUMU")
    print("-"*70)
    ls = report.learning_status
    print(f"  Retrain Gerekli: {'⚠️ EVET' if ls.get('retrain_needed') else '✅ Hayir'}")
    print(f"  Drift Tespiti: {'⚠️ EVET' if ls.get('drift_detected') else '✅ Hayir'}")
    print(f"  Gunluk Sharpe: {ls.get('daily_sharpe', 0):.4f}")
    print(f"  Gunluk IC: {ls.get('daily_ic', 0):.4f}")

    if report.alerts:
        print("\n⚠️  UYARILAR")
        print("-"*70)
        for alert in report.alerts:
            print(f"  • {alert}")

    print("="*70)

    # JSON raporu kaydet
    import os
    os.makedirs("reports", exist_ok=True)
    json_report = orchestrator.export_daily_report_json(date)
    with open(f"reports/daily_{date}.json", "w") as f:
        f.write(json_report)
    print(f"\n📄 Rapor kaydedildi: reports/daily_{date}.json")

    return report


def run_backtest(start_date: str, end_date: str):
    """Tarihsel walk-forward backtest — GERCEK VERI."""
    logger.info("Starting backtest", start=start_date, end=end_date)

    data_source = _get_data_source()
    universe = _get_universe()

    # BIST 100 hisseleri
    bist_100 = universe.BIST_100_TICKERS
    print(f"📊 Backtest hisseleri: {len(bist_100)} (BIST 100)")

    # Gercek veri cek
    print(f"📈 Veri cekiliyor: {start_date} → {end_date}")
    yf_tickers = [f"{t}.IS" for t in bist_100 if t != "XU100"] + ["XU100.IS"]

    market_data = data_source.get_multiple_stocks(
        yf_tickers,
        start_date=start_date,
        end_date=end_date,
        interval="1d"
    )
    market_data = {k.replace(".IS", ""): v for k, v in market_data.items()}

    if not market_data:
        print("❌ Veri yuklenemedi!")
        return None

    print(f"✅ Veri yuklendi: {len(market_data)} hisse")

    # Sektor haritasi
    sector_map = {t: universe.get_ticker_sector(t) for t in market_data.keys()}

    # Walk-forward backtest
    from services.backtest.walk_forward import WalkForwardEngine
    from services.backtest.engine import BacktestEngine
    from services.core.orchestrator import orchestrator

    wf = WalkForwardEngine(
        train_days=252,   # 1 yil
        test_days=63,     # 3 ay
        step_days=21,     # Aylik
        purge_days=5,
        embargo_days=5,
    )

    # Tarih listesi
    dates = sorted(set(
        d.strftime("%Y-%m-%d")
        for df in market_data.values()
        for d in df.index
    ))

    print(f"📅 Toplam {len(dates)} islem gunu")

    # Fold'lari olustur
    folds = wf.create_folds(dates)
    print(f"🔁 {len(folds)} walk-forward fold olusturuldu")

    if not folds:
        print("❌ Yeterli veri yok! Daha uzun bir tarih araligi secin.")
        return None

    print("\n" + "="*70)
    print(f"📈 ALPHA BIST — WALK-FORWARD BACKTEST")
    print(f"   {start_date} → {end_date}")
    print(f"   {len(folds)} fold | Purge: 5g | Embargo: 5g")
    print("="*70)

    all_results = []
    bt_engine = BacktestEngine()

    for i, fold in enumerate(folds, 1):
        print(f"\n📦 FOLD {i}/{len(folds)}")
        print(f"   Train: {fold['train_start']} → {fold['train_end']}")
        print(f"   Test:  {fold['test_start']} → {fold['test_end']}")

        # Train verisi
        train_data = {
            t: df[(df.index >= fold['train_start']) & (df.index <= fold['train_end'])]
            for t, df in market_data.items()
        }
        train_data = {k: v for k, v in train_data.items() if not v.empty}

        # Test verisi
        test_data = {
            t: df[(df.index >= fold['test_start']) & (df.index <= fold['test_end'])]
            for t, df in market_data.items()
        }
        test_data = {k: v for k, v in test_data.items() if not v.empty}

        if not train_data or not test_data:
            print(f"   ⚠️ Yetersiz veri, atlaniyor")
            continue

        # Train pipeline
        try:
            train_report = orchestrator.run_full_pipeline(
                date=fold['train_end'],
                market_data=train_data,
                sector_map=sector_map,
            )
        except Exception as e:
            logger.error("Train pipeline failed", fold=i, error=str(e))
            print(f"   ❌ Train pipeline hatasi: {e}")
            continue

        # Test: Train'deki ranking'i test doneminde uygula
        top_picks = train_report.top_opportunities[:10]

        # Test donemi getirileri
        test_returns = {}
        for opp in top_picks:
            ticker = opp['ticker']
            if ticker in test_data and not test_data[ticker].empty:
                df_test = test_data[ticker]
                start_price = df_test['Close'].iloc[0]
                end_price = df_test['Close'].iloc[-1]
                ret = (end_price / start_price - 1) * 100
                test_returns[ticker] = ret

        # Backtest engine ile islem simulasyonu
        signals = []
        for opp in top_picks:
            ticker = opp['ticker']
            if ticker in test_data and not test_data[ticker].empty:
                df_test = test_data[ticker]
                entry_price = df_test['Close'].iloc[0]
                signals.append({
                    "date": fold['test_start'],
                    "ticker": ticker,
                    "action": "BUY",
                    "price": entry_price,
                    "confidence": opp.get('confidence', 0.5),
                })
                exit_price = df_test['Close'].iloc[-1]
                signals.append({
                    "date": fold['test_end'],
                    "ticker": ticker,
                    "action": "SELL",
                    "price": exit_price,
                    "confidence": opp.get('confidence', 0.5),
                })

        # Price data for backtest engine
        price_data = {}
        for ticker, df in test_data.items():
            price_data[ticker] = [
                {"date": str(d), "close": row['Close'], "volume": row.get('Volume', 0)}
                for d, row in df.iterrows()
            ]

        bt_result = bt_engine.run_backtest(
            strategy_name=f"alpha_fold_{i}",
            signals=signals,
            price_data=price_data,
            initial_capital=100000,
            commission_rate=0.001,
            slippage_pct=0.05,
        )

        # Sonuc
        m = bt_result.metrics
        fold_result = {
            "fold": i,
            "train_start": fold['train_start'],
            "train_end": fold['train_end'],
            "test_start": fold['test_start'],
            "test_end": fold['test_end'],
            "total_return": m.total_return_pct,
            "sharpe": m.sharpe_ratio,
            "max_dd": m.max_drawdown_pct,
            "win_rate": m.win_rate,
            "trades": m.total_trades,
            "final_capital": bt_result.final_capital,
        }
        all_results.append(fold_result)

        print(f"   📊 Getiri: {m.total_return_pct:+.2f}% | Sharpe: {m.sharpe_ratio:.2f} | MaxDD: {m.max_drawdown_pct:.2f}% | Win: {m.win_rate:.1%} | Trades: {m.total_trades}")

    # Ozet
    print("\n" + "="*70)
    print("BACKTEST OZET")
    print("="*70)

    if all_results:
        returns = [r['total_return'] for r in all_results]
        sharpes = [r['sharpe'] for r in all_results]
        win_rates = [r['win_rate'] for r in all_results]
        max_dds = [r['max_dd'] for r in all_results]

        print(f"  Toplam Fold: {len(all_results)}")
        print(f"  Ort. Getiri: {np.mean(returns):+.2f}%")
        print(f"  Ort. Sharpe: {np.mean(sharpes):.2f}")
        print(f"  Ort. Win Rate: {np.mean(win_rates):.1%}")
        print(f"  Ort. Max DD: {np.mean(max_dds):.2f}%")
        print(f"  En Iyi Fold: {max(returns):+.2f}%")
        print(f"  En Kotu Fold: {min(returns):+.2f}%")
        print(f"  Basari Orani: {sum(1 for r in returns if r > 0) / len(returns):.1%}")
    else:
        print("  ❌ Hicbir fold basariyla tamamlanamadi")

    print("="*70)

    # JSON kaydet
    import os
    os.makedirs("reports", exist_ok=True)
    with open(f"reports/backtest_{start_date}_{end_date}.json", "w") as f:
        json.dump({
            "start_date": start_date,
            "end_date": end_date,
            "folds": all_results,
            "summary": {
                "avg_return": float(np.mean(returns)) if all_results else 0,
                "avg_sharpe": float(np.mean(sharpes)) if all_results else 0,
                "avg_win_rate": float(np.mean(win_rates)) if all_results else 0,
                "avg_max_dd": float(np.mean(max_dds)) if all_results else 0,
            }
        }, f, indent=2, default=str)

    return all_results


def run_learning_cycle(auto: bool = False):
    """Surekli ogrenme dongusu calistir."""
    logger.info("Starting learning cycle", auto=auto)

    from services.learning.continuous_learning import continuous_learning

    report = continuous_learning.get_learning_report()

    print("\n" + "="*70)
    print("🧠 ALPHA BIST — SUREKLI OGRENME RAPORU")
    print("="*70)
    print(f"  Toplam Dongu: {report['total_cycles']}")
    print(f"  Son 30 Gun Sharpe: {report['performance_summary']['avg_sharpe_30d']}")
    print(f"  Son 30 Gun IC: {report['performance_summary']['avg_ic_30d']}")
    print(f"  Son 30 Gun Win Rate: {report['performance_summary']['avg_win_rate_30d']}")
    print(f"  Aktif Model: {report['registry']['active_version'] or 'Yok'}")
    print(f"  Sampiyon Model: {report['registry']['champion_version'] or 'Yok'}")
    print(f"  Drift Durumu: {'⚠️ TESPIT EDILDI' if report['drift_status']['detected'] else '✅ Normal'}")
    print("="*70)

    if auto:
        print("\n🔄 Otomatik kontrol calistiriliyor...")
        # Gercek veri ile daily pipeline calistir
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report = run_daily_pipeline(today)
        if report:
            print(f"  Durum: {report.system_health.get('status', 'UNKNOWN')}")

    return report


def run_health_check():
    """Sistem saglik kontrolu."""
    logger.info("Running health check")

    from services.learning.super_intelligence import super_intelligence
    from services.core.orchestrator import orchestrator
    from services.data.data_source import data_source
    from services.ingestion.bist_universe import bist_universe

    health = super_intelligence.get_health_status()
    stats = orchestrator.get_pipeline_stats()
    cache_stats = data_source.get_cache_stats()

    print("\n" + "="*70)
    print("🏥 ALPHA BIST — SISTEM SAGLIK KONTROLU")
    print("="*70)
    print(f"  Genel Durum: {health.overall_status}")
    print(f"  Calisma Suresi: {health.uptime_hours:.1f} saat")
    print(f"  Bugunku Tahmin: {health.predictions_today}")
    print(f"  Bugunku Dogruluk: {health.accuracy_today:.2%}")
    print(f"  Drift Tespiti: {'⚠️ EVET' if health.drift_detected else '✅ Hayir'}")
    print(f"  Retrain Gerekli: {'⚠️ EVET' if health.retrain_needed else '✅ Hayir'}")
    print(f"\n  Evren:")
    print(f"    BIST 100: {len(bist_universe.BIST_100_TICKERS)} hisse")
    print(f"    BIST TUM: {len(bist_universe.BIST_ALL_TICKERS)} hisse")
    print(f"\n  Cache:")
    print(f"    Dosya: {cache_stats['files']}")
    print(f"    Boyut: {cache_stats['total_size_mb']} MB")
    print(f"\n  Pipeline Istatistikleri:")
    print(f"    Toplam Calisma: {stats['total_runs']}")
    print(f"    Basari Orani: {stats['success_rate']:.1%}")
    print(f"    Ortalama Sure: {stats['avg_duration_ms']:.0f}ms")
    print(f"    Son Hatalar: {stats['recent_errors']}")
    print(f"    Son Uyarilar: {stats['recent_warnings']}")

    if health.last_error:
        print(f"\n  Son Hata: {health.last_error}")

    print("="*70)

    return health


def run_full_system(date: str):
    """Tam sistem calistir (daily + backtest + learning + health)."""
    logger.info("Running full system", date=date)

    # 1. Daily pipeline
    report = run_daily_pipeline(date)

    # 2. Backtest (son 2 yil)
    end = datetime.strptime(date, "%Y-%m-%d")
    start = (end - timedelta(days=730)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    run_backtest(start, end_str)

    # 3. Learning cycle
    run_learning_cycle(auto=True)

    # 4. Health check
    run_health_check()

    return report


def main():
    parser = argparse.ArgumentParser(
        description="ALPHA BIST v4.0 — Gercek Veri, Gercek Backtest, Gercek Motor"
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "backtest", "learning", "health", "full"],
        default="daily",
        help="Calistirma modu"
    )
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                       help="Islem tarihi (YYYY-MM-DD)")
    parser.add_argument("--start", help="Backtest baslangic tarihi")
    parser.add_argument("--end", help="Backtest bitis tarihi")
    parser.add_argument("--auto", action="store_true",
                       help="Otomatik mod (learning icin)")
    parser.add_argument("--config", help="Konfigurasyon dosyasi")

    args = parser.parse_args()

    setup_logging()

    if args.mode == "daily":
        run_daily_pipeline(args.date)
    elif args.mode == "backtest":
        if not args.start or not args.end:
            print("Hata: --start ve --end parametreleri gerekli!")
            print("Ornek: python main.py --mode backtest --start 2022-01-01 --end 2024-01-01")
            sys.exit(1)
        run_backtest(args.start, args.end)
    elif args.mode == "learning":
        run_learning_cycle(auto=args.auto)
    elif args.mode == "health":
        run_health_check()
    elif args.mode == "full":
        run_full_system(args.date)


if __name__ == "__main__":
    main()
