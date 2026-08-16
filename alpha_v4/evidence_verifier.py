"""Verify extracted LLM evidence against immutable raw source documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .acquisition import FetchedDocument
from .llm_gateway import EventExtraction


@dataclass(frozen=True)
class EvidenceVerification:
    verified: bool
    reasons: tuple[str, ...]


def verify_event_evidence(
    extraction: EventExtraction,
    documents: Mapping[str, FetchedDocument],
) -> EvidenceVerification:
    reasons = []

    for fact_name, fact in extraction.facts.items():
        document = documents.get(fact.source_document_id)
        if document is None:
            reasons.append(f"missing_document:{fact_name}:{fact.source_document_id}")
            continue
        try:
            text = document.body.decode("utf-8")
        except UnicodeDecodeError:
            reasons.append(f"non_utf8_document:{fact_name}:{fact.source_document_id}")
            continue

        # Normalize only whitespace. We deliberately do not fuzzy-match semantics here:
        # evidence must be auditable text actually present in the captured source.
        normalized_document = " ".join(text.split())
        normalized_evidence = " ".join(fact.evidence_text.split())
        if normalized_evidence not in normalized_document:
            reasons.append(f"evidence_not_found:{fact_name}:{fact.source_document_id}")

    return EvidenceVerification(verified=not reasons, reasons=tuple(reasons))
