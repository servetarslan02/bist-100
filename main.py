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


def run_daily_pipeline(date: str, config: Optional[dict] = None):
    """Günlük pipeline çalıştır."""
    logger.info("Starting daily pipeline", date=date)

    from services.core.orchestrator import orchestrator

    # TODO: Veri kaynağından market data çek
    # Şimdilik mock data
    market_data = {}  # {ticker: DataFrame}
    sector_map = {}   # {ticker: sector}

    report = orchestrator.run_full_pipeline(
        date=date,
        market_data=market_data,
        sector_map=sector_map,
    )

    # Raporu yazdır
    print("\n" + "="*60)
    print(f"ALPHA BIST — Günlük Rapor ({date})")
    print("="*60)
    print(f"Rejim: {report.regime}")
    print(f"Sistem Durumu: {report.system_health.get('status', 'UNKNOWN')}")
    print(f"Pipeline Süresi: {report.system_health.get('pipeline_duration_ms', 0)}ms")
    print("\n--- Top 10 Fırsatlar ---")
    for opp in report.top_opportunities[:10]:
        print(f"  #{opp['rank']:2d} {opp['ticker']:6s} | Score: {opp['score']:6.2f} | "
              f"Dir: {opp['direction']:5s} | Conf: {opp['confidence']:5.1f}%")

    print("\n--- Portföy Önerisi ---")
    port = report.portfolio_recommendation
    print(f"  Toplam Pozisyon: {port.get('total_positions', 0)}")
    print(f"  Toplam Ağırlık: {port.get('total_weight', 0):.2%}")
    for pos in port.get('positions', [])[:5]:
        print(f"  {pos['ticker']:6s} | Weight: {pos['weight']:5.2%} | "
              f"Notional: {pos['notional']:>10,.0f} TL | Risk: {pos['risk_pct']:5.2f}%")

    print("\n--- Öğrenme Durumu ---")
    ls = report.learning_status
    print(f"  Retrain Gerekli: {ls.get('retrain_needed', False)}")
    print(f"  Drift Tespiti: {ls.get('drift_detected', False)}")
    print(f"  Günlük Sharpe: {ls.get('daily_sharpe', 0):.4f}")
    print(f"  Günlük IC: {ls.get('daily_ic', 0):.4f}")

    if report.alerts:
        print("\n--- UYARILAR ---")
        for alert in report.alerts:
            print(f"  ⚠️  {alert}")

    print("="*60)

    # JSON raporu kaydet
    json_report = orchestrator.export_daily_report_json(date)
    with open(f"reports/daily_{date}.json", "w") as f:
        f.write(json_report)

    return report


def run_backtest(start_date: str, end_date: str):
    """Tarihsel backtest çalıştır."""
    logger.info("Starting backtest", start=start_date, end=end_date)

    from services.backtest.walk_forward import walk_forward_engine

    # TODO: Tarihsel veri yükle
    # TODO: Walk-forward validation çalıştır

    print("\n" + "="*60)
    print(f"ALPHA BIST — Backtest Raporu ({start_date} → {end_date})")
    print("="*60)
    print("Backtest tamamlandı. Detaylar için reports/ klasörünü kontrol edin.")
    print("="*60)


def run_learning_cycle(auto: bool = False):
    """Sürekli öğrenme döngüsü çalıştır."""
    logger.info("Starting learning cycle", auto=auto)

    from services.learning.continuous_learning import continuous_learning
    from services.learning.super_intelligence import super_intelligence

    report = continuous_learning.get_learning_report()

    print("\n" + "="*60)
    print("ALPHA BIST — Sürekli Öğrenme Raporu")
    print("="*60)
    print(f"Toplam Döngü: {report['total_cycles']}")
    print(f"Son 30 Gün Sharpe: {report['performance_summary']['avg_sharpe_30d']}")
    print(f"Son 30 Gün IC: {report['performance_summary']['avg_ic_30d']}")
    print(f"Son 30 Gün Win Rate: {report['performance_summary']['avg_win_rate_30d']}")
    print(f"Aktif Model: {report['registry']['active_version']}")
    print(f"Şampiyon Model: {report['registry']['champion_version']}")
    print(f"Drift Durumu: {report['drift_status']['detected']}")
    print("="*60)

    if auto:
        # Otomatik retrain kontrolü
        print("\nOtomatik kontrol çalıştırılıyor...")
        # TODO: Güncel veri ile kontrol et

    return report


def run_health_check():
    """Sistem sağlık kontrolü."""
    logger.info("Running health check")

    from services.learning.super_intelligence import super_intelligence
    from services.core.orchestrator import orchestrator

    health = super_intelligence.get_health_status()
    stats = orchestrator.get_pipeline_stats()

    print("\n" + "="*60)
    print("ALPHA BIST — Sistem Sağlık Kontrolü")
    print("="*60)
    print(f"Genel Durum: {health.overall_status}")
    print(f"Çalışma Süresi: {health.uptime_hours:.1f} saat")
    print(f"Bugünkü Tahmin: {health.predictions_today}")
    print(f"Bugünkü Doğruluk: {health.accuracy_today:.2%}")
    print(f"Drift Tespiti: {health.drift_detected}")
    print(f"Retrain Gerekli: {health.retrain_needed}")
    print(f"\nPipeline İstatistikleri:")
    print(f"  Toplam Çalışma: {stats['total_runs']}")
    print(f"  Başarı Oranı: {stats['success_rate']:.1%}")
    print(f"  Ortalama Süre: {stats['avg_duration_ms']:.0f}ms")
    print(f"  Son Hatalar: {stats['recent_errors']}")
    print(f"  Son Uyarılar: {stats['recent_warnings']}")

    if health.last_error:
        print(f"\nSon Hata: {health.last_error}")

    print("="*60)

    return health


def run_full_system(date: str):
    """Tam sistem çalıştır (daily + backtest + learning)."""
    logger.info("Running full system", date=date)

    # 1. Daily pipeline
    report = run_daily_pipeline(date)

    # 2. Backtest (eğer veri varsa)
    # run_backtest("2023-01-01", date)

    # 3. Learning cycle
    run_learning_cycle(auto=True)

    # 4. Health check
    run_health_check()

    return report


def main():
    parser = argparse.ArgumentParser(
        description="ALPHA BIST — Süper Akıllı Quantitative Trading System"
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
    parser.add_argument("--config", help="Konfigürasyon dosyası")

    args = parser.parse_args()

    setup_logging()

    if args.mode == "daily":
        run_daily_pipeline(args.date)
    elif args.mode == "backtest":
        if not args.start or not args.end:
            print("Hata: --start ve --end parametreleri gerekli!")
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
