"""
ALPHA BIST — Feature Calculator Bridge
services.ml.feature_engine.FeatureEngine canonical motoruna bağlanır.
"""

from typing import Dict, Any
import polars as pl
from services.ml.feature_engine import FeatureEngine

class FeatureCalculator(FeatureEngine):
    """Canonical FeatureEngine bridge for feature calculator."""
    
    def compute_all_features(self, df: Any, ticker: str = "") -> Dict[str, float]:
        """Compute all features for given dataframe and ticker."""
        if df is None:
            return {}
        if hasattr(df, "to_pandas"):
            pdf = df.to_pandas()
        elif isinstance(df, pl.DataFrame):
            pdf = df
        else:
            return {}

        if len(pdf) < 5:
            return {}
        return self.compute_all(ticker=ticker, df=pdf)

feature_calculator = FeatureCalculator()
