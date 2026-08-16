import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from alpha_v4.llm_gateway import (
    EVENT_EXTRACTION_SCHEMA,
    EventExtraction,
    LLMProtocolError,
    OllamaStructuredClient,
)


VALID_EVENT = {
    "event_type": "contract_award",
    "entity_ids": ["EKGYO"],
    "facts": {
        "contract_value": {
            "value": 15397620000,
            "source_document_id": "kap-1622639",
            "evidence_text": "company total revenue share 15,397,620,000 TRY",
        },
        "binding_status": {
            "value": "tender_evaluation_ongoing",
            "source_document_id": "kap-1622639",
            "evidence_text": "evaluation process is ongoing",
        },
    },
    "key_unknowns": ["final_contract_status", "gross_margin"],
    "uncertainties": {"materiality": 0.4, "execution": 0.3},
}


class OllamaLikeHandler(BaseHTTPRequestHandler):
    seen_request = None

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        raw = self.rfile.read(length)
        type(self).seen_request = json.loads(raw.decode("utf-8"))
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        response = json.dumps(
            {
                "model": "local-test-model",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(VALID_EVENT),
                },
                "done": True,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        return


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaLikeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_structured_gateway_uses_real_http_and_schema_payload():
    server, thread = _server()
    try:
        client = OllamaStructuredClient(
            model="local-test-model",
            base_url=f"http://127.0.0.1:{server.server_port}",
        )
        event = client.extract_event(
            [{"role": "user", "content": "Extract facts from document kap-1622639"}]
        )

        assert event.event_type == "contract_award"
        assert event.facts["contract_value"].value == 15397620000
        assert event.facts["contract_value"].source_document_id == "kap-1622639"
        assert event.facts["contract_value"].evidence_sha256

        request = OllamaLikeHandler.seen_request
        assert request["stream"] is False
        assert request["format"] == EVENT_EXTRACTION_SCHEMA
        assert request["model"] == "local-test-model"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_llm_fact_without_evidence_is_rejected():
    bad = {
        **VALID_EVENT,
        "facts": {"contract_value": {"value": 10}},
    }

    with pytest.raises(LLMProtocolError, match="missing evidence"):
        EventExtraction.from_mapping(bad)


def test_llm_direct_trading_directive_is_rejected_at_top_level():
    bad = {**VALID_EVENT, "trade_action": "BUY"}

    with pytest.raises(LLMProtocolError, match="forbidden decision"):
        EventExtraction.from_mapping(bad)


def test_llm_target_price_hidden_inside_facts_is_rejected():
    bad = {
        **VALID_EVENT,
        "facts": {
            **VALID_EVENT["facts"],
            "target_price": {
                "value": 123,
                "source_document_id": "doc",
                "evidence_text": "invented",
            },
        },
    }

    with pytest.raises(LLMProtocolError, match="forbidden decision"):
        EventExtraction.from_mapping(bad)


def test_uncertainty_outside_unit_interval_is_rejected():
    bad = {**VALID_EVENT, "uncertainties": {"execution": 1.5}}

    with pytest.raises(LLMProtocolError, match="between 0 and 1"):
        EventExtraction.from_mapping(bad)
