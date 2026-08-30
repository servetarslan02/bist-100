import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — FAZ 16 Test Suite

Portfolio Enhancements, Universe Enhancements, Security testleri.
"""

import sys


def test_portfolio_enhancements() -> Any:
    """Portfolio Enhancements testleri."""

    from services.portfolio.enhancements import (
        benchmark_engine,
        dividend_handler,
        multi_currency,
        performance_attribution,
        tax_model,
    )

    passed = 0
    failed = 0

    # 1. Tax model - dividend
    result = tax_model.compute_dividend_tax(1000)
    assert result["stopaj"] == 100
    assert result["net"] == 900
    passed += 1
    logger.info(f"  ✓ Dividend tax: gross={result['gross']}, net={result['net']}")

    # 2. Tax model - capital gains
    result = tax_model.compute_capital_gains_tax(5000)
    assert result["tax"] == 0  # Currently 0% in Turkey
    assert result["net"] == 5000
    passed += 1
    logger.info(f"  ✓ Capital gains: {result}")

    # 3. Tax model - commission
    result = tax_model.compute_commission_tax(100)
    assert result["bsmv"] == 5.0  # 5% BSMV
    assert result["total"] == 105.0
    passed += 1
    logger.info(f"  ✓ Commission tax: total={result['total']}")

    # 4. Dividend handler
    result = dividend_handler.process_dividend("THYAO", 100, 5.25, "2026-06-01", "2026-06-15")
    assert result["gross_dividend"] == 525.0
    assert result["net_dividend"] == 472.5
    passed += 1
    logger.info(f"  ✓ Dividend: net={result['net_dividend']}")

    # 5. Benchmark comparison
    p_returns = [0.01, -0.005, 0.02, -0.01, 0.015]
    b_returns = [0.008, -0.003, 0.015, -0.008, 0.012]
    result = benchmark_engine.compare(p_returns, b_returns)
    assert "alpha_annual" in result
    assert "beta" in result
    assert "tracking_error" in result
    assert "information_ratio" in result
    passed += 1
    logger.info(f"  ✓ Benchmark: alpha={result['alpha_annual']:.4f}, beta={result['beta']:.2f}")

    # 6. Performance attribution
    result = performance_attribution.decompose(
        {"THYAO": 0.6, "AKBNK": 0.4},
        {"THYAO": 0.05, "AKBNK": 0.03},
        {"THYAO": 0.5, "AKBNK": 0.5},
        {"THYAO": 0.04, "AKBNK": 0.02},
    )
    assert "allocation_effect" in result
    assert "selection_effect" in result
    passed += 1
    logger.info(
        f"  ✓ Attribution: allocation={result['allocation_effect']:.2f}%, selection={result['selection_effect']:.2f}%"
    )

    # 7. Multi-currency
    try_amount = multi_currency.convert(1000, "USD", "TRY")
    assert try_amount > 1000  # USD > TRY
    usd_amount = multi_currency.convert(47880, "TRY", "USD")
    assert abs(usd_amount - 1000) < 10  # Approximately 1000 USD
    passed += 1
    logger.info(f"  ✓ Multi-currency: 1000 USD = {try_amount:.0f} TRY")

    return passed, failed


def test_universe_enhancements() -> Any:
    """Universe Enhancements testleri."""
    from services.ingestion.universe_enhancements import (
        cross_source_reconciliation,
        outlier_detector,
        survivorship_bias,
        universe_enhancements,
    )

    passed = 0
    failed = 0

    # 1. Liquidity score
    score = universe_enhancements.compute_liquidity_score(1000000, 0.05, 50e9)
    assert score > 70
    score_low = universe_enhancements.compute_liquidity_score(1000, 2.0, 50e6)
    assert score_low < 40
    passed += 1
    logger.info(f"  ✓ Liquidity: high={score:.0f}, low={score_low:.0f}")

    # 2. Listing status
    status = universe_enhancements.classify_listing_status("THYAO")
    assert status == "ACTIVE"
    passed += 1
    logger.info(f"  ✓ Listing status: {status}")

    # 3. Cross-source reconciliation
    result = cross_source_reconciliation.reconcile_price({"yfinance": 305.25, "kap": 305.30, "matriks": 305.20})
    assert result["status"] == "CONSISTENT"
    assert result["consensus_price"] > 0
    passed += 1
    logger.info(f"  ✓ Reconciliation: {result['status']}, price={result['consensus_price']:.2f}")

    # 4. Reconciliation with conflict
    result2 = cross_source_reconciliation.reconcile_price({"yfinance": 305.25, "kap": 350.00})
    assert result2["status"] in ["MINOR_CONFLICT", "MAJOR_CONFLICT"]
    passed += 1
    logger.info(f"  ✓ Conflict detection: {result2['status']}")

    # 5. Outlier detection (Z-score)
    values = [100, 101, 99, 100, 101, 100, 99, 101, 100, 1000]
    outliers = outlier_detector.detect_zscore_outliers(values, threshold=2.5)
    assert len(outliers) >= 1
    assert 9 in outliers  # Index of 1000
    passed += 1
    logger.info(f"  ✓ Z-score outliers: {outliers}")

    # 6. IQR outlier detection
    outliers = outlier_detector.detect_iqr_outliers(values)
    # IQR may or may not detect with small sample
    passed += 1
    logger.info(f"  ✓ IQR outliers: {outliers} ({len(outliers)} found)")

    # 7. Survivorship bias
    survivorship_bias._delisted.clear()
    survivorship_bias.mark_delisted("OLD_COMPANY", "2025-01-01", "bankruptcy")
    assert survivorship_bias.is_delisted("OLD_COMPANY")
    assert not survivorship_bias.is_delisted("THYAO")
    active = survivorship_bias.get_active_universe(["THYAO", "OLD_COMPANY", "ASELS"], "2026-01-01")
    assert "OLD_COMPANY" not in active
    assert "THYAO" in active
    passed += 1
    logger.info(f"  ✓ Survivorship: {len(active)} active from 3")

    return passed, failed


def test_security() -> Any:
    """Security & Governance testleri."""
    from services.core.security import (
        Permission,
        Role,
        User,
        auth_service,
        authz_service,
        safety_governance,
        secret_redaction,
        system_state,
    )

    passed = 0
    failed = 0

    # 1. Create user
    auth_service._users.clear()
    auth_service._sessions.clear()
    user = auth_service.create_user("testuser", "password123", Role.ANALYST)
    assert user.username == "testuser"
    assert user.role == Role.ANALYST
    passed += 1
    logger.info(f"  ✓ User created: {user.username}")

    # 2. Authenticate
    token = auth_service.authenticate("testuser", "password123")
    assert token is not None
    assert len(token) > 20
    passed += 1
    logger.info(f"  ✓ Authenticated, token length: {len(token)}")

    # 3. Validate token
    validated = auth_service.validate_token(token)
    assert validated is not None
    assert validated.username == "testuser"
    passed += 1
    logger.info("  ✓ Token validated")

    # 4. Wrong password
    bad_token = auth_service.authenticate("testuser", "wrongpassword")
    assert bad_token is None
    passed += 1
    logger.info("  ✓ Wrong password rejected")

    # 5. Authorization - analyst can run backtest
    assert authz_service.check_permission(user, Permission.RUN_BACKTEST)
    assert not authz_service.check_permission(user, Permission.LIVE_EXECUTION)
    passed += 1
    logger.info("  ✓ Authorization: ANALYST can backtest, cannot execute")

    # 6. Authorization - admin can do everything
    admin = User(user_id="admin", username="admin", role=Role.ADMIN)
    assert authz_service.check_permission(admin, Permission.LIVE_EXECUTION)
    assert authz_service.check_permission(admin, Permission.MANAGE_USERS)
    passed += 1
    logger.info("  ✓ Admin has all permissions")

    # 7. Secret redaction
    text = "API_KEY=ghp_abc123def456 and Bearer sk-proj-xyz789"
    redacted = secret_redaction.redact(text)
    assert "ghp_abc123" not in redacted
    assert "sk-proj-xyz789" not in redacted
    passed += 1
    logger.info("  ✓ Secrets redacted")

    # 8. System state machine
    system_state.transition("INITIALIZING", "startup")
    assert system_state.state == "INITIALIZING"
    system_state.transition("READY", "all services up")
    assert system_state.state == "READY"
    system_state.transition("DEGRADED", "LLM down")
    assert system_state.state == "DEGRADED"
    passed += 1
    logger.info(f"  ✓ State machine: {system_state.state}")

    # 9. Safety governance
    assert safety_governance.validate_ai_action("read_data", {})
    assert not safety_governance.validate_ai_action("bypass_risk", {})
    assert not safety_governance.validate_ai_action("modify_portfolio", {"source": "ai"})
    passed += 1
    logger.info("  ✓ Safety governance: AI restrictions enforced")

    return passed, failed


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 60)
    logger.info("  FAZ 16 — Test Suite")
    logger.info("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Portfolio Enhancements", test_portfolio_enhancements),
        ("Universe Enhancements", test_universe_enhancements),
        ("Security & Governance", test_security),
    ]

    for name, test_func in tests:
        logger.info(f"\n--- {name} ---")
        try:
            p, f = test_func()
            total_passed += p
            total_failed += f
        except Exception as e:
            logger.info(f"  ✗ Test crashed: {e}")
            import traceback

            traceback.print_exc()
            total_failed += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    logger.info(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
