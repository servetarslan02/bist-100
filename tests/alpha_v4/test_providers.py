import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from alpha_v4.acquisition import HttpSourceConfig, RawDocumentStore, SourceFetchError
from alpha_v4.providers import SnapshotProvider, SnapshotProviderConfig
from alpha_v4.source_history import PersistentSourceRegistry
from alpha_v4.source_registry import SourceKind, SourceRecord

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"official fixture payload"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(503)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _registry(database):
    registry = PersistentSourceRegistry(database)
    registry.register_if_missing(
        SourceRecord(
            source_id="official-test",
            kind=SourceKind.KAP,
            owner="Official Test Source",
            access_method="test-http",
            timezone_name="Europe/Istanbul",
            freshness_limit=timedelta(minutes=5),
        )
    )
    return registry


def _provider(database, base_url):
    return SnapshotProvider(
        SnapshotProviderConfig(
            http=HttpSourceConfig(
                source_id="official-test",
                base_url=base_url,
                timeout_seconds=2,
            ),
            surfaces={"ok": "/ok", "failure": "/failure"},
        ),
        RawDocumentStore(database),
        _registry(database),
    )


def test_snapshot_provider_fetches_real_http_and_persists_exact_raw_bytes(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    database = tmp_path / "providers.sqlite3"

    try:
        host, port = server.server_address
        provider = _provider(database, f"http://{host}:{port}")
        document = provider.snapshot("ok", fetched_at=T0)

        persisted = RawDocumentStore(database).get(document.document_id)
        assert persisted is not None
        assert persisted.body == b"official fixture payload"
        assert persisted.body_sha256 == document.body_sha256
        source = _registry(database).get("official-test")
        assert source.successful_observations == 1
        assert source.failed_observations == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_snapshot_provider_records_network_or_http_failure(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    database = tmp_path / "providers.sqlite3"

    try:
        host, port = server.server_address
        provider = _provider(database, f"http://{host}:{port}")
        with pytest.raises(SourceFetchError):
            provider.snapshot("failure", fetched_at=T0)

        source = _registry(database).get("official-test")
        assert source.successful_observations == 0
        assert source.failed_observations == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_snapshot_provider_rejects_unknown_surface_without_network_call(tmp_path):
    database = tmp_path / "providers.sqlite3"
    provider = _provider(database, "http://127.0.0.1:9")

    with pytest.raises(KeyError, match="unknown source surface"):
        provider.snapshot("not-allowlisted", fetched_at=T0)

    source = _registry(database).get("official-test")
    assert source.successful_observations == 0
    assert source.failed_observations == 0


def test_surface_config_rejects_absolute_urls_and_parent_traversal():
    http = HttpSourceConfig(source_id="official-test", base_url="https://example.test")

    with pytest.raises(ValueError, match="relative"):
        SnapshotProviderConfig(http=http, surfaces={"bad": "https://evil.test/x"})

    with pytest.raises(ValueError, match="parent traversal"):
        SnapshotProviderConfig(http=http, surfaces={"bad": "/a/../secret"})
