"""
ALPHA BIST — FAZ 14 Test Suite

Feature Discovery, Knowledge Graph, Audit Log, Factor Engine testleri.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_feature_discovery():
    """Feature Discovery testleri."""
    from services.features.discovery import feature_discovery_engine
    import numpy as np

    passed = 0
    failed = 0

    # Test data
    features = {
        "rsi_14": list(np.random.uniform(30, 70, 100)),
        "momentum_20d": list(np.random.normal(0, 5, 100)),
        "volume_zscore": list(np.random.normal(0, 1, 100)),
    }
    target = list(np.random.normal(0, 2, 100))

    # 1. Generate interactions
    discovered = feature_discovery_engine.generate_interactions(features, max_interactions=50)
    assert len(discovered) > 0
    passed += 1
    print(f"  ✓ Generated {len(discovered)} interactions")

    # 2. Compute interaction values
    values = feature_discovery_engine.compute_interaction_values(features, discovered)
    assert len(values) > 0
    passed += 1
    print(f"  ✓ Computed {len(values)} interaction values")

    # 3. Correlation filtering
    selected = feature_discovery_engine.filter_by_correlation(features, target, max_features=5)
    assert len(selected) <= 5
    passed += 1
    print(f"  ✓ Correlation filtered: {len(selected)} features")

    # 4. Mutual information
    mi = feature_discovery_engine.compute_mutual_information(features, target)
    assert len(mi) > 0
    passed += 1
    print(f"  ✓ MI computed for {len(mi)} features")

    # 5. Leakage detection
    # Create a leaked feature (perfectly correlated with target)
    features["leaked"] = target.copy()
    leaked = feature_discovery_engine.detect_leakage(features, target, threshold=0.99)
    assert "leaked" in leaked
    passed += 1
    print(f"  ✓ Leakage detected: {leaked}")

    # 6. Full pipeline
    del features["leaked"]
    discovered, mi_scores = feature_discovery_engine.run_discovery(features, target, max_features=10)
    selected_count = sum(1 for f in discovered if f.selected)
    assert selected_count > 0
    passed += 1
    print(f"  ✓ Full pipeline: {selected_count} selected from {len(discovered)}")

    return passed, failed


def test_knowledge_graph():
    """Knowledge Graph testleri."""
    from services.intelligence.knowledge_graph import knowledge_graph, Entity, Relation

    passed = 0
    failed = 0

    # Clear
    knowledge_graph._entities.clear()
    knowledge_graph._relations.clear()
    knowledge_graph._index.clear()

    # 1. Add entities
    knowledge_graph.add_entity(Entity(entity_id="thyao", entity_type="company", name="THYAO"))
    knowledge_graph.add_entity(Entity(entity_id="aviation", entity_type="sector", name="AVIATION"))
    knowledge_graph.add_entity(Entity(entity_id="macro_oil", entity_type="macro", name="OIL"))
    assert len(knowledge_graph._entities) == 3
    passed += 1
    print(f"  ✓ Added {len(knowledge_graph._entities)} entities")

    # 2. Add relations
    knowledge_graph.add_relation(Relation(source_id="thyao", target_id="aviation", relation_type="belongs_to"))
    knowledge_graph.add_relation(Relation(source_id="macro_oil", target_id="aviation", relation_type="affects", strength=-0.9))
    assert len(knowledge_graph._relations) == 2
    passed += 1
    print(f"  ✓ Added {len(knowledge_graph._relations)} relations")

    # 3. Get related entities
    related = knowledge_graph.get_related_entities("thyao")
    assert len(related) > 0
    passed += 1
    print(f"  ✓ THYAO related to: {[e.name for e, r in related]}")

    # 4. Find path
    path = knowledge_graph.find_path("thyao", "macro_oil")
    assert path is not None
    assert len(path) == 3  # thyao → aviation → macro_oil
    passed += 1
    print(f"  ✓ Path: {' → '.join(path)}")

    # 5. Impact propagation
    impacts = knowledge_graph.propagate_impact("macro_oil", 0.5)
    assert len(impacts) > 0
    passed += 1
    print(f"  ✓ Impact propagation: {impacts}")

    # 6. Load BIST defaults
    knowledge_graph._entities.clear()
    knowledge_graph._relations.clear()
    knowledge_graph._index.clear()
    knowledge_graph.load_bist_defaults()
    stats = knowledge_graph.get_stats()
    assert stats["total_entities"] > 20
    assert stats["total_relations"] > 10
    passed += 1
    print(f"  ✓ BIST defaults: {stats['total_entities']} entities, {stats['total_relations']} relations")

    return passed, failed


def test_audit_log():
    """Audit Log testleri."""
    from services.core.audit_log import audit_log

    passed = 0
    failed = 0

    # Clear
    audit_log._entries.clear()
    audit_log._index.clear()

    # 1. Log decision
    audit_log.log_decision("THYAO", "BUY", "LONG", 0.8, ["momentum strong"], ["high volatility"])
    assert len(audit_log._entries) == 1
    passed += 1
    print(f"  ✓ Decision logged")

    # 2. Log risk check
    audit_log.log_risk_check("THYAO", True, [{"name": "position_limit", "passed": True}])
    assert len(audit_log._entries) == 2
    passed += 1
    print(f"  ✓ Risk check logged")

    # 3. Log order
    audit_log.log_order("ORD-001", "THYAO", "BUY", 100, 305.25, "MARKET")
    passed += 1
    print(f"  ✓ Order logged")

    # 4. Log fill
    audit_log.log_fill("FILL-001", "ORD-001", "THYAO", "BUY", 100, 305.40, 11.42)
    passed += 1
    print(f"  ✓ Fill logged")

    # 5. Entity history
    history = audit_log.get_entity_history("ticker", "THYAO")
    assert len(history) >= 2  # decision + risk check
    passed += 1
    print(f"  ✓ Entity history: {len(history)} entries")

    # 6. Decision lineage
    lineage = audit_log.get_decision_lineage("THYAO")
    assert len(lineage) >= 2
    passed += 1
    print(f"  ✓ Decision lineage: {len(lineage)} steps")

    # 7. Recent entries
    recent = audit_log.get_recent(limit=10)
    assert len(recent) == min(10, len(audit_log._entries))
    passed += 1
    print(f"  ✓ Recent: {len(recent)} entries")

    # 8. Stats
    stats = audit_log.get_stats()
    assert stats["total_entries"] >= 4
    passed += 1
    print(f"  ✓ Stats: {stats}")

    # 9. Config change
    audit_log.log_config_change("risk.max_position_pct", 10, 15, "admin")
    passed += 1
    print(f"  ✓ Config change logged")

    # 10. State change
    audit_log.log_state_change("regime", "BIST", "RANGE", "TRENDING-UP", "breadth > 65")
    passed += 1
    print(f"  ✓ State change logged")

    return passed, failed


def test_factor_engine():
    """Factor Engine testleri."""
    from services.intelligence.factor_engine import factor_engine

    passed = 0
    failed = 0

    # 1. Value factor
    fundamentals = {"pe_ratio": 8.5, "pb_ratio": 1.2, "fcf_yield_pct": 6.0, "dividend_yield": 3.5}
    technicals = {"roc_5d": 3.0, "momentum_20d": 8.0, "trend_slope_20d": 1.0, "realized_vol_20d": 18}
    score = factor_engine.compute_factor_scores("THYAO", fundamentals, technicals)
    assert score.value_score > 50
    assert score.momentum_score > 50
    assert score.quality_score > 0
    assert score.composite_score > 0
    passed += 1
    print(f"  ✓ THYAO: value={score.value_score:.0f}, momentum={score.momentum_score:.0f}, quality={score.quality_score:.0f}, composite={score.composite_score:.0f}")

    # 2. High PE → lower value score
    score_high_pe = factor_engine.compute_factor_scores("TEST", {"pe_ratio": 50}, {"roc_5d": 0, "realized_vol_20d": 20})
    score_low_pe = factor_engine.compute_factor_scores("TEST", {"pe_ratio": 5}, {"roc_5d": 0, "realized_vol_20d": 20})
    assert score_low_pe.value_score > score_high_pe.value_score
    passed += 1
    print(f"  ✓ Value: low PE={score_low_pe.value_score:.0f} vs high PE={score_high_pe.value_score:.0f}")

    # 3. Portfolio exposure
    positions = [
        {"ticker": "THYAO", "value": 10000},
        {"ticker": "AKBNK", "value": 8000},
    ]
    factor_scores = {
        "THYAO": score,
        "AKBNK": factor_engine.compute_factor_scores("AKBNK", {"pe_ratio": 6, "roe": 0.18}, {"momentum_20d": 5, "realized_vol_20d": 22}),
    }
    exposure = factor_engine.compute_portfolio_exposure(positions, factor_scores)
    assert -1 <= exposure.value_exposure <= 1
    assert -1 <= exposure.momentum_exposure <= 1
    assert exposure.concentration_risk > 0
    passed += 1
    print(f"  ✓ Exposure: value={exposure.value_exposure:.2f}, momentum={exposure.momentum_exposure:.2f}, concentration={exposure.concentration_risk:.3f}")

    # 4. Low volatility factor
    score_low_vol = factor_engine.compute_factor_scores("LOWVOL", {}, {"realized_vol_20d": 10})
    score_high_vol = factor_engine.compute_factor_scores("HIGHVOL", {}, {"realized_vol_20d": 50})
    assert score_low_vol.low_vol_score > score_high_vol.low_vol_score
    passed += 1
    print(f"  ✓ Low vol: {score_low_vol.low_vol_score:.0f} vs high vol: {score_high_vol.low_vol_score:.0f}")

    return passed, failed


def main():
    print("=" * 60)
    print("  FAZ 14 — Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    tests = [
        ("Feature Discovery", test_feature_discovery),
        ("Knowledge Graph", test_knowledge_graph),
        ("Audit Log", test_audit_log),
        ("Factor Engine", test_factor_engine),
    ]

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            p, f = test_func()
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
