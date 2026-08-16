from datetime import datetime, timedelta, timezone

import pytest

from alpha_v4.source_history import PersistentSourceRegistry
from alpha_v4.source_registry import SourceKind, SourceRecord

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def _record():
    return SourceRecord(
        source_id="kap-official",
        kind=SourceKind.KAP,
        owner="KAP/MKK",
        access_method="public-web",
        timezone_name="Europe/Istanbul",
        freshness_limit=timedelta(minutes=5),
    )


def test_source_reliability_history_survives_restart(tmp_path):
    db = tmp_path / "sources.sqlite3"
    registry = PersistentSourceRegistry(db)
    registry.register(_record())
    registry.record_observation("kap-official", "SUCCESS", observed_at=T0)
    registry.record_observation(
        "kap-official", "SUCCESS", observed_at=T0 + timedelta(minutes=1)
    )
    registry.record_observation(
        "kap-official", "FAILURE", observed_at=T0 + timedelta(minutes=2)
    )
    registry.record_observation(
        "kap-official", "CONTRADICTION", observed_at=T0 + timedelta(minutes=3)
    )

    loaded = PersistentSourceRegistry(db).get("kap-official")

    assert loaded.successful_observations == 2
    assert loaded.failed_observations == 1
    assert loaded.contradictions == 1
    assert loaded.measured_reliability == pytest.approx(0.5)


def test_new_source_has_unknown_not_fake_reliability(tmp_path):
    registry = PersistentSourceRegistry(tmp_path / "sources.sqlite3")
    registry.register(_record())

    assert registry.get("kap-official").measured_reliability is None


def test_unknown_source_observation_is_rejected(tmp_path):
    registry = PersistentSourceRegistry(tmp_path / "sources.sqlite3")

    with pytest.raises(KeyError):
        registry.record_observation("missing", "SUCCESS", observed_at=T0)
