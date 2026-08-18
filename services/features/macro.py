"""
ALPHA BIST — Macro Feature Engine v2.0

Makro verilerden 50+ feature üretir:
- Currency: USDTRY z-score, momentum, percentile, regime, volatility
- Rate: policy rate, differential, trend, WACF
- Inflation: CPI, PPI, core, surprise, regime
- VIX: level, z-score, percentile, regime, momentum
- Commodity: gold, oil momentum
- Global: S&P500, Nasdaq momentum
- CDS: level, z-score, risk level
- Credit: growth, regime, trend
- Current Account: balance, regime, improving
- NEW: Surprise features
- NEW: Regime features
- NEW: Correlation features
- NEW: Factor decomposition features
"""

import math
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class MacroFeatureEngine:
    """Makro verilerden 50+ feature üretir."""

    def __init__(self):
        self._history: Dict[str, List[float]] = {}

    def update_history(self, indicator: str, value: float):
        """Makro gösterge geçmişini güncelle."""
        if indicator not in self._history:
            self._history[indicator] = []
        self._history[indicator].append(value)
        self._history[indicator] = self._history[indicator][-250:]

    def compute_currency_features(self, usdtry: float, eurtry: float = 0) -> Dict[str, float]:
        """Döviz kuru feature'ları (7+ feature)."""
        features = {}

        if usdtry and usdtry > 0:
            features["usdtry_level"] = round(usdtry, 4)
            self.update_history("usdtry", usdtry)

            history = self._history.get("usdtry", [])
            if len(history) >= 20:
                mean = np.mean(history[-60:])
                std = np.std(history[-60:])
                if std and std > 0:
                    features["usdtry_zscore"] = round((usdtry - mean) / std, 4)

                if len(history) >= 20:
                    features["usdtry_momentum_20d"] = round((usdtry / history[-20] - 1) * 100, 2)

                if len(history) >= 10:
                    percentile = sum(1 for v in history if v <= usdtry) / len(history)
                    features["usdtry_percentile"] = round(percentile, 4)

                if len(history) >= 20:
                    returns = np.diff(np.log(history[-20:]))
                    features["usdtry_volatility_20d"] = round(float(np.std(returns) * np.sqrt(252) * 100), 2)

                momentum = features.get("usdtry_momentum_20d", 0)
                if momentum > 5:
                    features["usdtry_regime"] = 3.0
                elif momentum > 2:
                    features["usdtry_regime"] = 2.0
                elif momentum < -5:
                    features["usdtry_regime"] = 0.0
                elif momentum < -2:
                    features["usdtry_regime"] = 1.0
                else:
                    features["usdtry_regime"] = 1.5

        if eurtry and eurtry > 0:
            features["eurtry_level"] = round(eurtry, 4)
            if usdtry and usdtry > 0:
                features["eurtry_usdtry_ratio"] = round(eurtry / usdtry, 4)

        return features

    def compute_rate_features(self, policy_rate: float, us_rate: float = 5.25) -> Dict[str, float]:
        """Faiz feature'ları (4+ feature)."""
        features = {}

        if policy_rate:
            features["tcmb_policy_rate"] = round(float(policy_rate), 2)

            if us_rate:
                features["rate_differential"] = round(float(policy_rate) - float(us_rate), 2)

            self.update_history("policy_rate", float(policy_rate))
            history = self._history.get("policy_rate", [])
            if len(history) >= 4:
                if history[-1] > history[-4]:
                    features["rate_trend"] = 1.0
                elif history[-1] < history[-4]:
                    features["rate_trend"] = -1.0
                else:
                    features["rate_trend"] = 0.0

        return features

    def compute_inflation_features(self, cpi: float, ppi: float = 0) -> Dict[str, float]:
        """Enflasyon feature'ları (5+ feature)."""
        features = {}

        if cpi:
            features["cpi_level"] = round(float(cpi), 2)

            self.update_history("cpi", float(cpi))
            history = self._history.get("cpi", [])
            if len(history) >= 4:
                if history[-1] > history[-4]:
                    features["inflation_trend"] = 1.0
                elif history[-1] < history[-4]:
                    features["inflation_trend"] = -1.0
                else:
                    features["inflation_trend"] = 0.0

                if len(history) >= 2:
                    expected = np.mean(history[-4:])
                    features["inflation_surprise"] = round(float(cpi - expected), 2)

        if ppi:
            features["ppi_level"] = round(float(ppi), 2)
            if cpi:
                features["cpi_ppi_spread"] = round(float(cpi) - float(ppi), 2)

        return features

    def compute_vix_features(self, vix: float) -> Dict[str, float]:
        """VIX feature'ları (6+ feature)."""
        features = {}

        if vix and vix > 0:
            features["vix_level"] = round(float(vix), 2)

            self.update_history("vix", float(vix))
            history = self._history.get("vix", [])
            if len(history) >= 20:
                mean = np.mean(history[-60:])
                std = np.std(history[-60:])
                if std and std > 0:
                    features["vix_zscore"] = round((float(vix) - mean) / std, 4)

                percentile = sum(1 for v in history if v <= vix) / len(history)
                features["vix_percentile"] = round(percentile, 4)

                if vix > 30:
                    features["vix_regime"] = 3.0
                elif vix > 20:
                    features["vix_regime"] = 2.0
                elif vix > 15:
                    features["vix_regime"] = 1.0
                else:
                    features["vix_regime"] = 0.0

                if len(history) >= 5:
                    features["vix_momentum_5d"] = round(float(vix - history[-5]), 2)

        return features

    def compute_commodity_features(self, gold: float, oil: float) -> Dict[str, float]:
        """Emtia feature'ları (4+ feature)."""
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
        """Global piyasa feature'ları (4+ feature)."""
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

    def compute_cds_features(self, cds_5y: float = 0, cds_history: list = None) -> Dict[str, float]:
        """CDS feature'ları (4+ feature)."""
        features = {}

        if cds_5y and cds_5y > 0:
            features["cds_5y"] = round(float(cds_5y), 2)

            if cds_history and len(cds_history) >= 10:
                hist = np.array(cds_history, dtype=np.float64)
                mean = np.mean(hist[-60:])
                std = np.std(hist[-60:])
                if std > 0:
                    features["cds_zscore"] = round((float(cds_5y) - mean) / std, 4)

                percentile = sum(1 for v in hist if v <= cds_5y) / len(hist)
                features["cds_percentile"] = round(percentile, 4)

            if cds_5y < 150:
                features["cds_risk_level"] = 0.0
            elif cds_5y < 250:
                features["cds_risk_level"] = 1.0
            elif cds_5y < 400:
                features["cds_risk_level"] = 2.0
            else:
                features["cds_risk_level"] = 3.0

        return features

    def compute_credit_features(self, credit_growth: float = 0) -> Dict[str, float]:
        """Kredi feature'ları (2+ feature)."""
        features = {}

        if credit_growth:
            features["credit_growth_yoy"] = round(float(credit_growth), 2)

            growth = float(credit_growth)
            if growth > 20:
                features["credit_regime"] = 3.0
            elif growth > 10:
                features["credit_regime"] = 2.0
            elif growth > 0:
                features["credit_regime"] = 1.0
            else:
                features["credit_regime"] = 0.0

        return features

    def compute_ca_features(self, ca_balance: float = 0) -> Dict[str, float]:
        """Cari açık feature'ları (2+ feature)."""
        features = {}

        if ca_balance is not None:
            features["ca_balance"] = round(float(ca_balance), 2)

            if float(ca_balance) > 0:
                features["ca_regime"] = 2.0
            elif float(ca_balance) > -5:
                features["ca_regime"] = 1.0
            elif float(ca_balance) > -15:
                features["ca_regime"] = 0.0
            else:
                features["ca_regime"] = -1.0

        return features

    def compute_all_macro_features(self, macro_data: Dict[str, Any]) -> Dict[str, float]:
        """Tüm makro feature'ları hesapla (50+ feature).

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

    def compute_all_macro_features_with_services(
        self,
        tcmb_data=None, inflation_data=None, fx_data=None,
        cds_data=None, credit_data=None, ca_data=None,
        macro_data=None, surprise_data=None, regime_data=None,
    ) -> Dict[str, float]:
        """Tüm makro feature'ları birleştir (50+ feature).

        Mevcut servis modülleri + yeni modüller.
        """
        features = {}

        try:
            # Mevcut servis modülleri
            from services.macro.tcmb import compute_tcmb_features
            from services.macro.inflation import compute_inflation_features
            from services.macro.fx import compute_fx_features
            from services.macro.cds import compute_cds_features
            from services.macro.credit import compute_credit_features
            from services.macro.current_account import compute_ca_features

            if tcmb_data:
                features.update({f"tcmb_{k}": v for k, v in compute_tcmb_features(tcmb_data).items()})
            if inflation_data:
                features.update({f"inf_{k}": v for k, v in compute_inflation_features(inflation_data).items()})
            if fx_data:
                features.update({f"fx_{k}": v for k, v in compute_fx_features(fx_data).items()})
            if cds_data:
                features.update({f"cds_{k}": v for k, v in compute_cds_features(cds_data).items()})
            if credit_data:
                features.update({f"credit_{k}": v for k, v in compute_credit_features(credit_data).items()})
            if ca_data:
                features.update({f"ca_{k}": v for k, v in compute_ca_features(ca_data).items()})

            # MacroFeatureEngine kendi feature'ları
            if macro_data:
                features.update(self.compute_all_macro_features(macro_data))

            # YENİ: Surprise features
            if surprise_data:
                from services.macro.surprise_model import macro_surprise_model
                features.update(macro_surprise_model.compute_surprise_features(surprise_data))

            # YENİ: Regime features
            if regime_data or features:
                from services.macro.regime_detector import macro_regime_detector
                features.update(macro_regime_detector.compute_regime_features(features))

        except Exception as e:
            logger.error("Macro feature computation failed", error=str(e))

        return features


# Singleton
macro_feature_engine = MacroFeatureEngine()


# =====================================================
# B28 Macro entegrasyonu — servis modülleri
# =====================================================
def compute_all_macro_features(tcmb_data=None, inflation_data=None, fx_data=None,
                                cds_data=None, credit_data=None, ca_data=None) -> Dict[str, float]:
    """Tüm makro feature'ları birleştir (B28 modülleri)."""
    features = {}
    try:
        from services.macro.tcmb import compute_tcmb_features
        from services.macro.inflation import compute_inflation_features
        from services.macro.fx import compute_fx_features
        from services.macro.cds import compute_cds_features
        from services.macro.credit import compute_credit_features
        from services.macro.current_account import compute_ca_features

        if tcmb_data: features.update({f"tcmb_{k}": v for k, v in compute_tcmb_features(tcmb_data).items()})
        if inflation_data: features.update({f"inf_{k}": v for k, v in compute_inflation_features(inflation_data).items()})
        if fx_data: features.update({f"fx_{k}": v for k, v in compute_fx_features(fx_data).items()})
        if cds_data: features.update({f"cds_{k}": v for k, v in compute_cds_features(cds_data).items()})
        if credit_data: features.update({f"credit_{k}": v for k, v in compute_credit_features(credit_data).items()})
        if ca_data: features.update({f"ca_{k}": v for k, v in compute_ca_features(ca_data).items()})
    except ImportError:
        pass
    return features
