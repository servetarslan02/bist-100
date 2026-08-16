"""Evidence-bound structured LLM gateway for ALPHA v4 event understanding.

Transport targets Ollama's local `/api/chat` structured-output interface. The gateway
is intentionally not a trading-decision API: direct action/target-price fields are
rejected and every extracted fact must carry evidence from a raw document.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


class LLMProtocolError(RuntimeError):
    pass


FORBIDDEN_DECISION_KEYS = {
    "buy",
    "sell",
    "trade_action",
    "action",
    "target_price",
    "position_size",
    "order",
}


EVENT_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_type": {"type": "string"},
        "entity_ids": {"type": "array", "items": {"type": "string"}},
        "facts": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "value": {},
                    "source_document_id": {"type": "string"},
                    "evidence_text": {"type": "string"},
                },
                "required": ["value", "source_document_id", "evidence_text"],
            },
        },
        "key_unknowns": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {
            "type": "object",
            "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    "required": ["event_type", "entity_ids", "facts", "key_unknowns", "uncertainties"],
}


@dataclass(frozen=True)
class EvidenceBoundFact:
    value: Any
    source_document_id: str
    evidence_text: str
    evidence_sha256: str

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> EvidenceBoundFact:
        required = {"value", "source_document_id", "evidence_text"}
        missing = required - set(mapping)
        if missing:
            raise LLMProtocolError(
                "fact missing evidence fields: " + ",".join(sorted(missing))
            )
        source_document_id = str(mapping["source_document_id"]).strip()
        evidence_text = str(mapping["evidence_text"]).strip()
        if not source_document_id or not evidence_text:
            raise LLMProtocolError("fact evidence must not be empty")
        return cls(
            value=mapping["value"],
            source_document_id=source_document_id,
            evidence_text=evidence_text,
            evidence_sha256=sha256(evidence_text.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class EventExtraction:
    event_type: str
    entity_ids: tuple[str, ...]
    facts: Mapping[str, EvidenceBoundFact]
    key_unknowns: tuple[str, ...]
    uncertainties: Mapping[str, float]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> EventExtraction:
        top_level_keys = {str(key).lower() for key in mapping}
        forbidden = FORBIDDEN_DECISION_KEYS & top_level_keys
        if forbidden:
            raise LLMProtocolError(
                "LLM event output contains forbidden decision keys: "
                + ",".join(sorted(forbidden))
            )

        required = {
            "event_type",
            "entity_ids",
            "facts",
            "key_unknowns",
            "uncertainties",
        }
        missing = required - set(mapping)
        if missing:
            raise LLMProtocolError(
                "event extraction missing fields: " + ",".join(sorted(missing))
            )

        event_type = str(mapping["event_type"]).strip()
        entity_ids = tuple(str(item).strip() for item in mapping["entity_ids"])
        if not event_type or not entity_ids or any(not item for item in entity_ids):
            raise LLMProtocolError("event_type and entity_ids are required")

        raw_facts = mapping["facts"]
        if not isinstance(raw_facts, Mapping):
            raise LLMProtocolError("facts must be an object")
        forbidden_fact_names = FORBIDDEN_DECISION_KEYS & {
            str(name).lower() for name in raw_facts
        }
        if forbidden_fact_names:
            raise LLMProtocolError(
                "LLM event facts contain forbidden decision keys: "
                + ",".join(sorted(forbidden_fact_names))
            )
        facts = {
            str(name): EvidenceBoundFact.from_mapping(value)
            for name, value in raw_facts.items()
            if isinstance(value, Mapping)
        }
        if len(facts) != len(raw_facts):
            raise LLMProtocolError("every fact must be an evidence-bound object")

        raw_uncertainties = mapping["uncertainties"]
        if not isinstance(raw_uncertainties, Mapping):
            raise LLMProtocolError("uncertainties must be an object")
        uncertainties: dict[str, float] = {}
        for name, value in raw_uncertainties.items():
            number = float(value)
            if not 0 <= number <= 1:
                raise LLMProtocolError("uncertainty values must be between 0 and 1")
            uncertainties[str(name)] = number

        return cls(
            event_type=event_type,
            entity_ids=entity_ids,
            facts=facts,
            key_unknowns=tuple(str(item) for item in mapping["key_unknowns"]),
            uncertainties=uncertainties,
        )


class OllamaStructuredClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 120.0,
    ):
        if not model.strip():
            raise ValueError("model is required")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def chat_json(
        self,
        messages: Iterable[Mapping[str, str]],
        *,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": list(messages),
                "stream": False,
                "format": schema,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                response_body = response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise LLMProtocolError(f"ollama request failed: {exc}") from exc

        try:
            envelope = json.loads(response_body.decode("utf-8"))
            content = envelope["message"]["content"]
            structured = json.loads(content)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise LLMProtocolError(
                "ollama returned invalid structured response"
            ) from exc
        if not isinstance(structured, Mapping):
            raise LLMProtocolError("structured response must be a JSON object")
        return structured

    def extract_event(self, messages: Iterable[Mapping[str, str]]) -> EventExtraction:
        structured = self.chat_json(messages, schema=EVENT_EXTRACTION_SCHEMA)
        return EventExtraction.from_mapping(structured)
