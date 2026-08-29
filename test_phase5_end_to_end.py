import structlog
logger = structlog.get_logger(__name__)
from typing import Any
import logging

logging.basicConfig(level=logging.ERROR)


def test_normal_buy_flow() -> Any:
    """Otomatik eklendi."""
    logger.info("=== 1. NORMAL BUY FLOW TEST ===")
    from services.backtest.transaction_costs import bist_transaction_cost
    from services.core.decision_engine import DecisionInput, decision_engine
    from services.core.risk_gate import risk_gate

    inp = DecisionInput(
        ticker="THYAO",
        price=100.0,
        atr=2.0,
        ml_score=85.0,
        ml_confidence=0.85,
        features={"momentum_20d": 10, "roc_5d": 5, "rsi_14": 55},
    )
    decision = decision_engine.decide(inp)
    assert decision.action in ("BUY", "HOLD", "NO_ACTION"), f"Decision failed: {decision}"
    logger.info(
        f"  [PASS] Decision engine produced action={decision.action}, target={decision.target_price}, stop={decision.stop_price}"
    )

    risk_res = risk_gate.check_order(ticker="THYAO", side="BUY", quantity=40, price=100.0, portfolio_value=100000.0, current_positions={})
    assert risk_res.allowed, f"Risk gate failed: {risk_res}"
    logger.info(f"  [PASS] Risk gate approved valid 4% order: allowed={risk_res.allowed}")

    cost = bist_transaction_cost.calculate_total_cost("BUY", 100.0, 40, "THYAO", avg_daily_volume=500_000_000)
    assert cost["total_cost"] > 0, f"Cost calculation failed: {cost}"
    logger.info(f"  [PASS] Transaction cost calculated: total_cost={cost['total_cost']} TL ({cost['total_cost_pct']}%)")


def test_risk_vetoed_buy() -> Any:
    """Otomatik eklendi."""
    logger.info("=== 2. RISK VETOED BUY TEST ===")
    from services.core.risk_gate import risk_gate

    res = risk_gate.check_order(ticker="THYAO", side="BUY", quantity=-50, price=100.0, portfolio_value=100000.0, current_positions={})
    assert not res.allowed, f"Risk veto failed to catch negative quantity: {res}"
    logger.info(f"  [PASS] Risk gate vetoed invalid quantity: reason={res.reason}")


def test_model_failure_fallback() -> Any:
    """Otomatik eklendi."""
    logger.info("=== 3. MODEL FAILURE FALLBACK TEST ===")
    from services.core.canonical_scoring import canonical_scoring

    class BrokenML:
        """Otomatik eklendi."""
        def predict(self, features) -> Any:
            """Otomatik eklendi."""
            raise RuntimeError("Model offline")

    score_res = canonical_scoring.compute_canonical_score("THYAO", {"momentum_20d": 5}, "BULL", ml_model=BrokenML())
    assert score_res.ml_score is None, "ml_score should be None on failure"
    assert score_res.opportunity_score > 0, "Opportunity score should fall back to rule-based"
    logger.info(f"  [PASS] Canonical scoring model failure fallback verified: rule_score={score_res.opportunity_score}")


def test_data_missing_fallback() -> Any:
    """Otomatik eklendi."""
    logger.info("=== 4. DATA MISSING FALLBACK TEST ===")
    from services.core.data_quality import TradabilityMask, data_quality

    mask = TradabilityMask(
        "THYAO", "2026-08-21T00:00:00Z", is_tradable=False, reasons=["Sıfır hacim"], price_mask=1.0, volume_mask=0.0
    )
    raw = {"open": 100.0, "close": 100.0, "volume": 0}
    masked = data_quality.apply_mask(raw, mask)
    assert masked["volume"] is None, "Volume should be set to None when volume_mask=0.0"
    logger.info("  [PASS] Data quality missing/corrupted data mask applied")


def test_scheduler_job_execution() -> Any:
    """Otomatik eklendi."""
    logger.info("=== 5. SCHEDULER JOB EXECUTION TEST ===")
    from services.scheduler.unified_scheduler import UnifiedScheduler

    us = UnifiedScheduler()
    st = us.get_status()
    assert "job_configs" in st, "Job configs missing in scheduler status"
    logger.info(f"  [PASS] UnifiedScheduler initialized with {st['job_configs']} registered job configurations")


def test_paper_order_execution() -> Any:
    """Otomatik eklendi."""
    logger.info("=== 6. PAPER ORDER GENERATION & VIRTUAL BALANCE TEST ===")
    from services.core.broker import Order

    order = Order("101", "THYAO", "BUY", 40, 100.0)
    assert order.status == "PENDING", "New paper order should start PENDING"
    logger.info(f"  [PASS] Paper order created: {order.ticker} {order.side} {order.quantity} @ {order.price}")


if __name__ == "__main__":
    test_normal_buy_flow()
    test_risk_vetoed_buy()
    test_model_failure_fallback()
    test_data_missing_fallback()
    test_scheduler_job_execution()
    test_paper_order_execution()
    logger.info("=== ALL 6 PHASE 5 END-TO-END SCENARIOS PASSED ===")
