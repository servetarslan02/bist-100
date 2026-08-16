import pytest

from alpha_v4.risk import RiskAction, RiskPolicy, RiskRequest, evaluate_risk


def _policy():
    return RiskPolicy(
        policy_version="1.0",
        max_position_fraction=0.10,
        max_sector_fraction=0.30,
        max_gross_exposure_fraction=0.80,
        minimum_liquidity_score=0.50,
    )


def _request(**overrides):
    values = dict(
        instrument_id="inst-a",
        sector_id="sector-x",
        requested_notional=8_000.0,
        portfolio_equity=100_000.0,
        current_instrument_notional=0.0,
        current_sector_notional=10_000.0,
        current_gross_exposure=20_000.0,
        liquidity_score=0.80,
        data_integrity_ok=True,
        model_integrity_ok=True,
        kill_switch_active=False,
    )
    values.update(overrides)
    return RiskRequest(**values)


def test_risk_gate_approves_within_all_limits():
    decision = evaluate_risk(_request(), _policy())

    assert decision.action is RiskAction.APPROVE
    assert decision.approved_notional == pytest.approx(8_000.0)


def test_risk_gate_reduces_instead_of_ignoring_position_limit():
    decision = evaluate_risk(
        _request(requested_notional=8_000, current_instrument_notional=7_000),
        _policy(),
    )

    assert decision.action is RiskAction.REDUCE
    assert decision.approved_notional == pytest.approx(3_000.0)


def test_unknown_data_integrity_fails_closed():
    decision = evaluate_risk(_request(data_integrity_ok=None), _policy())

    assert decision.action is RiskAction.NO_TRADE
    assert decision.approved_notional == 0
    assert "data_integrity_unresolved" in decision.reasons


def test_unknown_risk_state_fails_closed_instead_of_using_defaults():
    decision = evaluate_risk(_request(current_sector_notional=None), _policy())

    assert decision.action is RiskAction.NO_TRADE
    assert any(reason.startswith("missing_risk_state") for reason in decision.reasons)


def test_kill_switch_cannot_be_overridden_by_model_integrity():
    decision = evaluate_risk(
        _request(kill_switch_active=True, model_integrity_ok=True),
        _policy(),
    )

    assert decision.action is RiskAction.NO_TRADE
    assert "kill_switch_active" in decision.reasons


def test_low_liquidity_is_no_trade():
    decision = evaluate_risk(_request(liquidity_score=0.2), _policy())

    assert decision.action is RiskAction.NO_TRADE
    assert decision.reasons == ("liquidity_below_policy",)
