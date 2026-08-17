"""ALPHA BIST — Hybrid Model (FinGPT + RL)."""
from typing import Dict, Any
import structlog
logger = structlog.get_logger()

def hybrid_predict(rl_action: int, sentiment_score: float, market_state: str = "NORMAL") -> Dict[str, Any]:
    """FinGPT sentiment + RL action birleşimi."""
    # Sentiment-adjusted action
    if rl_action == 1 and sentiment_score > 0.6:
        action = "BUY"; confidence = 0.8
    elif rl_action == 2 and sentiment_score < 0.4:
        action = "SELL"; confidence = 0.8
    elif rl_action == 1 and sentiment_score < 0.4:
        action = "HOLD"; confidence = 0.5  # Conflict
    else:
        action = "HOLD"; confidence = 0.4
    return {"action": action, "confidence": confidence, "rl_action": rl_action, "sentiment": sentiment_score}
