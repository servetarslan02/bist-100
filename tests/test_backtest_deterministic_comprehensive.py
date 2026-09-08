"""
ALPHA BIST — Deterministic Recovery Comprehensive Test Suite

SystemCheckpoint, DeterministicRecovery, IdempotencyGuard sınıflarının
durum serileştirme, SHA-256 hash bütünlüğü, checkpoint oluşturma ve geri yükleme,
diskten okuma/temizleme, determinizm doğrulama, reprodüksiyon raporu
ve thread güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pytest

from services.backtest.deterministic import (
    DeterministicRecovery,
    IdempotencyGuard,
    SystemCheckpoint,
    deterministic_recovery,
    idempotency_guard,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_system_checkpoint_to_dict_and_repr() -> None:
    """SystemCheckpoint to_dict, compute_state_hash ve repr doğrulaması."""
    now = datetime.now(UTC)
    cp = SystemCheckpoint(
        checkpoint_id="cp_test_001",
        timestamp=now,
        config_snapshot={"param": "v1"},
        portfolio_state={"cash": 100_000.0},
        model_state={"weights": [1.0, 2.0]},
        feature_cache_state={"f1": 0.5},
        random_seed=42,
        execution_counter=5,
        hash_state="abc12345",
    )

    d = cp.to_dict()
    assert d["checkpoint_id"] == "cp_test_001"
    assert d["random_seed"] == 42
    assert d["execution_counter"] == 5
    assert len(cp.compute_state_hash()) == 16
    assert "cp_test_001" in repr(cp)
    assert "seed=42" in repr(cp)


def test_deterministic_recovery_create_and_restore(tmp_path: Path) -> None:
    """Checkpoint oluşturma, diske yazma ve restore_checkpoint testi."""
    recovery = DeterministicRecovery(storage_path=str(tmp_path))
    recovery.set_seed(100)

    cfg = {"mode": "TEST", "initial_capital": 50_000.0}
    portfolio = {"cash": 45_000.0, "positions": {"THYAO": 50}}

    cp = recovery.create_checkpoint(config=cfg, portfolio_state=portfolio)
    assert cp.checkpoint_id.startswith("cp_")
    assert cp.random_seed == 100

    # ID belirterek geri yükleme
    restored_cfg, restored_port, restored_seed = recovery.restore_checkpoint(cp.checkpoint_id)
    assert restored_cfg == cfg
    assert restored_port == portfolio
    assert restored_seed == 100

    # Son checkpoint'i geri yükleme (checkpoint_id=None)
    r_cfg, r_port, r_seed = recovery.restore_checkpoint(None)
    assert r_cfg == cfg
    assert r_port == portfolio


def test_deterministic_recovery_disk_reload_and_cleanup(tmp_path: Path) -> None:
    """Farklı bir DeterministicRecovery nesnesi ile diskten yükleme ve temizleme."""
    rec1 = DeterministicRecovery(storage_path=str(tmp_path))
    cp1 = rec1.create_checkpoint({"run": 1}, {"cash": 10_000.0})
    cp2 = rec1.create_checkpoint({"run": 2}, {"cash": 20_000.0})

    # Yeni nesne ile diskten okuma
    rec2 = DeterministicRecovery(storage_path=str(tmp_path))
    checkpoints = rec2.list_checkpoints()
    assert len(checkpoints) == 2

    r_cfg, _, _ = rec2.restore_checkpoint(cp1.checkpoint_id)
    assert r_cfg == {"run": 1}

    # Temizleme (keep_last=1)
    rec2.cleanup_old_checkpoints(keep_last=1)
    remaining = rec2.list_checkpoints()
    assert len(remaining) == 1
    assert remaining[0]["checkpoint_id"] == cp2.checkpoint_id


def test_deterministic_recovery_integrity_failure(tmp_path: Path) -> None:
    """Hash değiştirildiğinde bütünlük hatası fırlatıldığını doğrular."""
    recovery = DeterministicRecovery(storage_path=str(tmp_path))
    cp = recovery.create_checkpoint({"a": 1}, {"b": 2})

    # Sahte hash atayarak bütünlüğü boz
    cp.hash_state = "corrupted_hash"
    with pytest.raises(ValueError, match="bütünlük kontrolü başarısız"):
        recovery.restore_checkpoint(cp.checkpoint_id)


def test_validate_determinism() -> None:
    """validate_determinism fonksiyonunun rastgelelik ve determinizmi doğru ölçtüğünü test eder."""
    recovery = DeterministicRecovery()
    recovery.set_seed(42)

    def sample_func(size: int) -> np.ndarray:
        return np.random.normal(0, 1, size)

    # İlk çalıştırma
    np.random.seed(42)
    expected = sample_func(5)

    # Doğrulama
    is_det, actual = recovery.validate_determinism(sample_func, (5,), expected)
    assert is_det is True
    np.testing.assert_allclose(actual, expected)

    # Yanlış beklenen sonuç ile test
    is_det_bad, _ = recovery.validate_determinism(sample_func, (5,), expected + 1.0)
    assert is_det_bad is False


def test_generate_reproduction_report() -> None:
    """generate_reproduction_report PASS ve FAIL durumları doğrulaması."""
    recovery = DeterministicRecovery()

    orig_metrics = {"sharpe": 1.50, "return": 20.0, "max_dd": 5.0}
    repro_metrics_ok = {"sharpe": 1.5001, "return": 20.0002, "max_dd": 5.0}

    rep_pass = recovery.generate_reproduction_report(
        "run_1", "run_2", orig_metrics, repro_metrics_ok, tolerance=0.01
    )
    assert rep_pass["verdict"] == "PASS"
    assert rep_pass["is_reproducible"] is True
    assert len(rep_pass["discrepancies"]) == 0

    repro_metrics_fail = {"sharpe": 1.40, "return": 20.0, "max_dd": 5.0}
    rep_fail = recovery.generate_reproduction_report(
        "run_1", "run_3", orig_metrics, repro_metrics_fail, tolerance=0.01
    )
    assert rep_fail["verdict"] == "FAIL"
    assert rep_fail["is_reproducible"] is False
    assert len(rep_fail["discrepancies"]) == 1


def test_idempotency_guard() -> None:
    """IdempotencyGuard önbellekleme ve get_or_execute fonksiyon doğrulaması."""
    guard = IdempotencyGuard()
    call_count = 0

    def expensive_func(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x * 2

    # İlk çağrı
    res1 = guard.get_or_execute("op_double", {"x": 5}, expensive_func, 5)
    assert res1 == 10
    assert call_count == 1
    assert guard.is_already_executed("op_double", {"x": 5}) is True

    # İkinci çağrı (fonksiyon çalışmamalı, önbellekten dönmeli)
    res2 = guard.get_or_execute("op_double", {"x": 5}, expensive_func, 5)
    assert res2 == 10
    assert call_count == 1

    # Temizleme
    guard.clear_cache()
    assert guard.is_already_executed("op_double", {"x": 5}) is False
    assert "IdempotencyGuard" in repr(guard)
    assert repr(deterministic_recovery).startswith("DeterministicRecovery")
    assert repr(idempotency_guard).startswith("IdempotencyGuard")


def test_deterministic_recovery_thread_safety(tmp_path: Path) -> None:
    """Eşzamanlı checkpoint oluşturma ve idempotency denetimleri güvenliği."""
    recovery = DeterministicRecovery(storage_path=str(tmp_path))

    def _task(i: int) -> str:
        cp = recovery.create_checkpoint({"idx": i}, {"cash": i * 1000})
        return cp.checkpoint_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_task, i) for i in range(8)]
        ids = [f.result() for f in futures]

    assert len(ids) == 8
    assert len(set(ids)) == 8  # Tüm checkpoint id'leri benzersiz olmalı
