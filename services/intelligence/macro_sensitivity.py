"""
ALPHA BIST — Macro Sensitivity Engine v1.0

Her şirket için makro değişkenlereduyarlılık hesaplar:
- USD/TRY sensitivity (ithalat/ihracat bağımlılığı)
- Faiz sensitivity (borç yapısı)
- Emtia sensitivity (girdi maliyetleri)
- Global market sensitivity (korelasyon)

FAZ 3.3: Macro Sensitivity
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import structlog

logger = structlog.get_logger()


# Sektör bazlı makro hassasiyet varsayılanları
# Sektör bazlı makro hassasiyet.
# Pozitif = artış şirket için olumlu, Negatif = artış şirket için olumsuz
SECTOR_MACRO_SENSITIVITY = {
    "BANK": {
        "usdtry": -0.3,      # Döviz artışı → negatif (risk)
        "interest_rate": 0.9, # Faiz artışı → pozitif (faiz geliri)
        "oil": -0.1,         # Petrol artışı → hafif negatif
        "gold": 0.1,         # Altın artışı → hafif pozitif
        "global": 0.5,       # Global pozitif → pozitif
        "inflation": -0.7,   # Enflasyon artışı → negatif
    },
    "AVIATION": {
        "usdtry": -0.8,      # Döviz artışı → negatif (yakıt maliyeti, döviz borcu)
        "interest_rate": -0.5, # Faiz artışı → negatif (kredi maliyeti)
        "oil": -0.9,         # Petrol artışı → negatif (yakıt)
        "gold": 0.0,         # Yok
        "global": 0.6,       # Global pozitif → pozitif
        "inflation": -0.4,   # Enflasyon artışı → negatif
    },
    "ENERGY": {
        "usdtry": 0.5,       # Döviz artışı → pozitif (ihracat)
        "interest_rate": -0.4, # Faiz artışı → negatif
        "oil": 0.9,          # Petrol artışı → pozitif (üretici)
        "gold": 0.1,
        "global": 0.7,
        "inflation": 0.3,
    },
    "TECH": {
        "usdtry": 0.4,       # Döviz artışı → pozitif (ihracat geliri)
        "interest_rate": -0.6, # Faiz artışı → negatif (büyüme şirketleri)
        "oil": -0.1,
        "gold": 0.0,
        "global": 0.8,       # Global pozitif → pozitif
        "inflation": -0.3,
    },
    "RETAIL": {
        "usdtry": -0.6,      # Döviz artışı → negatif (ithalat maliyeti)
        "interest_rate": -0.5, # Faiz artışı → negatif (tüketici kredisi)
        "oil": -0.3,         # Petrol artışı → negatif (lojistik)
        "gold": 0.0,
        "global": 0.3,
        "inflation": -0.8,   # Enflasyon artışı → negatif (tüketici baskısı)
    },
    "METAL": {
        "usdtry": 0.4,       # Döviz artışı → pozitif (ihracat)
        "interest_rate": -0.3,
        "oil": -0.5,         # Petrol artışı → negatif (üretim maliyeti)
        "gold": 0.7,         # Altın artışı → pozitif
        "global": 0.8,       # Global pozitif → pozitif
        "inflation": 0.3,
    },
    "CONSTR": {
        "usdtry": -0.6,      # Döviz artışı → negatif (hammadde ithalatı)
        "interest_rate": -0.8, # Faiz artışı → negatif (kredi maliyeti)
        "oil": -0.4,
        "gold": 0.1,
        "global": 0.3,
        "inflation": -0.7,   # Enflasyon artışı → negatif
    },
    "FOOD": {
        "usdtry": -0.5,
        "interest_rate": -0.4,
        "oil": -0.3,
        "gold": 0.0,
        "global": 0.3,
        "inflation": -0.6,
    },
    "HOLDING": {
        "usdtry": -0.4,
        "interest_rate": -0.5,
        "oil": -0.2,
        "gold": 0.1,
        "global": 0.5,
        "inflation": -0.4,
    },
    "OTHER": {
        "usdtry": -0.4,
        "interest_rate": -0.4,
        "oil": -0.2,
        "gold": 0.1,
        "global": 0.4,
        "inflation": -0.4,
    },
}


class MacroSensitivityEngine:
    """Şirket bazlı makro hassasiyet hesaplama — dinamik güncelleme destekli."""

    def __init__(self):
        self._company_sensitivity: Dict[str, Dict[str, float]] = {}
        self._dynamic_sensitivity: Dict[str, Dict[str, float]] = {}  # sector → dynamic values
        self._sector_returns: Dict[str, List[float]] = {}  # sector → returns history
        self._macro_values: Dict[str, List[float]] = {}  # macro_var → values history
        self._window = 60  # Rolling window

    def get_sector_sensitivity(self, sector: str) -> Dict[str, float]:
        """Sektör bazlı makro hassasiyet."""
        return SECTOR_MACRO_SENSITIVITY.get(sector, SECTOR_MACRO_SENSITIVITY["OTHER"])

    def set_company_sensitivity(self, ticker: str, sensitivity: Dict[str, float]):
        """Şirket bazlı hassasiyet kaydet (override)."""
        self._company_sensitivity[ticker] = sensitivity

    def get_company_sensitivity(self, ticker: str, sector: str) -> Dict[str, float]:
        """Şirket hassasiyetini döndür.

        Önce şirket-specific, yoksa sektör bazlı.
        """
        if ticker in self._company_sensitivity:
            return self._company_sensitivity[ticker]
        return self.get_sector_sensitivity(sector)

    def compute_macro_impact(
        self,
        ticker: str,
        sector: str,
        macro_shocks: Dict[str, float],
    ) -> Dict[str, float]:
        """Makro şokların şirket üzerindeki etkisini hesapla.

        Args:
            ticker: Hisse kodu
            sector: Sektör kodu
            macro_shocks: {
                "usdtry_change": 0.10,      # %10 artış
                "interest_rate_change": 0.05, # 500bp
                "oil_change": 0.20,          # %20 artış
                "gold_change": 0.10,         # %10 artış
                "global_change": -0.10,      # %10 düşüş
                "inflation_change": 0.05,    # %5 artış
            }

        Returns:
            Etki skorları: {"usdtry_impact": -0.08, ...}
        """
        sensitivity = self.get_company_sensitivity(ticker, sector)
        impacts = {}

        mapping = {
            "usdtry_change": ("usdtry", "usdtry_impact"),
            "interest_rate_change": ("interest_rate", "interest_rate_impact"),
            "oil_change": ("oil", "oil_impact"),
            "gold_change": ("gold", "gold_impact"),
            "global_change": ("global", "global_impact"),
            "inflation_change": ("inflation", "inflation_impact"),
        }

        total_impact = 0.0
        for shock_key, (sens_key, impact_key) in mapping.items():
            shock = macro_shocks.get(shock_key, 0)
            sens = sensitivity.get(sens_key, 0)
            impact = shock * sens
            impacts[impact_key] = round(impact, 4)
            total_impact += impact

        impacts["total_macro_impact"] = round(total_impact, 4)

        # Etki yönü
        if total_impact > 0.02:
            impacts["macro_stance"] = 1.0  # POZİTİF
        elif total_impact < -0.02:
            impacts["macro_stance"] = -1.0  # NEGATİF
        else:
            impacts["macro_stance"] = 0.0  # NÖTR

        return impacts

    def compute_scenario_impact(
        self,
        ticker: str,
        sector: str,
        scenario: str,
    ) -> Dict[str, float]:
        """Önceden tanımlı senaryo etkisi hesapla."""
        scenarios = {
            "TCMB_RATE_HIKE_500BP": {"interest_rate_change": 0.05},
            "USDTRY_10_PCT": {"usdtry_change": 0.10},
            "OIL_SHOCK_20_PCT": {"oil_change": 0.20},
            "GLOBAL_RISK_OFF": {"global_change": -0.10, "usdtry_change": 0.05},
            "INFLATION_HIGH": {"inflation_change": 0.05},
        }

        macro_shocks = scenarios.get(scenario, {})
        if not macro_shocks:
            return {"error": f"Unknown scenario: {scenario}"}

        return self.compute_macro_impact(ticker, sector, macro_shocks)


    def update_dynamic(
        self,
        sector_returns: Dict[str, float],
        macro_values: Dict[str, float],
    ):
        """Dinamik hassasiyet güncelleme — günlük çağrılır.

        Args:
            sector_returns: {sector: daily_return}
            macro_values: {macro_var: value}
        """
        for sector, ret in sector_returns.items():
            if sector not in self._sector_returns:
                self._sector_returns[sector] = []
            self._sector_returns[sector].append(ret)
            self._sector_returns[sector] = self._sector_returns[sector][-self._window:]

        for var, val in macro_values.items():
            if var not in self._macro_values:
                self._macro_values[var] = []
            self._macro_values[var].append(val)
            self._macro_values[var] = self._macro_values[var][-self._window:]

        # Rolling korelasyon ile hassasiyet güncelle
        self._compute_dynamic_sensitivities()

    def _compute_dynamic_sensitivities(self):
        """Rolling korelasyon ile dinamik hassasiyet hesapla."""

        for sector, returns in self._sector_returns.items():
            if len(returns) < 20:
                continue

            dynamic = {}
            for macro_var, values in self._macro_values.items():
                if len(values) < 20:
                    continue

                # Son N gözlemi kullan
                n = min(len(returns), len(values), self._window)
                arr_ret = np.array(returns[-n:])
                arr_val = np.array(values[-n:])

                # NaN temizle
                mask = np.isfinite(arr_ret) & np.isfinite(arr_val)
                if mask.sum() < 10:
                    continue

                corr = np.corrcoef(arr_ret[mask], arr_val[mask])[0, 1]
                if not np.isnan(corr):
                    dynamic[macro_var] = round(float(corr), 4)

            if dynamic:
                self._dynamic_sensitivity[sector] = dynamic

    def get_dynamic_sensitivity(self, sector: str) -> Dict[str, float]:
        """Dinamik hassasiyet getir."""
        return self._dynamic_sensitivity.get(sector, {})

    def get_report(self) -> Dict[str, Any]:
        """Hassasiyet raporu."""
        return {
            "static_sectors": len(SECTOR_MACRO_SENSITIVITY),
            "dynamic_sectors": len(self._dynamic_sensitivity),
            "company_overrides": len(self._company_sensitivity),
            "dynamic_data": self._dynamic_sensitivity,
        }


# Singleton
macro_sensitivity_engine = MacroSensitivityEngine()
