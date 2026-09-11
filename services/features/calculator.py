"""
ALPHA BIST — Feature Calculator Bridge (Polars-Native)
services.ml.feature_engine.FeatureEngine canonical motoruna bağlanır.
"""

from typing import Any

import polars as pl

import structlog

from services.ml.feature_engine import FeatureEngine

logger = structlog.get_logger()


class FeatureCalculator(FeatureEngine):
    """Canonical FeatureEngine bridge for feature calculator.

    services.ml.feature_engine.FeatureEngine motoruna bağlanır.
    Polars-native hesaplama yapar.
    """

    def compute_all_features(self, df: Any, ticker: str = "", mask: Any = None) -> dict[str, float]:
        """Verilen DataFrame ve ticker için tüm feature'ları hesapla.

        Args:
            df: Girdi DataFrame'i (Polars, Pandars veya dict).
            ticker: Hisse senedi kodu.
            mask: Boolean maske dizisi (opsiyonel).

        Returns:
            Feature adı → değer dict'i.
        """
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

        if mask is not None and len(mask) == len(pdf):
            try:
                import numpy as np

                mask_arr = np.asarray(mask, dtype=bool)
                pdf = pdf.filter(pl.Series(mask_arr))
            except Exception as e:
                logger.warning("mask_uygulama_hatası", error=str(e), mask_uzunluk=len(mask))

        if len(pdf) < 5:
            return {}
        return self.compute_all(ticker=ticker, df=pdf)


feature_calculator = FeatureCalculator()
