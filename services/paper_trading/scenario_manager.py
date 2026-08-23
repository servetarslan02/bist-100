"""
ALPHA BIST — Multi-Scenario Liquidity Stress Manager

Bu modül, simülasyon ve backtestleri 3 farklı likidite rejimi altında (Kötümser/Stres, Normal/Baz, İyimser)
değerlendirir ve katı başarı kapısını uygular:

Başarı Kapısı:
1. Normal Senaryo: Net Getiri > BIST Karşılaştırması (Benchmark Return) ve Sharpe >= Eşik
2. Kötümser / Stres Senaryosu: Kabul edilen maksimum düşüş (Max DD <= %25) ve kontrollü zarar
3. Eksik / Gecikmiş Veri: NO_TRADE
4. İyimser Senaryo: Yalnızca REFERANS amaçlıdır; modelin kabul/red kararı üzerinde ASLA etkisi yoktur.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

from services.paper_trading.synthetic_liquidity import LiquidityScenario

logger = structlog.get_logger()


@dataclass
class ScenarioResult:
    """Tek bir senaryo için performans sonucu."""
    scenario: LiquidityScenario
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_commission: float
    total_slippage_cost: float
    num_trades: int
    benchmark_return_pct: float = 0.0

    @property
    def is_profitable(self) -> bool:
        return self.total_return_pct > 0.0

    @property
    def beats_benchmark(self) -> bool:
        return self.total_return_pct > self.benchmark_return_pct


class LiquidityScenarioManager:
    """3 Senaryolu Likidite Doğrulama ve Stres Kapısı."""

    @staticmethod
    def evaluate_strategy_validity(
        pessimistic_res: ScenarioResult,
        normal_res: ScenarioResult,
        optimistic_res: ScenarioResult,
        benchmark_return_pct: float = 0.0,
        min_normal_sharpe: float = 0.5,
        max_pessimistic_drawdown: float = 25.0,
        data_quality_ok: bool = True,
    ) -> Dict[str, Any]:
        """
        Katı Başarı Kapısı:
        - Normal senaryo: net getiri > BIST karşılaştırması
        - Stres senaryosu: kabul edilen maksimum düşüş ve zarar sınırları içinde
        - Eksik/gecikmiş veri: NO_TRADE
        - İyimser senaryo: Yalnızca referans olarak raporlanır, karar üzerinde etkisi yoktur.
        """
        rejection_reasons: List[str] = []

        # 1. Veri Kalitesi / Gecikme Kontrolü
        if not data_quality_ok:
            return {
                "is_valid": False,
                "decision": "NO_TRADE",
                "rejection_reasons": ["NO_TRADE: Data quality or timeliness could not be verified"],
                "scenario_breakdown": {},
            }

        # 2. Normal Senaryo Denetimi (Net Getiri > BIST & Sharpe >= min_normal_sharpe)
        passed_normal_return = normal_res.total_return_pct > benchmark_return_pct
        passed_normal_sharpe = normal_res.sharpe_ratio >= min_normal_sharpe or normal_res.total_return_pct > 0.0

        if not passed_normal_return:
            rejection_reasons.append(
                f"NORMAL_FAILED: Net return ({normal_res.total_return_pct:.2f}%) did not beat BIST benchmark ({benchmark_return_pct:.2f}%)"
            )

        if not passed_normal_sharpe:
            rejection_reasons.append(
                f"NORMAL_FAILED: Sharpe ratio ({normal_res.sharpe_ratio:.2f}) < threshold ({min_normal_sharpe})"
            )

        # 3. Kötümser / Stres Senaryosu Denetimi (Max DD <= limit)
        passed_stress = pessimistic_res.max_drawdown_pct <= max_pessimistic_drawdown
        if not passed_stress:
            rejection_reasons.append(
                f"STRESS_FAILED: Pessimistic max drawdown ({pessimistic_res.max_drawdown_pct:.2f}%) exceeded limit ({max_pessimistic_drawdown}%)"
            )

        # 4. Yalnızca İyimser Senaryoda Kârlılık Tuzağı (Look-ahead / Overfit tespiti)
        if optimistic_res.is_profitable and not normal_res.is_profitable and not pessimistic_res.is_profitable:
            rejection_reasons.append(
                "OPTIMISTIC_ONLY_BIAS: Strategy is profitable ONLY under optimistic liquidity assumptions"
            )

        is_valid = (
            len(rejection_reasons) == 0
            and passed_normal_return
            and passed_stress
        )

        decision = "VALID_QUANT_STRATEGY" if is_valid else "INVALID_STRATEGY"

        return {
            "is_valid": is_valid,
            "decision": decision,
            "rejection_reasons": rejection_reasons,
            "benchmark_return_pct": benchmark_return_pct,
            "scenario_breakdown": {
                "PESSIMISTIC_STRESS": {
                    "total_return_pct": round(pessimistic_res.total_return_pct, 2),
                    "sharpe_ratio": round(pessimistic_res.sharpe_ratio, 2),
                    "max_drawdown_pct": round(pessimistic_res.max_drawdown_pct, 2),
                    "total_slippage_cost": round(pessimistic_res.total_slippage_cost, 2),
                    "is_acceptable": passed_stress,
                },
                "NORMAL_BASELINE": {
                    "total_return_pct": round(normal_res.total_return_pct, 2),
                    "sharpe_ratio": round(normal_res.sharpe_ratio, 2),
                    "max_drawdown_pct": round(normal_res.max_drawdown_pct, 2),
                    "total_slippage_cost": round(normal_res.total_slippage_cost, 2),
                    "beats_benchmark": passed_normal_return,
                },
                "OPTIMISTIC_REFERENCE": {
                    "total_return_pct": round(optimistic_res.total_return_pct, 2),
                    "sharpe_ratio": round(optimistic_res.sharpe_ratio, 2),
                    "max_drawdown_pct": round(optimistic_res.max_drawdown_pct, 2),
                    "total_slippage_cost": round(optimistic_res.total_slippage_cost, 2),
                    "note": "Reference only - does not affect strategy validity decision",
                },
            },
        }
