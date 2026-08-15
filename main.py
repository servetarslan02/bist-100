#!/usr/bin/env python3
"""
ALPHA BIST — Main Entry Point v3.0

SÜPER AKILLI, TAM OTOMATİK SİSTEM

Kullanım:
    python main.py --mode daily --date 2024-01-15
    python main.py --mode backtest --start 2023-01-01 --end 2024-01-01
    python main.py --mode learning --auto
    python main.py --mode health

Modlar:
    daily: Günlük pipeline çalıştır
    backtest: Tarihsel backtest
    learning: Sürekli öğrenme döngüsü
    health: Sistem sağlık kontrolü
    full: Tüm pipeline + backtest + learning
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional
import structlog

logger = structlog.get_logger()


def setup_logging():
    """Logging yapılandırması."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def generate_mock_data(tickers, days=120):
    """Gerçekçi mock veri oluştur (test için)."""
    np.random.seed(42)
    market_data = {}
    
    configs = {
        "THYAO": {"start": 180, "trend": 0.001, "vol": 0.025},
        "GARAN": {"start": 120, "trend": -0.0003, "vol": 0.02},
        "ISCTR": {"start": 45, "trend": 0.0008, "vol": 0.018},
        "ASELS": {"start": 65, "trend": 0.0012, "vol": 0.022},
        "BIMAS": {"start": 350, "trend": 0.0002, "vol": 0.015},
        "XU100": {"start": 8500, "trend": 0.0004, "vol": 0.012},
    }
    
    for ticker in tickers:
        cfg = configs.get(ticker, {"start": 100, "trend": 0.0005, "vol": 0.02})
        dates = pd.date_range(end=datetime.now(), periods=days, freq='B')
        returns = np.random.normal(cfg["trend"], cfg["vol"], days)
        prices = cfg["start"] * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame(index=dates)
        df['Close'] = prices
        df['Open'] = prices * (1 + np.random.normal(0, 0.005, days))
        df['High'] = np.maximum(df['Open'], df['Close']) * (1 + np.abs(np.random.normal(0, 0.01, days)))
        df['Low'] = np.minimum(df['Open'], df['Close']) * (1 - np.abs(np.random.normal(0, 0.01, days)))
        df['Volume'] = np.random.randint(1000000, 10000000, days)
        market_data[ticker] = df
    
    return market_data


