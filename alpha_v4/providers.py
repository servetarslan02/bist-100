"""Allowlisted official-source snapshot adapters for ALPHA v4."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .acquisition import (
    FetchedDocument,
    HttpFetcher,
    HttpSourceConfig,
    RawDocumentStore,
    SourceFetchError,
)
from .source_catalog import seed_by_id


class SourceObservationRecorder(Protocol):
    def record_observation(
        self,
        source_id: str,
        outcome: str,
        *,
        observed_at: datetime,
        detail: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class SnapshotProviderConfig:
    http: HttpSourceConfig
    surfaces: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.surfaces:
            raise ValueError("at least one source surface is required")
        for name, path in self.surfaces.items():
            if not name.strip():
                raise ValueError("surface names must not be empty")
            if path.startswith(("http://", "https://")):
                raise ValueError("surface paths must be relative to the configured base URL")
            if ".." in path.split("/"):
                raise ValueError("surface paths must not contain parent traversal")


OFFICIAL_SURFACES: Mapping[str, Mapping[str, str]] = {
    "kap-official": {
        "company-directory": "/tr/sirketler/ALL",
        "disclosure-search": "/tr/bildirim-sorgu",
    },
    "bist-official-public": {
        "equity-market-data": "/veriler/pay-piyasasi-verileri",
        "market-data": "/piyasa-verileri",
    },
    "tcmb-evds": {
        "documentation": "/dokumanlar",
    },
}


class SnapshotProvider:
    """Fetch immutable raw snapshots only from named, pre-approved source surfaces."""

    def __init__(
        self,
        config: SnapshotProviderConfig,
        raw_store: RawDocumentStore,
        source_history: SourceObservationRecorder,
    ):
        self.config = config
        self.raw_store = raw_store
        self.source_history = source_history
        self.fetcher = HttpFetcher(config.http)

    def snapshot(
        self,
        surface: str,
        *,
        fetched_at: datetime | None = None,
    ) -> FetchedDocument:
        try:
            path = self.config.surfaces[surface]
        except KeyError as exc:
            raise KeyError(f"unknown source surface: {surface}") from exc

        observed_at = fetched_at or datetime.now(timezone.utc)
        try:
            document = self.fetcher.fetch(path, fetched_at=observed_at)
            if not document.body:
                raise SourceFetchError(
                    f"empty response body for {self.config.http.source_id}:{surface}"
                )
            self.raw_store.append(document)
        except (SourceFetchError, ValueError) as exc:
            self.source_history.record_observation(
                self.config.http.source_id,
                "FAILURE",
                observed_at=observed_at,
                detail=f"{surface}:{type(exc).__name__}",
            )
            raise

        self.source_history.record_observation(
            self.config.http.source_id,
            "SUCCESS",
            observed_at=observed_at,
            detail=f"{surface}:{document.status_code}:{document.body_sha256}",
        )
        return document


def official_snapshot_provider(
    source_id: str,
    *,
    raw_store: RawDocumentStore,
    source_history: SourceObservationRecorder,
) -> SnapshotProvider:
    try:
        surfaces = OFFICIAL_SURFACES[source_id]
    except KeyError as exc:
        raise KeyError(f"no official snapshot surfaces configured for: {source_id}") from exc
    seed = seed_by_id(source_id)
    return SnapshotProvider(
        SnapshotProviderConfig(http=seed.http, surfaces=surfaces),
        raw_store,
        source_history,
    )
