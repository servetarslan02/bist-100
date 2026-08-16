from datetime import datetime, timezone

import pytest

from alpha_v4.audit import AuditLedger
from alpha_v4.paper_engine import PaperDecisionRequest, PaperEngine
from alpha_v4.paper_ledger import PaperLedger
from alpha_v4.risk import RiskAction, RiskPolicy, RiskRequest

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def policy():
    return RiskPolicy(
        policy_version="1.0",
        max_position_fraction=0.10,
        max_sector_fraction=0.30,
        max_gross_exposure_fraction=0.80,
        minimum_liquidity_score=0.50,
    )


def build_request(*, requested=8_000.0, current_position=0.0, data_ok=True):
    return PaperDecisionRequest(
        decision_id="decision-1",
        account_id="paper-1",
        instrument_id="inst-a",
        ticker="AAA",
        model_id="model-validated",
        price=100.0,
        requested_notional=requested,
        commission_bps=10.0,
        state_snapshot_ids=("market-state-1", "asset-state-1"),
        feature_refs=("momentum@1", "relative_strength@1"),
        risk_request=RiskRequest(
            instrument_id="inst-a",
            sector_id="sector-x",
            requested_notional=requested,
            portfolio_equity=100_000.0,
            current_instrument_notional=current_position,
            current_sector_notional=10_000.0,
            current_gross_exposure=20_000.0,
            liquidity_score=0.8,
            data_integrity_ok=data_ok,
            model_integrity_ok=True,
        ),
    )


def engine(tmp_path, *, initial_cash=100_000.0):
    database = tmp_path / "alpha.sqlite3"
    ledger = PaperLedger(database)
    ledger.deposit("paper-1", initial_cash, event_time=T0)
    return (
        PaperEngine(
            ledger=ledger,
            audit=AuditLedger(database),
            risk_policy=policy(),
        ),
        ledger,
        AuditLedger(database),
    )


def test_no_trade_risk_decision_never_creates_fill(tmp_path):
    paper, ledger, audit = engine(tmp_path)

    result = paper.submit_buy(build_request(data_ok=None), event_time=T0)

    assert result.status == "NO_TRADE"
    assert result.fill_event_id is None
    assert result.risk.action is RiskAction.NO_TRADE
    assert ledger.reconstruct("paper-1").event_count == 1  # deposit only
    assert [entry.event_type for entry in audit.entries()] == [
        "DECISION_CREATED",
        "RISK_DECISION",
    ]
    assert audit.verify_chain().valid


def test_reduce_risk_decision_only_fills_approved_notional(tmp_path):
    paper, ledger, audit = engine(tmp_path)

    result = paper.submit_buy(
        build_request(requested=8_000.0, current_position=7_000.0),
        event_time=T0,
    )
    account = ledger.reconstruct("paper-1")

    assert result.status == "PAPER_FILLED"
    assert result.risk.action is RiskAction.REDUCE
    assert result.risk.approved_notional == pytest.approx(3_000.0)
    assert result.simulated_quantity == pytest.approx(30.0)
    assert account.positions["AAA"].quantity == pytest.approx(30.0)
    assert audit.entries()[-1].event_type == "PAPER_FILL_RECORDED"
    assert audit.verify_chain().valid


def test_approved_risk_still_cannot_overdraw_paper_cash(tmp_path):
    paper, ledger, audit = engine(tmp_path, initial_cash=1_000.0)

    result = paper.submit_buy(build_request(requested=8_000.0), event_time=T0)

    assert result.risk.action is RiskAction.APPROVE
    assert result.status == "FILL_REJECTED"
    assert result.fill_event_id is None
    assert ledger.reconstruct("paper-1").event_count == 1
    assert audit.entries()[-1].event_type == "PAPER_FILL_REJECTED"
    assert audit.verify_chain().valid


def test_request_lineage_must_match_risk_request():
    request = build_request()
    mismatched = RiskRequest(
        instrument_id="other",
        sector_id=request.risk_request.sector_id,
        requested_notional=request.requested_notional,
        portfolio_equity=100_000,
        current_instrument_notional=0,
        current_sector_notional=0,
        current_gross_exposure=0,
        liquidity_score=1,
        data_integrity_ok=True,
        model_integrity_ok=True,
    )

    with pytest.raises(ValueError, match="instrument mismatch"):
        PaperDecisionRequest(
            decision_id=request.decision_id,
            account_id=request.account_id,
            instrument_id=request.instrument_id,
            ticker=request.ticker,
            model_id=request.model_id,
            price=request.price,
            requested_notional=request.requested_notional,
            commission_bps=request.commission_bps,
            state_snapshot_ids=request.state_snapshot_ids,
            feature_refs=request.feature_refs,
            risk_request=mismatched,
        )
