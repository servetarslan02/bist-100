"""
ALPHA BIST — Event Replay Engine Comprehensive Test Suite

SystemState, ReplayDecision, AuditRecord, ReplaySnapshot ve EnhancedReplayEngine
sınıflarının durum kaydetme/geri yükleme, SHA-256 hash zinciri doğrulaması,
günlük point-in-time replay, karar karşılaştırması ve eşzamanlılık güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

from services.backtest.event_replay import (
    GENESIS_HASH,
    AuditRecord,
    EnhancedReplayEngine,
    ReplayDecision,
    ReplaySnapshot,
    SystemState,
)


def test_system_state_serialization() -> None:
    """SystemState to_dict ve repr doğrulaması."""
    now = datetime.now(UTC)
    state = SystemState(
        timestamp=now,
        cash=250_000.0,
        positions={"THYAO": {"quantity": 100, "entry_price": 250.0}},
        pending_orders=[],
        regime="BULL",
        feature_cache={"f1": 1.0},
        model_version="v2.1",
        config_hash="abc12345",
    )

    d = state.to_dict()
    assert d["cash"] == 250_000.0
    assert "THYAO" in d["positions"]
    assert d["regime"] == "BULL"
    assert "SystemState" in repr(state)
    assert "250,000" in repr(state)


def test_replay_decision_serialization() -> None:
    """ReplayDecision to_dict ve repr doğrulaması."""
    now = datetime.now(UTC)
    decision = ReplayDecision(
        timestamp=now,
        ticker="ASELS",
        action="BUY",
        score=88.5,
        confidence=0.92,
        features={"rsi": 35.0, "macd": 1.2},
        reasoning="Güçlü alım sinyali",
    )

    d = decision.to_dict()
    assert d["ticker"] == "ASELS"
    assert d["action"] == "BUY"
    assert d["score"] == 88.5
    assert d["confidence"] == 0.92
    assert "ReplayDecision" in repr(decision)


def test_audit_record_hash_chain_and_seal() -> None:
    """AuditRecord SHA-256 hashleme, seal mühürleme ve to_dict testleri."""
    now = datetime.now(UTC)
    record = AuditRecord(
        event_id="evt_000001",
        timestamp=now,
        event_type="trade",
        data={"ticker": "THYAO", "price": 100.0},
    )

    h1 = record.compute_hash(GENESIS_HASH)
    assert len(h1) == 16
    sealed_hash = record.seal(GENESIS_HASH)
    assert sealed_hash == h1
    assert record.hash_chain == h1

    d = record.to_dict()
    assert d["event_id"] == "evt_000001"
    assert d["hash_chain"] == h1
    assert "AuditRecord" in repr(record)


def test_replay_snapshot_repr() -> None:
    """ReplaySnapshot nesnesinin oluşturulması ve temsili."""
    now = datetime.now(UTC)
    snap = ReplaySnapshot(
        timestamp=now,
        equity=500_000.0,
        cash=200_000.0,
        positions={},
        decisions=[],
        trades=[],
        market_state={},
    )
    assert "500,000" in repr(snap)
    assert snap.equity == 500_000.0


def test_replay_engine_lifecycle_and_integrity() -> None:
    """EnhancedReplayEngine gün replay, audit zincir bütünlüğü ve get_audit_trail testi."""
    engine = EnhancedReplayEngine(max_position_pct=0.20)
    target_dt = datetime(2025, 1, 10, 10, 0, tzinfo=UTC)

    init_state = engine.create_snapshot(
        timestamp=target_dt,
        cash=100_000.0,
        positions={},
        regime="SIDEWAYS",
    )

    market_df = pl.DataFrame({
        "date": [target_dt, target_dt],
        "ticker": ["THYAO", "GARAN"],
        "open": [100.0, 50.0],
        "high": [102.0, 52.0],
        "low": [99.0, 49.0],
        "close": [101.0, 51.0],
        "volume": [10000, 20000],
    })

    def mock_features(df: pl.DataFrame, ticker: str, dt: datetime) -> dict[str, float]:
        return {"price": 100.0}

    def mock_signals(features: dict[str, float], ticker: str, dt: datetime) -> dict[str, Any]:
        if ticker == "THYAO":
            return {"action": "BUY", "score": 80.0, "confidence": 0.8, "reasoning": "Test BUY"}
        return {"action": "HOLD", "score": 50.0, "confidence": 0.5, "reasoning": "Test HOLD"}

    decisions, trades, audit_records = engine.replay_day(
        target_date=target_dt,
        market_data=market_df,
        initial_state=init_state,
        feature_engine=mock_features,
        signal_engine=mock_signals,
    )

    assert len(decisions) == 2
    assert len(trades) == 1
    assert trades[0]["ticker"] == "THYAO"
    assert trades[0]["side"] == "BUY"

    # Audit trail doğrulaması (to_dict hatası olmamalı)
    audit_trail = engine.get_audit_trail()
    assert len(audit_trail) > 0
    assert "event_id" in audit_trail[0]

    # Zincir bütünlüğü doğrulaması
    assert engine.verify_audit_integrity() is True


def test_compare_decisions_deterministic() -> None:
    """Karar karşılaştırma raporu determinizm doğrulaması."""
    engine = EnhancedReplayEngine()
    now = datetime.now(UTC)

    d1 = ReplayDecision(now, "THYAO", "BUY", 80.0, 0.9, {}, "ok")
    d2 = ReplayDecision(now, "ASELS", "HOLD", 50.0, 0.5, {}, "ok")

    cmp_res = engine.compare_decisions([d1, d2], [d1, d2])
    assert cmp_res["is_deterministic"] is True
    assert cmp_res["mismatches"] == 0

    # Farklı skorlu karar ile test
    d1_diff = ReplayDecision(now, "THYAO", "BUY", 85.0, 0.9, {}, "ok")
    cmp_diff = engine.compare_decisions([d1, d2], [d1_diff, d2])
    assert cmp_diff["is_deterministic"] is False
    assert cmp_diff["mismatches"] == 1


def test_replay_engine_fail_closed() -> None:
    """None girdi durumlarında ValueError doğrulaması."""
    engine = EnhancedReplayEngine()
    with pytest.raises(ValueError, match="snapshot None olamaz"):
        engine.restore_snapshot(None)  # type: ignore[arg-type]

    now = datetime.now(UTC)
    state = engine.create_snapshot(now, 1000.0, {})
    with pytest.raises(ValueError, match="market_data None olamaz"):
        engine.replay_day(now, None, state)  # type: ignore[arg-type]


def test_replay_engine_thread_concurrency() -> None:
    """Eşzamanlı snapshot ve audit kayıt üretiminin veri bütünlüğünü bozmadığını doğrular."""
    engine = EnhancedReplayEngine()
    now = datetime.now(UTC)

    def _task(idx: int) -> int:
        engine.create_snapshot(now, 10_000.0 * idx, {}, config_hash=f"hash_{idx}")
        engine._record_event(now, "state_change", {"idx": idx})
        return idx

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_task, i) for i in range(10)]
        results = [f.result() for f in futures]

    assert len(results) == 10
    assert engine.verify_audit_integrity() is True
