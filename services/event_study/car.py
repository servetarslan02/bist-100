"""ALPHA BIST — Cumulative Abnormal Return."""
import numpy as np

def calculate_car(abnormal_returns: np.ndarray) -> float:
    """CAR = Σ AR."""
    return float(np.sum(abnormal_returns))
