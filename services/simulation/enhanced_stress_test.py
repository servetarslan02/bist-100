"""
ALPHA BIST — Enhanced Stress Test v2.0

8+ stres senaryosu:
- Market Crash (-20%)
- Currency Crisis (USDTRY +30%)
- Rate Shock (+500bp)
- Sector Rotation
- Black Swan (-30%)
- Liquidity Crisis
- Stagflation
- Global Risk-Off
- Company-specific stress
- Breaking point analysis

Kaynaklar: arXiv Agentic Trading (2026), MDPI Regime-Dependent CVaR (2026)
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class StressScenario:
    """Stres senaryosu."""
    name: str
    description: str
    market_shock: float        # Piyasa şoku (%)
    vol_spike: float           # Volatilite çarpanı
    usd_shock: float           # USD/TRY şoku (%)
    rate_shock: float          # Faiz şoku (bp)
    sector_impacts: dict[str, float]  # Sektör bazlı etki
    probability: float         # Olasılık (yıllık)


@dataclass
class StressResult:
    """Stres testi sonucu."""
    scenario: str
    portfolio_impact_pct: float
    portfolio_impact_amount: float
    worst_position: str
    best_position: str
    position_impacts: list[dict[str, Any]]
    recovery_estimate_days: int | None = None


class EnhancedStressTestEngine:
    """Gelişmiş stres test motoru.

    8+ senaryo ile kapsamlı risk analizi.
    """

    # =====================================================
    # STRES SENARYOLARI
    # =====================================================

    SCENARIOS = [
        StressScenario(
            name="Market Crash -20%",
            description="BIST genelinde %20 düşüş",
            market_shock=-0.20,
            vol_spike=3.0,
            usd_shock=0.10,
            rate_shock=200,
            sector_impacts={
                "BANKING": -0.25, "FINANCE": -0.22, "INDUSTRY": -0.18,
                "TECHNOLOGY": -0.15, "CONSUMER": -0.20, "ENERGY": -0.22,
                "REAL_ESTATE": -0.25, "OTHER": -0.20,
            },
            probability=0.05,
        ),
        StressScenario(
            name="Currency Crisis (USDTRY +30%)",
            description="TL'nin %30 değer kaybı",
            market_shock=-0.15,
            vol_spike=2.5,
            usd_shock=0.30,
            rate_shock=500,
            sector_impacts={
                "BANKING": -0.20, "ENERGY": -0.25, "AVIATION": -0.30,
                "METAL": 0.10, "INDUSTRY": -0.10, "TECHNOLOGY": -0.15,
                "CONSUMER": -0.20, "OTHER": -0.15,
            },
            probability=0.03,
        ),
        StressScenario(
            name="Rate Shock +500bp",
            description="TCMB faiz artışı +500bp",
            market_shock=-0.10,
            vol_spike=2.0,
            usd_shock=0.05,
            rate_shock=500,
            sector_impacts={
                "BANKING": 0.05, "REAL_ESTATE": -0.20, "INDUSTRY": -0.12,
                "TECHNOLOGY": -0.15, "CONSUMER": -0.10, "ENERGY": -0.08,
                "OTHER": -0.10,
            },
            probability=0.08,
        ),
        StressScenario(
            name="Sector Rotation",
            description="Sektör rotasyonu (growth → value)",
            market_shock=-0.05,
            vol_spike=1.5,
            usd_shock=0.02,
            rate_shock=100,
            sector_impacts={
                "TECHNOLOGY": -0.15, "BANKING": 0.05, "INDUSTRY": 0.03,
                "CONSUMER": -0.08, "ENERGY": 0.02, "OTHER": -0.05,
            },
            probability=0.15,
        ),
        StressScenario(
            name="Black Swan -30%",
            description="Kuyruk riski olayı (%30 düşüş)",
            market_shock=-0.30,
            vol_spike=5.0,
            usd_shock=0.20,
            rate_shock=300,
            sector_impacts={
                "BANKING": -0.35, "FINANCE": -0.30, "INDUSTRY": -0.28,
                "TECHNOLOGY": -0.25, "CONSUMER": -0.30, "ENERGY": -0.32,
                "REAL_ESTATE": -0.35, "OTHER": -0.28,
            },
            probability=0.01,
        ),
        StressScenario(
            name="Liquidity Crisis",
            description="Likidite krizi (hacim çöküşü, spread genişleme)",
            market_shock=-0.15,
            vol_spike=4.0,
            usd_shock=0.15,
            rate_shock=400,
            sector_impacts={
                "BANKING": -0.25, "FINANCE": -0.20, "INDUSTRY": -0.12,
                "TECHNOLOGY": -0.10, "CONSUMER": -0.15, "ENERGY": -0.18,
                "SMALL_CAP": -0.30, "OTHER": -0.15,
            },
            probability=0.04,
        ),
        StressScenario(
            name="Stagflation",
            description="Durgunluk + yüksek enflasyon",
            market_shock=-0.12,
            vol_spike=2.0,
            usd_shock=0.25,
            rate_shock=600,
            sector_impacts={
                "BANKING": -0.10, "REAL_ESTATE": -0.20, "CONSUMER": -0.25,
                "TECHNOLOGY": -0.15, "INDUSTRY": -0.12, "ENERGY": 0.05,
                "FOOD": 0.03, "OTHER": -0.12,
            },
            probability=0.03,
        ),
        StressScenario(
            name="Global Risk-Off",
            description="Global risk-off (VIX +50%, emerging market çıkış)",
            market_shock=-0.12,
            vol_spike=2.5,
            usd_shock=0.10,
            rate_shock=200,
            sector_impacts={
                "BANKING": -0.15, "FINANCE": -0.12, "INDUSTRY": -0.10,
                "TECHNOLOGY": -0.18, "CONSUMER": -0.08, "ENERGY": -0.12,
                "OTHER": -0.12,
            },
            probability=0.10,
        ),
    ]

    def run_stress_test(
        self,
        portfolio_value: float,
        positions: list[dict[str, Any]],
    ) -> list[StressResult]:
        """Tüm stres senaryolarını çalıştır.

        Args:
            portfolio_value: Portföy değeri
            positions: Pozisyonlar [{"ticker", "value", "sector", "beta", "usd_sensitivity"}]

        Returns:
            Stres testi sonuçları
        """
        results = []

        for scenario in self.SCENARIOS:
            result = self._run_scenario(portfolio_value, positions, scenario)
            results.append(result)

        return results

    def _run_scenario(
        self,
        portfolio_value: float,
        positions: list[dict[str, Any]],
        scenario: StressScenario,
    ) -> StressResult:
        """Tek senaryo çalıştır."""
        total_impact = 0
        position_impacts = []

        for pos in positions:
            ticker = pos.get("ticker", "")
            value = pos.get("value", 0)
            sector = pos.get("sector", "OTHER")
            beta = pos.get("beta", 1.0)
            usd_sensitivity = pos.get("usd_sensitivity", 0.5)

            # Sektör bazlı etki
            sector_impact = scenario.sector_impacts.get(
                sector, scenario.market_shock
            )

            # Beta ayarlaması
            market_effect = scenario.market_shock * beta

            # USD etkisi
            usd_effect = scenario.usd_shock * usd_sensitivity

            # Toplam etki
            total_pos_impact = sector_impact + usd_effect
            # Market shock'u da dahil et (ağırlıklı)
            total_pos_impact = 0.6 * total_pos_impact + 0.4 * market_effect

            loss = value * total_pos_impact
            total_impact += loss

            position_impacts.append({
                "ticker": ticker,
                "sector": sector,
                "value": value,
                "impact_pct": round(total_pos_impact * 100, 2),
                "loss": round(loss, 2),
                "sector_impact_pct": round(sector_impact * 100, 2),
                "usd_impact_pct": round(usd_effect * 100, 2),
            })

        # En kötü ve en iyi pozisyon
        worst = min(position_impacts, key=lambda x: x["loss"]) if position_impacts else {}
        best = max(position_impacts, key=lambda x: x["loss"]) if position_impacts else {}

        return StressResult(
            scenario=scenario.name,
            portfolio_impact_pct=round(total_impact / portfolio_value * 100, 2) if portfolio_value > 0 else 0,
            portfolio_impact_amount=round(total_impact, 2),
            worst_position=worst.get("ticker", ""),
            best_position=best.get("ticker", ""),
            position_impacts=position_impacts,
        )

    def find_breaking_point(
        self,
        portfolio_value: float,
        positions: list[dict[str, Any]],
        max_loss_pct: float = 20.0,
    ) -> dict[str, Any]:
        """Breaking point analizi.

        Args:
            portfolio_value: Portföy değeri
            positions: Pozisyonlar
            max_loss_pct: Maksimum kayıp yüzdesi

        Returns:
            Breaking point sonuçları
        """
        results = self.run_stress_test(portfolio_value, positions)

        breaking = []
        for r in results:
            if abs(r.portfolio_impact_pct) >= max_loss_pct:
                breaking.append({
                    "scenario": r.scenario,
                    "impact_pct": r.portfolio_impact_pct,
                    "exceeds_by": abs(r.portfolio_impact_pct) - max_loss_pct,
                })

        return {
            "max_loss_pct": max_loss_pct,
            "max_loss_amount": portfolio_value * max_loss_pct / 100,
            "breaking_scenarios": breaking,
            "is_robust": len(breaking) == 0,
            "n_breaking": len(breaking),
            "worst_scenario": min(results, key=lambda r: r.portfolio_impact_pct).scenario,
            "worst_impact_pct": min(r.portfolio_impact_pct for r in results),
        }

    def get_scenario_summary(
        self,
        results: list[StressResult],
    ) -> dict[str, Any]:
        """Stres testi özeti.

        Args:
            results: Stres testi sonuçları

        Returns:
            Özet
        """
        impacts = [r.portfolio_impact_pct for r in results]

        return {
            "total_scenarios": len(results),
            "worst_impact_pct": round(min(impacts), 2),
            "best_impact_pct": round(max(impacts), 2),
            "avg_impact_pct": round(np.mean(impacts), 2),
            "median_impact_pct": round(np.median(impacts), 2),
            "worst_scenario": min(results, key=lambda r: r.portfolio_impact_pct).scenario,
            "scenarios": [
                {
                    "name": r.scenario,
                    "impact_pct": r.portfolio_impact_pct,
                    "impact_amount": r.portfolio_impact_amount,
                }
                for r in sorted(results, key=lambda r: r.portfolio_impact_pct)
            ],
        }

    def add_custom_scenario(
        self,
        name: str,
        market_shock: float,
        sector_impacts: dict[str, float],
        usd_shock: float = 0,
        rate_shock: float = 0,
        vol_spike: float = 2.0,
        probability: float = 0.05,
    ):
        """Özel stres senaryosu ekle.

        Args:
            name: Senaryo adı
            market_shock: Piyasa şoku (%)
            sector_impacts: Sektör bazlı etkiler
            usd_shock: USD şoku (%)
            rate_shock: Faiz şoku (bp)
            vol_spike: Volatilite çarpanı
            probability: Olasılık
        """
        scenario = StressScenario(
            name=name,
            description=f"Custom: {name}",
            market_shock=market_shock,
            vol_spike=vol_spike,
            usd_shock=usd_shock,
            rate_shock=rate_shock,
            sector_impacts=sector_impacts,
            probability=probability,
        )
        self.SCENARIOS.append(scenario)
        logger.info("Custom stress scenario added", name=name)


# Singleton
enhanced_stress_test = EnhancedStressTestEngine()
