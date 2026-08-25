"""
ALPHA BIST — Macro Stress Test v1.0

Makro stres testi — portfolio bazlı:
- 7 önceden tanımlı senaryo
- Özel senaryo desteği
- Breaking point analizi
- Sector ve pozisyon bazlı detay

KURAL: "USDTRY +10% olursa portföy ne olur?" sorusunu cevapla.
"""

from typing import Dict, List, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

from services.macro.config.macro_config import macro_config

logger = structlog.get_logger()


@dataclass
class PositionImpact:
    """Pozisyon etki sonucu."""
    ticker: str
    sector: str
    value: float
    weight: float
    impact_pct: float
    impact_value: float


@dataclass
class StressTestResult:
    """Stres testi sonucu."""
    scenario: str
    description: str
    shocks: Dict[str, float]
    total_impact_pct: float
    total_impact_value: float
    portfolio_value: float
    position_impacts: List[PositionImpact]
    worst_position: str
    best_position: str
    timestamp: str


@dataclass
class BreakingPointResult:
    """Breaking point sonucu."""
    shock_type: str
    breaking_point_pct: float
    portfolio_impact_at_breaking: float
    description: str


class MacroStressTest:
    """Makro stres testi motoru."""

    # Önceden tanımlı senaryolar (config'den de okunabilir)
    PREDEFINED_SCENARIOS = {
        "USDTRY_10_PCT": {"usdtry_change": 0.10},
        "TCMB_RATE_HIKE_500BP": {"interest_rate_change": 0.05},
        "VIX_SPIKE_50_PCT": {"vix_change": 0.50},
        "OIL_SHOCK_20_PCT": {"oil_change": 0.20},
        "GLOBAL_RISK_OFF": {"global_change": -0.10, "usdtry_change": 0.05},
        "INFLATION_HIGH": {"inflation_change": 0.05},
        "BIST_CRASH_10_PCT": {"bist_change": -0.10},
    }

    # Sektör hassasiyet matrisi
    SECTOR_SENSITIVITY = {
        "BANK": {"usdtry": -0.3, "interest_rate": 0.9, "oil": -0.1, "inflation": -0.7, "global": 0.5, "vix": -0.4, "bist": 0.7},
        "AVIATION": {"usdtry": -0.8, "interest_rate": -0.5, "oil": -0.9, "inflation": -0.4, "global": 0.6, "vix": -0.5, "bist": 0.6},
        "ENERGY": {"usdtry": 0.5, "interest_rate": -0.4, "oil": 0.9, "inflation": 0.3, "global": 0.7, "vix": -0.3, "bist": 0.5},
        "TECH": {"usdtry": 0.4, "interest_rate": -0.6, "oil": -0.1, "inflation": -0.3, "global": 0.8, "vix": -0.6, "bist": 0.8},
        "RETAIL": {"usdtry": -0.6, "interest_rate": -0.5, "oil": -0.3, "inflation": -0.8, "global": 0.3, "vix": -0.3, "bist": 0.6},
        "METAL": {"usdtry": 0.4, "interest_rate": -0.3, "oil": -0.5, "inflation": 0.3, "global": 0.8, "vix": -0.4, "bist": 0.7},
        "CONSTR": {"usdtry": -0.6, "interest_rate": -0.8, "oil": -0.4, "inflation": -0.7, "global": 0.3, "vix": -0.4, "bist": 0.7},
        "FOOD": {"usdtry": -0.5, "interest_rate": -0.4, "oil": -0.3, "inflation": -0.6, "global": 0.3, "vix": -0.3, "bist": 0.5},
        "HOLDING": {"usdtry": -0.4, "interest_rate": -0.5, "oil": -0.2, "inflation": -0.4, "global": 0.5, "vix": -0.4, "bist": 0.6},
        "OTHER": {"usdtry": -0.4, "interest_rate": -0.4, "oil": -0.2, "inflation": -0.4, "global": 0.4, "vix": -0.3, "bist": 0.5},
    }

    # Senaryo açıklamaları
    SCENARIO_DESCRIPTIONS = {
        "USDTRY_10_PCT": "Türk Lirası %10 değer kaybı",
        "TCMB_RATE_HIKE_500BP": "TCMB faiz artışı 500bp",
        "VIX_SPIKE_50_PCT": "VIX %50 artış (global risk-off)",
        "OIL_SHOCK_20_PCT": "Petrol fiyatları %20 artış",
        "GLOBAL_RISK_OFF": "Global risk-off (S&P500 -10%, USDTRY +5%)",
        "INFLATION_HIGH": "Enflasyon %5 artış",
        "BIST_CRASH_10_PCT": "BIST-100 %10 düşüş",
    }

    def run_stress_test(
        self,
        portfolio: Dict[str, Any],
        scenario: str,
    ) -> StressTestResult:
        """Stres testi çalıştır.

        Args:
            portfolio: {
                "total_value": float,
                "positions": [
                    {"ticker": str, "sector": str, "value": float, "weight": float},
                    ...
                ]
            }
            scenario: Senaryo adı

        Returns:
            StressTestResult
        """
        cfg = macro_config.stress_test
        shocks = cfg.predefined_scenarios.get(scenario)
        if not shocks:
            return self._empty_result(scenario, portfolio.get("total_value", 0))

        return self._run_scenario(portfolio, scenario, shocks)

    def run_custom_scenario(
        self,
        portfolio: Dict[str, Any],
        shocks: Dict[str, float],
        description: str = "Custom scenario",
    ) -> StressTestResult:
        """Özel senaryo stres testi."""
        return self._run_scenario(portfolio, "CUSTOM", shocks, description)

    def find_breaking_point(
        self,
        portfolio: Dict[str, Any],
        shock_type: str,
        threshold_pct: float = -0.10,
    ) -> BreakingPointResult:
        """Breaking point — kaç %'lik şok portföyü eşik kayıp ettirir?

        Binary search ile breaking point bul.
        """
        low, high = 0.0, 0.50  # %0 ile %50 arası
        tolerance = 0.01

        while high - low > tolerance:
            mid = (low + high) / 2
            shocks = {shock_type: mid}
            result = self._run_scenario(portfolio, "BREAKING_POINT", shocks)

            if result.total_impact_pct <= threshold_pct:
                high = mid
            else:
                low = mid

        breaking_point = round((low + high) / 2, 4)

        return BreakingPointResult(
            shock_type=shock_type,
            breaking_point_pct=round(breaking_point * 100, 2),
            portfolio_impact_at_breaking=round(threshold_pct * 100, 2),
            description=f"{shock_type} %{breaking_point*100:.1f} şoku portföyü %{abs(threshold_pct)*100:.0f} kayıp ettirir",
        )

    def run_all_scenarios(
        self,
        portfolio: Dict[str, Any],
    ) -> List[StressTestResult]:
        """Tüm önceden tanımlı senaryoları çalıştır."""
        cfg = macro_config.stress_test
        results = []

        for scenario in cfg.predefined_scenarios:
            result = self.run_stress_test(portfolio, scenario)
            results.append(result)

        return sorted(results, key=lambda r: r.total_impact_pct)

    def get_report(
        self,
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Stres testi raporu."""
        results = self.run_all_scenarios(portfolio)

        return {
            "portfolio_value": portfolio.get("total_value", 0),
            "scenario_count": len(results),
            "worst_scenario": {
                "name": results[0].scenario if results else "N/A",
                "impact_pct": results[0].total_impact_pct if results else 0,
            },
            "best_scenario": {
                "name": results[-1].scenario if results else "N/A",
                "impact_pct": results[-1].total_impact_pct if results else 0,
            },
            "scenarios": [
                {
                    "name": r.scenario,
                    "description": r.description,
                    "impact_pct": r.total_impact_pct,
                    "impact_value": r.total_impact_value,
                }
                for r in results
            ],
        }

    # ===================== INTERNAL =====================

    def _run_scenario(
        self,
        portfolio: Dict[str, Any],
        scenario: str,
        shocks: Dict[str, float],
        description: str = None,
    ) -> StressTestResult:
        """Senaryo çalıştır."""
        if description is None:
            description = self.SCENARIO_DESCRIPTIONS.get(scenario, scenario)

        positions = portfolio.get("positions", [])
        total_value = portfolio.get("total_value", 0)

        position_impacts = []
        total_impact_value = 0.0

        for pos in positions:
            ticker = pos.get("ticker", "")
            sector = pos.get("sector", "OTHER")
            value = pos.get("value", 0)
            weight = pos.get("weight", 0)

            # Sektör hassasiyeti
            sensitivity = self.SECTOR_SENSITIVITY.get(sector, self.SECTOR_SENSITIVITY["OTHER"])

            # Etki hesapla
            impact_pct = 0.0
            for shock_key, shock_value in shocks.items():
                sens_key = shock_key.replace("_change", "").replace("_pct", "")
                sens = sensitivity.get(sens_key, 0)
                impact_pct += shock_value * sens

            impact_value = value * impact_pct
            total_impact_value += impact_value

            position_impacts.append(PositionImpact(
                ticker=ticker,
                sector=sector,
                value=value,
                weight=weight,
                impact_pct=round(impact_pct * 100, 2),
                impact_value=round(impact_value, 2),
            ))

        total_impact_pct = total_impact_value / total_value if total_value > 0 else 0

        # En kötü ve en iyi pozisyon
        if position_impacts:
            worst = min(position_impacts, key=lambda p: p.impact_pct)
            best = max(position_impacts, key=lambda p: p.impact_pct)
        else:
            worst = PositionImpact("", "", 0, 0, 0, 0)
            best = PositionImpact("", "", 0, 0, 0, 0)

        return StressTestResult(
            scenario=scenario,
            description=description,
            shocks=shocks,
            total_impact_pct=round(total_impact_pct * 100, 2),
            total_impact_value=round(total_impact_value, 2),
            portfolio_value=total_value,
            position_impacts=position_impacts,
            worst_position=worst.ticker,
            best_position=best.ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _empty_result(self, scenario: str, total_value: float) -> StressTestResult:
        """Boş sonuç."""
        return StressTestResult(
            scenario=scenario,
            description=f"Unknown scenario: {scenario}",
            shocks={},
            total_impact_pct=0.0,
            total_impact_value=0.0,
            portfolio_value=total_value,
            position_impacts=[],
            worst_position="",
            best_position="",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# Singleton
macro_stress_test = MacroStressTest()
