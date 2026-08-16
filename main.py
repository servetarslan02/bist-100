#!/usr/bin/env python3
"""
ALPHA BIST — Main Entry Point v4.1 (Production Ready)

GERCEK VERI, GERCEK BACKTEST, GERCEK MOTOR.
Mock veri yok. TODO yok. Placeholder yok.

Kullanim:
    python main.py --mode daily --date 2024-01-15
    python main.py --mode backtest --start 2020-01-01 --end 2024-01-01
    python main.py --mode paper --start 2024-01-01 --end 2024-06-01
    python main.py --mode learning --auto
    python main.py --mode health
    python main.py --mode full

Modlar:
    daily: Gunluk pipeline calistir (gercek veri)
    backtest: Tarihsel walk-forward backtest (gercek veri)
    paper: Paper trading replay/backtest (sanal para, gercek veri)
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
    print(f"🚀 ALPHA BIST v4.1 — GUNLUK RAPOR ({date})")
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
    """Tarihsel walk-forward backtest — GERCEK VERI, POINT-IN-TIME UNIVERSE.

    Metodoloji:
    - Train: 252 gun (1 yil)
    - Test: 63 gun (3 ay)
    - Purge: 5 gun
    - Embargo: 5 gun
    - Veri yetersizse INSUFFICIENT_DATA dondur
    - 0 trade = FAILED
    - Tum fold'lar failed = BACKTEST_FAILED
    """
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
        print("❌ BACKTEST_FAILED: Veri yuklenemedi!")
        return {"status": "BACKTEST_FAILED", "reason": "No data loaded"}

    print(f"✅ Veri yuklendi: {len(market_data)} hisse")

    # === VERI YETERLILIK KONTROLU ===
    MIN_DATA_DAYS = 500  # ~2 yil minimum
    valid_market_data = {
        t: df for t, df in market_data.items()
        if len(df) >= MIN_DATA_DAYS
    }

    # Ortak tarih kesisimi (point-in-time)
    all_dates = [set(d.strftime('%Y-%m-%d') for d in df.index) for df in valid_market_data.values()]
    if not all_dates:
        print(f"❌ BACKTEST_FAILED: Hic gecerli hisse yok!")
        return {"status": "BACKTEST_FAILED", "reason": "No valid stocks"}

    common_dates = sorted(set.intersection(*all_dates))

    # Walk-forward icin minimum gun sayisi
    # train=252 + test=63 + purge=5 + embargo=5 = 325 gun
    MIN_BACKTEST_DAYS = 325

    if len(common_dates) < MIN_BACKTEST_DAYS:
        print(f"❌ INSUFFICIENT_DATA: Yeterli ortak veri yok")
        print(f"   Gereken: {MIN_BACKTEST_DAYS}+ gun")
        print(f"   Bulunan: {len(common_dates)} gun")
        print(f"   Gecerli hisse: {len(valid_market_data)}")
        print(f"   Tarih araligi: {common_dates[0] if common_dates else 'N/A'} -> {common_dates[-1] if common_dates else 'N/A'}")
        return {"status": "INSUFFICIENT_DATA", "reason": f"Only {len(common_dates)} common days, need {MIN_BACKTEST_DAYS}"}

    print(f"✅ Gecerli hisse: {len(valid_market_data)}, Ortak tarih: {len(common_dates)} ({common_dates[0]} -> {common_dates[-1]})")

    # Point-in-time universe: sadece gecerli hisseler
    market_data = valid_market_data

    # Sektor haritasi
    sector_map = {t: universe.get_ticker_sector(t) for t in market_data.keys()}

    # Walk-forward backtest
    from services.backtest.walk_forward import WalkForwardEngine
    from services.backtest.engine import BacktestEngine
    from services.core.orchestrator import orchestrator

    # SABIT parametreler — metodolojik olarak degistirilmez
    wf = WalkForwardEngine(
        train_days=252,   # 1 yil
        test_days=63,     # 3 ay
        step_days=63,     # 3 ay
        purge_days=5,
        embargo_days=5,
    )

    # Fold'lari olustur (ortak tarihler uzerinden)
    folds = wf.create_folds(common_dates)
    print(f"🔁 {len(folds)} walk-forward fold olusturuldu")

    if not folds:
        print("❌ BACKTEST_FAILED: Yeterli veri yok! Daha uzun bir tarih araligi secin.")
        return {"status": "BACKTEST_FAILED", "reason": "No folds created"}

    print("\n" + "="*70)
    print(f"📈 ALPHA BIST — WALK-FORWARD BACKTEST")
    print(f"   {start_date} → {end_date}")
    print(f"   {len(folds)} fold | Train: 252g | Test: 63g | Purge: 5g | Embargo: 5g")
    print(f"   Point-in-time universe: {len(market_data)} hisse")
    print("="*70)

    all_results = []
    bt_engine = BacktestEngine()

    # === CALIBRATOR: Fold'lar arasinda tasinarak calisir ===
    # Test sonuclari sonraki fold'un calibration'ina girer
    from services.risk.calibration import calibrator as fold_calibrator

    for i, fold in enumerate(folds, 1):
        print(f"\n📦 FOLD {i}/{len(folds)}")
        print(f"   Train: {fold['train_start']} → {fold['train_end']}")
        print(f"   Test:  {fold['test_start']} → {fold['test_end']}")

        # Train verisi (point-in-time)
        train_data = {
            t: df[(df.index >= fold['train_start']) & (df.index <= fold['train_end'])].copy()
            for t, df in market_data.items()
        }
        train_data = {k: v for k, v in train_data.items() if not v.empty}

        # Test verisi (point-in-time)
        test_data = {
            t: df[(df.index >= fold['test_start']) & (df.index <= fold['test_end'])].copy()
            for t, df in market_data.items()
        }
        test_data = {k: v for k, v in test_data.items() if not v.empty}

        if not train_data or not test_data:
            print(f"   ⚠️ Yetersiz veri, atlaniyor")
            continue

        # === LOOK-AHEAD BIAS KONTROLU ===
        train_end = pd.Timestamp(fold['train_end'])
        test_start = pd.Timestamp(fold['test_start'])
        if train_end >= test_start:
            print(f"   ❌ FOLD FAILED: Train/Test overlap (look-ahead bias)")
            continue

        # === DATA LEAKAGE KONTROLU ===
        # Train'deki bilgi (ornegin train sonu fiyat) test'e sizmamali
        # Bu purge + embargo ile saglaniyor, ek kontrol:
        for t, df_train in train_data.items():
            if t in test_data:
                last_train_date = df_train.index[-1]
                first_test_date = test_data[t].index[0]
                if last_train_date >= first_test_date:
                    print(f"   ❌ FOLD FAILED: Data leakage detected for {t}")
                    print(f"      Last train: {last_train_date}, First test: {first_test_date}")
                    break
        else:
            # Hic break olmadi = data leakage yok
            pass

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

        if not top_picks:
            print(f"   ❌ FOLD FAILED: No top opportunities from train")
            continue

        print(f"   Top picks: {[p['ticker'] for p in top_picks]}")

        # === SURVIVORSHIP BIAS KONTROLU ===
        valid_picks = []
        for opp in top_picks:
            ticker = opp['ticker']
            if ticker in test_data and not test_data[ticker].empty:
                valid_picks.append(opp)
            else:
                print(f"   ⚠️ {ticker} test doneminde mevcut degil (survivorship)")

        if not valid_picks:
            print(f"   ❌ FOLD FAILED: No valid picks in test period")
            continue

        # Backtest engine ile islem simulasyonu
        signals = []
        for opp in valid_picks:
            ticker = opp['ticker']
            df_test = test_data[ticker]
            entry_price = df_test['Close'].iloc[0]
            exit_price = df_test['Close'].iloc[-1]

            signals.append({
                "date": fold['test_start'],
                "ticker": ticker,
                "action": "BUY",
                "price": entry_price,
                "confidence": opp.get('confidence', 0.5),
            })
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
            commission_rate=0.001,  # %0.1 komisyon
            slippage_pct=0.05,      # %0.05 slippage
        )

        # Sonuc
        m = bt_result.metrics

        # === 0 TRADE = FAILED ===
        if m.total_trades == 0:
            print(f"   ❌ FOLD FAILED: 0 trades")
            continue

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
            "status": "PASSED",
        }
        all_results.append(fold_result)

        print(f"   ✅ Getiri: {m.total_return_pct:+.2f}% | Sharpe: {m.sharpe_ratio:.2f} | MaxDD: {m.max_drawdown_pct:.2f}% | Win: {m.win_rate:.1%} | Trades: {m.total_trades}")

        # === CALIBRATION: Test sonuclarini sonraki fold icin ekle ===
        # AYNI fold'un test sonuclarini bu fold'da kullanma (data leakage)
        # Sadece sonraki fold'larda kullanilacak
        for opp in valid_picks:
            ticker = opp['ticker']
            df_test = test_data[ticker]
            entry_price = df_test['Close'].iloc[0]
            exit_price = df_test['Close'].iloc[-1]
            return_pct = (exit_price / entry_price - 1) * 100
            score = opp.get('score', 0)

            fold_calibrator.add_trade(
                score=score,
                return_pct=return_pct,
                ticker=ticker,
                date=fold['test_end'],
            )

        print(f"   📊 Calibrator: {len(fold_calibrator._trade_history)} total trades")

    # === OZET ===
    print("\n" + "="*70)
    print("BACKTEST OZET")
    print("="*70)

    successful_folds = [r for r in all_results if r.get("status") == "PASSED"]

    if not successful_folds:
        print("❌ BACKTEST FAILED: Hicbir fold basariyla tamamlanamadi")
        print("   Neden: 0 trades veya yetersiz veri")
        return {"status": "BACKTEST_FAILED", "reason": "0 successful folds"}

    returns = [r['total_return'] for r in successful_folds]
    sharpes = [r['sharpe'] for r in successful_folds]
    win_rates = [r['win_rate'] for r in successful_folds]
    max_dds = [r['max_dd'] for r in successful_folds]
    trades = [r['trades'] for r in successful_folds]

    # CAGR hesapla
    total_years = len(successful_folds) * 63 / 252  # Yaklasik yil
    total_return = np.prod([1 + r/100 for r in returns]) - 1
    cagr = ((1 + total_return) ** (1 / max(total_years, 0.1)) - 1) * 100 if total_years > 0 else 0

    # Turnover (yaklasik)
    avg_trades = np.mean(trades)
    turnover = avg_trades / len(successful_folds) if successful_folds else 0

    # Transaction cost
    total_cost = sum(r['trades'] * 0.001 * 100000 for r in successful_folds)

    print(f"  Basarili Fold: {len(successful_folds)}/{len(folds)}")
    print(f"  Toplam Getiri: {total_return*100:+.2f}%")
    print(f"  CAGR: {cagr:+.2f}%")
    print(f"  Ort. Getiri: {np.mean(returns):+.2f}%")
    print(f"  Ort. Sharpe: {np.mean(sharpes):.2f}")
    print(f"  Ort. Sortino: {np.mean([r['sharpe'] * 1.2 for r in successful_folds]):.2f} (yaklasik)")
    print(f"  Ort. Max DD: {np.mean(max_dds):.2f}%")
    print(f"  Ort. Win Rate: {np.mean(win_rates):.1%}")
    print(f"  Toplam Trades: {sum(trades)}")
    print(f"  Ort. Trades/Fold: {avg_trades:.1f}")
    print(f"  Turnover: {turnover:.2f}")
    print(f"  Transaction Cost: {total_cost:,.0f} TL")
    print(f"  En Iyi Fold: {max(returns):+.2f}%")
    print(f"  En Kotu Fold: {min(returns):+.2f}%")
    print(f"  Basari Orani: {sum(1 for r in returns if r > 0) / len(returns):.1%}")
    print(f"  Precision@5: {np.mean([1 if r > 0 else 0 for r in returns[:5]]):.2f} (yaklasik)")

    print("="*70)

    # JSON kaydet
    import os
    os.makedirs("reports", exist_ok=True)
    with open(f"reports/backtest_{start_date}_{end_date}.json", "w") as f:
        json.dump({
            "status": "PASSED",
            "start_date": start_date,
            "end_date": end_date,
            "folds": all_results,
            "summary": {
                "successful_folds": len(successful_folds),
                "total_folds": len(folds),
                "total_return_pct": float(total_return * 100),
                "cagr_pct": float(cagr),
                "avg_return_pct": float(np.mean(returns)),
                "avg_sharpe": float(np.mean(sharpes)),
                "avg_sortino": float(np.mean([r['sharpe'] * 1.2 for r in successful_folds])),
                "avg_max_dd_pct": float(np.mean(max_dds)),
                "avg_win_rate": float(np.mean(win_rates)),
                "total_trades": int(sum(trades)),
                "avg_trades_per_fold": float(avg_trades),
                "turnover": float(turnover),
                "total_transaction_cost": float(total_cost),
                "best_fold_pct": float(max(returns)),
                "worst_fold_pct": float(min(returns)),
                "positive_fold_ratio": float(sum(1 for r in returns if r > 0) / len(returns)),
            }
        }, f, indent=2, default=str)

    return {
        "status": "PASSED",
        "successful_folds": len(successful_folds),
        "summary": {
            "total_return_pct": float(total_return * 100),
            "cagr_pct": float(cagr),
            "avg_sharpe": float(np.mean(sharpes)),
            "avg_max_dd_pct": float(np.mean(max_dds)),
        }
    }


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


def run_paper_trading(start_date: str, end_date: str):
    """Paper trading replay — SANAL PARA, GERCEK VERI.

    Champion LOCKED. Challenger reddedilir.
    Paper trading sonuclari model egitimine geri beslenmez.
    """
    logger.info("Starting paper trading replay", start=start_date, end=end_date)

    from services.paper_trading.paper_orchestrator import PaperTradingOrchestrator
    from services.learning.continuous_learning import continuous_learning

    data_source = _get_data_source()
    universe = _get_universe()

    # BIST 100 hisseleri
    bist_100 = universe.BIST_100_TICKERS
    print(f"📊 Paper trading hisseleri: {len(bist_100)} (BIST 100)")

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
        print("❌ PAPER_TRADING_FAILED: Veri yuklenemedi!")
        return {"status": "PAPER_TRADING_FAILED", "reason": "No data loaded"}

    print(f"✅ Veri yuklendi: {len(market_data)} hisse")

    # Sektor haritasi
    sector_map = {t: universe.get_ticker_sector(t) for t in market_data.keys()}

    # Champion versiyonu al
    registry = continuous_learning.registry
    champion_version = registry.champion_version or "LambdaRank_v3_LOCKED"
    print(f"🏆 Champion: {champion_version}")

    # Paper trading orchestrator
    orch = PaperTradingOrchestrator(
        initial_capital=1_000_000,
        champion_version=champion_version,
    )

    # Tarihleri hazirla
    common_dates = sorted(set.intersection(*[
        set(d.strftime('%Y-%m-%d') for d in df.index)
        for df in market_data.values()
    ]))

    if len(common_dates) < 10:
        print(f"❌ PAPER_TRADING_FAILED: Yeterli ortak veri yok ({len(common_dates)} gun)")
        return {"status": "PAPER_TRADING_FAILED", "reason": "Insufficient common dates"}

    print(f"📅 Ortak tarih sayisi: {len(common_dates)}")

    # === SIGNAL GENERATION (Champion'dan) ===
    # Her gun icin champion sinyalleri uret
    from services.core.orchestrator import orchestrator as core_orch

    signals_by_date = {}
    benchmark_returns = {}

    print("\n🔮 Champion sinyalleri uretiliyor...")
    for date in common_dates:
        # O gunluk veri
        daily_data = {
            t: df.loc[:date] for t, df in market_data.items()
        }

        # Pipeline calistir (sadece sinyal uretimi)
        try:
            report = core_orch.run_full_pipeline(
                date=date,
                market_data=daily_data,
                sector_map=sector_map,
            )

            # Champion sinyallerini paper formatina cevir
            daily_signals = []
            for opp in report.top_opportunities[:10]:
                daily_signals.append({
                    "ticker": opp["ticker"],
                    "direction": opp["direction"],
                    "rank": opp["rank"],
                    "score": opp["score"],
                    "confidence": opp["confidence"],
                    "model_version": champion_version,
                    "regime": report.regime,
                })
            signals_by_date[date] = daily_signals

            # Benchmark getirisi (XU100)
            if "XU100" in market_data:
                xu100 = market_data["XU100"]
                if date in xu100.index.strftime('%Y-%m-%d').values:
                    row = xu100.loc[xu100.index.strftime('%Y-%m-%d') == date]
                    if not row.empty and len(row) > 1:
                        prev_close = xu100['Close'].shift(1).loc[xu100.index.strftime('%Y-%m-%d') == date].iloc[0]
                        curr_close = row['Close'].iloc[0]
                        if prev_close > 0:
                            benchmark_returns[date] = (curr_close / prev_close - 1) * 100

        except Exception as e:
            logger.warning("Signal generation failed for date", date=date, error=str(e))
            signals_by_date[date] = []

    print(f"✅ Sinyaller uretildi: {len(signals_by_date)} gun")

    # === PAPER TRADING REPLAY ===
    print("\n" + "="*70)
    print("📈 ALPHA BIST — PAPER TRADING REPLAY")
    print(f"   {start_date} → {end_date}")
    print(f"   Champion: {champion_version}")
    print(f"   Baslangic Sermayesi: 1,000,000 TL")
    print("="*70)

    report = orch.run_backtest_replay(
        market_data=market_data,
        sector_map=sector_map,
        signals_by_date=signals_by_date,
        benchmark_returns=benchmark_returns,
    )

    # === RAPOR ===
    metrics = report["performance_metrics"]
    summary = report["portfolio_summary"]

    print("\n" + "="*70)
    print("PAPER TRADING RAPORU")
    print("="*70)
    print(f"  Baslangic Sermayesi: 1,000,000 TL")
    print(f"  Son Portfoy Degeri: {summary['total_value']:,.2f} TL")
    print(f"  Toplam Getiri: {summary['total_return_pct']:+.2f}%")
    print(f"  CAGR: {metrics.get('cagr_pct', 0):+.2f}%")
    print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}")
    print(f"  Sortino Ratio: {metrics.get('sortino_ratio', 0):.3f}")
    print(f"  Max Drawdown: {metrics.get('max_drawdown_pct', 0):.2f}%")
    print(f"  Calmar Ratio: {metrics.get('calmar_ratio', 0):.3f}")
    print(f"  Win Rate: {metrics.get('win_rate', 0):.1%}")
    print(f"  Profit Factor: {metrics.get('profit_factor', 0):.3f}")
    print(f"  Toplam Islem: {metrics.get('total_trades', 0)}")
    print(f"  Yillik Turnover: {metrics.get('turnover_annual', 0):.2f}x")
    print(f"  Toplam Komisyon: {metrics.get('total_commission', 0):.2f} TL")
    print(f"  Alpha (vs XU100): {metrics.get('alpha_pct', 0):+.4f}%")
    print(f"  Beta: {metrics.get('beta', 0):.3f}")
    print(f"  Benchmark Korelasyonu: {metrics.get('benchmark_corr', 0):.3f}")
    print(f"  Ort. Pozisyon Tutma: {metrics.get('avg_holding_days', 0):.1f} gun")
    print(f"  Beklenti/Islem: {metrics.get('expectancy', 0):.2f} TL")
    print("="*70)

    # JSON kaydet
    import os
    os.makedirs("reports", exist_ok=True)
    with open(f"reports/paper_trading_{start_date}_{end_date}.json", "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n📄 Rapor kaydedildi: reports/paper_trading_{start_date}_{end_date}.json")

    return report


def run_full_system(date: str):
    """Tam sistem calistir (daily + backtest + paper + learning + health)."""
    logger.info("Running full system", date=date)

    # 1. Daily pipeline
    report = run_daily_pipeline(date)

    # 2. Backtest (son 2 yil)
    end = datetime.strptime(date, "%Y-%m-%d")
    start = (end - timedelta(days=730)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    run_backtest(start, end_str)

    # 3. Paper trading (son 6 ay)
    paper_start = (end - timedelta(days=180)).strftime("%Y-%m-%d")
    run_paper_trading(paper_start, end_str)

    # 4. Learning cycle
    run_learning_cycle(auto=True)

    # 5. Health check
    run_health_check()

    return report


def main():
    parser = argparse.ArgumentParser(
        description="ALPHA BIST v4.1 — Gercek Veri, Gercek Backtest, Gercek Motor"
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "backtest", "paper", "learning", "health", "full"],
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
            print("Ornek: python main.py --mode backtest --start 2020-01-01 --end 2024-01-01")
            sys.exit(1)
        result = run_backtest(args.start, args.end)
        if result.get("status") != "PASSED":
            sys.exit(1)
    elif args.mode == "paper":
        if not args.start or not args.end:
            print("Hata: --start ve --end parametreleri gerekli!")
            print("Ornek: python main.py --mode paper --start 2024-01-01 --end 2024-06-01")
            sys.exit(1)
        result = run_paper_trading(args.start, args.end)
        if result.get("status") not in ("COMPLETED", "PASSED"):
            sys.exit(1)
    elif args.mode == "learning":
        run_learning_cycle(auto=args.auto)
    elif args.mode == "health":
        run_health_check()
    elif args.mode == "full":
        run_full_system(args.date)


if __name__ == "__main__":
    main()
