"""
ALPHA BIST — Scenario & Stress Test Engine v1.0

Senaryo analizi ve stres testleri:
- Makro senaryo girdileri → etki hesaplama
- Önceden tanımlı senaryolar (TCMB, USDTRY, BIST crash, vb.)
- Stres testleri (2008, 2020 benzeri)
- Breaking point analizi

FAZ 6.1-6.3: Scenario & Stress Test Engine
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class ScenarioInput:
    """Senaryo girdisi."""

    name: str
    description: str = ""
    usdtry_change: float = 0.0  # ör: 0.10 = %10 artış
    interest_rate_change: float = 0.0  # ör: 0.05 = 500bp
    bist_change: float = 0.0  # ör: -0.15 = %15 düşüş
    vix_change: float = 0.0  # ör: 0.50 = %50 artış
    oil_change: float = 0.0  # ör: 0.20 = %20 artış
    gold_change: float = 0.0  # ör: 0.10 = %10 artış
    inflation_change: float = 0.0  # ör: 0.05 = %5 artış
    global_change: float = 0.0  # ör: -0.10 = %10 düşüş


@dataclass
class AssetImpact:
    """Tek bir varlık üzerindeki etki."""

    ticker: str
    sector: str
    current_price: float
    estimated_impact_pct: float
    estimated_price: float
    impact_breakdown: dict[str, float]


@dataclass
class ScenarioResult:
    """Senaryo sonucu."""

    scenario: ScenarioInput
    portfolio_impact_pct: float
    portfolio_impact_value: float
    asset_impacts: list[AssetImpact]
    sector_impacts: dict[str, float]
    risk_change: dict[str, float]


@dataclass
class StressTestResult:
    """Stres testi sonucu."""

    scenario_name: str
    portfolio_loss_pct: float
    portfolio_loss_value: float
    worst_position: str
    worst_position_loss_pct: float
    var_breach: bool  # VaR aşıldı mı?
    recovery_days: int  # Tahmini toparlanma süresi


@dataclass
class BreakingPoint:
    """Kırılma noktası."""

    variable: str
    current_value: float
    breaking_value: float
    change_pct: float
    description: str


PREDEFINED_SCENARIOS = {
    "TCMB_RATE_HIKE_500BP": ScenarioInput(
        name="TCMB +500bp",
        description="TCMB politika faizi 500 baz puan artış",
        interest_rate_change=0.05,
    ),
    "USDTRY_10_PCT": ScenarioInput(
        name="USD/TRY +%10",
        description="Türk Lirası %10 değer kaybı",
        usdtry_change=0.10,
    ),
    "BIST_CRASH_15_PCT": ScenarioInput(
        name="BIST -%15",
        description="BIST 100 endeksi %15 düşüş",
        bist_change=-0.15,
    ),
    "VIX_SPIKE_50_PCT": ScenarioInput(
        name="VIX +%50",
        description="VIX endeksi %50 artış (global risk-off)",
        vix_change=0.50,
    ),
    "OIL_SHOCK_20_PCT": ScenarioInput(
        name="Petrol +%20",
        description="Ham petrol fiyatında %20 artış",
        oil_change=0.20,
    ),
    "GLOBAL_RISK_OFF": ScenarioInput(
        name="Global Risk-Off",
        description="Global risk-off: BIST düşüş, VIX artış, USDTRY artış",
        bist_change=-0.10,
        vix_change=0.40,
        usdtry_change=0.05,
        global_change=-0.08,
    ),
    "INFLATION_HIGH": ScenarioInput(
        name="Yüksek Enflasyon",
        description="Enflasyon beklentilerin üzerinde gerçekleşti",
        inflation_change=0.05,
        usdtry_change=0.03,
        interest_rate_change=0.02,
    ),
    "2008_CRISIS": ScenarioInput(
        name="2008 Krizi",
        description="2008 küresel finans krizi benzeri senaryo",
        bist_change=-0.50,
        vix_change=2.0,
        usdtry_change=0.30,
        global_change=-0.40,
        oil_change=-0.50,
    ),
    "2020_COVID": ScenarioInput(
        name="2020 COVID",
        description="2020 COVID çöküşü benzeri senaryo",
        bist_change=-0.30,
        vix_change=1.5,
        oil_change=-0.50,
        global_change=-0.25,
        usdtry_change=0.10,
    ),
}


class ScenarioEngine:
    """Senaryo analiz motoru."""

    def run_scenario(
        self,
        scenario: ScenarioInput,
        positions: list[dict[str, Any]],
        sector_sensitivity: Any | None = None,
    ) -> ScenarioResult:
        """Senaryo çalıştır.

        Args:
            scenario: Senaryo girdisi
            positions: [{"ticker": "THYAO", "sector": "AVIATION", "value": 10000, "price": 305}, ...]
            sector_sensitivity: MacroSensitivityEngine instance
        """
        asset_impacts = []
        sector_impacts: dict[str, list[float]] = {}

        macro_shocks = {
            "usdtry_change": scenario.usdtry_change,
            "interest_rate_change": scenario.interest_rate_change,
            "oil_change": scenario.oil_change,
            "gold_change": scenario.gold_change,
            "global_change": scenario.global_change,
            "inflation_change": scenario.inflation_change,
        }

        total_portfolio_value = sum(p.get("value", 0) for p in positions)
        weighted_impact = 0.0

        for pos in positions:
            ticker = pos.get("ticker", "")
            sector = pos.get("sector", "OTHER")
            value = pos.get("value", 0)
            price = pos.get("price", 0)

            # Sektör bazlı etki hesapla
            if sector_sensitivity:
                impacts = sector_sensitivity.compute_macro_impact(ticker, sector, macro_shocks)
                total_impact = impacts.get("total_macro_impact", 0)
            else:
                # Basitleştirilmiş etki
                total_impact = self._simplified_impact(sector, macro_shocks)

            # BIST genel etkisi
            bist_impact = scenario.bist_change * 0.7  # BIST etkisinin %70'i
            total_impact += bist_impact

            estimated_price = price * (1 + total_impact) if price > 0 else 0

            asset_impacts.append(
                AssetImpact(
                    ticker=ticker,
                    sector=sector,
                    current_price=price,
                    estimated_impact_pct=round(total_impact * 100, 2),
                    estimated_price=round(estimated_price, 2),
                    impact_breakdown=macro_shocks,
                )
            )

            # Sektör bazlı etki
            if sector not in sector_impacts:
                sector_impacts[sector] = []
            sector_impacts[sector].append(total_impact)

            # Portföy ağırlıklı etki
            weight = value / total_portfolio_value if total_portfolio_value > 0 else 0
            weighted_impact += total_impact * weight

        # Sektör ortalamaları
        sector_avg = {s: round(np.mean(impacts) * 100, 2) for s, impacts in sector_impacts.items()}

        portfolio_impact_value = total_portfolio_value * weighted_impact

        return ScenarioResult(
            scenario=scenario,
            portfolio_impact_pct=round(weighted_impact * 100, 2),
            portfolio_impact_value=round(portfolio_impact_value, 2),
            asset_impacts=asset_impacts,
            sector_impacts=sector_avg,
            risk_change={
                "volatility_change": abs(scenario.vix_change) * 0.3,
                "liquidity_change": abs(scenario.bist_change) * -0.2 if scenario.bist_change < 0 else 0,
            },
        )

    # F-012: Sektör duyarlılık matrisi — dışarıdan override edilebilir
    DEFAULT_SECTOR_SENSITIVITY = {
        "BANK": {"usdtry_change": -0.3, "interest_rate_change": 0.5, "bist_change": 0.8},
        "AVIATION": {"usdtry_change": -0.7, "oil_change": -0.8, "bist_change": 0.6},
        "ENERGY": {"oil_change": 0.7, "usdtry_change": 0.3, "bist_change": 0.7},
        "TECH": {"global_change": 0.7, "usdtry_change": 0.3, "bist_change": 0.8},
        "RETAIL": {"usdtry_change": -0.5, "inflation_change": -0.6, "bist_change": 0.6},
        "METAL": {"global_change": 0.6, "gold_change": 0.5, "bist_change": 0.7},
        "OTHER": {"bist_change": 0.7, "usdtry_change": -0.3},
    }

    def _simplified_impact(
        self,
        sector: str,
        shocks: dict[str, float],
        custom_sensitivity: dict[str, dict[str, float]] | None = None,
    ) -> float:
        """Basitleştirilmiş sektör etkisi (sensitivity engine yokken).

        F-012: custom_sensitivity parametresi ile dışarıdan matris override edilebilir.
        """
        sensitivity = custom_sensitivity or self.DEFAULT_SECTOR_SENSITIVITY
        sector_sens = sensitivity.get(sector, sensitivity.get("OTHER", {}))
        total = 0.0
        for shock_key, shock_value in shocks.items():
            sens = sector_sens.get(shock_key, 0)
            total += shock_value * sens

        return total

    def run_stress_test(
        self,
        positions: list[dict[str, Any]],
        scenarios: dict[str, ScenarioInput],
        sector_sensitivity: Any | None = None,
    ) -> list[StressTestResult]:
        """Stres testi çalıştır."""
        results = []

        for name, scenario in scenarios.items():
            scenario_result = self.run_scenario(scenario, positions, sector_sensitivity)

            # En kötü pozisyon
            worst = min(scenario_result.asset_impacts, key=lambda a: a.estimated_impact_pct)

            results.append(
                StressTestResult(
                    scenario_name=name,
                    portfolio_loss_pct=round(scenario_result.portfolio_impact_pct, 2),
                    portfolio_loss_value=round(abs(scenario_result.portfolio_impact_value), 2),
                    worst_position=worst.ticker,
                    worst_position_loss_pct=worst.estimated_impact_pct,
                    var_breach=abs(scenario_result.portfolio_impact_pct) > 5,  # %5 VaR eşiği
                    recovery_days=int(abs(scenario_result.portfolio_impact_pct) * 10),  # Tahmini
                )
            )

        return results

    def find_breaking_point(
        self,
        positions: list[dict[str, Any]],
        variable: str,
        max_change: float = 1.0,
        loss_threshold_pct: float = 20.0,
        sector_sensitivity: Any | None = None,
        support_negative: bool = True,  # F-019: Negatif şok desteği
    ) -> BreakingPoint:
        """Kırılma noktası bul.

        Portföyün ne kadar şoka dayanabileceğini bulur.
        F-019: Negatif şok desteği (bist_change=-0.50 gibi).
        """
        # Binary search — negatif şok desteği
        if support_negative:
            low, high = -max_change, max_change
        else:
            low, high = 0.0, max_change

        breaking_value = max_change

        for _ in range(20):  # 20 iterasyon
            mid = (low + high) / 2
            scenario = ScenarioInput(name="test", **{variable: mid})
            result = self.run_scenario(scenario, positions, sector_sensitivity)

            if abs(result.portfolio_impact_pct) >= loss_threshold_pct:
                breaking_value = mid
                high = mid
            else:
                low = mid

        return BreakingPoint(
            variable=variable,
            current_value=0.0,
            breaking_value=round(breaking_value, 4),
            change_pct=round(breaking_value * 100, 2),
            description=f"Portföy %{loss_threshold_pct} kayıp için {variable} değişimi: %{breaking_value * 100:.1f}",
        )


# Singleton
scenario_engine = ScenarioEngine()
