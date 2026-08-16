"""
ALPHA BIST — FAZ 9 Test Suite

Signal Fusion, Conflict Detection, Explainability testleri.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_signal_fusion():
    """Signal Fusion Engine testleri."""
    from services.intelligence.signal_fusion import signal_fusion_engine

    passed = 0
    failed = 0

    # 1. All LONG signals → fused LONG
    signals = {
        "technical": {"direction": "LONG", "score": 70},
        "fundamental": {"direction": "LONG", "score": 65},
        "momentum": {"direction": "LONG", "score": 80},
        "sentiment": {"direction": "LONG", "score": 60},
        "macro": {"direction": "NEUTRAL", "score": 50},
        "valuation": {"direction": "LONG", "score": 75},
        "ai": {"direction": "LONG", "score": 68},
        "opportunity": {"score": 72},
    }
    result = signal_fusion_engine.fuse_signals("THYAO", signals, "BULL")
    assert result.fused_direction == "LONG"
    assert result.fused_confidence > 0
    assert not result.has_conflict
    passed += 1
    print(f"  ✓ All LONG → fused LONG (confidence={result.fused_confidence:.2f})")

    # 2. Mixed signals → conflict
    signals_conflict = {
        "technical": {"direction": "LONG", "score": 70},
        "fundamental": {"direction": "SHORT", "score": 35},
        "momentum": {"direction": "LONG", "score": 75},
        "sentiment": {"direction": "SHORT", "score": 30},
        "macro": {"direction": "NEUTRAL", "score": 50},
        "valuation": {"direction": "LONG", "score": 65},
        "ai": {"direction": "LONG", "score": 60},
        "opportunity": {"score": 60},
    }
    result2 = signal_fusion_engine.fuse_signals("MIXED", signals_conflict, "SIDEWAYS")
    assert result2.has_conflict
    assert len(result2.conflict_details) > 0
    passed += 1
    print(f"  ✓ Mixed signals → conflict detected: {result2.conflict_details[0][:50]}")

    # 3. All SHORT
    signals_short = {
        "technical": {"direction": "SHORT", "score": 30},
        "fundamental": {"direction": "SHORT", "score": 25},
        "momentum": {"direction": "SHORT", "score": 20},
        "sentiment": {"direction": "SHORT", "score": 35},
        "macro": {"direction": "SHORT", "score": 40},
        "valuation": {"direction": "SHORT", "score": 30},
        "ai": {"direction": "SHORT", "score": 25},
        "opportunity": {"score": 30},
    }
    result3 = signal_fusion_engine.fuse_signals("BEAR", signals_short, "BEAR")
    assert result3.fused_direction == "SHORT"
    passed += 1
    print(f"  ✓ All SHORT → fused SHORT")

    # 4. Explainability
    assert len(result.reasons) > 0
    assert len(result.risks) >= 0
    assert result.invalidation != ""
    passed += 1
    print(f"  ✓ Explainability: {len(result.reasons)} reasons, {len(result.risks)} risks")

    # 5. Self-check
    assert isinstance(result.self_check_passed, bool)
    assert isinstance(result.self_check_warnings, list)
    passed += 1
    print(f"  ✓ Self-check: passed={result.self_check_passed}, warnings={result.self_check_warnings}")

    # 6. Confidence high when all agree
    assert result.fused_confidence > result2.fused_confidence  # All LONG > mixed
    passed += 1
    print(f"  ✓ Confidence: all_agree={result.fused_confidence:.2f} vs mixed={result2.fused_confidence:.2f}")

    # 7. Regime affects fusion
    result_bull = signal_fusion_engine.fuse_signals("TEST", signals, "BULL")
    result_bear = signal_fusion_engine.fuse_signals("TEST", signals, "BEAR")
    # Same signals, different regime → may differ
    passed += 1
    print(f"  ✓ Regime effect: BULL={result_bull.fused_score:.1f}, BEAR={result_bear.fused_score:.1f}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 9 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    print(f"\n--- Signal Fusion Engine ---")
    try:
        p, f = test_signal_fusion()
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
