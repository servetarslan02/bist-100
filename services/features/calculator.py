"""
ALPHA BIST — Feature Calculator Bridge
services.ml.feature_engine.FeatureEngine canonical motoruna bağlanır.
"""

from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
from services.ml.feature_engine import FeatureEngine, compute_universe_features

class FeatureCalculator(FeatureEngine):
    """Canonical FeatureEngine bridge for feature calculator."""
    
    def compute_all_features(self, df: pd.DataFrame, ticker: str = "") -> Dict[str, float]:
        """Compute all features for given dataframe and ticker."""
        if df is None or len(df) < 20:
            return {}
        return self.compute_all(ticker=ticker, df=df)

feature_calculator = FeatureCalculator()