def run_daily_pipeline(date: str, use_real_data: bool = False):
    """Günlük pipeline çalıştır."""
    logger.info("Starting daily pipeline", date=date)
    
    from services.ingestion.bist_universe import BIST_STOCKS
    
    # TÜM BIST HİSSELERİNİ TARA (BIST TÜM ~450+ hisse)
    from services.ingestion.bist_universe import BISTUniverse
    test_tickers = BISTUniverse.BIST_ALL_TICKERS + ["XU100"]
    
    if use_real_data:
        # Gerçek veri çek (Yahoo Finance)
        from services.data.data_source import data_source
        market_data = data_source.get_multiple_stocks(
            [f"{t}.IS" for t in test_tickers if t != "XU100"] + ["XU100.IS"],
            period="6mo", interval="1d"
        )
        # Ticker isimlerini düzelt (.IS kaldır)
        market_data = {k.replace(".IS", ""): v for k, v in market_data.items()}
    else:
        # Mock veri kullan
        print("📊 Mock veri kullanılıyor (gerçek veri için --real-data flag'i kullanın)")
        market_data = generate_mock_data(test_tickers)
    
    if not market_data:
        print("❌ Veri yüklenemedi!")
        return None
    
    # Sektör haritası
    from services.ingestion.bist_universe import get_sector
    sector_map = {t: get_sector(t) for t in market_data.keys()}
    
    # Pipeline çalıştır
    from services.core.orchestrator import orchestrator
    
    report = orchestrator.run_full_pipeline(
        date=date,
        market_data=market_data,
        sector_map=sector_map,
    )
    
    # Raporu yazdır
    print("\n" + "="*70)
    print(f"🚀 ALPHA BIST v3.0 — GÜNLÜK RAPOR ({date})")
    print("="*70)
    print(f"📊 Rejim: {report.regime}")
    print(f"💻 Sistem Durumu: {report.system_health.get('status', 'UNKNOWN')}")
    print(f"⏱️  Pipeline Süresi: {report.system_health.get('pipeline_duration_ms', 0)}ms")
    
    print("\n🏆 TOP 10 FIRSATLAR")
    print("-"*70)
    print(f"{'#':<3} {'Hisse':<8} {'Skor':<8} {'Yön':<6} {'Güven':<8} {'Sinyaller'}")
    print("-"*70)
    for opp in report.top_opportunities[:10]:
        signals = []
        if opp.get('direction') == 'LONG':
            signals.append("🟢 AL")
        else:
            signals.append("🔴 SAT")
        print(f"{opp['rank']:<3} {opp['ticker']:<8} {opp['score']:<8.2f} {opp['direction']:<6} {opp['confidence']:<7.1f}% {' '.join(signals)}")
    
    print("\n💼 PORTFÖY ÖNERİSİ")
    print("-"*70)
    port = report.portfolio_recommendation
    print(f"  Toplam Pozisyon: {port.get('total_positions', 0)}")
    print(f"  Toplam Ağırlık: {port.get('total_weight', 0):.2%}")
    print(f"  {'Hisse':<8} {'Ağırlık':<10} {'Tutar (TL)':<12} {'Risk %'}")
    print("-"*70)
    for pos in port.get('positions', [])[:5]:
        print(f"  {pos['ticker']:<8} {pos['weight']:<9.2%} {pos['notional']:<11,.0f} {pos['risk_pct']:<6.2f}%")
    
    print("\n🧠 ÖĞRENME DURUMU")
    print("-"*70)
    ls = report.learning_status
    print(f"  Retrain Gerekli: {'⚠️ EVET' if ls.get('retrain_needed') else '✅ Hayır'}")
    print(f"  Drift Tespiti: {'⚠️ EVET' if ls.get('drift_detected') else '✅ Hayır'}")
    print(f"  Günlük Sharpe: {ls.get('daily_sharpe', 0):.4f}")
    print(f"  Günlük IC: {ls.get('daily_ic', 0):.4f}")
    
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
    """Tarihsel backtest çalıştır."""
    logger.info("Starting backtest", start=start_date, end=end_date)
    
    from services.ingestion.bist_universe import BIST_STOCKS
    from services.data.data_source import data_source
    
    test_tickers = ["THYAO", "GARAN", "ISCTR", "ASELS", "BIMAS"]
    
    # Mock veri ile backtest (gerçek veri için use_real_data=True)
    market_data = generate_mock_data(test_tickers + ["XU100"], days=252)
    sector_map = {t: "BANKACILIK" if t in ["GARAN", "ISCTR"] else "HAVACILIK" if t == "THYAO" else "SAVUNMA" if t == "ASELS" else "PERAKENDE" for t in test_tickers}
    sector_map["XU100"] = "BENCHMARK"
    
    from services.core.orchestrator import orchestrator
    
    # Her ay için pipeline çalıştır (walk-forward yaklaşımı)
    print("\n" + "="*70)
    print(f"📈 ALPHA BIST — BACKTEST ({start_date} → {end_date})")
    print("="*70)
    
    dates = pd.date_range(start=start_date, end=end_date, freq='M')
    results = []
    
    for date in dates:
        date_str = date.strftime("%Y-%m-%d")
        report = orchestrator.run_full_pipeline(
            date=date_str,
            market_data=market_data,
            sector_map=sector_map,
        )
        results.append(report)
        print(f"  {date_str}: Rejim={report.regime:8s} | Fırsat={len(report.top_opportunities):2d} | Durum={report.system_health.get('status', 'UNKNOWN')}")
    
    print("\n" + "="*70)
    print("BACKTEST ÖZET")
    print("="*70)
    print(f"  Toplam Dönem: {len(results)}")
    print(f"  Başarılı: {sum(1 for r in results if r.system_health.get('status') == 'HEALTHY')}")
    print(f"  Uyarı: {sum(1 for r in results if r.system_health.get('status') == 'WARNING')}")
    print(f"  Hata: {sum(1 for r in results if r.system_health.get('status') == 'CRITICAL')}")
    print("="*70)


