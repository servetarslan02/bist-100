import json
import subprocess
import sys
from datetime import timedelta

import pytest

from alpha_v4.contracts import CanonicalEvent, EvidenceRef
from alpha_v4.runtime import AlphaRuntime, RuntimeConfig, RuntimeMode, UnknownSourceError
from alpha_v4.source_registry import SourceKind, SourceRecord, SourceRegistry


def test_cli_status_bootstraps_fresh_database(tmp_path):
    database = tmp_path / "runtime.sqlite3"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alpha_v4",
            "status",
            "--mode",
            "test",
            "--db",
            str(database),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["mode"] == "test"
    assert payload["event_store"] == "ready"
    assert payload["event_count"] == 0
    assert payload["real_money_execution"] is False
    assert database.exists()


def test_runtime_rejects_unregistered_event_source(tmp_path):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    event = CanonicalEvent(
        event_type="contract_award",
        source_id="unknown",
        source_timestamp=now,
        ingest_timestamp=now,
        effective_timestamp=now,
        entities=("TEST",),
        payload={"value": 1},
        evidence=(
            EvidenceRef(
                source_id="unknown",
                source_timestamp=now,
                ingest_timestamp=now,
                locator="test://1",
            ),
        ),
    )
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=tmp_path / "runtime.sqlite3")
    )

    with pytest.raises(UnknownSourceError):
        runtime.ingest_event(event)

    assert runtime.events.count() == 0


def test_runtime_ingests_only_registered_enabled_source(tmp_path):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    registry = SourceRegistry(
        [
            SourceRecord(
                source_id="kap",
                kind=SourceKind.KAP,
                owner="KAP",
                access_method="official",
                timezone_name="Europe/Istanbul",
                freshness_limit=timedelta(minutes=5),
            )
        ]
    )
    event = CanonicalEvent(
        event_type="contract_award",
        source_id="kap",
        source_timestamp=now,
        ingest_timestamp=now,
        effective_timestamp=now,
        entities=("TEST",),
        payload={"value": 1},
        evidence=(
            EvidenceRef(
                source_id="kap",
                source_timestamp=now,
                ingest_timestamp=now,
                locator="kap://1",
            ),
        ),
    )
    runtime = AlphaRuntime(
        RuntimeConfig(mode=RuntimeMode.TEST, database_path=tmp_path / "runtime.sqlite3"),
        source_registry=registry,
    )

    runtime.ingest_event(event)

    assert runtime.events.count() == 1
    assert runtime.health()["registered_sources"] == 1
