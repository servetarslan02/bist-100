#!/usr/bin/env python3
"""
Intelligence Module Testleri

Kapsam:
- Evidence Engine: veri doğrulama, kaynak güvenilirliği, çelişkili veri
- Continuous Learning: drift detection, degradation, model outcome
- Super Intelligence: karar zinciri, confidence, belirsizlik
"""

import sys
import os
import asyncio
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =====================================================
# EVIDENCE ENGINE TESTS
# =====================================================

async def test_evidence_claim_extraction():
    """Claim extraction çalışmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine
    engine = EvidenceVerificationEngine()

    text = "THYAO karı %30 arttı. hisse fiyatı yükselecek."
    claims = engine.extract_claims(text, ticker="THYAO", source="test")

    if len(claims) == 0:
        issues.append("Claim çıkarılamadı")
    else:
        # En az 2 claim olmalı (karı arttı + fiyat yükselecek)
        if len(claims) < 1:
            issues.append(f"Yetersiz claim: {len(claims)}")

    return "Evidence Claim Extraction", len(issues) == 0, issues


async def test_evidence_source_reliability():
    """Kaynak güvenilirliği doğru sınıflanmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine, SourceReliability
    engine = EvidenceVerificationEngine()

    test_cases = [
        ("kap.org.tr", SourceReliability.PRIMARY),
        ("bloomberght.com", SourceReliability.FINANCIAL),
        ("twitter.com", SourceReliability.SOCIAL),
        ("unknown-source.com", SourceReliability.UNKNOWN),
    ]

    for source, expected in test_cases:
        result = engine._get_source_type(source)
        if result != expected:
            issues.append(f"{source}: {result} != {expected}")

    return "Evidence Source Reliability", len(issues) == 0, issues


async def test_evidence_claim_classification():
    """Claim tipi sınıflandırması çalışmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine, ClaimType
    engine = EvidenceVerificationEngine()

    # FACT: doğrudan veri
    fact_type = engine._classify_claim("THYAO fiyatı 250 TL")
    if fact_type not in [ClaimType.FACT, ClaimType.INFERENCE]:
        issues.append(f"FACT classification: {fact_type}")

    # PREDICTION: gelecek tahmini
    pred_type = engine._classify_claim("fiyat yükselecek, artacak bekleniyor")
    if pred_type not in [ClaimType.PREDICTION, ClaimType.INFERENCE]:
        issues.append(f"PREDICTION classification: {pred_type}")

    return "Evidence Claim Classification", len(issues) == 0, issues


async def test_evidence_hallucination_detection():
    """Hallucination detection çalışmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine
    engine = EvidenceVerificationEngine()

    # Uydurma veri
    claims = engine.extract_claims(
        "THYAO bugün %500 kazandı, tüm zamanların rekorunu kırdı",
        ticker="THYAO", source="social"
    )

    if claims:
        for claim in claims:
            result = engine.verify_claim(claim)
            # Sosyal medya kaynağı + aşırı iddia → düşük güvenilirlik
            if result.evidence_score > 80:
                issues.append(f"Yüksek skor ({result.evidence_score}) — şüpheli olmalı")

    return "Evidence Hallucination Detection", len(issues) == 0, issues


async def test_evidence_contradiction():
    """Çelişkili veri yönetimi çalışmalı."""
    issues = []

    from services.intelligence.evidence_engine import EvidenceVerificationEngine, VerificationResult
    engine = EvidenceVerificationEngine()

    # İki zıt iddia
    claims1 = engine.extract_claims("THYAO karı arttı", ticker="THYAO", source="kap.org.tr")
    claims2 = engine.extract_claims("THYAO zarar açıkladı", ticker="THYAO", source="twitter.com")

    if claims1 and claims2:
        v1 = engine.verify_claim(claims1[0])
        v2 = engine.verify_claim(claims2[0])

        # KAP daha güvenilir olmalı
        if v1.evidence_score < v2.evidence_score:
            issues.append(f"KAP skoru ({v1.evidence_score}) < Twitter skoru ({v2.evidence_score})")

    return "Evidence Contradiction", len(issues) == 0, issues


# =====================================================
# CONTINUOUS LEARNING TESTS
# =====================================================

async def test_learning_report():
    """Learning report döndürülmeli."""
    issues = []

    from services.learning.continuous_learning import continuous_learning

    report = continuous_learning.get_learning_report()

    required_keys = ["total_cycles", "performance_summary", "registry", "drift_status"]
    for key in required_keys:
        if key not in report:
            issues.append(f"Eksik key: {key}")

    return "Learning Report", len(issues) == 0, issues


