"""
ALPHA BIST — Macro Feature Engine v1.0

Makro verilerden feature üretir:
- USD/TRY z-score, momentum, percentile, regime
- Faiz (TCMB policy rate, differential)
- Enflasyon (CPI, PPI, trend)
- VIX normalize
- Emtia (petrol, altın)
- Global risk appetite

FAZ 2.3: Macro Features
"""

import math
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class MacroFeatureEngine:
    """Makro verilerden feature üretir."""

    def __init__(self):
        self._history: Dict[str, List[float]] = {}

    def update_history(self, indicator: str, value: float):
        """Makro gösterge geçmişini güncelle."""
        if indicator not in self._history:
            self._history[indicator] = []
        self._history[indicator].append(value)
        # Son 250 gözlem tut (yaklaşık 1 yıl)
        self._history[indicator] = self._history[indicator][-250:]

    def compute_currency_features(self, usdtry: float, eurtry: float = 0) -> Dict[str, float]:
        """Döviz kuru feature'ları."""
        features = {}

        if usdtry and usdtry > 0:
            features["usdtry_level"] = round(usdtry, 4)

            # History'ye ekle
            self.update_history("usdtry", usdtry)

            # Z-score (son 60 gözlem)
            history = self._history.get("usdtry", [])
            if len(history) >= 20:
                mean = np.mean(history[-60:])
                std = np.std(history[-60:])
                if std > 0:
                    features["usdtry_zscore"] = round((usdtry - mean) / std, 4)

                # Momentum (son 20 gün)
                if len(history) >= 20:
                    features["usdtry_momentum_20d"] = round((usdtry / history[-20] - 1) * 100, 2)

                # Percentile
                if len(history) >= 10:
                    percentile = sum(1 for v in history if v <= usdtry) / len(history)
                    features["usdtry_percentile"] = round(percentile, 4)

                # Volatility (son 20 gün)
                if len(history) >= 20:
                    returns = np.diff(np.log(history[-20:]))
                    features["usdtry_volatility_20d"] = round(float(np.std(returns) * np.sqrt(252) * 100), 2)

                # Regime
                momentum = features.get("usdtry_momentum_20d", 0)
                if momentum > 5:
                    features["usdtry_regime"] = 3.0  # STRENGTHENING (TRY zayıflıyor)
                elif momentum > 2:
                    features["usdtry_regime"] = 2.0  # MILD_UP
                elif momentum < -5:
                    features["usdtry_regime"] = 0.0  # WEAKENING (TRY güçleniyor)
                elif momentum < -2:
                    features["usdtry_regime"] = 1.0  # MILD_DOWN
                else:
                    features["usdtry_regime"] = 1.5  # STABLE

        if eurtry and eurtry > 0:
            features["eurtry_level"] = round(eurtry, 4)
            if usdtry and usdtry > 0:
                features["eurtry_usdtry_ratio"] = round(eurtry / usdtry, 4)

        return features

    def compute_rate_features(self, policy_rate: float, us_rate: float = 5.25) -> Dict[str, float]:
        """Faiz feature'ları."""
        features = {}

        if policy_rate:
            features["tcmb_policy_rate"] = round(float(policy_rate), 2)

            # Rate differential
            if us_rate:
                features["rate_differential"] = round(float(policy_rate) - float(us_rate), 2)

            # History
            self.update_history("policy_rate", float(policy_rate))
            history = self._history.get("policy_rate", [])
            if len(history) >= 4:
                # Trend (son 4 gözlem)
                if history[-1] > history[-4]:
                    features["rate_trend"] = 1.0  # Rising
                elif history[-1] < history[-4]:
                    features["rate_trend"] = -1.0  # Falling
                else:
                    features["rate_trend"] = 0.0  # Stable

        return features

    def compute_inflation_features(self, cpi: float, ppi: float = 0) -> Dict[str, float]:
        """Enflasyon feature'ları."""
        features = {}

        if cpi:
            features["cpi_level"] = round(float(cpi), 2)

            self.update_history("cpi", float(cpi))
            history = self._history.get("cpi", [])
            if len(history) >= 4:
                # Trend
                if history[-1] > history[-4]:
                    features["inflation_trend"] = 1.0  # Rising
                elif history[-1] < history[-4]:
                    features["inflation_trend"] = -1.0  # Falling
                else:
                    features["inflation_trend"] = 0.0

                # Surprise (beklenti dışı)
                if len(history) >= 2:
                    expected = np.mean(history[-4:])
                    features["inflation_surprise"] = round(float(cpi - expected), 2)

        if ppi:
            features["ppi_level"] = round(float(ppi), 2)
            if cpi:
                features["cpi_ppi_spread"] = round(float(cpi) - float(ppi), 2)

        return features

    def compute_vix_features(self, vix: float) -> Dict[str, float]:
        """VIX feature'ları (raw VIX, 0-1 state ile karıştırılmamalı)."""
        features = {}

        if vix and vix > 0:
            features["vix_level"] = round(float(vix), 2)

            self.update_history("vix", float(vix))
            history = self._history.get("vix", [])
            if len(history) >= 20:
                mean = np.mean(history[-60:])
                std = np.std(history[-60:])
                if std > 0:
                    features["vix_zscore"] = round((float(vix) - mean) / std, 4)

                # Percentile
                percentile = sum(1 for v in history if v <= vix) / len(history)
                features["vix_percentile"] = round(percentile, 4)

                # Regime
                if vix > 30:
                    features["vix_regime"] = 3.0  # FEAR
                elif vix > 20:
                    features["vix_regime"] = 2.0  # ELEVATED
                elif vix > 15:
                    features["vix_regime"] = 1.0  # NORMAL
                else:
                    features["vix_regime"] = 0.0  # COMPLACENT

                # Momentum
                if len(history) >= 5:
                    features["vix_momentum_5d"] = round(float(vix - history[-5]), 2)

        return features

    def compute_commodity_features(self, gold: float, oil: float) -> Dict[str, float]:
        """Emtia feature'ları."""
        features = {}

        if gold and gold > 0:
            features["gold_price"] = round(float(gold), 2)
            self.update_history("gold", float(gold))
            history = self._history.get("gold", [])
            if len(history) >= 20:
                features["gold_momentum_20d"] = round((float(gold) / history[-20] - 1) * 100, 2)

        if oil and oil > 0:
            features["oil_price"] = round(float(oil), 2)
            self.update_history("oil", float(oil))
            history = self._history.get("oil", [])
            if len(history) >= 20:
                features["oil_momentum_20d"] = round((float(oil) / history[-20] - 1) * 100, 2)
                if len(history) >= 5:
                    features["oil_change_5d"] = round((float(oil) / history[-5] - 1) * 100, 2)

        return features

    def compute_global_features(self, sp500: float = 0, nasdaq: float = 0) -> Dict[str, float]:
        """Global piyasa feature'ları."""
        features = {}

        if sp500 and sp500 > 0:
            features["sp500_level"] = round(float(sp500), 2)
            self.update_history("sp500", float(sp500))
            history = self._history.get("sp500", [])
            if len(history) >= 20:
                features["sp500_momentum_20d"] = round((float(sp500) / history[-20] - 1) * 100, 2)

        if nasdaq and nasdaq > 0:
            features["nasdaq_level"] = round(float(nasdaq), 2)
            self.update_history("nasdaq", float(nasdaq))
            history = self._history.get("nasdaq", [])
            if len(history) >= 20:
                features["nasdaq_momentum_20d"] = round((float(nasdaq) / history[-20] - 1) * 100, 2)

        return features

    def compute_all_macro_features(self, macro_data: Dict[str, Any]) -> Dict[str, float]:
        """Tüm makro feature'ları hesapla.

        Args:
            macro_data: yfinance.fetch_macro() çıktısı veya benzer format
        """
        features = {}

        usdtry = macro_data.get("USD/TRY", {}).get("price", 0)
        eurtry = macro_data.get("EUR/TRY", {}).get("price", 0)
        gold = macro_data.get("Gold", {}).get("price", 0)
        oil = macro_data.get("Oil", {}).get("price", 0)
        vix = macro_data.get("VIX", {}).get("price", 0)
        sp500 = macro_data.get("S&P500", {}).get("price", 0)
        nasdaq = macro_data.get("Nasdaq", {}).get("price", 0)

        features.update(self.compute_currency_features(usdtry, eurtry))
        features.update(self.compute_vix_features(vix))
        features.update(self.compute_commodity_features(gold, oil))
        features.update(self.compute_global_features(sp500, nasdaq))

        # NaN/Inf temizle
        cleaned = {}
        for k, v in features.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                cleaned[k] = 0.0
            else:
                cleaned[k] = v

        return cleaned


# Singleton
macro_feature_engine = MacroFeatureEngine()
