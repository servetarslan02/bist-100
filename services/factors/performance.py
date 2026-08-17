"""ALPHA BIST — Factor Performance Tracker."""
from typing import Dict, Any, List
import numpy as np
import structlog
logger = structlog.get_logger()

def track_factor_performance(factor_returns: List[float], benchmark_returns: List[float]) -> Dict[str, Any]:
    """Faktör performansı takibi."""
    if not factor_returns or not benchmark_returns:
        return {"alpha": 0, "sharpe": 0, "max_drawdown": 0}
    f = np.array(factor_returns)
    b = np.array(benchmark_returns)
    excess = f - b
    alpha = float(np.mean(excess) * 252)
    sharpe = float(np.mean(f) / max(np.std(f), 0.001) * np.sqrt(252))
    cumulative = np.cumprod(1 + f)
    peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - peak) / peak
    max_dd = float(np.min(drawdown))
    return {"alpha": round(alpha, 4), "sharpe": round(sharpe, 4), "max_drawdown": round(max_dd, 4)}
