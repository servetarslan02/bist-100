"""ALPHA BIST — Statistical Significance Test."""
from typing import Dict, Any
import numpy as np

def test_significance(car: float, abnormal_returns: np.ndarray) -> Dict[str, Any]:
    """CAR'ın istatistiksel anlamlılığı."""
    n = len(abnormal_returns)
    if n < 2:
        return {"t_statistic": 0, "p_value": 1, "significant": False}
    std_err = np.std(abnormal_returns) / np.sqrt(n)
    t_stat = car / std_err if std_err > 0 else 0
    # Yaklaşık p-value (normal dağılım)
    p_value = 2 * (1 - min(abs(t_stat) / 3, 0.999))
    return {"t_statistic": round(t_stat, 4), "p_value": round(p_value, 4), "significant": abs(t_stat) > 1.96}
