"""ALPHA BIST — FinRL BIST Environment."""
import numpy as np
from typing import Dict, Any, Optional
import structlog
logger = structlog.get_logger()

class BISTTradingEnv:
    """BIST için FinRL trading environment."""
    def __init__(self, data: np.ndarray, initial_capital: float = 100000, lookback: int = 20):
        self.data = data
        self.initial_capital = initial_capital
        self.lookback = lookback
        self.reset()

    def reset(self):
        self.step_idx = self.lookback
        self.capital = self.initial_capital
        self.position = 0
        self.done = False
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        if self.step_idx >= len(self.data):
            return np.zeros(10)
        window = self.data[max(0, self.step_idx-self.lookback):self.step_idx]
        if len(window) == 0: return np.zeros(10)
        return np.array([
            window[-1, 0] if window.shape[1] > 0 else 0,  # close
            np.mean(window[:, 0]) if window.shape[1] > 0 else 0,  # sma
            np.std(window[:, 0]) if window.shape[1] > 0 else 0,  # vol
            self.capital / self.initial_capital,
            self.position,
            0, 0, 0, 0, 0
        ])

    def step(self, action: int):
        """Action: 0=HOLD, 1=BUY, 2=SELL."""
        if self.step_idx >= len(self.data):
            self.done = True; return self._get_state(), 0, True, {}
        price = self.data[self.step_idx, 0]
        reward = 0
        if action == 1 and self.position == 0:
            self.position = self.capital / price if price > 0 else 0
            self.capital = 0
        elif action == 2 and self.position > 0:
            self.capital = self.position * price
            reward = (self.capital - self.initial_capital) / self.initial_capital
            self.position = 0
        self.step_idx += 1
        if self.step_idx >= len(self.data): self.done = True
        return self._get_state(), reward, self.done, {}

finrl_env = BISTTradingEnv
