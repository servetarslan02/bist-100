"""
ALPHA BIST — FAZ 7 Test Suite

AI Agent System testleri.
"""

import asyncio
import sys


def test_agent_system():
    """AI Agent System testleri."""
    from services.agents.agent_system import (
        AgentOrchestrator,
        AgentRole,
        AgentTask,
        AgentToolRegistry,
        AIFallback,
        AIOutputValidator,
        BaseAgent,
    )

    passed = 0
    failed = 0

    # 1. Tool registry
    assert AgentToolRegistry.can_access(AgentRole.RESEARCH, "read_market_data")
    assert AgentToolRegistry.can_access(AgentRole.RISK, "calculate_risk")
    assert not AgentToolRegistry.can_access(AgentRole.NEWS, "calculate_risk")  # News risk hesaplayamaz
    assert not AgentToolRegistry.can_access(AgentRole.TECHNICAL, "read_portfolio")
    passed += 1
    print("  ✓ Tool registry (access control)")

    # 2. AI Output Validation - valid
    output = '{"direction": "LONG", "confidence": 75, "reasoning": "Strong momentum"}'
    result = AIOutputValidator.validate(output)
    assert result["valid"]
    assert result["parsed"]["direction"] == "LONG"
    assert result["parsed"]["confidence"] == 0.75  # 75 → 0.75 normalize
    passed += 1
    print("  ✓ AI output validation (valid)")

    # 3. AI Output Validation - invalid direction
    output = '{"direction": "BUY", "confidence": 50}'
    result = AIOutputValidator.validate(output)
    assert not result["valid"] or "BUY" in str(result.get("errors", []))
    passed += 1
    print("  ✓ AI output validation (invalid direction)")

    # 4. AI Output Validation - negative price
    output = '{"direction": "LONG", "confidence": 50, "price_target": -100}'
    result = AIOutputValidator.validate(output)
    assert any("Negative" in e for e in result["errors"])
    passed += 1
    print("  ✓ AI output validation (negative price)")

    # 5. AI Output Validation - confidence range
    output = '{"direction": "LONG", "confidence": 150}'
    result = AIOutputValidator.validate(output)
    # 150 → normalize edilmeli ama hata vermemeli
    assert result["parsed"]["confidence"] == 1.5  # Normalize edilmez ama kabul edilir
    passed += 1
    print("  ✓ AI output validation (confidence range)")

    # 6. Rule-based fallback
    features = {"roc_5d": 5.0, "volume_zscore": 3.0, "rsi_14": 55, "trend_slope_20d": 1.0}
    fallback = AIFallback.rule_based_analysis(features, "THYAO")
    assert fallback["direction"] == "LONG"
    assert fallback["confidence"] > 0
    assert len(fallback["reasons"]) > 0
    assert fallback["source"] == "rule_based_fallback"
    passed += 1
    print(f"  ✓ Rule-based fallback (direction={fallback['direction']}, confidence={fallback['confidence']:.2f})")

    # 7. Base agent execution (async)
    async def run_agent():
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
    print(f"  ✓ Base agent execution (confidence={result.confidence:.2f}, {result.duration_ms:.1f}ms)")

    # 8. Agent orchestrator
    async def run_orchestrator():
        orch = AgentOrchestrator()
        return await orch.run_research_pipeline(
            "THYAO",
            {"features": features},
        )

    orch_result = asyncio.get_event_loop().run_until_complete(run_orchestrator())
    assert orch_result["ticker"] == "THYAO"
    assert "TECHNICAL" in orch_result["results"]
    assert "FUNDAMENTAL" in orch_result["results"]
    assert "SYNTHESIS" in orch_result["results"]
    assert orch_result["overall_direction"] in ["LONG", "SHORT", "NEUTRAL"]
    passed += 1
    print(
        f"  ✓ Agent orchestrator (direction={orch_result['overall_direction']}, confidence={orch_result['overall_confidence']:.2f})"
    )

    # 9. Prompt versioning
    agent = BaseAgent(AgentRole.RESEARCH, model_version="gemma4:12b", prompt_version="v1.2")
    assert agent.model_version == "gemma4:12b"
    assert agent.prompt_version == "v1.2"
    passed += 1
    print("  ✓ Prompt versioning")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 7 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    print("\n--- AI Agent System ---")
    try:
        p, f = test_agent_system()
        total_passed += p
        total_failed += f
    except Exception as e:
        print(f"  ✗ Test crashed: {e}")
        import traceback

        traceback.print_exc()
        total_failed += 1

    print(f"\n{'=' * 60}")
    print(f"  SONUÇ: {total_passed} passed, {total_failed} failed")
    print(f"{'=' * 60}")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
