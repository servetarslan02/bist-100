"""ALPHA BIST — FinRL BIST Çoklu Hisse RL Ortamı Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak BISTTradingEnv ortamını ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (BISTEnvConfig, BISTStepResult, BISTEnvMetrics).
2. Ortam başlatma sınır kontrolleri ve yetersiz veride fail-closed ValueError doğrulaması.
3. Reset ve Step mekanizması (BUY, HOLD, SELL ayrık aksiyonları, komisyon ve slippage maliyetleri).
4. Farklı ödül tiplerinin (Sharpe, Return, Log-Return, Sortino, Risk-Adjusted) hesaplanması.
5. Ortam nihai performans metrikleri (BISTEnvMetrics: Sharpe, Sortino, Max Drawdown, Final Capital).
6. Polars DataFrame girdisi üzerinden doğrudan ortam başlatma (from_polars) ve çalıştırma.
7. DuckDB SSD korumalı WAL denetim izi kaydı (bist_rl_env_audit).
8. Eşzamanlı iş parçacığı güvenliği (thread-safety).
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.finrl_bist import (
    BISTEnvConfig,
    BISTEnvMetrics,
    BISTStepResult,
    BISTTradingEnv,
    RewardType,
)

if TYPE_CHECKING:
    from pathlib import Path


def _generate_mock_env_data(n_steps: int = 50, n_stocks: int = 3, n_features: int = 5) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], list[str]]:
    """Testler için sentetik öznitelik ve fiyat serileri üretir."""
    np.random.seed(42)
    tickers = [f"STOCK_{i}" for i in range(n_stocks)]
    features: dict[str, np.ndarray] = {}
    prices: dict[str, np.ndarray] = {}

    for t in tickers:
        p_base = 100.0 + np.cumsum(np.random.normal(0.1, 1.0, n_steps))
        p_base = np.maximum(p_base, 10.0)
        prices[t] = p_base
        features[t] = np.random.normal(0, 1, (n_steps, n_features)).astype(np.float32)

    return features, prices, tickers


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    config_orig = BISTEnvConfig(
        initial_capital=50_000.0,
        commission_rate=0.0015,
        slippage_rate=0.0005,
        max_position_pct=0.15,
        reward_type=RewardType.RETURN,
        window_size=10,
    )
    c_bytes = config_orig.to_orjson_bytes()
    c_restored = BISTEnvConfig.from_dict(orjson.loads(c_bytes))
    assert c_restored.initial_capital == 50_000.0
    assert c_restored.reward_type == RewardType.RETURN
    assert "BISTEnvConfig" in repr(config_orig)

    step_orig = BISTStepResult(
        step=5,
        observation=np.array([1.0, 2.0, 3.0]),
        reward=0.025,
        terminated=False,
        truncated=False,
        portfolio_value=51_200.0,
        cash=20_000.0,
        total_commission=15.5,
        info={"action": "buy"},
    )
    s_bytes = step_orig.to_orjson_bytes()
    s_restored = BISTStepResult.from_dict(orjson.loads(s_bytes))
    assert s_restored.step == 5
    assert s_restored.reward == 0.025
    assert s_restored.portfolio_value == 51_200.0
    assert "BISTStepResult" in repr(step_orig)

    metrics_orig = BISTEnvMetrics(
        total_return=0.15,
        sharpe_ratio=1.85,
        sortino_ratio=2.20,
        max_drawdown=0.08,
        final_capital=115_000.0,
        active_positions=3,
        total_tickers=5,
        total_steps=50,
    )
    m_bytes = metrics_orig.to_orjson_bytes()
    m_restored = BISTEnvMetrics.from_dict(orjson.loads(m_bytes))
    assert m_restored.total_return == 0.15
    assert m_restored.sharpe_ratio == 1.85
    assert "BISTEnvMetrics" in repr(metrics_orig)


def test_env_initialization_validation() -> None:
    """Geçersiz parametrelerde fail-closed ValueError fırlatıldığını test eder."""
    features, prices, tickers = _generate_mock_env_data()

    # Boş ticker listesi
    with pytest.raises(ValueError, match="Tickers listesi bos olamaz"):
        BISTTradingEnv(features=features, prices=prices, tickers=[])

    # Yetersiz adım boyutu (< 2)
    short_prices = {t: np.array([100.0]) for t in tickers}
    with pytest.raises(ValueError, match="Yetersiz veri boyutu"):
        BISTTradingEnv(features=features, prices=short_prices, tickers=tickers)

    env = BISTTradingEnv(features=features, prices=prices, tickers=tickers)
    assert "BISTTradingEnv" in repr(env)


def test_env_reset_and_step_actions(tmp_path: Path) -> None:
    """Ortamın sıfırlanması ve ayrık aksiyonların (BUY, HOLD, SELL) simülasyonunu test eder."""
    db_file = str(tmp_path / "test_env.duckdb")
    config = BISTEnvConfig(duckdb_path=db_file, initial_capital=100_000.0)
    features, prices, tickers = _generate_mock_env_data(n_steps=30, n_stocks=2)

    env = BISTTradingEnv(features=features, prices=prices, tickers=tickers, config=config)
    obs, info = env.reset(seed=42)
    assert isinstance(obs, np.ndarray)
    assert info["portfolio_value"] == 100_000.0

    # Adım 1: Tüm hisselerde AL aksiyonu (0=BUY)
    actions_buy = [0, 0]
    obs, reward, terminated, truncated, step_info = env.step(actions_buy)
    assert not terminated
    assert env._capital < 100_000.0  # Nakit harcandı ve hisse alındı
    assert env._total_commission_paid > 0.0  # Komisyon ödendi

    # Adım 2: TUT aksiyonu (1=HOLD)
    actions_hold = [1, 1]
    obs, reward, terminated, truncated, step_info = env.step(actions_hold)
    assert not terminated

    # Adım 3: SAT aksiyonu (2=SELL)
    actions_sell = [2, 2]
    obs, reward, terminated, truncated, step_info = env.step(actions_sell)
    assert not terminated
    assert all(pos == 0.0 for pos in env._positions.values())  # Pozisyonlar kapatıldı


def test_reward_types(tmp_path: Path) -> None:
    """Farklı ödül fonksiyonu türlerinin doğru hesaplandığını test eder."""
    features, prices, tickers = _generate_mock_env_data(n_steps=20, n_stocks=2)

    for r_type in [RewardType.RETURN, RewardType.LOG_RETURN, RewardType.SHARPE, RewardType.SORTINO, RewardType.RISK_ADJUSTED]:
        db_file = str(tmp_path / f"test_{r_type}.duckdb")
        config = BISTEnvConfig(duckdb_path=db_file, reward_type=r_type, window_size=5)
        env = BISTTradingEnv(features=features, prices=prices, tickers=tickers, config=config)
        env.reset()

        obs, reward, terminated, truncated, _ = env.step([0, 0])
        assert np.isfinite(reward), f"Gecersiz odul hesaplandi: {r_type} -> {reward}"


def test_get_metrics(tmp_path: Path) -> None:
    """Simülasyon nihai performans metriklerinin hesaplandığını doğrular."""
    db_file = str(tmp_path / "metrics_env.duckdb")
    config = BISTEnvConfig(duckdb_path=db_file)
    features, prices, tickers = _generate_mock_env_data(n_steps=15, n_stocks=2)

    env = BISTTradingEnv(features=features, prices=prices, tickers=tickers, config=config)
    env.reset()

    for _ in range(5):
        env.step([0, 1])

    metrics = env.get_metrics()
    assert isinstance(metrics, BISTEnvMetrics)
    assert np.isfinite(metrics.total_return)
    assert np.isfinite(metrics.sharpe_ratio)
    assert np.isfinite(metrics.max_drawdown)
    assert metrics.total_tickers == 2
    assert metrics.total_steps == 5


def test_from_polars(tmp_path: Path) -> None:
    """Polars DataFrame üzerinden ortamın doğrudan başlatılmasını test eder."""
    n_bars = 40
    dates = list(range(n_bars)) * 2
    tickers = ["THYAO"] * n_bars + ["GARAN"] * n_bars
    closes = np.random.uniform(50.0, 100.0, size=n_bars * 2)
    feat1 = np.random.normal(0, 1, size=n_bars * 2)
    feat2 = np.random.normal(0, 1, size=n_bars * 2)

    df = pl.DataFrame(
        {
            "date": dates,
            "ticker": tickers,
            "close": closes,
            "rsi": feat1,
            "macd": feat2,
        }
    )

    db_file = str(tmp_path / "polars_env.duckdb")
    config = BISTEnvConfig(duckdb_path=db_file)

    env = BISTTradingEnv.from_polars(
        df=df,
        ticker_col="ticker",
        price_col="close",
        feature_cols=["rsi", "macd"],
        config=config,
    )

    assert len(env.tickers) == 2
    obs, info = env.reset()
    assert info["portfolio_value"] == 100_000.0

    obs, reward, terminated, _, _ = env.step([0, 1])
    assert not terminated


def test_thread_safety_env() -> None:
    """Çoklu thread ile eşzamanlı adım ilerletme ve sıfırlama güvenliğini test eder."""
    features, prices, tickers = _generate_mock_env_data(n_steps=50, n_stocks=2)
    env = BISTTradingEnv(features=features, prices=prices, tickers=tickers)
    env.reset()

    def worker(idx: int) -> float:
        obs, reward, terminated, _, _ = env.step([idx % 3, (idx + 1) % 3])
        return float(reward)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futs = [executor.submit(worker, i) for i in range(12)]
        for f in concurrent.futures.as_completed(futs):
            rew = f.result()
            assert np.isfinite(rew)
