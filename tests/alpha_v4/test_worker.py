import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from alpha_v4.acquisition import HttpSourceConfig, SourceFetchError
from alpha_v4.providers import SnapshotProvider, SnapshotProviderConfig
from alpha_v4.runtime import AlphaRuntime, RuntimeConfig, RuntimeMode
from alpha_v4.worker import run_snapshot_cycle

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"worker fixture payload"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(503)
        self.end_headers()

    def log_message(self, format, *args):
        return


def _runtime_and_provider(tmp_path):
    database = tmp_path / "worker.sqlite3"
    runtime = AlphaRuntime(RuntimeConfig(mode=RuntimeMode.TEST, database_path=database))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = SnapshotProvider(
        SnapshotProviderConfig(
            http=HttpSourceConfig(
                source_id="kap-official",
                base_url=f"http://127.0.0.1:{server.server_port}",
                timeout_seconds=2,
            ),
            surfaces={"ok": "/ok", "failure": "/failure"},
        ),
        runtime.raw_documents,
        runtime.source_registry,
    )
    return database, runtime, provider, server, thread


def test_worker_cycle_is_idempotent_and_audited(tmp_path):
    database, runtime, provider, server, thread = _runtime_and_provider(tmp_path)
    try:
        first = run_snapshot_cycle(
            runtime,
            source_id="kap-official",
            surface="ok",
            owner_id="worker-a",
            cycle_key="2026-08-16T12:00Z",
            started_at=T0,
            provider=provider,
        )
        duplicate = run_snapshot_cycle(
            runtime,
            source_id="kap-official",
            surface="ok",
            owner_id="worker-b",
            cycle_key="2026-08-16T12:00Z",
            started_at=T0 + timedelta(minutes=1),
            provider=provider,
        )

        assert first.status == "SUCCEEDED"
        assert first.run_id is not None
        assert first.document_id is not None
        assert first.byte_count == len(b"worker fixture payload")
        assert runtime.raw_documents.get(first.document_id) is not None
        assert runtime.jobs.get(first.run_id).status == "SUCCEEDED"
        assert duplicate.status == "SKIPPED"
        assert duplicate.run_id is None
        assert [entry.event_type for entry in runtime.audit.entries()] == [
            "SOURCE_SNAPSHOT_COMPLETED"
        ]
        assert runtime.audit.verify_chain().valid

        restarted = AlphaRuntime(
            RuntimeConfig(mode=RuntimeMode.TEST, database_path=database)
        )
        assert restarted.jobs.get(first.run_id).status == "SUCCEEDED"
        assert restarted.raw_documents.get(first.document_id) is not None
        assert restarted.audit.verify_chain().valid
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_worker_failure_is_finalized_and_audited(tmp_path):
    database, runtime, provider, server, thread = _runtime_and_provider(tmp_path)
    try:
        with pytest.raises(SourceFetchError):
            run_snapshot_cycle(
                runtime,
                source_id="kap-official",
                surface="failure",
                owner_id="worker-a",
                cycle_key="failed-cycle",
                started_at=T0,
                provider=provider,
            )

        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT run_id, status FROM job_runs WHERE job_name = ? AND idempotency_key = ?",
                ("official-snapshot:kap-official:failure", "failed-cycle"),
            ).fetchone()
        assert row is not None
        assert row[1] == "FAILED"
        assert runtime.jobs.get(row[0]).status == "FAILED"
        assert runtime.audit.entries()[-1].event_type == "SOURCE_SNAPSHOT_FAILED"
        assert runtime.audit.verify_chain().valid
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_active_lease_prevents_second_worker_from_fetching(tmp_path):
    _, runtime, provider, server, thread = _runtime_and_provider(tmp_path)
    job_name = "official-snapshot:kap-official:ok"
    try:
        held = runtime.jobs.try_start(
            job_name=job_name,
            owner_id="worker-a",
            idempotency_key="held",
            started_at=T0,
            lease_for=timedelta(minutes=10),
        )
        assert held is not None

        blocked = run_snapshot_cycle(
            runtime,
            source_id="kap-official",
            surface="ok",
            owner_id="worker-b",
            cycle_key="new-cycle",
            started_at=T0 + timedelta(minutes=1),
            provider=provider,
        )

        assert blocked.status == "SKIPPED"
        assert blocked.document_id is None
        source = runtime.source_registry.get("kap-official")
        assert source.successful_observations == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
