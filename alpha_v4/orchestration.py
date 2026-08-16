"""Idempotent evidence-ingestion orchestration for ALPHA v4 research events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .acquisition import FetchedDocument
from .event_pipeline import canonicalize_extraction
from .llm_gateway import EventExtraction
from .runtime import AlphaRuntime


class IngestionConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class EventIngestionOutcome:
    raw_document_id: str
    event_id: str
    audit_entry_id: str | None
    duplicate: bool


class EvidenceEventIngestor:
    """Persist evidence and one canonical research event with audit lineage."""

    def __init__(self, runtime: AlphaRuntime):
        self.runtime = runtime

    def ingest(
        self,
        document: FetchedDocument,
        extraction: EventExtraction,
        *,
        source_timestamp: datetime,
        ingest_timestamp: datetime,
        effective_timestamp: datetime,
    ) -> EventIngestionOutcome:
        stored_document = self.runtime.raw_documents.get(document.document_id)
        if stored_document is None:
            self.runtime.raw_documents.append(document)
        elif stored_document != document:
            raise IngestionConflictError(
                f"raw document identity conflict: {document.document_id}"
            )

        event = canonicalize_extraction(
            extraction,
            documents={document.document_id: document},
            source_timestamp=source_timestamp,
            ingest_timestamp=ingest_timestamp,
            effective_timestamp=effective_timestamp,
        )
        stored_event = self.runtime.events.get(event.event_id)
        if stored_event is not None:
            if stored_event != event:
                raise IngestionConflictError(
                    f"canonical event conflict: {event.event_id}"
                )
            return EventIngestionOutcome(
                raw_document_id=document.document_id,
                event_id=event.event_id,
                audit_entry_id=None,
                duplicate=True,
            )

        self.runtime.ingest_event(event)
        audit_entry = self.runtime.audit.append(
            "CANONICAL_EVENT_INGESTED",
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "source_id": event.source_id,
                "raw_document_id": document.document_id,
                "entity_ids": list(event.entities),
            },
            created_at=ingest_timestamp,
        )
        return EventIngestionOutcome(
            raw_document_id=document.document_id,
            event_id=event.event_id,
            audit_entry_id=audit_entry.entry_id,
            duplicate=False,
        )
