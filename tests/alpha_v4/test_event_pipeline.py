from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from alpha_v4.acquisition import FetchedDocument
from alpha_v4.event_pipeline import EvidenceIntegrityError, canonicalize_extraction
from alpha_v4.llm_gateway import EventExtraction
from alpha_v4.storage import AppendOnlyEventStore


UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
BODY = (
    "Project highest offer: company total revenue share 15,397,620,000 TRY. "
    "The evaluation process is ongoing."
).encode("utf-8")


def _document():
    return FetchedDocument(
        document_id="kap-doc",
        source_id="kap-official",
        url="https://www.kap.org.tr/tr/Bildirim/1622639",
        fetched_at=T0 + timedelta(minutes=2),
        status_code=200,
        content_type="text/html",
        body_sha256=sha256(BODY).hexdigest(),
        body=BODY,
    )


def _extraction(evidence_text="company total revenue share 15,397,620,000 TRY"):
    return EventExtraction.from_mapping(
        {
            "event_type": "contract_award",
            "entity_ids": ["EKGYO"],
            "facts": {
                "company_share_value": {
                    "value": 15397620000,
                    "source_document_id": "kap-doc",
                    "evidence_text": evidence_text,
                },
                "binding_status": {
                    "value": "evaluation_ongoing",
                    "source_document_id": "kap-doc",
                    "evidence_text": "The evaluation process is ongoing.",
                },
            },
            "key_unknowns": ["final_contract_status"],
            "uncertainties": {"execution": 0.35},
        }
    )


def test_verified_extraction_becomes_replayable_canonical_event(tmp_path):
    event = canonicalize_extraction(
        _extraction(),
        documents={"kap-doc": _document()},
        source_timestamp=T0,
        ingest_timestamp=T0 + timedelta(minutes=2),
        effective_timestamp=T0,
    )

    assert event.source_id == "kap-official"
    assert event.entities == ("EKGYO",)
    assert event.payload["facts"]["company_share_value"]["value"] == 15397620000
    assert len(event.evidence) == 2

    db = tmp_path / "events.sqlite3"
    AppendOnlyEventStore(db).append(event)
    loaded = AppendOnlyEventStore(db).get(event.event_id)

    assert loaded == event


def test_hallucinated_evidence_text_blocks_canonical_event():
    with pytest.raises(EvidenceIntegrityError, match="evidence_not_found"):
        canonicalize_extraction(
            _extraction("this sentence does not exist in source"),
            documents={"kap-doc": _document()},
            source_timestamp=T0,
            ingest_timestamp=T0 + timedelta(minutes=2),
            effective_timestamp=T0,
        )


def test_missing_raw_document_blocks_canonical_event():
    with pytest.raises(EvidenceIntegrityError, match="missing_document"):
        canonicalize_extraction(
            _extraction(),
            documents={},
            source_timestamp=T0,
            ingest_timestamp=T0 + timedelta(minutes=2),
            effective_timestamp=T0,
        )
