"""
ALPHA BIST — Canlı Piyasa Portföy Tahsis Raporu
"""
import time

import numpy as np

from services.portfolio.autonomous_conviction_engine import (
    AutonomousConvictionEngine,
    CandidateAsset,
)
from services.scanner.bist_ml_scanner import BistMLScanner


def run_live_allocation(total_capital: float = 1_000_000.0, regime: str = "SIDEWAYS"):
    t0 = time.time()
    scanner = BistMLScanner()
    opportunities = scanner.scan_all_opportunities(limit=100)
    dur = time.time() - t0

    candidates = []
    for op in opportunities:
        atr_pct = float(op.get("atr_pct", 3.0))
        vol_ratio = float(op.get("volume_ratio", 1.0))
        candidates.append(
            CandidateAsset(
                ticker=op["ticker"],
                confidence_score=float(op["score"]) / 100.0,
                expected_return=float(op["expected_return_pct"]) / 100.0,
                volatility=max(0.15, (atr_pct / 100.0) * 1.5),
                sector=op.get("sector", "OTHER"),
                rsi=float(op.get("rsi", 50.0)),
                volume_flow_score=float(np.clip(vol_ratio * 30.0, 10.0, 100.0)),
                current_price=float(op["price"]),
                strategy_type=op.get("strategy_type", "VOLUME_BREAKOUT"),
            )
        )

    engine = AutonomousConvictionEngine()
    plan = engine.allocate_conviction_portfolio(candidates, market_regime=regime)

    op_map = {op["ticker"]: op for op in opportunities}

    print("=========================================================================================")
    print(f"CANLI PİYASA PORTFÖY ALIM VE TAHSİS PLANI (BIST 647 HİSSE - {dur:.2f} sn)")
    print("=========================================================================================")
    print(f"Piyasa Rejimi          : {plan.market_regime}")
    print(f"Toplam Sermaye         : {total_capital:,.0f} TL")
    print(f"Hisselere Ayrılan Pay  : %{plan.total_exposure * 100:.1f} ({total_capital * plan.total_exposure:,.0f} TL)")
    print(f"Nakit Tamponu          : %{plan.cash_weight * 100:.1f} ({total_capital * plan.cash_weight:,.0f} TL)")
    print(f"Portföye Alınan Hisse  : {plan.num_positions} adet")
    print(f"Elenme Nedeni Olanlar  : {len(plan.rejected_tickers)} adet (Alfa barajı veya güven skoru yetersiz)")
    print("-----------------------------------------------------------------------------------------")
    print(f"{'HİSSE':<7} | {'STRATEJİ':<15} | {'PAY (%)':<8} | {'TUTAR (TL)':<12} | {'LOT':<8} | {'FİYAT':<8} | {'STOP-LOSS':<10} | {'HEDEF':<10} | {'BEKLENEN'}")
    print("-----------------------------------------------------------------------------------------")

    sorted_weights = sorted(plan.weights.items(), key=lambda x: x[1], reverse=True)
    for ticker, weight in sorted_weights:
        op = op_map.get(ticker, {})
        strat = op.get("strategy_type", "SWING")
        price = float(op.get("price", 0.0))
        stop_p = float(op.get("stop_loss", 0.0))
        target_p = float(op.get("target_price", 0.0))
        exp_ret = float(op.get("expected_return_pct", 0.0))
        tutar = total_capital * weight
        lot = int(tutar / price) if price > 0 else 0

        print(
            f"{ticker:<7} | {strat:<15} | %{weight*100:>6.2f} | {tutar:>10,.0f} TL | {lot:>8,} | "
            f"{price:>7.2f} TL | {stop_p:>8.2f} TL | {target_p:>8.2f} TL | +%{exp_ret:.1f}"
        )

    print("-----------------------------------------------------------------------------------------")
    print(f"NAKİT   | {'CASH_BUFFER':<15} | %{plan.cash_weight*100:>6.2f} | {total_capital*plan.cash_weight:>10,.0f} TL | -        | -        | -          | -          | Savunma")
    print("=========================================================================================\n")

if __name__ == "__main__":
    run_live_allocation()
