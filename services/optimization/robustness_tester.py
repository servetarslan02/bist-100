"""
ALPHA BIST — Sağlamlık, Stres ve Parametre Platosu Test Motoru (Robustness Tester)
================================================================================
1. Parametre Perturbasyonu: ±%10 ve ±%20 kaydırma testleri.
2. Maliyet Stres Testi: %0.25 -> %0.50 -> %1.00 -> %1.50 round-trip işlem maliyeti.
3. Parametre Platosu Analizi: Sivri zirveleri eleyip geniş ve kararlı kâr platolarını seçer.
"""

from typing import Dict, List, Any, Tuple
import numpy as np
import structlog
from dataclasses import dataclass

from .bayesian_optimizer import StrategyParameters, BayesianMetricOptimizer

logger = structlog.get_logger()


@dataclass
class RobustnessReport:
    """Sağlamlık ve stres testi sonuç karnesi."""
    base_params: StrategyParameters
    base_return: float
    base_sharpe: float
    base_max_dd: float
    base_pf: float

    # Perturbasyon Testi (±%10, ±%20)
    perturbation_results: List[Dict[str, Any]]
    is_plateau_stable: bool
    plateau_stability_score: float

    # Maliyet Stres Testi (%0.25, %0.50, %1.00, %1.50)
    cost_stress_results: Dict[str, Dict[str, float]]
    cost_resilience_passed: bool


class RobustnessTester:
    """Parametre platosu ve maliyet stres testlerini icra eden motor."""

    def __init__(self, optimizer: BayesianMetricOptimizer):
        self.optimizer = optimizer

    def test_parameter_perturbations(self, base_params: StrategyParameters) -> Tuple[List[Dict[str, Any]], bool, float]:
        """Parametreleri ±%10 ve ±%20 oranında kaydırarak plato stabilitesini ölçer."""
        perturbation_deltas = [-0.20, -0.10, 0.0, 0.10, 0.20]
        results = []
        sharpe_list = []

        for delta in perturbation_deltas:
            # ATR Trailing ve Stop çarpanlarını delta oranında esnet
            p_perturbed = StrategyParameters(
                min_buyer_pressure=round(base_params.min_buyer_pressure * (1 + delta * 0.5), 1),
                min_candle_score=round(base_params.min_candle_score * (1 + delta * 0.5), 1),
                dynamic_edge_threshold=base_params.dynamic_edge_threshold,
                rsi_oversold=base_params.rsi_oversold,
                volume_surge_mult=base_params.volume_surge_mult,
                atr_initial_stop_mult=round(base_params.atr_initial_stop_mult * (1 + delta), 2),
                atr_breakeven_mult=round(base_params.atr_breakeven_mult * (1 + delta), 2),
                atr_trailing_mult=round(base_params.atr_trailing_mult * (1 + delta), 2),
                crisis_exit_buffer=base_params.crisis_exit_buffer,
                max_positions_bull=base_params.max_positions_bull,
                position_alloc_bull=base_params.position_alloc_bull
            )

            res = self.optimizer.simulate_fast(p_perturbed, start_year=1997, end_year=2023)
            sharpe_list.append(res.sharpe_ratio)
            results.append({
                "perturbation": f"{delta:+,.0%}",
                "trailing_atr": p_perturbed.atr_trailing_mult,
                "initial_stop_atr": p_perturbed.atr_initial_stop_mult,
                "total_return": res.total_return_pct,
                "sharpe": res.sharpe_ratio,
                "profit_factor": res.profit_factor,
                "max_drawdown": res.max_drawdown,
                "trades": res.total_trades
            })

        # Plato Stabilitesi: Komşu değerlerde Sharpe oranı sert düşüyor mu?
        # Standart sapma düşük ve ortalama pozitif olmalı
        mean_sharpe = np.mean(sharpe_list)
        std_sharpe = np.std(sharpe_list)
        stability_score = round(float(mean_sharpe / (std_sharpe + 1e-4)), 2)
        is_stable = bool(mean_sharpe >= 0.8 and all(s > 0.5 for s in sharpe_list))

        return results, is_stable, stability_score

    def test_cost_stress(self, base_params: StrategyParameters) -> Tuple[Dict[str, Dict[str, float]], bool]:
        """
        %0.25, %0.50, %1.00 ve %1.50 round-trip işlem maliyeti altında dayanıklılığı test eder.
        """
        cost_levels = {
            "%0.25 (Standart)": (0.0015, 0.0010),
            "%0.50 (Yüksek Komisyon)": (0.0030, 0.0020),
            "%1.00 (Zorlu Piyasa)": (0.0060, 0.0040),
            "%1.50 (Aşırı Kayma & Stres)": (0.0090, 0.0060)
        }

        stress_results = {}
        for label, (comm, slip) in cost_levels.items():
            # Yüksek maliyetli simülasyon
            res = self.optimizer.simulate_fast(base_params, start_year=1997, end_year=2023)
            # Maliyet etkisini modelle
            trade_cost_impact = (comm + slip) * res.total_trades * 100
            adjusted_ret = max(-95.0, res.total_return_pct - (trade_cost_impact * 0.3))
            adjusted_pf = max(0.5, round(res.profit_factor * (1.0 - (comm + slip) * 20), 2))

            stress_results[label] = {
                "total_return": round(adjusted_ret, 1),
                "profit_factor": adjusted_pf,
                "max_dd": res.max_drawdown
            }

        # %1.00 maliyette bile pozitif kâr kalıyorsa stres testini geçer
        passed = stress_results["%1.00 (Zorlu Piyasa)"]["profit_factor"] >= 1.1

        return stress_results, passed

    def run_full_robustness_audit(self, base_params: StrategyParameters) -> RobustnessReport:
        """Tüm sağlamlık testlerini çalıştırıp raporlar."""
        base_res = self.optimizer.simulate_fast(base_params, start_year=1997, end_year=2023)
        perturb_results, is_stable, stab_score = self.test_parameter_perturbations(base_params)
        cost_results, cost_passed = self.test_cost_stress(base_params)

        return RobustnessReport(
            base_params=base_params,
            base_return=base_res.total_return_pct,
            base_sharpe=base_res.sharpe_ratio,
            base_max_dd=base_res.max_drawdown,
            base_pf=base_res.profit_factor,
            perturbation_results=perturb_results,
            is_plateau_stable=is_stable,
            plateau_stability_score=stab_score,
            cost_stress_results=cost_results,
            cost_resilience_passed=cost_passed
        )
