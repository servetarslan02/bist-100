from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.paper_ledger import (
    InsufficientCashError,
    InsufficientPositionError,
    MissingMarkError,
    PaperLedger,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _fill(ledger, account, *, side, quantity, price, commission, minutes):
    return ledger.record_fill(
        account,
        ticker="AAA",
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        event_time=T0 + timedelta(minutes=minutes),
        decision_id=f"decision-{minutes}",
        risk_decision_id=f"risk-{minutes}",
        model_id="paper-model",
    )


def test_paper_ledger_reconstructs_cash_cost_basis_and_pnl_after_restart(tmp_path):
    db = tmp_path / "paper.sqlite3"
    ledger = PaperLedger(db)
    ledger.deposit("paper-1", 1000.0, event_time=T0)
    _fill(ledger, "paper-1", side="BUY", quantity=5, price=100, commission=5, minutes=1)

    state = PaperLedger(db).reconstruct("paper-1")
    position = state.positions["AAA"]

    assert state.cash == pytest.approx(495.0)
    assert position.quantity == pytest.approx(5.0)
    assert position.average_cost == pytest.approx(101.0)
    assert state.fees_paid == pytest.approx(5.0)

    marked = PaperLedger(db).mark_to_market("paper-1", {"AAA": 110.0})
    assert marked.market_value == pytest.approx(550.0)
    assert marked.equity == pytest.approx(1045.0)
    assert marked.unrealized_pnl == pytest.approx(45.0)

    _fill(
        PaperLedger(db),
        "paper-1",
        side="SELL",
        quantity=2,
        price=120,
        commission=2,
        minutes=2,
    )
    after_sell = PaperLedger(db).reconstruct("paper-1")

    assert after_sell.cash == pytest.approx(733.0)
    assert after_sell.positions["AAA"].quantity == pytest.approx(3.0)
    assert after_sell.positions["AAA"].average_cost == pytest.approx(101.0)
    assert after_sell.realized_pnl == pytest.approx(36.0)
    assert after_sell.fees_paid == pytest.approx(7.0)


def test_buy_fill_fails_closed_when_cash_is_insufficient(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    ledger.deposit("paper-1", 100.0, event_time=T0)

    with pytest.raises(InsufficientCashError):
        _fill(
            ledger,
            "paper-1",
            side="BUY",
            quantity=2,
            price=100,
            commission=1,
            minutes=1,
        )

    assert ledger.reconstruct("paper-1").event_count == 1


def test_sell_fill_fails_closed_when_position_is_insufficient(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    ledger.deposit("paper-1", 1000.0, event_time=T0)
    _fill(ledger, "paper-1", side="BUY", quantity=1, price=100, commission=0, minutes=1)

    with pytest.raises(InsufficientPositionError):
        _fill(
            ledger,
            "paper-1",
            side="SELL",
            quantity=2,
            price=110,
            commission=0,
            minutes=2,
        )

    assert ledger.reconstruct("paper-1").positions["AAA"].quantity == pytest.approx(1.0)


def test_mark_to_market_never_substitutes_average_cost_for_missing_live_mark(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    ledger.deposit("paper-1", 1000.0, event_time=T0)
    _fill(ledger, "paper-1", side="BUY", quantity=1, price=100, commission=0, minutes=1)

    with pytest.raises(MissingMarkError):
        ledger.mark_to_market("paper-1", {})


def test_all_fills_require_decision_risk_and_model_lineage(tmp_path):
    ledger = PaperLedger(tmp_path / "paper.sqlite3")
    ledger.deposit("paper-1", 1000.0, event_time=T0)

    with pytest.raises(ValueError, match="decision_id"):
        ledger.record_fill(
            "paper-1",
            ticker="AAA",
            side="BUY",
            quantity=1,
            price=100,
            commission=0,
            event_time=T0 + timedelta(minutes=1),
            decision_id="",
            risk_decision_id="risk-1",
            model_id="model-1",
        )
