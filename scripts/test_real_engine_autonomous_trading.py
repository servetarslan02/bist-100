"""
ALPHA BIST — Real Engine End-to-End Autonomous Trading Verification Script

Bu script, basit/düz testler yerine GERÇEK ÇALIŞAN SİSTEM MOTORLARIMIZI
(PaperTradingOrchestrator, VirtualPortfolio, AutonomousConvictionEngine, PaperRiskGate, PaperExecutionEngine)
birebir bağlayarak adım adım çalıştırır:

1. Kriz Dönemi: 0 hisse seçimi, %100 nakit koruması
2. Seçici Dönem: Sadece 2-3 süper hisseye yüksek ağırlıklı (%18-%22) alım
3. Kârı Koşturma (Let Winners Run): %30 kârda güçlü hisseyi gün kısıtsız tutma & Trailing Stop yükseltme
4. Gücü Biteni Satma (Conviction Decay): Sinyali sönen hisseyi 2. günde anında satma & T+2 nakde dönme
5. Geniş Boğa Rallisi: 12+ hisseye yayılma ve sektör disiplini
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from datetime import datetime, timedelta
import polars as pl
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception as exc:
        sys.stderr.write(f"Encoding warning: {exc}\n")

import structlog

from services.paper_trading.paper_orchestrator import PaperTradingOrchestrator
from services.paper_trading.paper_risk_gate import PaperRiskGate
from services.paper_trading.state_store import PaperStateStore
from services.portfolio.autonomous_conviction_engine import (
    AutonomousConvictionEngine,
    CandidateAsset,
    ExitAction,
    OpenPositionState,
)

logger = structlog.get_logger()


def build_historical_market_data(tickers: list[str], base_prices: dict[str, float], n_days: int = 35) -> dict[str, pl.DataFrame]:
    """Gerçekçi 35 günlük OHLCV geçmiş barlar veri havuzu oluşturur."""
    market_data = {}
    dates = [(datetime(2026, 1, 5) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n_days)]

    for t in tickers:
        base_p = base_prices.get(t, 50.0)
        closes, opens, highs, lows, vols = [], [], [], [], []

        curr_p = base_p
        for i in range(n_days):
            open_p = curr_p * (1.0 + 0.002)
            high_p = open_p * (1.0 + 0.015)
            low_p = open_p * (1.0 - 0.012)
            close_p = (open_p + high_p + low_p) / 3.0
            closes.append(round(close_p, 2))
            opens.append(round(open_p, 2))
            highs.append(round(high_p, 2))
            lows.append(round(low_p, 2))
            vols.append(2_500_000 + i * 50_000)
            curr_p = close_p

        df = pl.DataFrame({
            "Date": dates,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": vols,
        })
        market_data[t] = df

    return market_data


def run_real_engine_simulation():
    print("=" * 80)
    print("🚀 ALPHA BIST — GERÇEK MOTOR OTONOM İŞLEM & KÂR KOŞTURMA SİMÜLASYONU")
    print("=" * 80)

    # 1. Gerçek Motor Bileşenlerini Başlat
    test_db_path = Path("data/test_real_autonomous_state.db")
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception as exc:
            logger.debug("Test db unlink notice", error=str(exc))

    store = PaperStateStore(db_path=str(test_db_path))
    risk_gate = PaperRiskGate(max_position_pct=25.0, max_sector_pct=35.0)
    conviction_engine = AutonomousConvictionEngine(
        base_hurdle_rate=0.35,
        min_entry_confidence=0.60,
        exit_confidence_threshold=0.48,
        trailing_stop_pct=0.06,
        max_single_stock_cap=0.25,
    )

    orchestrator = PaperTradingOrchestrator(
        champion_version="LambdaRank_v3_LOCKED",
        initial_capital=1_000_000.0,
        store=store,
        require_next_open=True,
        strict_t2=True,
    )
    orchestrator.risk_gate = risk_gate

    all_tickers = [
        "GARAN", "AKBNK", "THYAO", "PGSUS", "EREGL", "BIMAS",
        "SISE", "ASELS", "TUPRS", "KCHOL", "SAHOL", "ENKAI",
        "FROTO", "TOASO", "CCOLA", "MGROS"
    ]
    base_prices = {
        "GARAN": 100.0, "AKBNK": 60.0, "THYAO": 250.0, "PGSUS": 800.0,
        "EREGL": 45.0, "BIMAS": 400.0, "SISE": 50.0, "ASELS": 65.0,
        "TUPRS": 160.0, "KCHOL": 210.0, "SAHOL": 90.0, "ENKAI": 40.0,
        "FROTO": 1100.0, "TOASO": 260.0, "CCOLA": 600.0, "MGROS": 450.0
    }
    sector_map = {
        "GARAN": "BANK", "AKBNK": "BANK", "THYAO": "TRANS", "PGSUS": "TRANS",
        "EREGL": "STEEL", "BIMAS": "RETAIL", "MGROS": "RETAIL", "SISE": "GLASS",
        "ASELS": "DEFENSE", "TUPRS": "ENERGY", "KCHOL": "HOLDING", "SAHOL": "HOLDING",
        "ENKAI": "CONSTRUCT", "FROTO": "AUTO", "TOASO": "AUTO", "CCOLA": "BEV"
    }

    market_data = build_historical_market_data(all_tickers, base_prices, n_days=30)

    # -------------------------------------------------------------------------
    # SEZON 1 (GÜN 1): Kriz / Alfa Yokluğu -> 0 Hisse / %100 Nakitte Bekle
    # -------------------------------------------------------------------------
    print("\n▶ [SEZON 1 / GÜN 1] Kriz ve Alfa Yokluğu Testi:")
    c_s1 = [
        CandidateAsset(t, confidence_score=0.45, expected_return=0.15, volatility=0.35, sector=sector_map[t])
        for t in all_tickers[:8]
    ]
    plan_s1 = conviction_engine.allocate_conviction_portfolio(c_s1, market_regime="BEAR")
    print(f"   Motorun Kararı : {plan_s1.rationale}")
    print(f"   Seçilen Hisse  : {plan_s1.num_positions} adet | Nakit Oranı: %{plan_s1.cash_weight*100:.1f}")

    assert plan_s1.num_positions == 0
    assert plan_s1.cash_weight == 1.0

    # -------------------------------------------------------------------------
    # SEZON 2 (GÜN 2): Seçici Ayrışma -> Sadece 2 Lider Hisseye Ağır Giriş (%22 ve %18)
    # -------------------------------------------------------------------------
    print("\n▶ [SEZON 2 / GÜN 2] Seçici Lider Ayrışması Testi:")
    c_s2 = [
        CandidateAsset("THYAO", confidence_score=0.92, expected_return=0.75, volatility=0.25, sector="TRANS"),
        CandidateAsset("GARAN", confidence_score=0.88, expected_return=0.65, volatility=0.28, sector="BANK"),
        CandidateAsset("EREGL", confidence_score=0.50, expected_return=0.20, volatility=0.32, sector="STEEL"),
        CandidateAsset("SISE", confidence_score=0.45, expected_return=0.18, volatility=0.30, sector="GLASS"),
    ]
    plan_s2 = conviction_engine.allocate_conviction_portfolio(c_s2, market_regime="SIDEWAYS")
    print(f"   Motorun Kararı : {plan_s2.rationale}")
    print(f"   Seçilen Hisseler ve Ağırlıklar: {plan_s2.weights}")

    assert plan_s2.num_positions == 2
    assert "THYAO" in plan_s2.selected_tickers
    assert "GARAN" in plan_s2.selected_tickers
    assert plan_s2.weights["THYAO"] >= 0.18  # Güçlü hisseye yüksek sermaye payı

    # Sinyalleri Gerçek Orchestrator'a Gönder
    signals_s2 = [
        {
            "ticker": t,
            "direction": "LONG",
            "model_version": "LambdaRank_v3_LOCKED",
            "conviction_weight": plan_s2.weights[t],
            "confidence": next(c.confidence_score for c in c_s2 if c.ticker == t),
        }
        for t in plan_s2.selected_tickers
    ]

    report_s2 = orchestrator.run_daily_cycle(
        date="2026-01-06",
        market_data=market_data,
        sector_map=sector_map,
        champion_signals=signals_s2,
        is_morning_execution=True,
    )
    positions_s2 = orchestrator.portfolio.get_all_positions()
    pos_tickers_s2 = [p["ticker"] for p in positions_s2]
    print(f"   Orchestrator İşlem Durumu: {report_s2.get('status')} | Açılan Pozisyonlar: {pos_tickers_s2}")
    print(f"   Portföy Değeri: {orchestrator.portfolio.get_total_value():,.2f} TL | Kalan Nakit: {orchestrator.portfolio.cash:,.2f} TL")

    assert len(positions_s2) == 2
    assert "THYAO" in pos_tickers_s2
    assert "GARAN" in pos_tickers_s2

    # -------------------------------------------------------------------------
    # SEZON 3 (GÜN 15): Kârı Koşturma (Let Winners Run) -> THYAO %30 Kârda, Satma!
    # -------------------------------------------------------------------------
    print("\n▶ [SEZON 3 / GÜN 15] Kârı Koşturma (Let Winners Run) Testi:")
    thyao_pos = orchestrator.portfolio.get_position("THYAO")
    entry_p = thyao_pos["avg_cost"]
    curr_thyao_p = entry_p * 1.30  # %30 Ralli yaptı

    open_pos_list = [
        OpenPositionState(
            ticker="THYAO",
            entry_price=entry_p,
            current_price=curr_thyao_p,
            highest_price=curr_thyao_p,
            entry_date="2026-01-06",
            holding_days=15,
            current_confidence=0.90,  # Güçlü güven devam ediyor
            sector="TRANS",
            quantity=thyao_pos["quantity"],
        )
    ]

    exit_decisions_s3 = conviction_engine.evaluate_position_exits(
        positions=open_pos_list,
        current_scores={"THYAO": 0.90},
        current_prices={"THYAO": curr_thyao_p},
    )
    d_thyao = exit_decisions_s3[0]
    print(f"   THYAO Durumu: Kâr = %{d_thyao.unrealized_pnl_pct*100:.1f} | Gün = 15 | Model Güveni = {d_thyao.current_confidence}")
    print(f"   Motorun Kararı: {d_thyao.action} ({d_thyao.reason})")

    assert d_thyao.action == ExitAction.HOLD_AND_RUN
    assert d_thyao.trailing_stop_price > entry_p  # Trailing stop kârı kilitlemiş olmalı

    # -------------------------------------------------------------------------
    # SEZON 4 (GÜN 16): Güç Kaybı (Conviction Decay) -> GARAN Sinyali Söndü, Anında Sat!
    # -------------------------------------------------------------------------
    print("\n▶ [SEZON 4 / GÜN 16] Güç Kaybı (Conviction Decay Exit) ile Anında Satış:")
    garan_pos = orchestrator.portfolio.get_position("GARAN")
    garan_entry = garan_pos["avg_cost"]
    curr_garan_p = garan_entry * 1.05  # %5 kârda ama sinyal bitti

    garan_open_state = [
        OpenPositionState(
            ticker="GARAN",
            entry_price=garan_entry,
            current_price=curr_garan_p,
            highest_price=garan_entry * 1.08,
            entry_date="2026-01-06",
            holding_days=10,
            current_confidence=0.38,  # Güven çöktü (< 0.48)
            sector="BANK",
            quantity=garan_pos["quantity"],
        )
    ]

    exit_decisions_s4 = conviction_engine.evaluate_position_exits(
        positions=garan_open_state,
        current_scores={"GARAN": 0.38},
        current_prices={"GARAN": curr_garan_p},
    )
    d_garan = exit_decisions_s4[0]
    print(f"   GARAN Durumu: Model Güveni {d_garan.current_confidence} seviyesine geriledi.")
    print(f"   Motorun Kararı: {d_garan.action} ({d_garan.reason})")

    assert d_garan.action == ExitAction.FULL_EXIT

    # Orchestrator'da Satışı İcra Et
    exit_signal = [{
        "ticker": "GARAN",
        "direction": "SHORT",
        "model_version": "LambdaRank_v3_LOCKED",
    }]
    report_s4 = orchestrator.run_daily_cycle(
        date="2026-01-20",
        market_data=market_data,
        sector_map=sector_map,
        champion_signals=exit_signal,
        is_morning_execution=True,
    )
    positions_after_sell = orchestrator.portfolio.get_all_positions()
    pos_tickers_after_sell = [p["ticker"] for p in positions_after_sell]
    print(f"   Satış Sonrası Kalan Pozisyonlar: {pos_tickers_after_sell}")
    print(f"   T+2 Takas Havuzuna Aktarılan Para: {orchestrator.portfolio.unsettled_cash_t2:,.2f} TL")

    assert "GARAN" not in pos_tickers_after_sell
    assert "THYAO" in pos_tickers_after_sell  # Kazanan tutuldu, yorulan satıldı!

    # -------------------------------------------------------------------------
    # SEZON 5 (GÜN 25): Büyük Ralli -> 12 Hisseye Otonom Yayılma
    # -------------------------------------------------------------------------
    print("\n▶ [SEZON 5 / GÜN 25] Geniş Boğa Rallisi & 12+ Hisseye Yayılma Testi:")
    c_s5 = [
        CandidateAsset(t, confidence_score=0.78 + (i % 4) * 0.04, expected_return=0.55 + (i % 3) * 0.10, volatility=0.24, sector=sector_map[t])
        for i, t in enumerate(all_tickers[:14])
    ]
    plan_s5 = conviction_engine.allocate_conviction_portfolio(c_s5, market_regime="BULL")
    print(f"   Motorun Kararı : {plan_s5.rationale}")
    print(f"   Seçilen Hisse Sayısı: {plan_s5.num_positions} adet | Toplam Maruziyet: %{plan_s5.total_exposure*100:.1f}")

    assert plan_s5.num_positions >= 12
    assert plan_s5.total_exposure >= 0.85

    print("\n" + "=" * 80)
    print("🏆 TÜM GERÇEK MOTOR OTONOM TESTLERİ %100 BAŞARIYLA TAMAMLANDI!")
    print("=" * 80)


if __name__ == "__main__":
    run_real_engine_simulation()