def run_learning_cycle(auto: bool = False):
    """Sürekli öğrenme döngüsü çalıştır."""
    logger.info("Starting learning cycle", auto=auto)
    
    from services.learning.continuous_learning import continuous_learning
    
    report = continuous_learning.get_learning_report()
    
    print("\n" + "="*70)
    print("🧠 ALPHA BIST — SÜREKLİ ÖĞRENME RAPORU")
    print("="*70)
    print(f"  Toplam Döngü: {report['total_cycles']}")
    print(f"  Son 30 Gün Sharpe: {report['performance_summary']['avg_sharpe_30d']}")
    print(f"  Son 30 Gün IC: {report['performance_summary']['avg_ic_30d']}")
    print(f"  Son 30 Gün Win Rate: {report['performance_summary']['avg_win_rate_30d']}")
    print(f"  Aktif Model: {report['registry']['active_version'] or 'Yok'}")
    print(f"  Şampiyon Model: {report['registry']['champion_version'] or 'Yok'}")
    print(f"  Drift Durumu: {'⚠️ TESPİT EDİLDİ' if report['drift_status']['detected'] else '✅ Normal'}")
    print("="*70)
    
    if auto:
        print("\n🔄 Otomatik kontrol çalıştırılıyor...")
        # Mock veri ile daily pipeline çalıştır
        from services.ingestion.bist_universe import BIST_STOCKS
        market_data = generate_mock_data(["THYAO", "GARAN", "ISCTR"], days=60)
        sector_map = {t: "TEST" for t in market_data.keys()}
        
        from services.core.orchestrator import orchestrator
        report = orchestrator.run_full_pipeline(
            date=datetime.now().strftime("%Y-%m-%d"),
            market_data=market_data,
            sector_map=sector_map,
        )
        print(f"  Durum: {report.system_health.get('status', 'UNKNOWN')}")
    
    return report


def run_health_check():
    """Sistem sağlık kontrolü."""
    logger.info("Running health check")
    
    from services.learning.super_intelligence import super_intelligence
    from services.core.orchestrator import orchestrator
    
    health = super_intelligence.get_health_status()
    stats = orchestrator.get_pipeline_stats()
    
    print("\n" + "="*70)
    print("🏥 ALPHA BIST — SİSTEM SAĞLIK KONTROLÜ")
    print("="*70)
    print(f"  Genel Durum: {health.overall_status}")
    print(f"  Çalışma Süresi: {health.uptime_hours:.1f} saat")
    print(f"  Bugünkü Tahmin: {health.predictions_today}")
    print(f"  Bugünkü Doğruluk: {health.accuracy_today:.2%}")
    print(f"  Drift Tespiti: {'⚠️ EVET' if health.drift_detected else '✅ Hayır'}")
    print(f"  Retrain Gerekli: {'⚠️ EVET' if health.retrain_needed else '✅ Hayır'}")
    print(f"\n  Pipeline İstatistikleri:")
    print(f"    Toplam Çalışma: {stats['total_runs']}")
    print(f"    Başarı Oranı: {stats['success_rate']:.1%}")
    print(f"    Ortalama Süre: {stats['avg_duration_ms']:.0f}ms")
    print(f"    Son Hatalar: {stats['recent_errors']}")
    print(f"    Son Uyarılar: {stats['recent_warnings']}")
    
    if health.last_error:
        print(f"\n  Son Hata: {health.last_error}")
    
    print("="*70)
    
    return health


def run_full_system(date: str):
    """Tam sistem çalıştır (daily + backtest + learning + health)."""
    logger.info("Running full system", date=date)
    
    # 1. Daily pipeline
    report = run_daily_pipeline(date)
    
    # 2. Learning cycle
    run_learning_cycle(auto=True)
    
    # 3. Health check
    run_health_check()
    
    return report


def main():
    parser = argparse.ArgumentParser(
        description="ALPHA BIST v3.0 — Süper Akıllı Quantitative Trading System"
    )
    parser.add_argument(
        "--mode",
        choices=["daily", "backtest", "learning", "health", "full"],
        default="daily",
        help="Çalıştırma modu"
    )
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                       help="İşlem tarihi (YYYY-MM-DD)")
    parser.add_argument("--start", help="Backtest başlangıç tarihi")
    parser.add_argument("--end", help="Backtest bitiş tarihi")
    parser.add_argument("--auto", action="store_true",
                       help="Otomatik mod (learning için)")
    parser.add_argument("--real-data", action="store_true",
                       help="Gerçek veri kullan (Yahoo Finance)")
    parser.add_argument("--config", help="Konfigürasyon dosyası")

    args = parser.parse_args()

    setup_logging()

    if args.mode == "daily":
        run_daily_pipeline(args.date, use_real_data=args.real_data)
    elif args.mode == "backtest":
        if not args.start or not args.end:
            print("Hata: --start ve --end parametreleri gerekli!")
            print("Örnek: python main.py --mode backtest --start 2023-01-01 --end 2024-01-01")
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
