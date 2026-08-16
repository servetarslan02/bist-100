"""Raw source acquisition primitives for ALPHA v4.

The acquisition layer stores exact bytes plus source/fetch metadata before any parser,
LLM or feature transformation touches the content. This preserves replayability and
source provenance.
"""

from __future__ import annotations

import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


class SourceFetchError(RuntimeError):
    pass


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or default_port


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_origin: tuple[str, str, int]):
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != self.allowed_origin:
            raise SourceFetchError("redirect escaped configured source origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class HttpSourceConfig:
    source_id: str
    base_url: str
    timeout_seconds: float = 15.0
    user_agent: str = "ALPHA-v4-research/0.1"
    max_body_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.base_url.strip():
            raise ValueError("source_id and base_url are required")
        _origin(self.base_url)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")


@dataclass(frozen=True)
class FetchedDocument:
    document_id: str
    source_id: str
    url: str
    fetched_at: datetime
    status_code: int
    content_type: str | None
    body_sha256: str
    body: bytes


class HttpFetcher:
    def __init__(self, config: HttpSourceConfig):
        self.config = config
        self._allowed_origin = _origin(config.base_url)
        self._opener = urllib.request.build_opener(
            _SameOriginRedirectHandler(self._allowed_origin)
        )

    def fetch(
        self, path_or_url: str, *, fetched_at: datetime | None = None
    ) -> FetchedDocument:
        observed = fetched_at or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        observed = observed.astimezone(timezone.utc)

        if path_or_url.startswith(("http://", "https://")):
            url = path_or_url
            if _origin(url) != self._allowed_origin:
                raise ValueError("absolute URL is outside configured source origin")
        else:
            url = self.config.base_url.rstrip("/") + "/" + path_or_url.lstrip("/")

        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.config.user_agent, "Accept": "*/*"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self.config.timeout_seconds) as response:
                final_url = response.geturl()
                if _origin(final_url) != self._allowed_origin:
                    raise SourceFetchError("response escaped configured source origin")
                body = response.read(self.config.max_body_bytes + 1)
                if len(body) > self.config.max_body_bytes:
                    raise SourceFetchError(
                        f"response exceeded {self.config.max_body_bytes} byte limit"
                    )
                status = int(getattr(response, "status", 200))
                content_type = response.headers.get("Content-Type")
        except SourceFetchError:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise SourceFetchError(
                f"fetch failed for {self.config.source_id}: {exc}"
            ) from exc

        body_hash = sha256(body).hexdigest()
        identity = (
            f"{self.config.source_id}|{final_url}|{observed.isoformat()}|{body_hash}"
        )
        return FetchedDocument(
            document_id=sha256(identity.encode("utf-8")).hexdigest(),
            source_id=self.config.source_id,
            url=final_url,
            fetched_at=observed,
            status_code=status,
            content_type=content_type,
            body_sha256=body_hash,
            body=body,
        )


class RawDocumentStore:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_documents (
                    document_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    content_type TEXT,
                    body_sha256 TEXT NOT NULL,
                    body BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_raw_docs_source_time
                    ON raw_documents(source_id, fetched_at);
                """
            )

    def append(self, document: FetchedDocument) -> None:
        actual_hash = sha256(document.body).hexdigest()
        if actual_hash != document.body_sha256:
            raise ValueError("document body hash mismatch")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO raw_documents (
                    document_id, source_id, url, fetched_at, status_code,
                    content_type, body_sha256, body
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    document.source_id,
                    document.url,
                    document.fetched_at.isoformat(),
                    document.status_code,
                    document.content_type,
                    document.body_sha256,
                    document.body,
                ),
            )

    def get(self, document_id: str) -> FetchedDocument | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM raw_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        if row is None:
            return None
        return FetchedDocument(
            document_id=row["document_id"],
            source_id=row["source_id"],
            url=row["url"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            status_code=int(row["status_code"]),
            content_type=row["content_type"],
            body_sha256=row["body_sha256"],
            body=bytes(row["body"]),
        )
