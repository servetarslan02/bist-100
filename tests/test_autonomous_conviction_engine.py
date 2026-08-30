"""
ALPHA BIST — Test Suite for Autonomous Conviction & Dynamic Profit-Running Engine
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.portfolio.autonomous_conviction_engine import (
    AutonomousConvictionEngine,
    CandidateAsset,
    ExitAction,
    OpenPositionState,
)
from services.portfolio.portfolio_optimizer import (
    OptimizationMethod,
    PortfolioOptimizer,
)


def test_zero_candidates_100_percent_cash():
    """Piyasada alfa yokken veya güven düşkken 0 hisse alıp %100 nakitte kalma testi."""
    engine = AutonomousConvictionEngine(base_hurdle_rate=0.40, min_entry_confidence=0.65)

    candidates = [
        CandidateAsset(ticker="GARAN", confidence_score=0.50, expected_return=0.20, volatility=0.30, sector="BANK"),
        CandidateAsset(ticker="THYAO", confidence_score=0.60, expected_return=0.35, volatility=0.35, sector="TRANS"),
        CandidateAsset(ticker="EREGL", confidence_score=0.45, expected_return=0.10, volatility=0.28, sector="STEEL"),
    ]

    plan = engine.allocate_conviction_portfolio(candidates, market_regime="SIDEWAYS")

    assert plan.num_positions == 0
    assert plan.cash_weight == 1.0
    assert plan.total_exposure == 0.0
    assert len(plan.selected_tickers) == 0
    assert len(plan.rejected_tickers) == 3
    print("  [PASS] test_zero_candidates_100_percent_cash")


def test_concentrated_three_winners():
    """Piyasada sadece 3 süper fırsat varken zorla 8 almayıp sadece 3 hisseye yoğunlaşma testi."""
    engine = AutonomousConvictionEngine(base_hurdle_rate=0.35, min_entry_confidence=0.65)

    candidates = [
        # Süper fırsatlar (Barajı geçenler)
        CandidateAsset(ticker="GARAN", confidence_score=0.92, expected_return=0.75, volatility=0.25, sector="BANK"),
        CandidateAsset(ticker="THYAO", confidence_score=0.88, expected_return=0.65, volatility=0.28, sector="TRANS"),
        CandidateAsset(ticker="BIMAS", confidence_score=0.82, expected_return=0.55, volatility=0.20, sector="RETAIL"),
        # Barajı geçemeyen vasatlar
        CandidateAsset(ticker="EREGL", confidence_score=0.55, expected_return=0.30, volatility=0.35, sector="STEEL"),
        CandidateAsset(ticker="SISE", confidence_score=0.40, expected_return=0.20, volatility=0.30, sector="GLASS"),
        CandidateAsset(ticker="ASELS", confidence_score=0.62, expected_return=0.40, volatility=0.32, sector="DEFENSE"),
    ]

    plan = engine.allocate_conviction_portfolio(candidates, market_regime="SIDEWAYS")

    assert plan.num_positions == 3
    assert set(plan.selected_tickers) == {"GARAN", "THYAO", "BIMAS"}
    # En yüksek güvenli GARAN en yüksek payı almalı
    assert plan.weights["GARAN"] >= plan.weights["THYAO"] >= plan.weights["BIMAS"]
    assert plan.weights["GARAN"] > 0.15  # Tek hissede güçlü ağırlık
    assert plan.cash_weight > 0.0  # Nakit tamponu korunmalı
    print("  [PASS] test_concentrated_three_winners")


def test_broad_sixteen_stock_rally():
    """Geniş BIST boğa rallisinde 16 hisseye yayılma ve sektör tavanı testi."""
    engine = AutonomousConvictionEngine(base_hurdle_rate=0.30, min_entry_confidence=0.60)

    sectors = ["BANK", "TRANS", "STEEL", "RETAIL", "ENERGY"]
    candidates = []
    for i in range(16):
        ticker = f"STOCK_{i:02d}"
        sec = sectors[i % len(sectors)]
        candidates.append(
            CandidateAsset(
                ticker=ticker,
                confidence_score=0.75 + (i % 5) * 0.04,  # 0.75 - 0.91
                expected_return=0.50 + (i % 4) * 0.10,  # 0.50 - 0.80
                volatility=0.25,
                sector=sec,
            )
        )

    plan = engine.allocate_conviction_portfolio(candidates, market_regime="BULL")

    assert plan.num_positions >= 14
    assert plan.total_exposure >= 0.85  # Boğada yüksek maruziyet
    # Sektör tavanı kontrolü (%35'i geçemez)
    sector_sums = {}
    for t, w in plan.weights.items():
        sec = next(c.sector for c in candidates if c.ticker == t)
        sector_sums[sec] = sector_sums.get(sec, 0.0) + w
    for sec, sum_w in sector_sums.items():
        assert sum_w <= 0.3501, f"Sektör tavanı aşıldı: {sec} = {sum_w}"
    print("  [PASS] test_broad_sixteen_stock_rally")


def test_let_winners_run_profit_holding():
    """Kârı devam eden ve sinyali güçlü hisseyi gün kısıtına bakmadan tutma testi."""
    engine = AutonomousConvictionEngine(trailing_stop_pct=0.06)

    position = OpenPositionState(
        ticker="THYAO",
        entry_price=100.0,
        current_price=125.0,  # %25 Kârda
        highest_price=125.0,
        entry_date="2026-01-05",
        holding_days=45,  # 45 gündür taşınıyor (takvim engeline takılmamalı)
        current_confidence=0.88,  # Güçlü güven devam ediyor
        sector="TRANS",
    )

    decisions = engine.evaluate_position_exits(
        positions=[position],
        current_scores={"THYAO": 0.88},
        current_prices={"THYAO": 125.0},
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == ExitAction.HOLD_AND_RUN
    assert d.unrealized_pnl_pct == 0.25
    # Trailing stop fiyatı 125 * 0.94 = 117.5 TL'ye yükseltilmiş olmalı
    assert d.trailing_stop_price == 117.5
    print("  [PASS] test_let_winners_run_profit_holding")


def test_conviction_decay_exit():
    """Gücü ve güven skoru biten hisseyi periyot beklemeden anında satma testi."""
    engine = AutonomousConvictionEngine(exit_confidence_threshold=0.48)

    position = OpenPositionState(
        ticker="EREGL",
        entry_price=50.0,
        current_price=52.0,  # %4 Kârda
        highest_price=54.0,
        entry_date="2026-02-01",
        holding_days=3,  # Henüz 3. gün ama sinyali söndü
        current_confidence=0.40,  # Güven skoru 0.40'a çöktü
        sector="STEEL",
    )

    decisions = engine.evaluate_position_exits(
        positions=[position],
        current_scores={"EREGL": 0.40},
        current_prices={"EREGL": 52.0},
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == ExitAction.FULL_EXIT
    assert "Güveni Çöktü" in d.reason
    print("  [PASS] test_conviction_decay_exit")


def test_trailing_stop_breach_exit():
    """Tepeden %6 geri çekilmede kârı kilitleyip çıkma testi."""
    engine = AutonomousConvictionEngine(trailing_stop_pct=0.06)

    position = OpenPositionState(
        ticker="GARAN",
        entry_price=100.0,
        current_price=112.0,  # 120 TL zirvesinden 112 TL'ye (%6.6) düştü
        highest_price=120.0,
        entry_date="2026-01-10",
        holding_days=15,
        current_confidence=0.80,
        trailing_stop_price=112.8,  # 120 * 0.94 = 112.8 TL
        sector="BANK",
    )

    decisions = engine.evaluate_position_exits(
        positions=[position],
        current_scores={"GARAN": 0.80},
        current_prices={"GARAN": 112.0},
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == ExitAction.FULL_EXIT
    assert "Trailing Stop Vuruldu" in d.reason
    print("  [PASS] test_trailing_stop_breach_exit")


def test_parabolic_trim_profit():
    """Aşırı primlenen hissede (%40+ kâr) kısmi kâr alma (Trim) testi."""
    engine = AutonomousConvictionEngine()

    position = OpenPositionState(
        ticker="SISE",
        entry_price=40.0,
        current_price=58.0,  # %45 Kâr
        highest_price=58.0,
        entry_date="2026-01-01",
        holding_days=20,
        current_confidence=0.70,  # Normal seviyede
        sector="GLASS",
    )

    decisions = engine.evaluate_position_exits(
        positions=[position],
        current_scores={"SISE": 0.70},
        current_prices={"SISE": 58.0},
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == ExitAction.TRIM_PROFIT
    assert d.suggested_trim_ratio == 0.40
    print("  [PASS] test_parabolic_trim_profit")


def test_hard_stop_loss():
    """%7 zarar eşiğinde katı stop-loss tetiklenme testi."""
    engine = AutonomousConvictionEngine()

    position = OpenPositionState(
        ticker="AKBNK",
        entry_price=100.0,
        current_price=92.0,  # -%8 Zarar
        highest_price=100.0,
        entry_date="2026-02-10",
        holding_days=2,
        current_confidence=0.75,
        sector="BANK",
    )

    decisions = engine.evaluate_position_exits(
        positions=[position],
        current_scores={"AKBNK": 0.75},
        current_prices={"AKBNK": 92.0},
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == ExitAction.STOP_LOSS
    assert "Zarar Kes" in d.reason
    print("  [PASS] test_hard_stop_loss")


def test_dynamic_hurdle_rate_regime_sensitivity():
    """Rejimlere göre alfa barajının dinamik esneme testi."""
    engine = AutonomousConvictionEngine(base_hurdle_rate=0.35)

    hr_bull = engine.compute_dynamic_hurdle_rate("BULL")
    hr_sideways = engine.compute_dynamic_hurdle_rate("SIDEWAYS")
    hr_bear = engine.compute_dynamic_hurdle_rate("BEAR")
    hr_crisis = engine.compute_dynamic_hurdle_rate("CRISIS")

    assert hr_bull < hr_sideways < hr_bear < hr_crisis
    assert hr_crisis >= 0.75  # Krizde hisse almak için devasa getiri şart
    print("  [PASS] test_dynamic_hurdle_rate_regime_sensitivity")


def test_portfolio_optimizer_autonomous_integration():
    """PortfolioOptimizer sınıfına AUTONOMOUS_CONVICTION metodunun entegrasyon testi."""
    opt = PortfolioOptimizer()
    tickers = ["GARAN", "AKBNK", "THYAO", "BIMAS"]
    np.random.seed(42)
    rets = np.random.normal(0.001, 0.02, (100, 4))
    exp_rets = np.array([0.50, 0.40, 0.65, 0.35])

    res = opt.optimize(
        tickers=tickers,
        returns_matrix=rets,
        method=OptimizationMethod.AUTONOMOUS_CONVICTION,
        expected_returns=exp_rets,
        sector_map={"GARAN": "BANK", "AKBNK": "BANK", "THYAO": "TRANS", "BIMAS": "RETAIL"},
    )

    assert res.is_optimal is True
    assert len(res.weights) > 0
    # En yüksek getiri beklentili THYAO (0.65) en yüksek ağırlığı almalı
    assert res.weights.get("THYAO", 0.0) >= res.weights.get("BIMAS", 0.0)
    print("  [PASS] test_portfolio_optimizer_autonomous_integration")


if __name__ == "__main__":
    print("Running Autonomous Conviction Engine Test Suite...")
    test_zero_candidates_100_percent_cash()
    test_concentrated_three_winners()
    test_broad_sixteen_stock_rally()
    test_let_winners_run_profit_holding()
    test_conviction_decay_exit()
    test_trailing_stop_breach_exit()
    test_parabolic_trim_profit()
    test_hard_stop_loss()
    test_dynamic_hurdle_rate_regime_sensitivity()
    test_portfolio_optimizer_autonomous_integration()
    print("\nALL 10/10 Autonomous Conviction & Profit-Running tests PASSED!")
