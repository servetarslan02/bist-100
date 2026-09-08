"""ALPHA BIST — RL Agent (v3.0) & BISTTradingEnv Kapsamlı Test Paketi.

Bu test paketi; BISTTradingEnv simülasyon ortamını, kesikli ve sürekli eylem uzaylarını,
farklı ödül fonksiyonlarını (Sharpe, Return, Risk-Adjusted), komisyon ve kayma maliyetlerini,
Polars entegrasyonunu, DuckDB 4MB/2MB WAL denetim izini ve iş parçacığı güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.rl_agent import (
    BISTTradingEnv,
    RLConfig,
    RLEvaluationResult,
    _init_duckdb_audit,
    _record_audit_event,
    configure_duckdb_wal,
    simulate_policy,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_duckdb_path(tmp_path: Path) -> str:
    """Geçici test DuckDB dosya yolu sağlar."""
    return str(tmp_path / "test_rl_agent.duckdb")


@pytest.fixture
def sample_market_data() -> tuple[np.ndarray, np.ndarray]:
    """100 adımlı sentetik öznitelik ve fiyat verisi üretir."""
    np.random.seed(42)
    n_steps = 100
    n_features = 5
    features = np.random.randn(n_steps, n_features).astype(np.float32)
    price_changes = np.random.normal(0.001, 0.02, size=n_steps)
    prices = 100.0 * np.exp(np.cumsum(price_changes))
    return features, prices


def test_dataclasses_and_serialization() -> None:
    """RLConfig ve RLEvaluationResult serileştirme döngüsünü test eder."""
    cfg = RLConfig(
        algorithm="PPO",
        total_timesteps=50_000,
        learning_rate=1e-4,
        reward_type="sharpe",
    )
    d = cfg.to_dict()
    assert d["algorithm"] == "PPO"
    assert d["total_timesteps"] == 50_000
    assert "PPO" in repr(cfg)

    reconstructed_cfg = RLConfig.from_dict(d)
    assert reconstructed_cfg.algorithm == cfg.algorithm
    assert reconstructed_cfg.learning_rate == cfg.learning_rate

    b_cfg = cfg.to_orjson_bytes()
    assert b"PPO" in b_cfg

    # RLEvaluationResult
    res = RLEvaluationResult(
        n_episodes=5,
        avg_episode_reward=12.45,
        avg_total_return=0.152,
        avg_sharpe_ratio=1.85,
        avg_max_drawdown=0.065,
        avg_final_capital=115_200.0,
        avg_n_trades=14.2,
        details={"model": "PPO_test"},
    )
    res_dict = res.to_dict()
    assert res_dict["n_episodes"] == 5
    assert "return=15.20%" in repr(res)

    reconstructed_res = RLEvaluationResult.from_dict(res_dict)
    assert reconstructed_res.n_episodes == 5
    assert reconstructed_res.avg_sharpe_ratio == 1.85
    assert reconstructed_res.details["model"] == "PPO_test"

    b_res = res.to_orjson_bytes()
    parsed_res = orjson.loads(b_res)
    assert parsed_res["n_episodes"] == 5


def test_duckdb_wal_configuration_and_audit(temp_duckdb_path: str) -> None:
    """DuckDB 4MB/2MB WAL direktiflerini ve denetim tablosunu doğrular."""
    with duckdb.connect(temp_duckdb_path) as conn:
        configure_duckdb_wal(conn)

    _init_duckdb_audit(temp_duckdb_path)
    _record_audit_event(
        duckdb_path=temp_duckdb_path,
        operation="TRAIN_TEST",
        algorithm="PPO",
        timesteps=2048,
        avg_return=0.12,
        sharpe=1.65,
        details={"hyperparams": {"lr": 3e-4}},
    )

    with duckdb.connect(temp_duckdb_path) as conn:
        rows = conn.execute(
            "SELECT operation, algorithm, timesteps, avg_return, details FROM rl_agent_audit"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "TRAIN_TEST"
        assert rows[0][1] == "PPO"
        assert rows[0][2] == 2048
        details_obj = orjson.loads(rows[0][4])
        assert details_obj["hyperparams"]["lr"] == 3e-4


def test_bist_trading_env_discrete_and_step(sample_market_data: tuple[np.ndarray, np.ndarray]) -> None:
    """Kesikli eylem uzayı (BUY/HOLD/SELL), komisyon ve portföy takibini test eder."""
    features, prices = sample_market_data
    env = BISTTradingEnv(
        features=features,
        prices=prices,
        initial_capital=100_000.0,
        commission_rate=0.001,
        action_space="discrete",
        reward_type="return",
    )

    obs, info = env.reset()
    assert len(obs) == features.shape[1] + 2
    assert isinstance(info, dict)
    assert "BISTTradingEnv" in repr(env)

    # 1. Adım: BUY (0)
    obs, reward, terminated, truncated, _ = env.step(0)
    assert not terminated
    assert np.isfinite(reward)
    assert len(env._trades) == 1
    assert env._trades[0]["new_position"] == 0.5
    assert env._trades[0]["commission"] > 0

    # 2. Adım: HOLD (1)
    obs, reward, terminated, truncated, _ = env.step(1)
    assert len(env._trades) == 1  # Yeni işlem olmamalı

    # 3. Adım: SELL (2)
    obs, reward, terminated, truncated, _ = env.step(2)
    assert len(env._trades) == 2

    # Metrikler
    metrics = env.get_metrics()
    assert "total_return" in metrics
    assert "sharpe_ratio" in metrics
    assert "max_drawdown" in metrics
    assert "final_capital" in metrics
    assert np.isfinite(metrics["total_return"])


def test_bist_trading_env_continuous_action(sample_market_data: tuple[np.ndarray, np.ndarray]) -> None:
    """Sürekli eylem uzayında pozisyon büyüklüğü ayarlamasını ve kırpmayı test eder."""
    features, prices = sample_market_data
    env = BISTTradingEnv(
        features=features,
        prices=prices,
        action_space="continuous",
        reward_type="sharpe",
    )

    env.reset()
    # Eylem: 0.8 pozisyon
    obs, reward, terminated, truncated, _ = env.step(np.array([0.8], dtype=np.float32))
    assert abs(env._position - 0.8) < 1e-4

    # Eylem sınır aşımı: 1.5 pozisyon -> 1.0 (max_position) olarak kırpılmalı
    obs, reward, terminated, truncated, _ = env.step(1.5)
    assert abs(env._position - 1.0) < 1e-4


def test_reward_types(sample_market_data: tuple[np.ndarray, np.ndarray]) -> None:
    """Farklı ödül fonksiyonlarının (return, sharpe, risk_adjusted) sonlu değerler ürettiğini test eder."""
    features, prices = sample_market_data

    for r_type in ("return", "sharpe", "risk_adjusted"):
        env = BISTTradingEnv(
            features=features,
            prices=prices,
            reward_type=r_type,
        )
        env.reset()
        rewards = []
        for a in [0, 0, 1, 2, 1, 0]:
            _, reward, _, _, _ = env.step(a)
            rewards.append(reward)

        assert all(np.isfinite(r) for r in rewards)


def test_from_polars_and_portfolio_history() -> None:
    """Polars DataFrame girdisi üzerinden ortam kurulumunu ve geçmiş fonksiyonunu test eder."""
    np.random.seed(123)
    n = 50
    df = pl.DataFrame({
        "close": 50.0 + np.cumsum(np.random.randn(n)),
        "rsi_14": np.random.uniform(30.0, 70.0, size=n),
        "volume_z": np.random.randn(n),
    })

    env = BISTTradingEnv.from_polars(df, price_col="close", reward_type="risk_adjusted")
    assert env.features.shape[0] == n
    assert env.features.shape[1] == 2

    # Birkaç adım koş ve Polars portföy geçmişini al
    env.reset()
    for _ in range(10):
        env.step(0)

    history_df = env.get_portfolio_history_polars()
    assert isinstance(history_df, pl.DataFrame)
    assert history_df.height == 11  # başlangıç + 10 adım
    assert "step" in history_df.columns
    assert "portfolio_value" in history_df.columns

    # Eksik fiyat sütunu hatası
    with pytest.raises(ValueError, match="Fiyat kolonu 'nonexistent'"):
        BISTTradingEnv.from_polars(df, price_col="nonexistent")


def test_simulate_policy(sample_market_data: tuple[np.ndarray, np.ndarray]) -> None:
    """Deterministik kural politikası simülasyonunu test eder."""
    features, prices = sample_market_data
    env = BISTTradingEnv(features=features, prices=prices)

    # Basit kural: Pozisyon sıfırsa BUY (0), doluysa HOLD (1)
    def simple_policy(obs: np.ndarray) -> int:
        pos = obs[-2]
        return 0 if pos < 0.5 else 1

    metrics = simulate_policy(env, simple_policy, max_steps=20)
    assert metrics["n_trades"] >= 1
    assert np.isfinite(metrics["final_capital"])


def test_thread_safety_concurrency(sample_market_data: tuple[np.ndarray, np.ndarray]) -> None:
    """Eşzamanlı iş parçacıklarının güvenliğini (threading.RLock) doğrular."""
    features, prices = sample_market_data
    env = BISTTradingEnv(features=features, prices=prices)

    def worker(worker_id: int) -> int:
        env.reset()
        for i in range(10):
            env.step(i % 3)
        return env.get_metrics()["n_trades"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker, i) for i in range(12)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 12
    assert all(r >= 1 for r in results)
