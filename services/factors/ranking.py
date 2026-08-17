"""ALPHA BIST — Multi-Factor Ranking."""
from typing import Dict, Any, List
import structlog
logger = structlog.get_logger()

def rank_stocks(universe: List[Dict[str, Any]], factor_weights: Dict[str, float]) -> List[Dict[str, Any]]:
    """Çok faktörlü hisse sıralaması."""
    for stock in universe:
        total_score = 0
        for factor, weight in factor_weights.items():
            total_score += stock.get("factors", {}).get(factor, 0) * weight
        stock["factor_score"] = total_score
    universe.sort(key=lambda s: s.get("factor_score", 0), reverse=True)
    return universe
