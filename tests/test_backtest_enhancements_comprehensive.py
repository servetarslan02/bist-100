"""
ALPHA BIST — Backtest Enhancements Comprehensive Test Suite

BacktestEnhancements, MarketImpact, ExecutionResult, CorporateAction sınıflarının
T+1 takas gecikmesi, market impact hesabı (square-root / participation rate),
delisted hisse yönetimi, IPO sonrası işlem kısıtı, temettü/bölünme düzeltmeleri
ve likidite kontrollerini doğrular.
"""

from __future__ import annotations

import concurrent.futures

from services.backtest.backtest_enhancements import (
    BacktestEnhancements,
    CorporateAction,
    ExecutionResult,
    MarketImpact,
    backtest_enhancements,
)


def test_market_impact_and_execution_result_repr() -> None:
    """MarketImpact ve ExecutionResult nesnelerinin repr doğrulaması."""
    impact = MarketImpact(
        ticker="THYAO",
        trade_size=500_000.0,
        adv=10_000_000.0,
        participation_rate=0.05,
        temporary_impact_pct=0.22,
        permanent_impact_pct=0.025,
        total_impact_pct=0.245,
        is_feasible=True,
    )
    assert "THYAO" in repr(impact)
    assert "impact=0.24%" in repr(impact)

    res = ExecutionResult(
        ticker="ASELS",
        signal_date="2025-01-01",
        execution_date="2025-01-02",
        delay_days=1,
        price_change_pct=0.0,
        can_execute=True,
        reason="T+1",
    )
    assert "ASELS" in repr(res)
    assert "2025-01-01→2025-01-02" in repr(res)


def test_corporate_action_repr() -> None:
    """CorporateAction nesnesi dize temsili testi."""
    ca = CorporateAction(
        ticker="GARAN",
        action_type="dividend",
        ex_date="2025-04-15",
        value=3.50,
        description="Nakit temettü",
    )
    assert "GARAN" in repr(ca)
    assert "dividend" in repr(ca)


def test_t_plus_1_execution_and_weekends() -> None:
    """T+1 kuralı, hafta sonu atlama ve delisted hisse kontrolleri."""
    enh = BacktestEnhancements()

    # Hafta içi: Çarşamba (2025-01-08) -> Perşembe (2025-01-09)
    res_midweek = enh.check_t_plus_1("THYAO", "2025-01-08")
    assert res_midweek.can_execute is True
    assert res_midweek.execution_date == "2025-01-09"
    assert res_midweek.delay_days == 1

    # Hafta sonu: Cuma (2025-01-10) -> Pazartesi (2025-01-13)
    res_weekend = enh.check_t_plus_1("THYAO", "2025-01-10")
    assert res_weekend.can_execute is True
    assert res_weekend.execution_date == "2025-01-13"
    assert res_weekend.delay_days == 3

    # Delisted hisse engeli
    enh.register_delisted("OLDSTK", "2025-01-05")
    res_delist = enh.check_t_plus_1("OLDSTK", "2025-01-08")
    assert res_delist.can_execute is False
    assert "delisted" in res_delist.reason

    # Hatalı tarih formatı
    res_err = enh.check_t_plus_1("THYAO", "invalid-date")
    assert res_err.can_execute is False
    assert "Geçersiz tarih" in res_err.reason


def test_estimate_market_impact() -> None:
    """Piyasa etkisi (market impact) matematiksel model doğrulaması."""
    enh = BacktestEnhancements(max_participation_rate=0.10, market_impact_coefficient=0.1)

    # ADV sıfır veya negatif durumu
    zero_adv = enh.estimate_market_impact("BIMAS", 100_000.0, 0.0)
    assert zero_adv.is_feasible is False
    assert zero_adv.total_impact_pct == 0.0

    # Normal işlem (%5 katılım oranı)
    # trade = 500k, adv = 10m -> part = 0.05
    # temp = 0.1 * sqrt(0.05) * 100 = ~2.236%
    # perm = 0.1 * 0.05 / 2 * 100 = 0.25%
    # total = ~2.486%
    impact = enh.estimate_market_impact("BIMAS", 500_000.0, 10_000_000.0)
    assert impact.is_feasible is True
    assert impact.participation_rate == 0.05
    assert 2.0 <= impact.total_impact_pct <= 3.0

    # Aşırı hacim katılımı (%15 > %10 limit)
    over_impact = enh.estimate_market_impact("BIMAS", 1_500_000.0, 10_000_000.0)
    assert over_impact.is_feasible is False
    assert over_impact.participation_rate == 0.15


