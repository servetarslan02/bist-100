"""Minimal HTTP process surface for ALPHA v4 runtime health checks."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .runtime import AlphaRuntime


class RuntimeHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server bound to exactly one ALPHA runtime instance."""

    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], runtime: AlphaRuntime):
        self.runtime = runtime
        super().__init__(server_address, RuntimeHealthHandler)


class RuntimeHealthHandler(BaseHTTPRequestHandler):
    """Expose only operational health; no trading or broker endpoints exist here."""

    server: RuntimeHTTPServer

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(200, self.server.runtime.health())
            return
        self._write_json(404, {"error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        """Keep CI/process logs deterministic; callers can add structured logging later."""


def build_server(runtime: AlphaRuntime, host: str, port: int) -> RuntimeHTTPServer:
    if not host.strip():
        raise ValueError("host is required")
    if port < 0 or port > 65_535:
        raise ValueError("port must be between 0 and 65535")
    return RuntimeHTTPServer((host, port), runtime)


def serve_forever(runtime: AlphaRuntime, host: str, port: int) -> None:
    """Run the V4 health process until interrupted."""
    server = build_server(runtime, host, port)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
