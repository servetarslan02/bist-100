"""
ALPHA BIST — Evidence Verification Test Suite
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_evidence_engine():
    """Evidence Engine testleri."""
    from services.intelligence.evidence_engine import (
        evidence_engine, ClaimType, VerificationResult, SourceReliability,
    )

    passed = 0
    failed = 0

    # 1. Claim extraction
    text = "Şirket yeni sözleşme imzaladı. Bu durumda gelirler artacak. Tahminime göre %15 büyüme olacak."
    claims = evidence_engine.extract_claims(text, "THYAO", "ai")
    assert len(claims) >= 2
    passed += 1
    print(f"  ✓ Claim extraction: {len(claims)} claims")

    # 2. Claim type classification
    assert evidence_engine._classify_claim("KAP açıklandı") == ClaimType.FACT
    assert evidence_engine._classify_claim("Bu nedenle fiyat düşecek") == ClaimType.INFERENCE
    assert evidence_engine._classify_claim("Tahminime göre yükselecek") == ClaimType.PREDICTION
    assert evidence_engine._classify_claim("Bence bu iyi bir yatırım") == ClaimType.OPINION
    passed += 1
    print(f"  ✓ Claim type classification")

    # 3. Source reliability
    assert evidence_engine._get_source_type("kap.org.tr") == SourceReliability.PRIMARY
    assert evidence_engine._get_source_type("bloomberg.com") == SourceReliability.FINANCIAL
    assert evidence_engine._get_source_type("dunya.com") == SourceReliability.NEWS
    assert evidence_engine._get_source_type("twitter.com") == SourceReliability.SOCIAL
    assert evidence_engine._get_source_type("unknown.com") == SourceReliability.UNKNOWN
    passed += 1
    print(f"  ✓ Source reliability")

    # 4. Fact verification (primary source)
    from services.intelligence.evidence_engine import Claim
    claim = Claim(
        claim_id="C1",
        text="Şirket yeni sözleşme imzaladı",
        source="kap.org.tr",
        source_type=SourceReliability.PRIMARY,
        ticker="THYAO",
    )
    result = evidence_engine.verify_claim(claim)
    assert result.result == VerificationResult.VERIFIED
    assert result.evidence_score >= 70
    passed += 1
    print(f"  ✓ Fact verification: {result.result.value}, score={result.evidence_score:.0f}")

    # 5. Prediction verification (lower confidence)
    claim_pred = Claim(
        claim_id="C2",
        text="Tahminime göre fiyat yükselecek",
        source="ai",
        source_type=SourceReliability.ANALYSIS,
    )
    result_pred = evidence_engine.verify_claim(claim_pred)
    assert result_pred.claim_type == ClaimType.PREDICTION
    assert result_pred.evidence_score < result.evidence_score  # Daha düşük güven
    passed += 1
    print(f"  ✓ Prediction: score={result_pred.evidence_score:.0f}")

    # 6. Social media (low reliability)
    claim_social = Claim(
        claim_id="C3",
        text="Bu hisse patlayacak",
        source="twitter.com",
        source_type=SourceReliability.SOCIAL,
    )
    result_social = evidence_engine.verify_claim(claim_social)
    assert result_social.source_reliability == SourceReliability.SOCIAL
    assert result_social.evidence_score < result.evidence_score  # Social < Primary
    passed += 1
    print(f"  ✓ Social media: score={result_social.evidence_score:.0f}")

    # 7. Hallucination detection
    halluc = evidence_engine.detect_hallucination(
        "THYAO 500 TL olacak ve ASELS %20 artacak",
        {},
    )
    assert len(halluc["tickers_mentioned"]) >= 2
    assert len(halluc["prices_mentioned"]) >= 1
    passed += 1
    print(f"  ✓ Hallucination detection: {len(halluc['tickers_mentioned'])} tickers")

    # 8. Batch verification
    batch = [
        Claim("B1", "KAP açıklandı", "kap.org.tr", SourceReliability.PRIMARY),
        Claim("B2", "Söylentiye göre", "twitter.com", SourceReliability.SOCIAL),
    ]
    results = evidence_engine.verify_batch(batch)
    assert len(results) == 2
    assert results[0].evidence_score > results[1].evidence_score
    passed += 1
    print(f"  ✓ Batch: primary={results[0].evidence_score:.0f}, social={results[1].evidence_score:.0f}")

    return passed, failed


def main():
    print("=" * 60)
    print("  Evidence Verification Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    print(f"\n--- Evidence Engine ---")
    try:
        p, f = test_evidence_engine()
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