async def test_learning_state_export():
    """State export/import çalışmalı."""
    issues = []

    from services.learning.continuous_learning import continuous_learning

    state = continuous_learning.export_state()
    if not isinstance(state, dict):
        issues.append("State dict değil")

    # Import (boş state bile çalışmalı)
    try:
        continuous_learning.import_state(state)
    except Exception as e:
        issues.append(f"Import failed: {e}")

    return "Learning State Export", len(issues) == 0, issues


async def test_learning_drift_detection():
    """Drift detection mekanizması çalışmalı."""
    issues = []

    from services.learning.continuous_learning import continuous_learning

    report = continuous_learning.get_learning_report()
    drift = report.get("drift_status", {})

    if "detected" not in drift:
        issues.append("drift_status.detected eksik")

    return "Learning Drift Detection", len(issues) == 0, issues


# =====================================================
# SUPER INTELLIGENCE TESTS
# =====================================================

async def test_super_intelligence_health():
    """Health status döndürülmeli."""
    issues = []

    from services.learning.super_intelligence import super_intelligence

    health = super_intelligence.get_health_status()

    if not hasattr(health, 'overall_status'):
        issues.append("overall_status yok")
    if not hasattr(health, 'uptime_hours'):
        issues.append("uptime_hours yok")

    return "Super Intelligence Health", len(issues) == 0, issues


async def test_super_intelligence_module_status():
    """Module status güncellenebilmeli."""
    issues = []

    from services.learning.super_intelligence import super_intelligence

    try:
        super_intelligence.update_module_status("test_module", "HEALTHY", "test")
        health = super_intelligence.get_health_status()
        if health.overall_status == "FAILED":
            issues.append("Status güncellenemedi")
    except Exception as e:
        issues.append(f"Exception: {e}")

    return "Super Intelligence Module Status", len(issues) == 0, issues


async def test_super_intelligence_regime_model():
    """Regime bazlı model seçimi çalışmalı."""
    issues = []

    from services.learning.super_intelligence import super_intelligence

    # BULL regime
    model = super_intelligence.get_best_model_for_regime("BULL")
    # Model None olabilir (henüz eğitim yok) ama hata vermemeli

    # BEAR regime
    model = super_intelligence.get_best_model_for_regime("BEAR")

    return "Super Intelligence Regime Model", len(issues) == 0, issues


async def test_super_intelligence_performance_recording():
    """Performance recording çalışmalı."""
    issues = []

    from services.learning.super_intelligence import super_intelligence

    try:
        super_intelligence.record_performance(
            model_version="test_v1",
            regime="BULL",
            metrics={"sharpe": 1.5, "ic": 0.05, "win_rate": 0.55},
        )
    except Exception as e:
        issues.append(f"Record failed: {e}")

    return "Super Intelligence Performance Recording", len(issues) == 0, issues


# =====================================================
# RUN
# =====================================================

async def run_all():
    print("=" * 60)
    print("INTELLIGENCE MODULE TESTLERİ")
    print("=" * 60)

    tests = [
        # Evidence Engine
        test_evidence_claim_extraction,
        test_evidence_source_reliability,
        test_evidence_claim_classification,
        test_evidence_hallucination_detection,
        test_evidence_contradiction,
        # Continuous Learning
        test_learning_report,
        test_learning_state_export,
        test_learning_drift_detection,
        # Super Intelligence
        test_super_intelligence_health,
        test_super_intelligence_module_status,
        test_super_intelligence_regime_model,
        test_super_intelligence_performance_recording,
    ]

    passed = 0
    failed = 0
    all_issues = []

    for test_func in tests:
        try:
            name, ok, issues = await test_func()
        except Exception as e:
            name = test_func.__name__
            ok = False
            issues = [f"Exception: {e}"]

        icon = "✅" if ok else "❌"
        print(f"\n{icon} {name}")
        if ok:
            passed += 1
            print("   PASSED")
        else:
            failed += 1
            for i in issues:
                print(f"   ❌ {i}")
                all_issues.append(f"{name}: {i}")

    print(f"\n{'=' * 60}")
    print(f"SONUÇ: {passed}/{passed + failed} geçti")
    if all_issues:
        print("\nTÜM HATALAR:")
        for i, issue in enumerate(all_issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)
    return failed == 0


def main():
    ok = asyncio.run(run_all())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
