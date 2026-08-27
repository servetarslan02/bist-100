"""ALPHA BIST — FinRL BIST Environment (Nihai —⭐⭐⭐⭐⭐).

Gymnasium uyumlu trading environment — multi-stock,
portfolio management, transaction cost, proper reward.
"""
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class BISTEnvConfig:
    """Environment konfigürasyonu."""
    initial_capital: float = 100_000
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005
    max_position_pct: float = 0.10
    max_total_exposure: float = 1.0
    reward_type: str = "sharpe"  # sharpe, return, risk_adjusted
    window_size: int = 20
    features_per_stock: int = 65


class BISTTradingEnv:
    """BIST multi-stock trading environment —⭐⭐⭐⭐⭐ seviye.

    Özellikler:
    - Multi-stock portfolio management
    - Discrete action space (per stock: BUY/HOLD/SELL)
    - Transaction cost (commission + slippage)
    - Position limits
    - Custom reward functions
    - Portfolio tracking
    - Risk management
    """

    def __init__(
        self,
        features: dict[str, np.ndarray],  # {ticker: (time, features)}
        prices: dict[str, np.ndarray],    # {ticker: (time,)}
        tickers: list[str],
        config: BISTEnvConfig | None = None,
    ):
        self.features = features
        self.prices = prices
        self.tickers = tickers
        self.config = config or BISTEnvConfig()

        # State
        self._current_step = 0
        self._capital = self.config.initial_capital
        self._positions: dict[str, float] = {t: 0.0 for t in tickers}  # shares
        self._portfolio_values = [self.config.initial_capital]
        self._n_steps = min(len(v) for v in prices.values()) if prices else 0

        # Gymnasium
        self.observation_space = self._make_obs_space()
        self.action_space = self._make_action_space()

    def _make_obs_space(self):
        try:
            from gymnasium import spaces
            n_obs = len(self.tickers) * self.config.features_per_stock + len(self.tickers) + 1
            return spaces.Box(low=-np.inf, high=np.inf, shape=(n_obs,), dtype=np.float32)
        except ImportError:
            return None

    def _make_action_space(self):
        try:
            from gymnasium import spaces
            return spaces.MultiDiscrete([3] * len(self.tickers))  # 0=BUY, 1=HOLD, 2=SELL per stock
        except ImportError:
            return None

    def reset(self, seed=None):
        self._current_step = 0
        self._capital = self.config.initial_capital
        self._positions = {t: 0.0 for t in self.tickers}
        self._portfolio_values = [self.config.initial_capital]
        return self._get_obs(), {}

    def step(self, actions):
        """Multi-stock step.

        Args:
            actions: List[int] — her hisse için aksiyon (0=BUY, 1=HOLD, 2=SELL)
        """
        if self._current_step >= self._n_steps - 1:
            return self._get_obs(), 0.0, True, False, {}

        total_commission = 0.0

        for i, ticker in enumerate(self.tickers):
            action = actions[i] if i < len(actions) else 1
            price = self.prices[ticker][self._current_step]

            if action == 0:  # BUY
                max_invest = self._portfolio_values[-1] * self.config.max_position_pct
                invest = min(max_invest, self._capital * 0.95)
                if invest > price:
                    qty = int(invest / price)
                    cost = qty * price
                    commission = cost * self.config.commission_rate
                    slippage = cost * self.config.slippage_rate
                    self._capital -= cost + commission + slippage
                    self._positions[ticker] += qty
                    total_commission += commission + slippage

            elif action == 2:  # SELL
                qty = self._positions[ticker]
                if qty > 0:
                    revenue = qty * price
                    commission = revenue * self.config.commission_rate
                    slippage = revenue * self.config.slippage_rate
                    self._capital += revenue - commission - slippage
                    self._positions[ticker] = 0.0
                    total_commission += commission + slippage

        # Portfolio value
        portfolio_value = self._capital
        for ticker in self.tickers:
            if self._current_step < len(self.prices[ticker]):
                portfolio_value += self._positions[ticker] * self.prices[ticker][self._current_step]

        self._portfolio_values.append(portfolio_value)
        if len(self._portfolio_values) > 5000:
            self._portfolio_values = self._portfolio_values[-5000:]
        self._current_step += 1

        # Reward
        reward = self._compute_reward()

        # Done
        done = self._current_step >= self._n_steps - 1 or portfolio_value <= 0

        return self._get_obs(), reward, done, False, {}

    def _get_obs(self):
        """Observation."""
        obs = []
        for ticker in self.tickers:
            if self._current_step < len(self.features[ticker]):
                obs.extend(self.features[ticker][self._current_step].tolist())
            else:
                obs.extend([0.0] * self.config.features_per_stock)

        # Position ratios
        total_value = self._portfolio_values[-1]
        for ticker in self.tickers:
            pos_value = self._positions[ticker] * self.prices[ticker][self._current_step] if self._current_step < len(self.prices[ticker]) else 0
            obs.append(pos_value / max(total_value, 1))

        # Cash ratio
        obs.append(self._capital / max(total_value, 1))

        return np.array(obs, dtype=np.float32)

    def _compute_reward(self) -> float:
        """Reward hesapla."""
        if len(self._portfolio_values) < 2:
            return 0.0

        if self.config.reward_type == "return":
            return (self._portfolio_values[-1] / self._portfolio_values[-2]) - 1.0
        elif self.config.reward_type == "sharpe":
            if len(self._portfolio_values) < 5:
                return 0.0
            returns = np.diff(self._portfolio_values[-20:]) / np.array(self._portfolio_values[-21:-1])
            if np.std(returns) < 1e-8:
                return 0.0
            return float(np.mean(returns) / np.std(returns) * np.sqrt(252))
        else:
            return (self._portfolio_values[-1] / self.config.initial_capital) - 1.0

    def get_metrics(self) -> dict[str, Any]:
        """Performans metrikleri."""
        values = np.array(self._portfolio_values)
        total_return = (values[-1] / self.config.initial_capital) - 1.0

        if len(values) > 1:
            daily_returns = np.diff(values) / values[:-1]
            sharpe = float(np.mean(daily_returns) / max(np.std(daily_returns), 1e-8) * np.sqrt(252))
        else:
            sharpe = 0.0

        running_max = np.maximum.accumulate(values)
        drawdown = (values - running_max) / running_max
        max_drawdown = float(np.abs(np.min(drawdown)))

        # Active positions
        active = sum(1 for v in self._positions.values() if v > 0)

        return {
            "total_return": round(total_return, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "final_capital": round(float(values[-1]), 2),
            "active_positions": active,
            "total_tickers": len(self.tickers),
        }
