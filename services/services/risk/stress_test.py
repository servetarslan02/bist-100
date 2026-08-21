"""
ALPHA BIST — Stress Test Engine v1.0

Kapsamlı stres test motoru:
- Historical scenarios (2008, 2020, 2022)
- Hypothetical scenarios (USDTRY, BIST crash, TCMB)
- Monte Carlo simulation (10,000+ paths)
- Breaking point analysis
- Portfolio impact scoring

Kaynaklar:
- CFA Institute — Measuring and Managing Market Risk (2026)
- ScienceDirect — Integrated Risk Management Framework (2026)
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class ScenarioResult:
    """Tek senaryo sonucu."""
    scenario_name: str
    scenario_type: str  # historical, hypothetical, monte_carlo
    total_impact_pct: float
    total_impact_amount: float
    position_impacts: List[Dict[str, Any]]
    worst_position: str
    best_position: str
    recovery_estimate_days: Optional[int] = None


@dataclass
class StressTestReport:
    """Stres testi raporu."""
    portfolio_value: float
    scenarios: List[ScenarioResult]
    worst_scenario: ScenarioResult
    best_scenario: ScenarioResult
    avg_impact_pct: float
    max_loss_amount: float
    risk_score: float  # 0-100
    recommendations: List[str]


class StressTestEngine:
    """Kapsamlı stres test motoru."""

    # =====================================================
    # TARİHSEL SENARYOLAR
    # =====================================================
    HISTORICAL_SCENARIOS = {
        "2008_GLOBAL_CRISIS": {
            "name": "2008 Global Finansal Kriz",
            "bist_return": -0.52,
            "usdtry_change": 0.30,
            "vix_level": 80,
            "sector_impacts": {
                "BANKING": -0.60,
                "FINANCE": -0.55,
                "INDUSTRY": -0.45,
                "TECHNOLOGY": -0.40,
                "CONSUMER": -0.35,
                "ENERGY": -0.50,
                "REAL_ESTATE": -0.55,
                "OTHER": -0.45,
            },
            "recovery_days": 500,
        },
        "2020_COVID": {
            "name": "2020 COVID-19 Çöküşü",
            "bist_return": -0.35,
            "usdtry_change": 0.15,
            "vix_level": 65,
            "sector_impacts": {
                "BANKING": -0.30,
                "FINANCE": -0.25,
                "INDUSTRY": -0.40,
                "TECHNOLOGY": -0.15,
                "CONSUMER": -0.45,
                "ENERGY": -0.50,
                "REAL_ESTATE": -0.30,
                "OTHER": -0.35,
            },
            "recovery_days": 180,
        },
        "2022_INFLATION": {
            "name": "2022 Enflasyon Şoku",
            "bist_return": -0.25,
            "usdtry_change": 0.40,
            "vix_level": 35,
            "sector_impacts": {
                "BANKING": -0.15,
                "FINANCE": -0.20,
                "INDUSTRY": -0.30,
                "TECHNOLOGY": -0.35,
                "CONSUMER": -0.40,
                "ENERGY": -0.10,
                "REAL_ESTATE": -0.25,
                "OTHER": -0.25,
            },
            "recovery_days": 300,
        },
        "2018_LIRA_CRISIS": {
            "name": "2018 TL Krizi",
            "bist_return": -0.30,
            "usdtry_change": 0.70,
            "vix_level": 45,
            "sector_impacts": {
                "BANKING": -0.45,
                "FINANCE": -0.40,
                "INDUSTRY": -0.25,
                "TECHNOLOGY": -0.20,
                "CONSUMER": -0.35,
                "ENERGY": -0.30,
                "REAL_ESTATE": -0.40,
                "OTHER": -0.30,
            },
            "recovery_days": 400,
        },
    }

    # =====================================================
    # HİPOTETİK SENARYOLAR
    # =====================================================
    HYPOTHETICAL_SCENARIOS = {
        "USDTRY_10_PCT": {
            "name": "USD/TRY %10 Artış",
            "usdtry_change": 0.10,
            "sector_impacts": {
                "BANKING": -0.05,
                "ENERGY": -0.08,
                "INDUSTRY": -0.03,
                "OTHER": -0.05,
            },
        },
        "BIST_CRASH_15_PCT": {
            "name": "BIST %15 Çöküş",
            "bist_return": -0.15,
            "sector_impacts": {
                "BANKING": -0.18,
                "FINANCE": -0.15,
                "INDUSTRY": -0.12,
                "TECHNOLOGY": -0.10,
                "CONSUMER": -0.15,
                "ENERGY": -0.20,
                "OTHER": -0.15,
            },
        },
        "TCMB_RATE_HIKE_500BP": {
            "name": "TCMB +500bp Faiz Artışı",
            "rate_change": 0.05,
            "sector_impacts": {
                "BANKING": 0.05,      # Bankalar faizden kazanır
                "FINANCE": -0.03,
                "INDUSTRY": -0.08,
                "TECHNOLOGY": -0.10,
                "CONSUMER": -0.05,
                "REAL_ESTATE": -0.15,
                "OTHER": -0.05,
            },
        },
        "GLOBAL_RISK_OFF": {
            "name": "Global Risk-Off (VIX +50%)",
            "vix_change": 0.50,
            "bist_return": -0.10,
            "sector_impacts": {
                "BANKING": -0.12,
                "FINANCE": -0.10,
                "INDUSTRY": -0.08,
                "TECHNOLOGY": -0.15,
                "CONSUMER": -0.05,
                "ENERGY": -0.10,
                "OTHER": -0.10,
            },
        },
        "GEOPOLITICAL_SHOCK": {
            "name": "Jeopolitik Şok",
            "bist_return": -0.20,
            "usdtry_change": 0.15,
            "vix_change": 0.30,
            "sector_impacts": {
                "BANKING": -0.25,
                "FINANCE": -0.20,
                "INDUSTRY": -0.15,
                "TECHNOLOGY": -0.10,
                "CONSUMER": -0.20,
                "ENERGY": -0.25,
                "DEFENSE": 0.10,
                "OTHER": -0.18,
            },
        },
    }

    def run_scenario(
        self,
        portfolio: Dict[str, Any],
        scenario_key: str,
    ) -> ScenarioResult:
        """Tek senaryo çalıştır.

        Args:
            portfolio: Portföy bilgisi {"positions": [{"ticker", "value", "sector"}], "total_value"}
            scenario_key: Senaryo anahtarı

        Returns:
            ScenarioResult
        """
        scenario = self.HISTORICAL_SCENARIOS.get(scenario_key) or \
                   self.HYPOTHETICAL_SCENARIOS.get(scenario_key)

        if not scenario:
            return ScenarioResult(
                scenario_name=f"UNKNOWN: {scenario_key}",
                scenario_type="unknown",
                total_impact_pct=0,
                total_impact_amount=0,
                position_impacts=[],
                worst_position="",
                best_position="",
            )

        total_value = portfolio.get("total_value", 0)
        positions = portfolio.get("positions", [])
        position_impacts = []

        for pos in positions:
            ticker = pos.get("ticker", "")
            value = pos.get("value", 0)
            sector = pos.get("sector", "OTHER")

            # Sektör bazlı etki
            sector_impacts = scenario.get("sector_impacts", {})
            impact_pct = sector_impacts.get(sector, scenario.get("bist_return", -0.10))

            # Dolar etkisi (dolar bazlı geliri olan şirketler için)
            usdtry_change = scenario.get("usdtry_change", 0)
            if usdtry_change > 0:
                # Basit heuristic: ihracatçı şirketler dolar artışından kazanır
                if sector in ["INDUSTRY", "ENERGY"]:
                    impact_pct += usdtry_change * 0.3  # Kısmi hedge
                else:
                    impact_pct -= usdtry_change * 0.2  # Negatif etki

            impact_amount = value * impact_pct
            position_impacts.append({
                "ticker": ticker,
                "sector": sector,
                "value": value,
                "impact_pct": round(impact_pct * 100, 2),
                "impact_amount": round(impact_amount, 2),
            })

        total_impact = sum(p["impact_amount"] for p in position_impacts)
        total_impact_pct = (total_impact / total_value * 100) if total_value > 0 else 0

        # En kötü ve en iyi pozisyon
        worst = min(position_impacts, key=lambda x: x["impact_amount"]) if position_impacts else {}
        best = max(position_impacts, key=lambda x: x["impact_amount"]) if position_impacts else {}

        return ScenarioResult(
            scenario_name=scenario.get("name", scenario_key),
            scenario_type="historical" if scenario_key in self.HISTORICAL_SCENARIOS else "hypothetical",
            total_impact_pct=round(total_impact_pct, 2),
            total_impact_amount=round(total_impact, 2),
            position_impacts=position_impacts,
            worst_position=worst.get("ticker", ""),
            best_position=best.get("ticker", ""),
            recovery_estimate_days=scenario.get("recovery_days"),
        )

    def run_all_scenarios(
        self,
        portfolio: Dict[str, Any],
    ) -> StressTestReport:
        """Tüm senaryoları çalıştır.

        Args:
            portfolio: Portföy bilgisi

        Returns:
            StressTestReport
        """
        scenarios = []

        # Tarihsel senaryolar
        for key in self.HISTORICAL_SCENARIOS:
            result = self.run_scenario(portfolio, key)
            scenarios.append(result)

        # Hipotetik senaryolar
        for key in self.HYPOTHETICAL_SCENARIOS:
            result = self.run_scenario(portfolio, key)
            scenarios.append(result)

        if not scenarios:
            return StressTestReport(
                portfolio_value=portfolio.get("total_value", 0),
                scenarios=[],
                worst_scenario=None,
                best_scenario=None,
                avg_impact_pct=0,
                max_loss_amount=0,
                risk_score=0,
                recommendations=["No scenarios available"],
            )

        worst = min(scenarios, key=lambda x: x.total_impact_amount)
        best = max(scenarios, key=lambda x: x.total_impact_amount)
        avg_impact = np.mean([s.total_impact_pct for s in scenarios])
        max_loss = abs(worst.total_impact_amount)

        # Risk skoru (0-100)
        risk_score = self._calculate_risk_score(scenarios, portfolio.get("total_value", 1))

        # Öneriler
        recommendations = self._generate_recommendations(scenarios, risk_score)

        return StressTestReport(
            portfolio_value=portfolio.get("total_value", 0),
            scenarios=scenarios,
            worst_scenario=worst,
            best_scenario=best,
            avg_impact_pct=round(avg_impact, 2),
            max_loss_amount=round(max_loss, 2),
            risk_score=round(risk_score, 1),
            recommendations=recommendations,
        )

    def run_monte_carlo_stress(
        self,
        portfolio: Dict[str, Any],
        returns_history: np.ndarray,
        n_simulations: int = 10000,
        holding_days: int = 5,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Monte Carlo stres testi.

        Args:
            portfolio: Portföy bilgisi
            returns_history: Geçmiş getiri dizisi
            n_simulations: Simülasyon sayısı
            holding_days: Tutma süresi
            seed: Rastgele tohum

        Returns:
            Monte Carlo sonuçları
        """
        if seed is not None:
            np.random.seed(seed)

        total_value = portfolio.get("total_value", 0)
        mu = np.mean(returns_history)
        sigma = np.std(returns_history, ddof=1)

        # Simülasyon.  Sabit getiri serisine yapay %2 volatilite eklemek
        # hiç olmayan bir stres riski üretir.  Günlük getirileri de toplamak
        # yerine bileşikleştiriyoruz; P&L'nin portföy değeriyle tutarlı
        # olması için gerekli olan budur.
        if sigma <= 0:
            cumulative_returns = np.full(
                n_simulations, (1.0 + mu) ** holding_days - 1.0
            )
        else:
            daily_returns = np.random.normal(mu, sigma, (n_simulations, holding_days))
            cumulative_returns = np.prod(1.0 + daily_returns, axis=1) - 1.0
        simulated_pnl = cumulative_returns * total_value

        # İstatistikler
        percentiles = {
            1: float(np.percentile(simulated_pnl, 1)),
            5: float(np.percentile(simulated_pnl, 5)),
            10: float(np.percentile(simulated_pnl, 10)),
            25: float(np.percentile(simulated_pnl, 25)),
            50: float(np.percentile(simulated_pnl, 50)),
            75: float(np.percentile(simulated_pnl, 75)),
            90: float(np.percentile(simulated_pnl, 90)),
            95: float(np.percentile(simulated_pnl, 95)),
            99: float(np.percentile(simulated_pnl, 99)),
        }

        return {
            "n_simulations": n_simulations,
            "holding_days": holding_days,
            "portfolio_value": total_value,
            "mean_pnl": float(np.mean(simulated_pnl)),
            "std_pnl": float(np.std(simulated_pnl)),
            "worst_case": float(np.min(simulated_pnl)),
            "best_case": float(np.max(simulated_pnl)),
            "percentiles": percentiles,
            "prob_loss": float(np.mean(simulated_pnl < 0) * 100),
            "prob_loss_5pct": float(np.mean(simulated_pnl < -total_value * 0.05) * 100),
            "prob_loss_10pct": float(np.mean(simulated_pnl < -total_value * 0.10) * 100),
        }

    def find_breaking_point(
        self,
        portfolio: Dict[str, Any],
        max_loss_pct: float = 20.0,
    ) -> Dict[str, Any]:
        """Breaking point analizi — portföy ne kadar kaybeder?

        Args:
            portfolio: Portföy bilgisi
            max_loss_pct: Maksimum kayıp yüzdesi

        Returns:
            Breaking point sonuçları
        """
        total_value = portfolio.get("total_value", 0)
        positions = portfolio.get("positions", [])

        # Her senaryo için breaking point kontrolü
        breaking_scenarios = []

        for key, scenario in {**self.HISTORICAL_SCENARIOS, **self.HYPOTHETICAL_SCENARIOS}.items():
            result = self.run_scenario(portfolio, key)
            if abs(result.total_impact_pct) >= max_loss_pct:
                breaking_scenarios.append({
                    "scenario": scenario.get("name", key),
                    "impact_pct": result.total_impact_pct,
                    "impact_amount": result.total_impact_amount,
                    "exceeds_by": abs(result.total_impact_pct) - max_loss_pct,
                })

        return {
            "max_loss_pct": max_loss_pct,
            "max_loss_amount": total_value * max_loss_pct / 100,
            "breaking_scenarios": breaking_scenarios,
            "is_robust": len(breaking_scenarios) == 0,
            "n_breaking": len(breaking_scenarios),
        }

    def _calculate_risk_score(self, scenarios: List[ScenarioResult], total_value: float) -> float:
        """Risk skoru hesapla (0-100)."""
        if not scenarios or total_value <= 0:
            return 50.0

        # En kötü senaryo etkisi
        worst_impact = abs(min(s.total_impact_pct for s in scenarios))

        # Ortalama etki
        avg_impact = abs(np.mean([s.total_impact_pct for s in scenarios]))

        # Risk skoru: kötü senaryo ne kadar kötüyse skor o kadar yüksek
        score = 0

        # Worst case (ağırlık: %40)
        if worst_impact > 50:
            score += 40
        elif worst_impact > 30:
            score += 30
        elif worst_impact > 20:
            score += 20
        elif worst_impact > 10:
            score += 10

        # Average case (ağırlık: %30)
        if avg_impact > 25:
            score += 30
        elif avg_impact > 15:
            score += 20
        elif avg_impact > 10:
            score += 15
        elif avg_impact > 5:
            score += 10

        # Senaryo sayısı (ağırlık: %15)
        n_negative = sum(1 for s in scenarios if s.total_impact_pct < -10)
        score += min(15, n_negative * 3)

        # Konsantrasyon (ağırlık: %15)
        if scenarios:
            worst_position_impact = max(
                abs(p["impact_pct"])
                for s in scenarios
                for p in s.position_impacts
            ) if any(s.position_impacts for s in scenarios) else 0
            score += min(15, worst_position_impact / 2)

        return min(100, score)

    def _generate_recommendations(self, scenarios: List[ScenarioResult], risk_score: float) -> List[str]:
        """Stres testi sonuçlarına göre öneriler."""
        recommendations = []

        if risk_score > 70:
            recommendations.append("⚠️ YÜKSEK RİSK: Portföy stres testlerinde büyük kayıplar gösteriyor")

        worst = min(scenarios, key=lambda x: x.total_impact_pct) if scenarios else None
        if worst and abs(worst.total_impact_pct) > 30:
            recommendations.append(f"🔴 En kötü senaryo (%{abs(worst.total_impact_pct):.1f} kayıp) çok agresif")

        # Sektör konsantrasyonu kontrolü
        sector_impacts = {}
        for s in scenarios:
            for p in s.position_impacts:
                sector = p.get("sector", "OTHER")
                if sector not in sector_impacts:
                    sector_impacts[sector] = []
                sector_impacts[sector].append(abs(p["impact_pct"]))

        for sector, impacts in sector_impacts.items():
            avg_impact = np.mean(impacts)
            if avg_impact > 20:
                recommendations.append(f"🟡 {sector} sektörü stres altında çok etkileniyor (ortalama %{avg_impact:.1f})")

        if not recommendations:
            recommendations.append("✅ Portföy stres testlerinde makul seviyelerde")

        return recommendations


# Singleton
stress_test_engine = StressTestEngine()
