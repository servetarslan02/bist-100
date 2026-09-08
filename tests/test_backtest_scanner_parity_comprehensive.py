"""
ALPHA BIST — Scanner Parity Comprehensive Test Suite

ParityConfig, ParityCheckResult, ParityReport, BacktestScannerParity ve FeatureVersionLock
sınıflarının feature/signal/risk/cost parite kontrollerini, tolerans aşımlarını,
eksik/fazla anahtar analizini, sürüm kilitleme mekanizmasını ve thread güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime

import polars as pl
import pytest

from services.backtest.scanner_parity import (
    BacktestScannerParity,
    FeatureVersionLock,
    ParityCheckResult,
    ParityConfig,
    ParityReport,
    feature_version_lock,
    parity_checker,
)


def test_parity_config_hash_and_repr() -> None:
    """ParityConfig hash hesaplama ve repr doğrulaması."""
    cfg = ParityConfig(
        feature_version="v2.0",
        scoring_version="v2.1",
        risk_version="v1.5",
        cost_model_version="v3.0",
    )
    assert len(cfg.config_hash) == 16
    assert "feature=v2.0" in repr(cfg)
    assert cfg.config_hash in repr(cfg)


def test_parity_check_result_and_report_serialization() -> None:
    """ParityCheckResult ve ParityReport to_dict metotları doğrulaması."""
    res1 = ParityCheckResult(
        check_type="feature",
        is_parity=True,
        backtest_value={"rsi": 50.0},
        live_value={"rsi": 50.0},
        difference=0.0,
    )
    d1 = res1.to_dict()
    assert d1["check_type"] == "feature"
    assert d1["is_parity"] is True
    assert "UYUMLU" in repr(res1)

    report = ParityReport(
        timestamp=datetime.now(UTC).isoformat(),
        config_hash="abc12345",
        total_checks=1,
        passed_checks=1,
        failed_checks=0,
        is_full_parity=True,
        checks=[res1],
    )
    rep_d = report.to_dict()
    assert rep_d["is_full_parity"] is True
    assert rep_d["passed"] == 1
    assert "full_parity=True" in repr(report)


def test_verify_feature_parity_tolerances_and_mismatches() -> None:
    """verify_feature_parity eksik anahtar, tolerans aşımı ve uyumlu durumları doğrular."""
    checker = BacktestScannerParity()

    def mock_feats(df: pl.DataFrame, ticker: str, dt: datetime) -> dict[str, float]:
        return {"rsi": 50.0001, "macd": 1.5, "extra": 10.0}

    checker.register_engines(feature_engine=mock_feats, signal_engine=lambda f, t: 75.0)

    df = pl.DataFrame({"date": [datetime.now(UTC)], "close": [100.0]})
    dt = datetime.now(UTC)

    # 1. Beklenen değerle tolerans içinde uyumlu durum
    res_ok = checker.verify_feature_parity(
        data=df,
        ticker="THYAO",
        timestamp=dt,
        expected_features={"rsi": 50.0001, "macd": 1.5},
        tolerance=1e-4,
    )
    assert res_ok.is_parity is True
    assert "extra" in res_ok.details["fazla_anahtarlar"]

    # 2. Tolerans aşımı
    res_diff = checker.verify_feature_parity(
        data=df,
        ticker="THYAO",
        timestamp=dt,
        expected_features={"rsi": 55.0},
        tolerance=0.01,
    )
    assert res_diff.is_parity is False
    assert res_diff.details["uyusmazlik_sayisi"] > 0

    # 3. Eksik anahtar
    res_missing = checker.verify_feature_parity(
        data=df,
        ticker="THYAO",
        timestamp=dt,
        expected_features={"missing_feat": 10.0},
    )
    assert res_missing.is_parity is False
    assert "missing_feat" in res_missing.details["eksik_anahtarlar"]


def test_verify_signal_risk_and_cost_parity() -> None:
    """Signal, Risk ve Cost motorlarının parite doğrulaması."""
    checker = BacktestScannerParity()

    checker.register_engines(
        feature_engine=lambda df, t, dt: {"f1": 1.0},
        signal_engine=lambda feats, t: 85.0,
        risk_engine=lambda port, ord: ord.get("qty", 0) <= 100,
        cost_engine=lambda ord, mkt: 12.5,
    )

    # Sinyal paritesi
    sig_res = checker.verify_signal_parity({"f1": 1.0}, "THYAO", expected_score=85.0)
    assert sig_res.is_parity is True
    sig_res_bad = checker.verify_signal_parity({"f1": 1.0}, "THYAO", expected_score=90.0)
    assert sig_res_bad.is_parity is False

    # Risk paritesi
    risk_res = checker.verify_risk_parity({}, {"qty": 50}, expected_decision=True)
    assert risk_res.is_parity is True
    risk_res_fail = checker.verify_risk_parity({}, {"qty": 150}, expected_decision=True)
    assert risk_res_fail.is_parity is False

    # Maliyet paritesi
    cost_res = checker.verify_cost_parity({}, {}, expected_cost=12.5)
    assert cost_res.is_parity is True
    cost_res_bad = checker.verify_cost_parity({}, {}, expected_cost=15.0)
    assert cost_res_bad.is_parity is False


def test_run_full_parity_check() -> None:
    """run_full_parity_check tam pipeline denetimi ve girdi doğrulama testi."""
    checker = BacktestScannerParity()
    checker.register_engines(
        feature_engine=lambda df, t, dt: {"rsi": 50.0},
        signal_engine=lambda f, t: 80.0,
    )

    df = pl.DataFrame({
        "ticker": ["THYAO", "ASELS"],
        "date": [datetime.now(UTC), datetime.now(UTC)],
        "close": [100.0, 50.0],
    })

    report = checker.run_full_parity_check(
        test_data=df,
        test_tickers=["THYAO", "ASELS"],
        test_timestamp=datetime.now(UTC),
    )

    assert report.total_checks >= 2
    assert report.is_full_parity is True

    # Geçersiz girdi kontrolü
    with pytest.raises(ValueError, match="test verisi boş olamaz"):
        checker.run_full_parity_check(pl.DataFrame(), ["THYAO"], datetime.now(UTC))

    with pytest.raises(ValueError, match="en az bir hisse"):
        checker.run_full_parity_check(df, [], datetime.now(UTC))


def test_feature_version_lock_lifecycle() -> None:
    """FeatureVersionLock sürüm kaydetme, aktif sürüm değiştirme ve doğrulama testi."""
    lock = FeatureVersionLock()
    lock.register_version(
        version="v1.0",
        feature_names=["rsi_14", "macd"],
        computation_config={"window": 14},
    )

    assert "v1.0" in lock.list_versions()
    info = lock.get_version_info("v1.0")
    assert info is not None
    assert info["feature_names"] == ["rsi_14", "macd"]
    assert len(info["hash"]) == 16

    lock.set_active_version("v1.0")
    assert lock.get_active_version() == "v1.0"
    assert lock.validate_version_match("v1.0") is True
    assert lock.validate_version_match("v2.0") is False

    # Hata fırlatma kontrolleri
    with pytest.raises(ValueError, match="Sürüm adı boş olamaz"):
        lock.register_version("", ["f1"], {})

    with pytest.raises(ValueError, match="en az bir öznitelik"):
        lock.register_version("v2.0", [], {})

    with pytest.raises(ValueError, match="Bilinmeyen feature versiyonu"):
        lock.set_active_version("non_existent_version")

    assert repr(feature_version_lock).startswith("FeatureVersionLock")
    assert repr(parity_checker).startswith("BacktestScannerParity")


def test_scanner_parity_thread_safety() -> None:
    """Eşzamanlı thread'lerde parite denetimi ve sürüm kilidi güvenliği."""
    checker = BacktestScannerParity()
    checker.register_engines(
        feature_engine=lambda df, t, dt: {"p": 10.0},
        signal_engine=lambda f, t: 50.0,
    )
    df = pl.DataFrame({"ticker": ["GARAN"], "close": [10.0]})
    dt = datetime.now(UTC)

    def _task(i: int) -> bool:
        res = checker.verify_feature_parity(df, "GARAN", dt)
        return res.is_parity

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_task, i) for i in range(8)]
        results = [f.result() for f in futures]

    assert all(results)
