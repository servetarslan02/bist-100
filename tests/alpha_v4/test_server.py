import http.client
import json
import threading

from alpha_v4.runtime import AlphaRuntime, RuntimeConfig, RuntimeMode
from alpha_v4.server import build_server


def test_health_server_runs_as_real_process_surface(tmp_path):
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=tmp_path / "alpha.sqlite3")
    )
    server = build_server(runtime, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address
        connection = http.client.HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/health")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 200
        assert payload["mode"] == "test"
        assert payload["audit_chain_valid"] is True
        assert payload["registered_sources"] > 0
        assert payload["real_money_execution"] is False
        assert all(value == "ready" for value in payload["stores"].values())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert not thread.is_alive()


def test_unknown_http_path_is_fail_closed(tmp_path):
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=tmp_path / "alpha.sqlite3")
    )
    server = build_server(runtime, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        host, port = server.server_address
        connection = http.client.HTTPConnection(host, port, timeout=2)
        connection.request("GET", "/trade")
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()

        assert response.status == 404
        assert payload == {"error": "not_found"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
