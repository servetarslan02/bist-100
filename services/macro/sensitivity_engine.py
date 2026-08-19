"""ALPHA BIST — Dynamic Sensitivity Engine v2.0

Dinamik sektör-macro hassasiyet — rolling korelasyon:
- 60 günlük rolling window ile sector-macro korelasyon
- Sensitivity trend tracking (artıyor/azalıyor/sabit)
- Company-specific override (döviz borcu, ithalat bağımlılığı)
- Factor decomposition (USDTRY/faiz/enflasyon/global katkısı)
- Anlamlılık testi (p-value)

KURAL: Sabit hassasiyet yok — her şey rolling korelasyon.
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class SensitivityResult:
    """Sektör hassasiyet sonucu."""
    sector: str
    usdtry_sensitivity: float
    rate_sensitivity: float
    inflation_sensitivity: float
    vix_sensitivity: float
    oil_sensitivity: float
    gold_sensitivity: float
    # Trend
    usdtry_trend: str = "STABLE"  # INCREASING, DECREASING, STABLE
    rate_trend: str = "STABLE"
    # Anlamlılık
    usdtry_p_value: float = 1.0
    rate_p_value: float = 1.0
    # Meta
    n_observations: int = 0
    window_days: int = 60

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sector": self.sector,
            "usdtry_sensitivity": round(self.usdtry_sensitivity, 4),
            "rate_sensitivity": round(self.rate_sensitivity, 4),
            "inflation_sensitivity": round(self.inflation_sensitivity, 4),
            "vix_sensitivity": round(self.vix_sensitivity, 4),
            "oil_sensitivity": round(self.oil_sensitivity, 4),
            "gold_sensitivity": round(self.gold_sensitivity, 4),
            "usdtry_trend": self.usdtry_trend,
            "rate_trend": self.rate_trend,
            "usdtry_p_value": round(self.usdtry_p_value, 4),
            "rate_p_value": round(self.rate_p_value, 4),
            "n_observations": self.n_observations,
        }


@dataclass
class CompanySensitivity:
    """Şirket bazlı hassasiyet override."""
    ticker: str
    sector: str
    # Override ağırlıkları (1.0 = sektör hassasiyeti kullan, >1 = daha hassas, <1 = daha az)
    usdtry_override: float = 1.0
    rate_override: float = 1.0
    inflation_override: float = 1.0
    # Neden
    reason: str = ""  # "fx_debt", "import_dependent", "exporter", "rate_sensitive"


class DynamicSensitivityEngine:
    """Dinamik sektör-macro hassasiyet motoru.

    Özellikler:
    - 60 günlük rolling window ile sector-macro korelasyon
    - Sensitivity trend tracking
    - Company-specific override (döviz borcu, ithalat bağımlılığı)
    - Factor decomposition
    - Anlamlılık testi
    """

    # Varsayılan sektör hassasiyetleri (rolling data yoksa fallback)
    DEFAULT_SENSITIVITIES = {
        "BANKING": {"usdtry": -0.6, "rate": -0.7, "inflation": -0.4, "vix": -0.5, "oil": -0.1, "gold": 0.2},
        "TECHNOLOGY": {"usdtry": -0.3, "rate": -0.4, "inflation": -0.2, "vix": -0.6, "oil": -0.1, "gold": 0.1},
        "INDUSTRY": {"usdtry": -0.5, "rate": -0.5, "inflation": -0.3, "vix": -0.4, "oil": -0.3, "gold": 0.1},
        "ENERGY": {"usdtry": -0.2, "rate": -0.3, "inflation": -0.2, "vix": -0.3, "oil": 0.7, "gold": 0.1},
        "RETAIL": {"usdtry": -0.5, "rate": -0.4, "inflation": -0.5, "vix": -0.4, "oil": -0.2, "gold": 0.1},
        "CONSTRUCTION": {"usdtry": -0.7, "rate": -0.6, "inflation": -0.3, "vix": -0.3, "oil": -0.2, "gold": 0.1},
        "TELECOM": {"usdtry": -0.2, "rate": -0.3, "inflation": -0.2, "vix": -0.3, "oil": -0.1, "gold": 0.1},
        "MINING": {"usdtry": 0.3, "rate": -0.2, "inflation": 0.1, "vix": -0.3, "oil": 0.2, "gold": 0.6},
        "FOOD": {"usdtry": -0.3, "rate": -0.3, "inflation": -0.4, "vix": -0.2, "oil": -0.2, "gold": 0.1},
        "METAL": {"usdtry": -0.4, "rate": -0.4, "inflation": -0.2, "vix": -0.4, "oil": -0.1, "gold": 0.3},
    }

    def __init__(self, window: int = 60, min_observations: int = 20):
        self._window = window
        self._min_observations = min_observations

        # Rolling data
        self._sector_returns: Dict[str, List[float]] = {}  # sector → returns
        self._macro_values: Dict[str, List[float]] = {}    # macro_var → values

        # Company overrides
        self._company_overrides: Dict[str, CompanySensitivity] = {}

        # Cache
        self._sensitivity_cache: Dict[str, SensitivityResult] = {}
        self._last_cache_update: Optional[datetime] = None

    def update(self, sector_returns: Dict[str, float], macro_values: Dict[str, float]):
        """Günlük güncelleme — rolling window'a veri ekle.

        Args:
            sector_returns: {sector: daily_return}
            macro_values: {macro_var: value} — usdtry_change, rate_change, inflation, vix, oil, gold
        """
        # Sector returns
        for sector, ret in sector_returns.items():
            if sector not in self._sector_returns:
                self._sector_returns[sector] = []
            self._sector_returns[sector].append(ret)
            # Rolling window
            if len(self._sector_returns[sector]) > self._window * 2:
                self._sector_returns[sector] = self._sector_returns[sector][-self._window:]

        # Macro values
        for var, val in macro_values.items():
            if var not in self._macro_values:
                self._macro_values[var] = []
            self._macro_values[var].append(val)
            if len(self._macro_values[var]) > self._window * 2:
                self._macro_values[var] = self._macro_values[var][-self._window:]

        # Cache invalidation
        self._last_cache_update = None

    def register_company_override(self, ticker: str, sector: str, override: CompanySensitivity):
        """Şirket bazlı hassasiyet override kaydet."""
        override.ticker = ticker
        override.sector = sector
        self._company_overrides[ticker] = override

    def compute_dynamic_sensitivity(self, sector: str) -> SensitivityResult:
        """Sektör için dinamik hassasiyet hesapla — rolling korelasyon.

        Args:
            sector: Sektör adı

        Returns:
            SensitivityResult
        """
        # Cache kontrol
        if self._last_cache_update and sector in self._sensitivity_cache:
            return self._sensitivity_cache[sector]

        sector_rets = self._sector_returns.get(sector, [])

        if len(sector_rets) < self._min_observations:
            # Fallback: varsayılan hassasiyet
            return self._get_default_sensitivity(sector)

        # Rolling korelasyonlar
        usdtry_sens, usdtry_p = self._compute_rolling_corr(sector_rets, "usdtry_change")
        rate_sens, rate_p = self._compute_rolling_corr(sector_rets, "rate_change")
        inflation_sens, inflation_p = self._compute_rolling_corr(sector_rets, "inflation")
        vix_sens, vix_p = self._compute_rolling_corr(sector_rets, "vix")
        oil_sens, oil_p = self._compute_rolling_corr(sector_rets, "oil_change")
        gold_sens, gold_p = self._compute_rolling_corr(sector_rets, "gold_change")

        # Trend
        usdtry_trend = self._compute_sensitivity_trend(sector_rets, "usdtry_change")
        rate_trend = self._compute_sensitivity_trend(sector_rets, "rate_change")

        result = SensitivityResult(
            sector=sector,
            usdtry_sensitivity=usdtry_sens,
            rate_sensitivity=rate_sens,
            inflation_sensitivity=inflation_sens,
            vix_sensitivity=vix_sens,
            oil_sensitivity=oil_sens,
            gold_sensitivity=gold_sens,
            usdtry_trend=usdtry_trend,
            rate_trend=rate_trend,
            usdtry_p_value=usdtry_p,
            rate_p_value=rate_p,
            n_observations=len(sector_rets),
            window_days=self._window,
        )

        # Cache
        self._sensitivity_cache[sector] = result
        self._last_cache_update = datetime.now(timezone.utc)

        return result

    def get_company_sensitivity(self, ticker: str, sector: str) -> SensitivityResult:
        """Şirket bazlı hassasiyet — sector + override.

        Args:
            ticker: Hisse kodu
            sector: Sektör

        Returns:
            SensitivityResult (override uygulanmış)
        """
        sector_sens = self.compute_dynamic_sensitivity(sector)

        # Override var mı?
        override = self._company_overrides.get(ticker)
        if not override:
            return sector_sens

        # Override uygula
        return SensitivityResult(
            sector=sector,
            usdtry_sensitivity=sector_sens.usdtry_sensitivity * override.usdtry_override,
            rate_sensitivity=sector_sens.rate_sensitivity * override.rate_override,
            inflation_sensitivity=sector_sens.inflation_sensitivity * override.inflation_override,
            vix_sensitivity=sector_sens.vix_sensitivity,
            oil_sensitivity=sector_sens.oil_sensitivity,
            gold_sensitivity=sector_sens.gold_sensitivity,
            usdtry_trend=sector_sens.usdtry_trend,
            rate_trend=sector_sens.rate_trend,
            usdtry_p_value=sector_sens.usdtry_p_value,
            rate_p_value=sector_sens.rate_p_value,
            n_observations=sector_sens.n_observations,
        )

    def compute_factor_decomposition(
        self,
        ticker: str,
        sector: str,
        daily_return: float,
        macro_changes: Dict[str, float],
    ) -> Dict[str, float]:
        """Factor decomposition — hangi faktör ne kadar katkı yaptı.

        Args:
            ticker: Hisse kodu
            sector: Sektör
            daily_return: Günlük getiri
            macro_changes: {macro_var: daily_change}

        Returns:
            {factor: contribution} — usdtry, rate, inflation, vix, oil, gold, residual
        """
        sens = self.get_company_sensitivity(ticker, sector)

        contributions = {}

        # Her faktörün katkısı = sensitivity × macro_change
        factor_map = {
            "usdtry": (sens.usdtry_sensitivity, macro_changes.get("usdtry_change", 0)),
            "rate": (sens.rate_sensitivity, macro_changes.get("rate_change", 0)),
            "inflation": (sens.inflation_sensitivity, macro_changes.get("inflation", 0)),
            "vix": (sens.vix_sensitivity, macro_changes.get("vix", 0)),
            "oil": (sens.oil_sensitivity, macro_changes.get("oil_change", 0)),
            "gold": (sens.gold_sensitivity, macro_changes.get("gold_change", 0)),
        }

        explained = 0.0
        for factor, (sensitivity, change) in factor_map.items():
            contribution = sensitivity * change
            contributions[factor] = round(contribution, 6)
            explained += contribution

        # Residual (açıklanamayan kısım)
        contributions["residual"] = round(daily_return - explained, 6)
        contributions["explained_ratio"] = round(abs(explained) / max(abs(daily_return), 1e-8), 4)

        return contributions

    def compute_all_sensitivities(self) -> Dict[str, SensitivityResult]:
        """Tüm sektörler için hassasiyet hesapla."""
        results = {}
        all_sectors = set(list(self._sector_returns.keys()) + list(self.DEFAULT_SENSITIVITIES.keys()))
        for sector in all_sectors:
            results[sector] = self.compute_dynamic_sensitivity(sector)
        return results

    def get_sensitivity_summary(self) -> Dict[str, Any]:
        """Hassasiyet özeti — en hassas sektörler."""
        all_sens = self.compute_all_sensitivities()

        # USDTRY'ye en hassas sektörler
        usdtry_ranking = sorted(
            all_sens.items(),
            key=lambda x: abs(x[1].usdtry_sensitivity),
            reverse=True,
        )

        return {
            "n_sectors": len(all_sens),
            "usdtry_most_sensitive": [
                {"sector": s, "sensitivity": round(r.usdtry_sensitivity, 4)}
                for s, r in usdtry_ranking[:3]
            ],
            "n_company_overrides": len(self._company_overrides),
            "window_days": self._window,
        }

    def _compute_rolling_corr(
        self,
        sector_returns: List[float],
        macro_var: str,
    ) -> Tuple[float, float]:
        """Rolling korelasyon hesapla.

        Returns:
            (correlation, p_value)
        """
        macro_vals = self._macro_values.get(macro_var, [])
        if not macro_vals:
            return 0.0, 1.0

        # Uzunlukları eşitle
        n = min(len(sector_returns), len(macro_vals))
        if n < self._min_observations:
            return 0.0, 1.0

        sr = np.array(sector_returns[-n:])
        mv = np.array(macro_vals[-n:])

        # NaN temizle
        mask = np.isfinite(sr) & np.isfinite(mv)
        sr = sr[mask]
        mv = mv[mask]

        if len(sr) < self._min_observations:
            return 0.0, 1.0

        # Korelasyon
        try:
            corr = float(np.corrcoef(sr, mv)[0, 1])
            if np.isnan(corr):
                return 0.0, 1.0
        except Exception:
            return 0.0, 1.0

        # p-value (basitleştirilmiş — t-test)
        try:
            n_obs = len(sr)
            if n_obs > 2 and abs(corr) < 1.0:
                t_stat = corr * np.sqrt((n_obs - 2) / (1 - corr**2))
                # Basit p-value approximation
                from scipy import stats
                p_value = float(2 * stats.t.sf(abs(t_stat), n_obs - 2))
            else:
                p_value = 1.0
        except Exception:
            p_value = 1.0

        return round(corr, 4), round(p_value, 4)

    def _compute_sensitivity_trend(
        self,
        sector_returns: List[float],
        macro_var: str,
    ) -> str:
        """Sensitivite trendi — son 20 gün vs önceki 20 gün."""
        macro_vals = self._macro_values.get(macro_var, [])
        if not macro_vals:
            return "STABLE"

        n = min(len(sector_returns), len(macro_vals))
        if n < 40:
            return "STABLE"

        sr = np.array(sector_returns[-n:])
        mv = np.array(macro_vals[-n:])

        # İlk yarım
        mid = n // 2
        corr_first = np.corrcoef(sr[:mid], mv[:mid])[0, 1]
        corr_second = np.corrcoef(sr[mid:], mv[mid:])[0, 1]

        if np.isnan(corr_first) or np.isnan(corr_second):
            return "STABLE"

        diff = abs(corr_second) - abs(corr_first)
        if diff > 0.1:
            return "INCREASING"
        elif diff < -0.1:
            return "DECREASING"
        return "STABLE"

    def _get_default_sensitivity(self, sector: str) -> SensitivityResult:
        """Varsayılan hassasiyet (rolling data yoksa)."""
        defaults = self.DEFAULT_SENSITIVITIES.get(sector.upper(), {
            "usdtry": -0.4, "rate": -0.4, "inflation": -0.3, "vix": -0.4, "oil": -0.1, "gold": 0.1,
        })

        return SensitivityResult(
            sector=sector,
            usdtry_sensitivity=defaults.get("usdtry", -0.4),
            rate_sensitivity=defaults.get("rate", -0.4),
            inflation_sensitivity=defaults.get("inflation", -0.3),
            vix_sensitivity=defaults.get("vix", -0.4),
            oil_sensitivity=defaults.get("oil", -0.1),
            gold_sensitivity=defaults.get("gold", 0.1),
            n_observations=0,
            window_days=self._window,
        )


# Singleton
macro_sensitivity_engine = DynamicSensitivityEngine()
