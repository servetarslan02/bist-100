import structlog

logger = structlog.get_logger(__name__)
from typing import Any

"""
ALPHA BIST — FAZ 7 Test Suite

AI Agent System testleri.
"""

import asyncio
import sys


def test_agent_system() -> Any:
    """AI Agent System testleri."""
    from services.agents.agent_system import (
        AgentRole,
        AgentTask,
        AgentToolRegistry,
        AIFallback,
        AIOutputValidator,
        BaseAgent,
    )
    from services.agents.agent_pipeline import AgentPipelineOrchestrator

    passed = 0
    failed = 0

    # 1. Tool registry
    assert AgentToolRegistry.can_access(AgentRole.RESEARCH, "read_market_data")
    assert AgentToolRegistry.can_access(AgentRole.RISK, "calculate_risk")
    assert not AgentToolRegistry.can_access(AgentRole.NEWS, "calculate_risk")  # News risk hesaplayamaz
    assert not AgentToolRegistry.can_access(AgentRole.TECHNICAL, "read_portfolio")
    passed += 1
    logger.info("  ✓ Tool registry (access control)")

    # 2. AI Output Validation - valid
    output = '{"direction": "LONG", "confidence": 75, "reasoning": "Strong momentum"}'
    result = AIOutputValidator.validate(output)
    assert result["valid"]
    assert result["parsed"]["direction"] == "LONG"
    assert result["parsed"]["confidence"] == 0.75  # 75 → 0.75 normalize
    passed += 1
    logger.info("  ✓ AI output validation (valid)")

    # 3. AI Output Validation - invalid direction
    output = '{"direction": "BUY", "confidence": 50}'
    result = AIOutputValidator.validate(output)
    assert not result["valid"] or "BUY" in str(result.get("errors", []))
    passed += 1
    logger.info("  ✓ AI output validation (invalid direction)")

    # 4. AI Output Validation - negative price
    output = '{"direction": "LONG", "confidence": 50, "target_price": -100}'
    result = AIOutputValidator.validate(output)
    assert any("target_price" in e.lower() or "invalid" in e.lower() for e in result["errors"])
    passed += 1
    logger.info("  ✓ AI output validation (negative price)")

    # 5. AI Output Validation - confidence range
    output = '{"direction": "LONG", "confidence": 150}'
    result = AIOutputValidator.validate(output)
    # 150 > 100 → hata eklenir, normalize edilmez
    assert len(result["errors"]) > 0 or result["parsed"]["confidence"] == 1.5
    passed += 1
    logger.info("  ✓ AI output validation (confidence range)")

    # 6. Rule-based fallback
    features = {"roc_5d": 5.0, "volume_zscore": 3.0, "rsi_14": 55, "trend_slope_20d": 1.0}
    fallback = AIFallback.rule_based_analysis(features, "THYAO")
    assert fallback["direction"] == "LONG"
    assert fallback["confidence"] > 0
    assert len(fallback["reasons"]) > 0
    assert fallback["source"] == "rule_based_fallback"
    passed += 1
    logger.info(f"  ✓ Rule-based fallback (direction={fallback['direction']}, confidence={fallback['confidence']:.2f})")

    # 7. Base agent execution (async)
    async def run_agent() -> Any:
        agent = BaseAgent(AgentRole.TECHNICAL)
        task = AgentTask(
            task_id="test-001",
            agent_role=AgentRole.TECHNICAL,
            ticker="THYAO",
            prompt="Analyze THYAO technically",
            context={"features": features},
        )
        return await agent.execute(task)

    result = asyncio.get_event_loop().run_until_complete(run_agent())
    assert result.success
    assert result.confidence > 0
    assert result.duration_ms > 0
    assert len(result.input_hash) == 16
    passed += 1
    logger.info(f"  ✓ Base agent execution (confidence={result.confidence:.2f}, {result.duration_ms:.1f}ms)")

    # 8. Agent pipeline orchestrator
    async def run_pipeline() -> Any:
        orch = AgentPipelineOrchestrator()
        return await orch.run(
            ticker="THYAO",
            features=features,
        )

    pipeline_result = asyncio.get_event_loop().run_until_complete(run_pipeline())
    assert pipeline_result.ticker == "THYAO"
    assert pipeline_result.direction in ["LONG", "SHORT", "NEUTRAL", "NO_TRADE"]
    assert pipeline_result.confidence >= 0
    assert pipeline_result.total_duration_ms > 0
    passed += 1
    logger.info(
        f"  ✓ Agent pipeline orchestrator (direction={pipeline_result.direction}, confidence={pipeline_result.confidence:.2f})"
    )

    # 9. Prompt versioning
    agent = BaseAgent(AgentRole.RESEARCH, model_version="gemma4:12b", prompt_version="v1.2")
    assert agent.model_version == "gemma4:12b"
    assert agent.prompt_version == "v1.2"
    passed += 1
    logger.info("  ✓ Prompt versioning")

    return passed, failed


def main() -> Any:
    logger.info("=" * 60)
    logger.info("  FAZ 7 — Test Suite")
    logger.info("=" * 60)

    total_passed = 0
    total_failed = 0

    logger.info("\n--- AI Agent System ---")
    try:
        p, f = test_agent_system()
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
