"""ALPHA BIST — RL Agent Trainer."""
from typing import Dict, Any, Optional
import structlog
logger = structlog.get_logger()

def train_rl_agent(env, total_timesteps: int = 100000, algorithm: str = "PPO"):
    """RL agent eğitimi (PPO)."""
    try:
        from stable_baselines3 import PPO
        model = PPO("MlpPolicy", env, verbose=0)
        model.learn(total_timesteps=total_timesteps)
        logger.info("RL agent trained", algorithm=algorithm, timesteps=total_timesteps)
        return model
    except ImportError:
        logger.warning("stable-baselines3 not installed")
        return None
