import sqlite3
from datetime import datetime, timedelta, timezone

from alpha_v4.audit import AuditLedger

UTC = timezone.utc
T0 = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_audit_chain_is_restart_safe_and_verifiable(tmp_path):
    db = tmp_path / "audit.sqlite3"
    ledger = AuditLedger(db)
    first = ledger.append(
        "DECISION_CREATED",
        {
            "decision_id": "d1",
            "instrument_id": "inst-a",
            "model_id": "model-1",
            "state_snapshot_ids": ["s1"],
            "feature_refs": ["momentum@1"],
        },
        created_at=T0,
        entry_id="audit-1",
    )
    second = ledger.append(
        "RISK_DECISION",
        {
            "decision_id": "d1",
            "risk_decision_id": "r1",
            "action": "NO_TRADE",
            "reasons": ["data_integrity_unresolved"],
        },
        created_at=T0 + timedelta(seconds=1),
        entry_id="audit-2",
    )

    restarted = AuditLedger(db)
    verification = restarted.verify_chain()
    entries = restarted.entries()

    assert verification.valid
    assert verification.checked_entries == 2
    assert entries[0].entry_hash == first.entry_hash
    assert entries[1].previous_hash == first.entry_hash
    assert entries[1].entry_hash == second.entry_hash


def test_silent_payload_rewrite_is_detected(tmp_path):
    db = tmp_path / "audit.sqlite3"
    ledger = AuditLedger(db)
    ledger.append(
        "DECISION_CREATED",
        {"decision_id": "d1", "requested_notional": 1000},
        created_at=T0,
        entry_id="audit-1",
    )
    ledger.append(
        "RISK_DECISION",
        {"decision_id": "d1", "action": "REDUCE", "approved_notional": 500},
        created_at=T0 + timedelta(seconds=1),
        entry_id="audit-2",
    )

    # Simulate a privileged/manual DB tamper. The audit verifier must catch it.
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE audit_entries SET payload_json = ? WHERE entry_id = ?",
            ('{"decision_id":"d1","requested_notional":999999}', "audit-1"),
        )

    verification = AuditLedger(db).verify_chain()

    assert not verification.valid
    assert verification.first_invalid_sequence == 1
    assert verification.reason == "entry_hash_mismatch"


def test_hash_chain_detects_deleted_middle_entry(tmp_path):
    db = tmp_path / "audit.sqlite3"
    ledger = AuditLedger(db)
    for index in range(3):
        ledger.append(
            "EVENT",
            {"index": index},
            created_at=T0 + timedelta(seconds=index),
            entry_id=f"e-{index}",
        )

    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM audit_entries WHERE entry_id = 'e-1'")

    verification = AuditLedger(db).verify_chain()

    assert not verification.valid
    assert verification.reason == "previous_hash_mismatch"
