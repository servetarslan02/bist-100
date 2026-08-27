"""
ALPHA BIST — Feature Calculator Bridge (Polars-Native)
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

        # Polars DataFrame'e çevir
        if isinstance(df, pl.DataFrame):
            pdf = df
        elif hasattr(df, "to_pandas"):
            pdf = pl.from_pandas(df.to_pandas())
        elif hasattr(df, "to_dict"):
            pdf = pl.DataFrame(df)
        else:
            return {}

        if len(pdf) < 5:
            return {}
        return self.compute_all(ticker=ticker, df=pdf)


feature_calculator = FeatureCalculator()
