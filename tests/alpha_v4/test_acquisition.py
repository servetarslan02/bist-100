import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from alpha_v4.acquisition import (
    HttpFetcher,
    HttpSourceConfig,
    RawDocumentStore,
    SourceFetchError,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
BODY = b'{"source":"official-test","value":123}'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data":
            body = BODY
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/large":
            body = b"x" * 128
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/redirect-cross-origin":
            self.send_response(302)
            self.send_header(
                "Location", f"http://localhost:{self.server.server_port}/data"
            )
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_http_acquisition_uses_real_socket_and_preserves_exact_raw_bytes(tmp_path):
    server, thread = _server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        fetcher = HttpFetcher(
            HttpSourceConfig(source_id="official-test", base_url=base)
        )
        document = fetcher.fetch("/data", fetched_at=T0)

        assert document.status_code == 200
        assert document.body == BODY
        assert document.body_sha256
        assert document.content_type.startswith("application/json")
        assert document.url == base + "/data"
        assert document.fetched_at == T0

        db = tmp_path / "raw.sqlite3"
        RawDocumentStore(db).append(document)
        loaded = RawDocumentStore(db).get(document.document_id)

        assert loaded == document
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_absolute_url_cannot_escape_source_boundary():
    fetcher = HttpFetcher(
        HttpSourceConfig(source_id="kap", base_url="https://www.kap.org.tr")
    )

    with pytest.raises(ValueError, match="outside configured source"):
        fetcher.fetch("https://example.com/not-kap")


def test_redirect_cannot_escape_exact_source_origin():
    server, thread = _server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        fetcher = HttpFetcher(
            HttpSourceConfig(source_id="official-test", base_url=base)
        )

        with pytest.raises(SourceFetchError, match="redirect escaped"):
            fetcher.fetch("/redirect-cross-origin", fetched_at=T0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_response_body_limit_is_enforced_before_persistence():
    server, thread = _server()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        fetcher = HttpFetcher(
            HttpSourceConfig(
                source_id="official-test",
                base_url=base,
                max_body_bytes=64,
            )
        )

        with pytest.raises(SourceFetchError, match="exceeded 64 byte limit"):
            fetcher.fetch("/large", fetched_at=T0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_naive_fetch_timestamp_is_rejected_before_network():
    fetcher = HttpFetcher(
        HttpSourceConfig(source_id="official-test", base_url="http://127.0.0.1:9")
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        fetcher.fetch("/data", fetched_at=T0.replace(tzinfo=None))


def test_raw_store_detects_body_tampering(tmp_path):
    from alpha_v4.acquisition import FetchedDocument

    document = FetchedDocument(
        document_id="doc",
        source_id="test",
        url="http://localhost/data",
        fetched_at=T0,
        status_code=200,
        content_type="text/plain",
        body_sha256="not-the-real-hash",
        body=b"actual",
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        RawDocumentStore(tmp_path / "raw.sqlite3").append(document)
