"""ALPHA BIST — Feature Calculator Bridge (Polars-Native).

services.ml.feature_engine.FeatureEngine canonical motoruna bağlanır.
Girdi olarak Polars, Pandars veya dict kabul eder, Polars-native hesaplama yapar.
"""

from typing import Any

import polars as pl
import structlog

from services.ml.feature_engine import FeatureEngine

logger = structlog.get_logger(__name__)

# Feature hesaplaması için minimum satır sayısı
DEFAULT_MIN_ROWS_FOR_FEATURE: int = 5


class FeatureCalculator(FeatureEngine):
    """Canonical FeatureEngine bridge for feature calculator.

    services.ml.feature_engine.FeatureEngine motoruna bağlanır.
    Polars-native hesaplama yapar. Farklı DataFrame formatlarını
    (Polars, Pandas, dict) otomatik olarak Polars'a dönüştürür.
    """

    def compute_all_features(
        self,
        df: Any,
        ticker: str = "",
        mask: Any = None,
    ) -> dict[str, Any]:
        """Verilen DataFrame ve ticker için tüm feature'ları hesapla.

        Girdi DataFrame'i Polars değilse otomatik dönüştürülür.
        Boolean maske uygulanabilir (satır filtreleme).
        Yetersiz veri durumunda boş dict döner.

        Args:
            df: Girdi DataFrame'i (Polars, Pandas veya dict).
            ticker: Hisse senedi kodu.
            mask: Boolean maske dizisi (opsiyonel). True olan
                satırlar hesaplamaya dahil edilir.

        Returns:
            Feature adı → değer dict'i. Yetersiz veri veya
            hata durumunda boş dict.
        """
        if df is None:
            logger.debug("compute_all_features_null_input", ticker=ticker)
            return {}

        # Polars DataFrame'e çevir
        pdf = self._to_polars(df)
        if pdf is None or len(pdf) == 0:
            logger.debug("compute_all_features_empty_df", ticker=ticker)
            return {}

        # Maske uygula
        if mask is not None:
            pdf = self._apply_mask(pdf, mask)

        # Minimum satır kontrolü
        if len(pdf) < DEFAULT_MIN_ROWS_FOR_FEATURE:
            logger.debug(
                "compute_all_features_insufficient_rows",
                ticker=ticker,
                rows=len(pdf),
                required=DEFAULT_MIN_ROWS_FOR_FEATURE,
            )
            return {}

        # Feature hesapla
        try:
            return self.compute_all(ticker=ticker, df=pdf)
        except Exception as e:
            logger.error(
                "compute_all_features_error",
                ticker=ticker,
                error=str(e),
                rows=len(pdf),
            )
            return {}

    def _to_polars(self, df: Any) -> pl.DataFrame | None:
        """DataFrame'i Polars formatına dönüştür.

        Polars-native yaklaşım: girdi doğrudan Polars DataFrame olmalı.
        Pandas dönüşümü legacy uyumluluk için desteklenir ancak
        yeni kodlarda Polars kullanılması zorunludur.

        Args:
            df: Polars DataFrame, Pandas DataFrame veya dict.

        Returns:
            Polars DataFrame veya None (dönüşüm başarısızsa).
        """
        if isinstance(df, pl.DataFrame):
            return df
        if isinstance(df, dict):
            try:
                return pl.DataFrame(df)
            except Exception as e:
                logger.warning("dict_to_polars_donuşüm_hatası", error=str(e))
                return None
        # Legacy Pandas uyumluluk — yeni kodlarda kullanılmamalı
        if hasattr(df, "to_pandas"):
            logger.warning(
                "legacy_pandas_donüşümü",
                tip=type(df).__name__,
                mesaj="Polars DataFrame kullanın, Pandas dönüşümü deprecated.",
            )
            try:
                return pl.from_pandas(df.to_pandas())
            except Exception as e:
                logger.warning("pandas_to_polars_donuşüm_hatası", error=str(e))
                return None
        logger.warning("desteklenmeyen_df_formatı", tip=type(df).__name__)
        return None

    def _apply_mask(self, pdf: pl.DataFrame, mask: Any) -> pl.DataFrame:
        """Boolean maskeyi DataFrame'e uygula.

        Args:
            pdf: Polars DataFrame.
            mask: Boolean maske dizisi.

        Returns:
            Filtrelenmiş DataFrame. Maske uygulanamazsa orijinali döner.
        """
        if len(mask) != len(pdf):
            logger.warning(
                "mask_uzunluk_uyumsuz",
                mask_uzunluk=len(mask),
                df_uzunluk=len(pdf),
            )
            return pdf
        try:
            import numpy as np

            mask_arr = np.asarray(mask, dtype=bool)
            return pdf.filter(pl.Series(mask_arr))
        except Exception as e:
            logger.warning(
                "mask_uygulama_hatası",
                error=str(e),
                mask_uzunluk=len(mask),
            )
            return pdf



    def __repr__(self) -> str:
        """FeatureCalculator kısa temsili.
    
        Returns:
            Sınıf bilgisi.
        """
        return f"FeatureCalculator()"
def __repr__(self) -> str:
        """FeatureCalculator kısa temsili.

        Returns:
            Sınıf adı.
        """
        return "FeatureCalculator()"
feature_calculator = FeatureCalculator()
