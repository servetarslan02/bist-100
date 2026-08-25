"""ALPHA BIST — RL Agent (Nihai —⭐⭐⭐⭐⭐).

Reinforcement Learning agent — PPO, A2C, DQN desteği,
custom reward function, multi-action space, proper training.
"""
import numpy as np
from typing import Dict, Any, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class RLConfig:
    """RL Agent konfigürasyonu."""
    algorithm: str = "PPO"  # PPO, A2C, DQN
    total_timesteps: int = 100_000
    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    reward_type: str = "sharpe"  # sharpe, return, risk_adjusted
    action_space: str = "discrete"  # discrete (BUY/HOLD/SELL), continuous (position_size)
    device: str = "auto"


class BISTTradingEnv:
    """BIST trading environment — Gymnasium uyumlu.

    Özellikler:
    - Discrete action space (BUY/HOLD/SELL)
    - Continuous action space (position size -1 ile 1 arası)
    - Custom reward functions (Sharpe, return, risk-adjusted)
    - Transaction cost dahil
    - Position tracking
    - Multi-feature observation
    """

    def __init__(
        self,
        features: np.ndarray,
        prices: np.ndarray,
        returns: Optional[np.ndarray] = None,
        initial_capital: float = 100_000,
        commission_rate: float = 0.001,
        max_position: float = 1.0,
        reward_type: str = "sharpe",
        action_space: str = "discrete",
    ):
        self.features = features
        self.prices = prices
        self.returns = returns if returns is not None else np.diff(prices) / prices[:-1]
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.max_position = max_position
        self.reward_type = reward_type
        self.action_space_type = action_space

        # State
        self._current_step = 0
        self._capital = initial_capital
        self._position = 0.0  # -1 ile 1 arası
        self._portfolio_values = [initial_capital]
        self._trades = []

        # Gymnasium interface
        self.observation_space = self._make_observation_space()
        self.action_space = self._make_action_space()

    def _make_observation_space(self):
        """Observation space oluştur."""
        try:
            from gymnasium import spaces
            return spaces.Box(low=-np.inf, high=np.inf, shape=(self.features.shape[1] + 2,), dtype=np.float32)
        except ImportError:
            return None

    def _make_action_space(self):
        """Action space oluştur."""
        try:
            from gymnasium import spaces
            if self.action_space_type == "discrete":
                return spaces.Discrete(3)  # BUY, HOLD, SELL
            else:
                return spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)
        except ImportError:
            return None

    def reset(self, seed=None):
        """Environment'ı sıfırla."""
        self._current_step = 0
        self._capital = self.initial_capital
        self._position = 0.0
        self._portfolio_values = [self.initial_capital]
        self._trades = []
        return self._get_observation(), {}

    def step(self, action):
        """Bir adım ilerle."""
        if self._current_step >= len(self.returns) - 1:
            return self._get_observation(), 0.0, True, False, {}

        # Action'ı position'a dönüştür
        if self.action_space_type == "discrete":
            if action == 0:  # BUY
                new_position = min(self._position + 0.5, self.max_position)
            elif action == 2:  # SELL
                new_position = max(self._position - 0.5, -self.max_position)
            else:  # HOLD
                new_position = self._position
        else:
            new_position = float(action) * self.max_position

        # Transaction cost
        position_change = abs(new_position - self._position)
        commission = position_change * self.commission_rate * self._capital

        # Return
        daily_return = self.returns[self._current_step]
        portfolio_return = self._position * daily_return * self._capital

        # Update
        self._capital += portfolio_return - commission
        self._position = new_position
        self._portfolio_values.append(self._capital)
        if len(self._portfolio_values) > 5000:
            self._portfolio_values = self._portfolio_values[-5000:]
        self._current_step += 1

        # Reward
        reward = self._compute_reward()

        # Done
        done = self._current_step >= len(self.returns) - 1 or self._capital <= 0

        return self._get_observation(), reward, done, False, {}

    def _get_observation(self):
        """Observation döndür."""
        if self._current_step >= len(self.features):
            return np.zeros(self.features.shape[1] + 2, dtype=np.float32)

        obs = np.concatenate([
            self.features[self._current_step],
            [self._position, self._capital / self.initial_capital],
        ]).astype(np.float32)
        return obs

    def _compute_reward(self) -> float:
        """Reward hesapla."""
        if len(self._portfolio_values) < 2:
            return 0.0

        if self.reward_type == "return":
            return (self._portfolio_values[-1] / self._portfolio_values[-2]) - 1.0
        elif self.reward_type == "sharpe":
            if len(self._portfolio_values) < 5:
                return 0.0
            returns = np.diff(self._portfolio_values[-20:]) / np.array(self._portfolio_values[-21:-1])
            if np.std(returns) < 1e-8:
                return 0.0
            return float(np.mean(returns) / np.std(returns) * np.sqrt(252))
        else:  # risk_adjusted
            return (self._portfolio_values[-1] / self.initial_capital) - 1.0

    def get_metrics(self) -> Dict[str, Any]:
        """Performans metrikleri."""
        values = np.array(self._portfolio_values)
        total_return = (values[-1] / self.initial_capital) - 1.0
        daily_returns = np.diff(values) / values[:-1]
        sharpe = float(np.mean(daily_returns) / max(np.std(daily_returns), 1e-8) * np.sqrt(252))

        running_max = np.maximum.accumulate(values)
        drawdown = (values - running_max) / running_max
        max_drawdown = float(np.abs(np.min(drawdown)))

        return {
            "total_return": round(total_return, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "final_capital": round(float(values[-1]), 2),
            "n_trades": len(self._trades),
        }


def train_rl_agent(
    env: Any,
    config: Optional[RLConfig] = None,
) -> Any:
    """RL agent eğit.

    Args:
        env: Gymnasium environment
        config: RL konfigürasyonu

    Returns:
        Eğitilmiş model
    """
    config = config or RLConfig()

    try:
        from stable_baselines3 import PPO, A2C, DQN
        from stable_baselines3.common.vec_env import DummyVecEnv
    except ImportError:
        logger.warning("stable-baselines3 not installed — pip install stable-baselines3")
        return None

    # Vectorize environment
    vec_env = DummyVecEnv([lambda: env])

    # Model seçimi
    if config.algorithm == "PPO":
        model = PPO(
            "MlpPolicy", vec_env,
            learning_rate=config.learning_rate,
            gamma=config.gamma,
            gae_lambda=config.gae_lambda,
            clip_range=config.clip_range,
            ent_coef=config.ent_coef,
            vf_coef=config.vf_coef,
            max_grad_norm=config.max_grad_norm,
            n_steps=config.n_steps,
            batch_size=config.batch_size,
            n_epochs=config.n_epochs,
            verbose=0,
            device=config.device,
        )
    elif config.algorithm == "A2C":
        model = A2C(
            "MlpPolicy", vec_env,
            learning_rate=config.learning_rate,
            gamma=config.gamma,
            gae_lambda=config.gae_lambda,
            ent_coef=config.ent_coef,
            vf_coef=config.vf_coef,
            max_grad_norm=config.max_grad_norm,
            n_steps=config.n_steps,
            verbose=0,
            device=config.device,
        )
    elif config.algorithm == "DQN":
        model = DQN(
            "MlpPolicy", vec_env,
            learning_rate=config.learning_rate,
            gamma=config.gamma,
            batch_size=config.batch_size,
            verbose=0,
            device=config.device,
        )
    else:
        logger.error("unknown_algorithm", algorithm=config.algorithm)
        return None

    # Eğitim
    logger.info("rl_training_started", algorithm=config.algorithm, timesteps=config.total_timesteps)
    model.learn(total_timesteps=config.total_timesteps)
    logger.info("rl_training_completed", algorithm=config.algorithm)

    return model


def evaluate_rl_agent(model: Any, env: Any, n_episodes: int = 10) -> Dict[str, Any]:
    """RL agent'ı değerlendir.

    Args:
        model: Eğitilmiş RL modeli
        env: Test environment'ı
        n_episodes: Test episode sayısı

    Returns:
        Performans metrikleri
    """
    episode_rewards = []
    episode_metrics = []

    for episode in range(n_episodes):
        obs, _ = env.reset()
        total_reward = 0
        done = False

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, done, _, _ = env.step(action)
            total_reward += reward

        episode_rewards.append(total_reward)
        episode_metrics.append(env.get_metrics())

    # Ortalama metrikler
    avg_metrics = {}
    if episode_metrics:
        for key in episode_metrics[0]:
            values = [m[key] for m in episode_metrics if isinstance(m.get(key), (int, float))]
            if values:
                avg_metrics[f"avg_{key}"] = round(float(np.mean(values)), 4)
                avg_metrics[f"std_{key}"] = round(float(np.std(values)), 4)

    avg_metrics["avg_episode_reward"] = round(float(np.mean(episode_rewards)), 4)
    avg_metrics["n_episodes"] = n_episodes

    return avg_metrics
