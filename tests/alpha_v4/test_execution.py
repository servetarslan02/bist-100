import pytest

from alpha_v4.execution import (
    ExecutionPolicy,
    ExecutionSimulator,
    MarketExecutionState,
)


def simulator():
    return ExecutionSimulator(
        ExecutionPolicy(
            policy_version="1.0",
            commission_bps=10.0,
            base_slippage_bps=5.0,
            max_volume_participation=0.10,
            minimum_notional=0.0,
        )
    )


def market(**overrides):
    values = dict(
        bid=99.0,
        ask=101.0,
        last=100.0,
        available_volume=1_000.0,
        data_integrity_ok=True,
    )
    values.update(overrides)
    return MarketExecutionState(**values)


def test_buy_fill_pays_spread_slippage_and_commission():
    fill = simulator().simulate_market_order(
        side="BUY",
        requested_quantity=50.0,
        market=market(),
    )

    expected_price = 101.0 * 1.0005
    assert fill.status == "FILLED"
    assert fill.filled_quantity == pytest.approx(50.0)
    assert fill.fill_price == pytest.approx(expected_price)
    assert fill.spread_cost == pytest.approx(50.0)
    assert fill.slippage_cost == pytest.approx((expected_price - 101.0) * 50.0)
    assert fill.commission == pytest.approx(50.0 * expected_price * 0.001)


def test_liquidity_participation_causes_partial_fill():
    fill = simulator().simulate_market_order(
        side="BUY",
        requested_quantity=500.0,
        market=market(available_volume=1_000.0),
    )

    assert fill.status == "PARTIAL_FILL"
    assert fill.filled_quantity == pytest.approx(100.0)


def test_missing_quote_is_no_fill_not_fake_last_price_fill():
    fill = simulator().simulate_market_order(
        side="BUY",
        requested_quantity=10.0,
        market=market(bid=None, ask=None, last=100.0),
    )

    assert fill.status == "NO_FILL"
    assert fill.fill_price is None
    assert fill.reasons == ("missing_bid_ask",)


def test_missing_liquidity_is_no_fill():
    fill = simulator().simulate_market_order(
        side="SELL",
        requested_quantity=10.0,
        market=market(available_volume=None),
    )

    assert fill.status == "NO_FILL"
    assert fill.reasons == ("missing_liquidity",)


def test_bad_market_data_fails_closed():
    fill = simulator().simulate_market_order(
        side="BUY",
        requested_quantity=10.0,
        market=market(data_integrity_ok=False),
    )

    assert fill.status == "NO_FILL"
    assert fill.reasons == ("market_data_integrity_failed",)


def test_invalid_crossed_quote_is_rejected():
    fill = simulator().simulate_market_order(
        side="BUY",
        requested_quantity=10.0,
        market=market(bid=102.0, ask=101.0),
    )

    assert fill.status == "NO_FILL"
    assert fill.reasons == ("invalid_quote",)
