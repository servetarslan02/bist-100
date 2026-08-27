"""
ALPHA BIST — Risk Parity Position Sizing v1.0

Risk parity: Her pozisyonun eşit risk katkısı sağlar.
Markowitz'un aksine getiri tahmini gerektirmez, sadece risk dağılımına odaklanır.

Kaynaklar:
- ScienceDirect — Integrated Risk Management Framework (2026)
- arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
from scipy.optimize import minimize

logger = structlog.get_logger()


@dataclass
class RiskParityResult:
    """Risk parity sonucu."""
    weights: dict[str, float]        # ticker → weight
    risk_contributions: dict[str, float]  # ticker → risk katkısı (%)
    portfolio_volatility: float
    diversification_ratio: float
    optimization_success: bool
    iterations: int


class RiskParityOptimizer:
    """Risk Parity optimizasyonu.

    Amaç: Her pozisyonun portföy riskine eşit katkı sağlaması.
    Bu, konsantrasyon riskini azaltır ve çeşitlendirmeyi maksimize eder.
    """

    def __init__(self, tolerance: float = 1e-8, max_iterations: int = 1000):
        self.tolerance = tolerance
        self.max_iterations = max_iterations

    def optimize(
        self,
        cov_matrix: np.ndarray,
        tickers: list[str],
        target_risk_contributions: dict[str, float] | None = None,
    ) -> RiskParityResult:
        """Risk parity ağırlıkları hesapla.

        Args:
            cov_matrix: Kovaryans matrisi (n_assets × n_assets)
            tickers: Hisse kodları
            target_risk_contributions: Hedef risk katkıları (opsiyonel, eşit varsayılan)

        Returns:
            RiskParityResult
        """
        n_assets = len(tickers)

        if n_assets == 0:
            return RiskParityResult(
                weights={}, risk_contributions={},
                portfolio_volatility=0, diversification_ratio=0,
                optimization_success=False, iterations=0,
            )

        if n_assets == 1:
            return RiskParityResult(
                weights={tickers[0]: 1.0},
                risk_contributions={tickers[0]: 100.0},
                portfolio_volatility=np.sqrt(cov_matrix[0, 0]),
                diversification_ratio=1.0,
                optimization_success=True, iterations=0,
            )

        # Hedef risk katkıları (eşit)
        if target_risk_contributions is None:
            target_rc = np.ones(n_assets) / n_assets
        else:
            target_rc = np.array([
                target_risk_contributions.get(t, 1.0 / n_assets)
                for t in tickers
            ])
            target_rc = target_rc / target_rc.sum()  # Normalize

        # Optimizasyon
        result = self._solve_risk_parity(cov_matrix, target_rc)

        weights_array = result["weights"]
        weights_dict = {tickers[i]: float(weights_array[i]) for i in range(n_assets)}

        # Risk katkıları
        rc = self._risk_contributions(weights_array, cov_matrix)
        rc_dict = {tickers[i]: float(rc[i]) * 100 for i in range(n_assets)}

        # Portföy volatilitesi
        port_vol = float(np.sqrt(weights_array @ cov_matrix @ weights_array))

        # Diversification ratio
        weighted_vols = weights_array * np.sqrt(np.diag(cov_matrix))
        div_ratio = float(np.sum(weighted_vols) / port_vol) if port_vol > 0 else 0

        return RiskParityResult(
            weights=weights_dict,
            risk_contributions=rc_dict,
            portfolio_volatility=port_vol,
            diversification_ratio=div_ratio,
            optimization_success=result["success"],
            iterations=result["iterations"],
        )

    def _solve_risk_parity(
        self,
        cov_matrix: np.ndarray,
        target_rc: np.ndarray,
    ) -> dict[str, Any]:
        """Risk parity optimizasyonu çöz."""
        n = cov_matrix.shape[0]

        # Başlangıç ağırlıkları (eşit)
        w0 = np.ones(n) / n

        # Kısıtlar: ağırlıkların toplamı = 1, ağırlıklar >= 0
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.001, 1.0) for _ in range(n)]

        # Amaç fonksiyonu: risk katkılarının hedeften sapması
        def objective(w):
            rc = self._risk_contributions(w, cov_matrix)
            return np.sum((rc - target_rc) ** 2)

        # Optimizasyon
        result = minimize(
            objective,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": self.max_iterations, "ftol": self.tolerance},
        )

        # Negatif değerleri temizle, SONRA normalize et (sıra önemli:
        # önce normalize edip sonra negatifleri sıfırlamak, kalan
        # ağırlıkların toplamının 1'den sapmasına yol açabilir).
        weights = result.x
        weights = np.maximum(weights, 0)
        weight_sum = weights.sum()
        weights = weights / weight_sum if weight_sum > 0 else np.ones(n) / n

        return {
            "weights": weights,
            "success": result.success,
            "iterations": result.nit,
        }

    def _risk_contributions(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> np.ndarray:
        """Risk katkıları hesapla.

        RC_i = w_i × (Σw)_i / σ_p

        Her pozisyonun portföy volatilitesine katkısı.
        """
        portfolio_vol = np.sqrt(weights @ cov_matrix @ weights)
        if portfolio_vol <= 0:
            return np.ones(len(weights)) / len(weights)

        marginal_risk = cov_matrix @ weights / portfolio_vol
        risk_contrib = weights * marginal_risk
        risk_contrib_pct = risk_contrib / risk_contrib.sum()

        return risk_contrib_pct

    def compute_risk_budget_weights(
        self,
        cov_matrix: np.ndarray,
        tickers: list[str],
        risk_budgets: dict[str, float],
    ) -> RiskParityResult:
        """Risk bütçesi bazlı ağırlıklar.

        Farklı varlıklar için farklı risk bütçeleri belirleyebilirsiniz.
        Örneğin: hisse %60, tahvil %30, emtia %10 risk katkısı.

        Args:
            cov_matrix: Kovaryans matrisi
            tickers: Hisse kodları
            risk_budgets: ticker → risk bütçesi (0-1 arası)

        Returns:
            RiskParityResult
        """
        return self.optimize(cov_matrix, tickers, risk_budgets)

    def compare_with_equal_weight(
        self,
        cov_matrix: np.ndarray,
        tickers: list[str],
    ) -> dict[str, Any]:
        """Risk parity vs equal weight karşılaştırması."""
        n = len(tickers)

        # Risk parity
        rp_result = self.optimize(cov_matrix, tickers)

        # Equal weight
        ew_weights = np.ones(n) / n
        ew_vol = float(np.sqrt(ew_weights @ cov_matrix @ ew_weights))
        ew_rc = self._risk_contributions(ew_weights, cov_matrix)
        ew_rc_dict = {tickers[i]: float(ew_rc[i]) * 100 for i in range(n)}

        return {
            "risk_parity": {
                "weights": rp_result.weights,
                "volatility": rp_result.portfolio_volatility,
                "risk_contributions": rp_result.risk_contributions,
                "diversification_ratio": rp_result.diversification_ratio,
            },
            "equal_weight": {
                "weights": {t: 1.0 / n for t in tickers},
                "volatility": ew_vol,
                "risk_contributions": ew_rc_dict,
                "diversification_ratio": float(np.sum(ew_weights * np.sqrt(np.diag(cov_matrix))) / ew_vol)
                if ew_vol > 0 else 0,
            },
            "volatility_reduction": round((1 - rp_result.portfolio_volatility / ew_vol) * 100, 2)
            if ew_vol > 0 else 0,
        }


# Singleton
risk_parity_optimizer = RiskParityOptimizer()
