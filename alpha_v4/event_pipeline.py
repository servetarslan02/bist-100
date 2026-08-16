"""Canonical event construction from evidence-bound structured extraction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .acquisition import FetchedDocument
from .contracts import CanonicalEvent, EvidenceRef
from .evidence_verifier import verify_event_evidence
from .llm_gateway import EventExtraction


class EvidenceIntegrityError(RuntimeError):
    pass


def canonicalize_extraction(
    extraction: EventExtraction,
    *,
    documents: Mapping[str, FetchedDocument],
    source_timestamp: datetime,
    ingest_timestamp: datetime,
    effective_timestamp: datetime,
) -> CanonicalEvent:
    verification = verify_event_evidence(extraction, documents)
    if not verification.verified:
        raise EvidenceIntegrityError(";".join(verification.reasons))

    source_ids = {
        documents[fact.source_document_id].source_id
        for fact in extraction.facts.values()
    }
    if len(source_ids) != 1:
        raise EvidenceIntegrityError(
            "single canonical extraction must have one primary source"
        )
    source_id = next(iter(source_ids))

    evidence = tuple(
        EvidenceRef(
            source_id=documents[fact.source_document_id].source_id,
            source_timestamp=source_timestamp,
            ingest_timestamp=ingest_timestamp,
            locator=documents[fact.source_document_id].url,
            evidence_text=fact.evidence_text,
        )
        for _, fact in sorted(extraction.facts.items())
    )

    payload = {
        "facts": {
            name: {
                "value": fact.value,
                "source_document_id": fact.source_document_id,
                "evidence_sha256": fact.evidence_sha256,
            }
            for name, fact in sorted(extraction.facts.items())
        },
        "key_unknowns": list(extraction.key_unknowns),
        "uncertainties": dict(sorted(extraction.uncertainties.items())),
    }

    return CanonicalEvent(
        event_type=extraction.event_type,
        source_id=source_id,
        source_timestamp=source_timestamp,
        ingest_timestamp=ingest_timestamp,
        effective_timestamp=effective_timestamp,
        entities=tuple(extraction.entity_ids),
        payload=payload,
        evidence=evidence,
    )
