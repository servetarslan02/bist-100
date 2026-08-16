import http.client
import json
import sqlite3
import threading
from datetime import datetime, timezone

from alpha_v4.runtime import AlphaRuntime, RuntimeConfig, RuntimeMode
from alpha_v4.server import build_server


def _request(server, path):
    host, port = server.server_address
    connection = http.client.HTTPConnection(host, port, timeout=2)
    connection.request("GET", path)
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, payload


def test_health_server_runs_as_real_process_surface(tmp_path):
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=tmp_path / "alpha.sqlite3")
    )
    server = build_server(runtime, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, payload = _request(server, "/health/ready")
        assert status == 200
        assert payload["ready"] is True
        assert payload["mode"] == "test"
        assert payload["audit_chain_valid"] is True
        assert payload["registered_sources"] > 0
        assert payload["real_money_execution"] is False
        assert payload["checks"]["database"]["integrity"] == "ok"
        assert all(value == "ready" for value in payload["stores"].values())

        live_status, live_payload = _request(server, "/health/live")
        assert live_status == 200
        assert live_payload == {
            "alive": True,
            "mode": "test",
            "real_money_execution": False,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not thread.is_alive()


def test_readiness_fails_closed_when_audit_history_is_tampered(tmp_path):
    database = tmp_path / "alpha.sqlite3"
    runtime = AlphaRuntime(RuntimeConfig(mode=RuntimeMode.TEST, database_path=database))
    runtime.audit.append(
        "TEST_AUDIT",
        {"value": 1},
        created_at=datetime.now(timezone.utc),
        entry_id="audit-entry-1",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_entries SET payload_json = ? WHERE entry_id = ?",
            ('{"value":999}', "audit-entry-1"),
        )

    server = build_server(runtime, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        ready_status, ready_payload = _request(server, "/health/ready")
        assert ready_status == 503
        assert ready_payload["ready"] is False
        assert ready_payload["checks"]["database"]["ok"] is True
        assert ready_payload["checks"]["audit_chain"]["ok"] is False
        assert ready_payload["stores"]["audit"] == "corrupt"

        live_status, live_payload = _request(server, "/health/live")
        assert live_status == 200
        assert live_payload["alive"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unknown_http_path_is_fail_closed(tmp_path):
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=tmp_path / "alpha.sqlite3")
    )
    server = build_server(runtime, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status, payload = _request(server, "/trade")
        assert status == 404
        assert payload == {"error": "not_found"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
