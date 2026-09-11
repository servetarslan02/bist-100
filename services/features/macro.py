"""ALPHA BIST — Macro Feature Engine

Makro-ekonomik feature hesaplama motoru. BIST piyasası için makro
göstergelerden (USD/TRY, ABD 10Y, VIX, Brent, Altın) feature üretir.

Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.

Kullanım:
    from services.features.macro import macro_feature_engine

    features = macro_feature_engine.compute_features({
        "usdtry": 34.5,
        "usdtry_change_pct": 0.5,
        "us10y": 4.2,
        "vix": 18.5,
        "brent_crude": 82.0,
        "gold": 2650.0,
    })
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

DEFAULT_VIX_HIGH_THRESHOLD: float = 25.0
DEFAULT_USDTRY_CHANGE_THRESHOLD: float = 1.0
DEFAULT_BRENT_CHANGE_THRESHOLD: float = 3.0


# ---------------------------------------------------------------------------
# Ana sınıf
# ---------------------------------------------------------------------------


class MacroFeatureEngine:
    """Makro-ekonomik feature hesaplama motoru.

    BIST piyasası için makro göstergelerden (USD/TRY, ABD 10Y, VIX, Brent, Altın)
    feature üretir. Risk appetite composite skoru hesaplar.

    Thread-safe: Paylaşılan singleton erişimi threading.Lock ile korunur.

    Özellikler:
        - USD/TRY seviye ve değişim feature'ları
        - ABD 10Y tahvil getirisi feature'ları
        - VIX seviye ve rejim feature'ları
        - Brent petrol seviye ve değişim feature'ları
        - Altın seviye feature'ı
        - Risk appetite composite skoru
    """

    def __init__(self) -> None:
        """Makro feature motoru başlatıcısı.

        Boş bir makro önbellek oluşturur.

        Returns:
            None.

        Raises:
            Yok.
        """
        self._cache: dict[str, float] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        """MacroFeatureEngine kısa temsili.

        Returns:
            Önbellek durumu.
        """
        with self._lock:
            cache_size = len(self._cache)
        return f"MacroFeatureEngine(cached_features={cache_size})"

    # ------------------------------------------------------------------
    # Dış API
    # ------------------------------------------------------------------

    def compute_features(
        self,
        macro_data: dict[str, Any],
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Makro göstergelerden feature hesaplar.

        USD/TRY, ABD 10Y, VIX, Brent ve Altın verilerinden feature üretir.
        Eksik veriler NaN olarak işaretlenir (0.0 değil).

        Args:
            macro_data: Makro göstergeler sözlüğü.
                Beklenen anahtarlar: usdtry, usdtry_change_pct, us10y,
                us10y_change_pct, vix, brent_crude, brent_change_pct, gold.
            market_data: Opsiyonel piyasa verisi (cross-asset feature'lar için).

        Returns:
            Feature adı → değer sözlüğü.

        Raises:
            Yok — eksik veriler NaN olarak döner.
        """
        features: dict[str, float] = {}

        # USD/TRY features
        usdtry = macro_data.get("usdtry")
        features["macro_usdtry_level"] = self._safe_float(usdtry)
        features["macro_usdtry_change"] = self._safe_float(macro_data.get("usdtry_change_pct"))

        # US 10Y yield
        us10y = macro_data.get("us10y")
        features["macro_us10y_level"] = self._safe_float(us10y)
        features["macro_us10y_change"] = self._safe_float(macro_data.get("us10y_change_pct"))

        # VIX
        vix = macro_data.get("vix")
        vix_float = self._safe_float(vix)
        features["macro_vix_level"] = vix_float
        if np.isnan(vix_float):
            features["macro_vix_regime"] = float("nan")
        else:
            features["macro_vix_regime"] = 1.0 if vix_float > DEFAULT_VIX_HIGH_THRESHOLD else 0.0

        # Brent crude
        brent = macro_data.get("brent_crude")
        features["macro_brent_level"] = self._safe_float(brent)
        features["macro_brent_change"] = self._safe_float(macro_data.get("brent_change_pct"))

        # Gold
        gold = macro_data.get("gold")
        features["macro_gold_level"] = self._safe_float(gold)

        # Risk appetite composite
        risk_factors: list[float] = []
        vix_regime = features.get("macro_vix_regime")
        if vix_regime is not None and not np.isnan(vix_regime):
            risk_factors.append(vix_regime)
        usdtry_change = features.get("macro_usdtry_change")
        if usdtry_change is not None and not np.isnan(usdtry_change):
            risk_factors.append(1.0 if usdtry_change > DEFAULT_USDTRY_CHANGE_THRESHOLD else 0.0)
        brent_change = features.get("macro_brent_change")
        if brent_change is not None and not np.isnan(brent_change):
            risk_factors.append(1.0 if brent_change > DEFAULT_BRENT_CHANGE_THRESHOLD else 0.0)
        features["macro_risk_score"] = float(np.mean(risk_factors)) if risk_factors else float("nan")

        with self._lock:
            self._cache = features

        logger.debug(
            "macro_features_computed",
            feature_count=len(features),
            risk_score=features["macro_risk_score"],
        )

        return features

    def get_cached(self) -> dict[str, float]:
        """Önbellekteki makro feature'ları döndürür.

        Returns:
            Feature dict'inin kopyası. Önbellek boşsa boş dict döner.
        """
        with self._lock:
            return self._cache.copy()

    def clear_cache(self) -> int:
        """Önbelleği temizler.

        Returns:
            Temizlenen feature sayısı.
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
        logger.info("macro_cache_cleared", count=count)
        return count

    def compute_all_macro_features(
        self,
        macro_data: dict[str, Any],
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Tüm makro feature'ları hesaplar (backward-compatible wrapper).

        Orchestrator bu metodu çağırır. compute_features ile aynı işi yapar.

        Args:
            macro_data: Makro göstergeler sözlüğü.
            market_data: Opsiyonel piyasa verisi.

        Returns:
            Feature adı → değer sözlüğü.
        """
        return self._compute_features_internal(macro_data, market_data)

    # ------------------------------------------------------------------
    # İç yardımcı metodlar
    # ------------------------------------------------------------------

    def _compute_features_internal(
        self,
        macro_data: dict[str, Any],
        market_data: dict[str, Any] | None,
    ) -> dict[str, float]:
        """Feature hesaplama implementasyonu.

        Args:
            macro_data: Makro göstergeler sözlüğü.
            market_data: Opsiyonel piyasa verisi.

        Returns:
            Feature adı → değer sözlüğü.
        """
        return self.compute_features(macro_data, market_data)

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Değeri güvenli float'a dönüştürür.

        None → NaN, dönüşüm hatası → NaN.

        Args:
            value: Dönüştürülecek değer.

        Returns:
            Float değer veya NaN.
        """
        if value is None:
            return float("nan")
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("nan")


__all__: list[str] = ["MacroFeatureEngine", "macro_feature_engine"]

# Singleton
macro_feature_engine = MacroFeatureEngine()
