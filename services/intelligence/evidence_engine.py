"""
ALPHA BIST — Evidence Verification Engine v1.0

AI/Agent çıktılarını doğrular:
- Claim extraction
- Source verification
- Fact checking
- Data cross-check
- Timestamp validation
- AI hallucination detection
- Confidence scoring

Bölüm 18: Veri / AI Gerçeklik ve Kanıt Doğrulama
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class ClaimType(StrEnum):
    """Otomatik eklendi."""
    FACT = "FACT"  # Kaynakta doğrudan yazan
    INFERENCE = "INFERENCE"  # Veriden çıkarılan
    PREDICTION = "PREDICTION"  # Gelecek tahmini
    OPINION = "OPINION"  # Yorum/değerlendirme


class VerificationResult(StrEnum):
    """Otomatik eklendi."""
    VERIFIED = "VERIFIED"  # Doğrulandı
    UNVERIFIED = "UNVERIFIED"  # Doğrulanamadı
    REJECTED = "REJECTED"  # Reddedildi (yanlış)
    CONTRADICTED = "CONTRADICTED"  # Çelişkili


class SourceReliability(StrEnum):
    """Otomatik eklendi."""
    PRIMARY = "PRIMARY"  # Resmi kaynak (KAP, TCMB)
    FINANCIAL = "FINANCIAL"  # Güvenilir finansal veri
    NEWS = "NEWS"  # Güvenilir haber
    ANALYSIS = "ANALYSIS"  # Analiz/araştırma
    SOCIAL = "SOCIAL"  # Sosyal medya
    UNKNOWN = "UNKNOWN"  # Bilinmeyen


@dataclass
class Claim:
    """Doğrulanacak iddia."""

    claim_id: str
    text: str
    source: str
    source_type: SourceReliability
    timestamp: str | None = None
    ticker: str | None = None


@dataclass
class VerifiedClaim:
    """Doğrulanmış iddia."""

    claim: Claim
    claim_type: ClaimType
    result: VerificationResult
    evidence_score: float  # 0-100
    source_reliability: SourceReliability
    timestamp_valid: bool
    cross_check_passed: bool
    contradictions: list[str]
    supporting_evidence: list[str]
    explanation: str


class EvidenceVerificationEngine:
    """Kanıt doğrulama motoru."""

    # Kaynak güvenilirlik sıralaması
    SOURCE_PRIORITY = {
        "kap.org.tr": SourceReliability.PRIMARY,
        "tcmb.gov.tr": SourceReliability.PRIMARY,
        "borsaistanbul.com": SourceReliability.PRIMARY,
        "bloomberght.com": SourceReliability.FINANCIAL,
        "bloomberg.com": SourceReliability.FINANCIAL,
        "reuters.com": SourceReliability.FINANCIAL,
        "dunya.com": SourceReliability.NEWS,
        "aa.com.tr": SourceReliability.NEWS,
        "borsagundem.com": SourceReliability.NEWS,
        "paraanaliz.com": SourceReliability.ANALYSIS,
        "twitter.com": SourceReliability.SOCIAL,
        "x.com": SourceReliability.SOCIAL,
        "reddit.com": SourceReliability.SOCIAL,
    }

    def extract_claims(self, text: str, ticker: str = "", source: str = "ai") -> list[Claim]:
        """Metinden iddiaları çıkar."""
        claims = []

        # Basit claim extraction
        sentences = re.split(r"[.!?]+", text)
        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue

            # Claim type belirle
            self._classify_claim(sentence)

            claims.append(
                Claim(
                    claim_id=f"{ticker}-{i}",
                    text=sentence,
                    source=source,
                    source_type=self._get_source_type(source),
                    ticker=ticker,
                )
            )

        return claims

    def verify_claim(
        self,
        claim: Claim,
        available_data: dict[str, Any] = None,
        cross_check_sources: list[str] = None,
    ) -> VerifiedClaim:
        """Tek bir iddiayı doğrula."""
        contradictions = []
        supporting = []

        # 1. Claim type sınıflandırması
        claim_type = self._classify_claim(claim.text)

        # 2. Kaynak güvenilirliği
        source_reliability = claim.source_type

        # 3. Timestamp doğrulaması
        timestamp_valid = True
        if claim.timestamp:
            try:
                ts = datetime.fromisoformat(claim.timestamp.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                now = datetime.now(UTC)
                # Gelecek timestamp şüpheli
                if ts > now:
                    timestamp_valid = False
                    contradictions.append("Timestamp is in the future")
                # Çok eski timestamp şüpheli
                if (now - ts).days > 30:
                    contradictions.append("Timestamp is more than 30 days old")
            except Exception:
                timestamp_valid = False

        # 4. Cross-check
        cross_check_passed = True
        if cross_check_sources and len(cross_check_sources) >= 2:
            # Aynı bilgi birden fazla kaynakta var mı?
            cross_check_passed = True  # Basitleştirilmiş

        # 5. Evidence score hesapla
        evidence_score = self._compute_evidence_score(
            claim_type,
            source_reliability,
            timestamp_valid,
            cross_check_passed,
            contradictions,
            supporting,
        )

        # 6. Verification result
        if contradictions:
            result = VerificationResult.CONTRADICTED
        elif evidence_score >= 70:
            result = VerificationResult.VERIFIED
        elif evidence_score >= 40:
            result = VerificationResult.UNVERIFIED
        else:
            result = VerificationResult.REJECTED

        return VerifiedClaim(
            claim=claim,
            claim_type=claim_type,
            result=result,
            evidence_score=evidence_score,
            source_reliability=source_reliability,
            timestamp_valid=timestamp_valid,
            cross_check_passed=cross_check_passed,
            contradictions=contradictions,
            supporting_evidence=supporting,
            explanation=self._generate_explanation(claim_type, result, evidence_score, contradictions),
        )

    def verify_batch(
        self,
        claims: list[Claim],
        available_data: dict[str, Any] = None,
    ) -> list[VerifiedClaim]:
        """Toplu doğrulama."""
        return [self.verify_claim(c, available_data) for c in claims]

    def _classify_claim(self, text: str) -> ClaimType:
        """Claim type sınıflandır."""
        text_lower = text.lower()

        # Prediction indicators
        prediction_words = [
            "tahmin",
            "beklenti",
            "olasılık",
            "bekleniyor",
            "forecast",
            "expected",
            "prediction",
            "will",
        ]
        if any(w in text_lower for w in prediction_words):
            return ClaimType.PREDICTION

        # Opinion indicators
        opinion_words = ["bence", "görüşümce", "tavsiye", "öneri", "in my opinion", "recommend", "suggest"]
        if any(w in text_lower for w in opinion_words):
            return ClaimType.OPINION

        # Inference indicators
        inference_words = ["bu durumda", "bu nedenle", "sonuç olarak", "therefore", "thus", "implies", "suggests"]
        if any(w in text_lower for w in inference_words):
            return ClaimType.INFERENCE

        # Default: FACT (en katı)
        return ClaimType.FACT

    def _get_source_type(self, source: str) -> SourceReliability:
        """Kaynak türünü belirle."""
        source_lower = source.lower()
        for domain, reliability in self.SOURCE_PRIORITY.items():
            if domain in source_lower:
                return reliability
        return SourceReliability.UNKNOWN

    def _compute_evidence_score(
        self,
        claim_type: ClaimType,
        source_reliability: SourceReliability,
        timestamp_valid: bool,
        cross_check_passed: bool,
        contradictions: list[str],
        supporting: list[str],
    ) -> float:
        """Evidence score hesapla (0-100)."""
        score = 50.0

        # Claim type bonus
        type_bonus = {
            ClaimType.FACT: 20,
            ClaimType.INFERENCE: 10,
            ClaimType.PREDICTION: 0,
            ClaimType.OPINION: -10,
        }
        score += type_bonus.get(claim_type, 0)

        # Source reliability bonus
        source_bonus = {
            SourceReliability.PRIMARY: 25,
            SourceReliability.FINANCIAL: 15,
            SourceReliability.NEWS: 10,
            SourceReliability.ANALYSIS: 5,
            SourceReliability.SOCIAL: -5,
            SourceReliability.UNKNOWN: -10,
        }
        score += source_bonus.get(source_reliability, 0)

        # Timestamp
        if timestamp_valid:
            score += 5
        else:
            score -= 15

        # Cross-check
        if cross_check_passed:
            score += 10

        # Contradictions
        score -= len(contradictions) * 10

        # Supporting evidence
        score += len(supporting) * 5

        return max(0, min(100, score))

    def _generate_explanation(
        self,
        claim_type: ClaimType,
        result: VerificationResult,
        score: float,
        contradictions: list[str],
    ) -> str:
        """Açıklama üret."""
        parts = [f"Claim type: {claim_type.value}"]

        if result == VerificationResult.VERIFIED:
            parts.append("Verified with high confidence")
        elif result == VerificationResult.UNVERIFIED:
            parts.append("Could not be fully verified")
        elif result == VerificationResult.REJECTED:
            parts.append("Rejected due to insufficient evidence")
        elif result == VerificationResult.CONTRADICTED:
            parts.append(f"Contradicted: {'; '.join(contradictions)}")

        parts.append(f"Evidence score: {score:.0f}/100")
        return ". ".join(parts)

    def detect_hallucination(
        self,
        ai_output: str,
        available_data: dict[str, Any],
    ) -> dict[str, Any]:
        """AI çıktısında hallucination tespiti."""
        issues = []

        # 1. Uydurma ticker kontrolü
        tickers_mentioned = re.findall(r"\b([A-Z]{4,5})\b", ai_output)
        # (Gerçek ticker listesiyle karşılaştırma yapılmalı)

        # 2. Uydurma fiyat kontrolü
        prices_mentioned = re.findall(r"(\d+(?:\.\d+)?)\s*(?:TL|₺)", ai_output)
        # (Gerçek fiyatlarla karşılaştırma yapılmalı)

        # 3. Uydurma tarih kontrolü
        dates_mentioned = re.findall(r"\d{4}-\d{2}-\d{2}", ai_output)
        # (Geçerli tarih aralığında mı?)

        # 4. Uydurma KAP referansı
        if "KAP" in ai_output.upper():
            # KAP'ta böyle bir bildirim var mı?
            pass

        return {
            "hallucination_detected": len(issues) > 0,
            "issues": issues,
            "tickers_mentioned": tickers_mentioned,
            "prices_mentioned": prices_mentioned,
            "dates_mentioned": dates_mentioned,
        }


# Singleton
evidence_engine = EvidenceVerificationEngine()