def test_ipo_and_delisting_registry() -> None:
    """IPO takibi ve gün kısıtlaması doğrulaması."""
    enh = BacktestEnhancements()
    enh.register_ipo("NEWIPO", "2025-01-01")

    # 10 gün sonra (30 gün altı) -> False
    assert enh.is_post_ipo("NEWIPO", "2025-01-11", min_days=30) is False
    # 40 gün sonra -> True
    assert enh.is_post_ipo("NEWIPO", "2025-02-10", min_days=30) is True

    # Kaydı olmayan hisse için varsayılan True
    assert enh.is_post_ipo("REGULAR", "2025-01-10") is True

    # Delist sorgusu
    enh.register_delisted("DELIST_CO", "2025-03-01")
    assert enh.is_delisted("DELIST_CO", "2025-02-28") is False
    assert enh.is_delisted("DELIST_CO", "2025-03-01") is True
    assert enh.is_delisted("UNKNOWN", "2025-03-01") is False


def test_corporate_actions_and_adjustments() -> None:
    """Temettü, bedelli/bedelsiz bölünme düzeltmeleri testi."""
    enh = BacktestEnhancements()

    # Temettü düşüşü
    adj_div = enh.adjust_for_dividend(price=100.0, dividend=5.0)
    assert adj_div == 95.0
    assert enh.adjust_for_dividend(price=100.0, dividend=0.0) == 100.0

    # Bölünme (1'e 2 bölünme)
    adj_split = enh.adjust_for_split(price=200.0, ratio=2.0)
    assert adj_split == 100.0
    assert enh.adjust_for_split(price=200.0, ratio=0.0) == 200.0

    # Şirket olayları listeleme
    ca1 = CorporateAction("THYAO", "dividend", "2025-05-15", 4.0, "Temettü")
    ca2 = CorporateAction("THYAO", "split", "2025-06-20", 2.0, "Bölünme")
    ca3 = CorporateAction("ASELS", "dividend", "2025-05-15", 1.0, "Temettü")

    enh.register_corporate_action(ca1)
    enh.register_corporate_action(ca2)
    enh.register_corporate_action(ca3)

    actions = enh.get_corporate_actions("THYAO", "2025-05-01", "2025-05-30")
    assert len(actions) == 1
    assert actions[0].action_type == "dividend"

    # Tarih formatı hatası
    assert enh.get_corporate_actions("THYAO", "bad-date", "bad-date") == []


def test_liquidity_constraints_and_summary() -> None:
    """Likidite denetimi ve get_summary çıktısı."""
    enh = BacktestEnhancements(min_adv_threshold=1_000_000.0, max_participation_rate=0.10)

    # Yetersiz ADV
    ok_adv, r_adv = enh.check_liquidity("LOW_VOL", adv=500_000.0, trade_size=10_000.0)
    assert ok_adv is False
    assert "minimum eşiğin" in r_adv

    # Aşırı katılım oranı
    ok_part, r_part = enh.check_liquidity("HIGH_VOL", adv=2_000_000.0, trade_size=300_000.0)
    assert ok_part is False
    assert "maksimumun" in r_part

    # Yeterli likidite
    ok_good, _ = enh.check_liquidity("GOOD_VOL", adv=5_000_000.0, trade_size=100_000.0)
    assert ok_good is True

    summary = enh.get_summary()
    assert "delisted_stocks" in summary
    assert "max_participation_rate" in summary
    assert repr(backtest_enhancements).startswith("BacktestEnhancements")


def test_backtest_enhancements_thread_safety() -> None:
    """Eşzamanlı thread'lerde delist, IPO ve corporate action kayıt güvenliği."""
    enh = BacktestEnhancements()

    def _task(i: int) -> None:
        enh.register_delisted(f"DEL_{i}", f"2025-01-{i + 1:02d}")
        enh.register_ipo(f"IPO_{i}", f"2025-02-{i + 1:02d}")
        enh.register_corporate_action(
            CorporateAction(f"SYM_{i}", "dividend", f"2025-03-{i + 1:02d}", 1.0, "Test")
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_task, i) for i in range(10)]
        for f in futures:
            f.result()

    summary = enh.get_summary()
    assert summary["delisted_stocks"] == 10
    assert summary["ipo_dates"] == 10
    assert summary["corporate_actions"] == 10
