"""
ALPHA BIST — Quantitative Portfolio Optimizer Engine v2.0

BIST-100 İçin Çok Yöntemli, Kısıt Duyarlı ve Deterministik Portföy Optimizasyonu:
1. Risk Parity (Eşit Risk Katkısı / ERC) + PSD Ledoit-Wolf Kovaryans
2. Hierarchical Risk Parity (HRP — Lopez de Prado Hiyerarşik Ağaç Kümeleme)
3. Mean-Variance / Max Sharpe (Markowitz + L2 Regularization + Sürtünme Cezası)
4. Black-Litterman (Model Sinyal Görüşleri + Denge Getirisi Füzyonu)
5. Minimum Variance (Global Minimum Varyans)
6. BIST-Özgü Kısıtlar:
   - Sektör Konsantrasyon Tavanı (Maks %25-30)
   - Tekil Pozisyon Tavanı (Maks %10)
   - Toz Pozisyon Eşiği (Min %1.5 altı temizleme)
   - Likidite Kısıtı & ADV Katılım Çarpanı
   - Turnover Cezası (Aşırı işlem engelleme)
   - Hysteresis (Gereksiz mikro-rebalancing filtresi)
   - Rejim Duyarlı Nakit Tamponu ve Maruziyet Tavanı
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np
import structlog
from scipy.cluster.hierarchy import linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

from services.risk.covariance import CovarianceEstimator, covariance_estimator, ensure_positive_semi_definite
from services.risk.liquidity_risk import LiquidityRiskEngine, liquidity_risk_engine

logger = structlog.get_logger()


class OptimizationMethod(StrEnum):
    RISK_PARITY = "RISK_PARITY"
    HIERARCHICAL_RISK_PARITY = "HRP"
    MAX_SHARPE = "MAX_SHARPE"
    MIN_VARIANCE = "MIN_VARIANCE"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"
    EQUAL_WEIGHT = "EQUAL_WEIGHT"


@dataclass
class PortfolioOptimizerConstraints:
    """Portföy optimizasyon kısıtları ve sürtünme parametreleri."""

    max_position_pct: float = 0.10  # Tek hissede maksimum ağırlık (%10)
    min_position_pct: float = 0.015  # Minimum pozisyon eşiği (%1.5, tozluluk filtresi)
    max_sector_pct: float = 0.30  # Sektör tavanı (%30)
    max_total_exposure: float = 1.00  # Toplam hisse maruziyeti (kaldıraçsız = 1.0)
    min_cash_buffer_pct: float = 0.05  # Zorunlu nakit rezervi (%5)
    turnover_penalty_lambda: float = 0.015  # Aşırı rebalance turnover ceza katsayısı
    transaction_cost_pct: float = 0.0015  # %0.15 ortalama BIST işlem maliyeti
    hysteresis_threshold: float = 0.02  # %2 altındaki küçük sapmalarda işlem yapmama
    l2_regularization: float = 0.002  # Aşırı yoğunlaşmayı engelleyen L2 ceza


@dataclass
class OptimizationResult:
    """Optimizasyon çıktısı."""

    weights: dict[str, float]  # ticker -> weight (0 - 1)
    method: OptimizationMethod
    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    diversification_ratio: float
    turnover_from_current: float
    estimated_transaction_cost_tl: float
    effective_positions_count: int
    sector_exposures: dict[str, float]
    cash_weight: float
    is_optimal: bool
    warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class PortfolioOptimizer:
    """BIST Portföy Optimizasyon Motoru."""

    def __init__(
        self,
        cov_est: CovarianceEstimator = covariance_estimator,
        liq_engine: LiquidityRiskEngine = liquidity_risk_engine,
    ):
        self.cov_estimator = cov_est
        self.liquidity_engine = liq_engine

    def optimize(
        self,
        tickers: list[str],
        returns_matrix: np.ndarray,  # (n_samples, n_assets)
        method: OptimizationMethod = OptimizationMethod.RISK_PARITY,
        expected_returns: np.ndarray | None = None,
        model_scores: dict[str, float] | None = None,
        current_weights: dict[str, float] | None = None,
        sector_map: dict[str, str] | None = None,
        liquidity_scores: dict[str, float] | None = None,
        regime: str = "SIDEWAYS",
        constraints: PortfolioOptimizerConstraints | None = None,
        portfolio_value: float = 100000.0,
    ) -> OptimizationResult:
        """Tüm BIST kısıtlarına ve piyasa rejimine uygun portföy optimizasyonu.

        Args:
            tickers: Portföye aday hisse kodları
            returns_matrix: (T x N) getiri matrisi
            method: Optimizasyon yöntemi
            expected_returns: Varlık beklenen getirileri (opsiyonel)
            model_scores: Model tahmin skorları (0-100, Black-Litterman için)
            current_weights: Mevcut portföy ağırlıkları
            sector_map: {ticker: sector} eşlemesi
            liquidity_scores: {ticker: liquidity_score [0-100]}
            regime: Mevcut piyasa rejimi (BULL, SIDEWAYS, BEAR, CRISIS)
            constraints: Kısıt nesnesi
            portfolio_value: Portföy büyüklüğü (TL)
        """
        c = constraints or PortfolioOptimizerConstraints()
        n_assets = len(tickers)
        warnings = []

        if n_assets == 0:
            return self._empty_result(method, warnings=["Boş hisse evreni verildi."])

        if n_assets == 1:
            return OptimizationResult(
                weights={tickers[0]: 1.0 - c.min_cash_buffer_pct},
                method=method,
                expected_return=0.0,
                portfolio_volatility=0.20,
                sharpe_ratio=0.0,
                diversification_ratio=1.0,
                turnover_from_current=0.0,
                estimated_transaction_cost_tl=0.0,
                effective_positions_count=1,
                sector_exposures={sector_map.get(tickers[0], "OTHER"): 1.0 - c.min_cash_buffer_pct}
                if sector_map
                else {},
                cash_weight=c.min_cash_buffer_pct,
                is_optimal=True,
            )

        # 1. Ledoit-Wolf Shrinkage & Positive Semi-Definite (PSD) Kovaryans
        cov_res = self.cov_estimator.estimate(returns_matrix, tickers)
        cov_matrix = ensure_positive_semi_definite(cov_res["covariance"], min_eigenvalue=1e-6)

        # 2. Beklenen Getiriler (Expected Returns)
        if expected_returns is None:
            if model_scores is not None:
                # Skorlardan beklenen getiri türet (z-score scaling)
                scores_arr = np.array([model_scores.get(t, 50.0) for t in tickers])
                std_scores = np.std(scores_arr) if np.std(scores_arr) > 1e-4 else 1.0
                expected_returns = (scores_arr - np.mean(scores_arr)) / std_scores * 0.05 + 0.15
            else:
                expected_returns = np.mean(returns_matrix, axis=0) * 252.0

        # 3. Yönteme Göre Ham Ağırlıkların Çözümü
        raw_weights, is_opt = self._solve_raw_weights(
            method=method,
            tickers=tickers,
            cov_matrix=cov_matrix,
            expected_returns=expected_returns,
            current_weights=current_weights,
            constraints=c,
        )

        # 4. Kısıtlar, Likidite, Sektör, Hysteresis ve Rejim Filtresi
        final_weights, cash_weight = self._apply_comprehensive_constraints(
            raw_weights=raw_weights,
            tickers=tickers,
            current_weights=current_weights or {},
            sector_map=sector_map or {},
            liquidity_scores=liquidity_scores or {},
            regime=regime,
            constraints=c,
            warnings=warnings,
        )

        # 5. Portföy Metriklerinin Hesaplanması
        w_vec = np.array([final_weights.get(t, 0.0) for t in tickers])
        invested_weight = float(np.sum(w_vec))

        if invested_weight > 1e-6:
            port_vol = float(np.sqrt(w_vec.T @ cov_matrix @ w_vec) * np.sqrt(252.0))
            port_ret = float(np.dot(w_vec, expected_returns))
            sharpe = (port_ret - 0.40) / port_vol if port_vol > 1e-4 else 0.0  # 40% risksiz faiz
            weighted_vols = w_vec * np.sqrt(np.diag(cov_matrix)) * np.sqrt(252.0)
            div_ratio = float(np.sum(weighted_vols) / port_vol) if port_vol > 1e-4 else 1.0
        else:
            port_vol = 0.0
            port_ret = 0.0
            sharpe = 0.0
            div_ratio = 1.0

        # Turnover ve İşlem Maliyeti
        curr_w = current_weights or {}
        all_ticks = set(final_weights.keys()) | set(curr_w.keys())
        turnover = sum(abs(final_weights.get(t, 0.0) - curr_w.get(t, 0.0)) for t in all_ticks) / 2.0
        est_cost_tl = turnover * portfolio_value * c.transaction_cost_pct * 2.0

        # Sektör dağılımı
        sector_exp: dict[str, float] = {}
        for t, w in final_weights.items():
            sec = (sector_map or {}).get(t, "OTHER")
            sector_exp[sec] = sector_exp.get(sec, 0.0) + w

        eff_positions = sum(1 for w in final_weights.values() if w >= c.min_position_pct)

        return OptimizationResult(
            weights={k: round(v, 4) for k, v in final_weights.items() if v > 0},
            method=method,
            expected_return=round(port_ret, 4),
            portfolio_volatility=round(port_vol, 4),
            sharpe_ratio=round(sharpe, 3),
            diversification_ratio=round(div_ratio, 3),
            turnover_from_current=round(turnover, 4),
            estimated_transaction_cost_tl=round(est_cost_tl, 2),
            effective_positions_count=eff_positions,
            sector_exposures={k: round(v, 4) for k, v in sector_exp.items()},
            cash_weight=round(cash_weight, 4),
            is_optimal=is_opt,
            warnings=warnings,
        )

    # =====================================================
    # HAM OPTİMİZASYON YÖNTEMLERİ
    # =====================================================
    def _solve_raw_weights(
        self,
        method: OptimizationMethod,
        tickers: list[str],
        cov_matrix: np.ndarray,
        expected_returns: np.ndarray,
        current_weights: dict[str, float] | None,
        constraints: PortfolioOptimizerConstraints,
    ) -> tuple[np.ndarray, bool]:
        """Seçilen yönteme göre ham optimal ağırlıkları hesaplar."""
        n = len(tickers)

        if method == OptimizationMethod.EQUAL_WEIGHT:
            return np.ones(n) / n, True

        elif method == OptimizationMethod.RISK_PARITY:
            return self._solve_risk_parity(cov_matrix)

        elif method == OptimizationMethod.HIERARCHICAL_RISK_PARITY:
            return self._solve_hrp(cov_matrix), True

        elif method == OptimizationMethod.MIN_VARIANCE:
            return self._solve_min_variance(cov_matrix, constraints)

        elif method == OptimizationMethod.MAX_SHARPE:
            return self._solve_mean_variance(
                cov_matrix=cov_matrix,
                expected_returns=expected_returns,
                current_weights=current_weights,
                tickers=tickers,
                constraints=constraints,
            )

        elif method == OptimizationMethod.BLACK_LITTERMAN:
            return self._solve_black_litterman(
                cov_matrix=cov_matrix,
                expected_returns=expected_returns,
                tickers=tickers,
                constraints=constraints,
            )

        return np.ones(n) / n, True

    def _solve_risk_parity(self, cov_matrix: np.ndarray) -> tuple[np.ndarray, bool]:
        """Eşit Risk Katkısı (Equal Risk Contribution — Spinu, 2013)."""
        n = cov_matrix.shape[0]
        init_w = 1.0 / np.sqrt(np.diag(cov_matrix))
        init_w = init_w / np.sum(init_w)

        def objective(w):
            w = np.maximum(w, 1e-8)
            port_var = w.T @ cov_matrix @ w
            marginal_contrib = cov_matrix @ w
            risk_contrib = w * marginal_contrib
            # Target equal risk contribution: 1/N of total variance
            target = port_var / n
            return np.sum((risk_contrib - target) ** 2)

        bounds = [(1e-5, 1.0) for _ in range(n)]
        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        res = minimize(objective, init_w, bounds=bounds, constraints=cons, method="SLSQP", options={"maxiter": 500})
        if res.success:
            w = np.maximum(res.x, 0.0)
            return w / np.sum(w), True

        # Fallback to inverse volatility
        inv_vol = 1.0 / np.sqrt(np.maximum(np.diag(cov_matrix), 1e-8))
        return inv_vol / np.sum(inv_vol), False

    def _solve_hrp(self, cov_matrix: np.ndarray) -> np.ndarray:
        """Hierarchical Risk Parity (HRP — Lopez de Prado, 2016)."""
        n = cov_matrix.shape[0]
        stds = np.sqrt(np.maximum(np.diag(cov_matrix), 1e-8))
        corr = cov_matrix / np.outer(stds, stds)
        np.fill_diagonal(corr, 1.0)
        corr = np.clip(corr, -1.0, 1.0)

        # Distance matrix d_ij = sqrt(0.5 * (1 - rho_ij))
        dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
        np.fill_diagonal(dist, 0.0)

        # Single linkage clustering
        condensed_dist = squareform(dist, checks=False)
        link = linkage(condensed_dist, method="single")

        # Quasi-diagonalization (sort items by hierarchical tree order)
        sorted_indices = self._get_quasi_diag_order(link)

        # Recursive Bisection
        weights = pd_hrp_bisection = np.ones(n)
        items = [sorted_indices]

        while len(items) > 0:
            items = [
                sub_items[j:k]
                for sub_items in items
                for j, k in ((0, len(sub_items) // 2), (len(sub_items) // 2, len(sub_items)))
                if len(sub_items) > 1
            ]
            for i in range(0, len(items), 2):
                c1 = items[i]
                c2 = items[i + 1]
                v1 = self._get_cluster_variance(cov_matrix, c1)
                v2 = self._get_cluster_variance(cov_matrix, c2)
                alpha = 1.0 - v1 / (v1 + v2) if (v1 + v2) > 1e-12 else 0.5
                weights[c1] *= alpha
                weights[c2] *= 1.0 - alpha

        return weights / np.sum(weights)

    def _get_quasi_diag_order(self, link: np.ndarray) -> list[int]:
        """Ağaç hiyerarşisi sırasını çıkarır."""
        n = link.shape[0] + 1
        order = [int(link[-1, 0]), int(link[-1, 1])]
        for i in range(link.shape[0] - 2, -1, -1):
            cluster_id = n + i
            if cluster_id in order:
                idx = order.index(cluster_id)
                left = int(link[i, 0])
                right = int(link[i, 1])
                order = order[:idx] + [left, right] + order[idx + 1 :]
        return [x for x in order if x < n]

    def _get_cluster_variance(self, cov_matrix: np.ndarray, cluster_indices: list[int]) -> float:
        """Küme varyansını Inverse-Variance Allocation ile hesaplar."""
        sub_cov = cov_matrix[np.ix_(cluster_indices, cluster_indices)]
        inv_diag = 1.0 / np.maximum(np.diag(sub_cov), 1e-8)
        w = inv_diag / np.sum(inv_diag)
        return float(w.T @ sub_cov @ w)

    def _solve_min_variance(
        self, cov_matrix: np.ndarray, constraints: PortfolioOptimizerConstraints
    ) -> tuple[np.ndarray, bool]:
        """Global Minimum Variance Portfolio."""
        n = cov_matrix.shape[0]
        init_w = np.ones(n) / n

        def objective(w):
            return w.T @ cov_matrix @ w + constraints.l2_regularization * np.sum(w**2)

        bounds = [(0.0, constraints.max_position_pct) for _ in range(n)]
        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        res = minimize(objective, init_w, bounds=bounds, constraints=cons, method="SLSQP")
        if res.success:
            w = np.maximum(res.x, 0.0)
            return w / np.sum(w), True
        return init_w, False

    def _solve_mean_variance(
        self,
        cov_matrix: np.ndarray,
        expected_returns: np.ndarray,
        current_weights: dict[str, float] | None,
        tickers: list[str],
        constraints: PortfolioOptimizerConstraints,
    ) -> tuple[np.ndarray, bool]:
        """Markowitz Max Sharpe with L2 regularizer and turnover penalty."""
        n = len(tickers)
        init_w = np.ones(n) / n
        curr_arr = (
            np.array([current_weights.get(t, 0.0) for t in tickers]) if current_weights is not None else np.zeros(n)
        )

        rf_daily = 0.40 / 252.0  # %40 yıllık risksiz faiz bazlı

        def objective(w):
            port_ret = np.dot(w, expected_returns)
            port_var = w.T @ cov_matrix @ w
            port_vol = np.sqrt(max(port_var, 1e-8))

            # Negated Sharpe
            sharpe = (port_ret - rf_daily * 252.0) / (port_vol * np.sqrt(252.0))

            # Turnover penalty
            turnover = np.sum(np.abs(w - curr_arr))
            turnover_cost = constraints.turnover_penalty_lambda * turnover

            # L2 concentration regularization
            l2 = constraints.l2_regularization * np.sum(w**2)

            return -sharpe + turnover_cost + l2

        bounds = [(0.0, constraints.max_position_pct) for _ in range(n)]
        cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        res = minimize(objective, init_w, bounds=bounds, constraints=cons, method="SLSQP", options={"maxiter": 500})
        if res.success:
            w = np.maximum(res.x, 0.0)
            return w / np.sum(w), True
        return init_w, False

    def _solve_black_litterman(
        self,
        cov_matrix: np.ndarray,
        expected_returns: np.ndarray,
        tickers: list[str],
        constraints: PortfolioOptimizerConstraints,
        tau: float = 0.05,
    ) -> tuple[np.ndarray, bool]:
        """Black-Litterman Model Integration with Model Ranking Views."""
        n = len(tickers)
        # Equilibrium prior Pi = delta * Sigma * w_eq
        w_eq = np.ones(n) / n
        delta = 2.5
        pi = delta * cov_matrix @ w_eq

        # Identity view matrix P (each asset has an absolute view from expected_returns)
        P = np.eye(n)
        Q = expected_returns / 252.0  # Daily view returns

        # View uncertainty Omega = tau * diag(P * Sigma * P^T)
        Omega = np.diag(np.diag(tau * P @ cov_matrix @ P.T))

        # Posterior return E[R] = [(tau*Sigma)^-1 + P^T * Omega^-1 * P]^-1 * [(tau*Sigma)^-1 * pi + P^T * Omega^-1 * Q]
        tau_cov_inv = np.linalg.pinv(tau * cov_matrix)
        omega_inv = np.linalg.pinv(Omega)

        M = np.linalg.pinv(tau_cov_inv + P.T @ omega_inv @ P)
        post_ret = M @ (tau_cov_inv @ pi + P.T @ omega_inv @ Q) * 252.0

        return self._solve_mean_variance(
            cov_matrix=cov_matrix,
            expected_returns=post_ret,
            current_weights=None,
            tickers=tickers,
            constraints=constraints,
        )

    # =====================================================
    # KAPSAMLI KISIT VE SÜRTÜNME MOTORU
    # =====================================================
    def _apply_comprehensive_constraints(
        self,
        raw_weights: np.ndarray,
        tickers: list[str],
        current_weights: dict[str, float],
        sector_map: dict[str, str],
        liquidity_scores: dict[str, float],
        regime: str,
        constraints: PortfolioOptimizerConstraints,
        warnings: list[str],
    ) -> tuple[dict[str, float], float]:
        """Optimizasyon sonrası gerçekçi kısıtları, sürtünmeleri ve rejim maruziyetini uygular."""
        weights = {tickers[i]: float(raw_weights[i]) for i in range(len(tickers))}

        # 1. Likidite Haircut Uygulaması (Likidite puanı düşük hisseleri kırp)
        for t in list(weights.keys()):
            l_score = liquidity_scores.get(t, 75.0)
            if l_score < 40.0:
                haircut = max(0.20, l_score / 50.0)
                weights[t] *= haircut
                warnings.append(f"{t} düşük likidite nedeniyle %{round((1-haircut)*100, 1)} küçültüldü.")

        # 2. Tozluluk / Minimum Pozisyon Filtresi (Küçük kalıntıları sıfırla)
        for t in list(weights.keys()):
            if weights[t] < constraints.min_position_pct:
                weights[t] = 0.0

        # 3. Tekil Pozisyon Üst Limiti (%10 Tavan)
        for t in list(weights.keys()):
            weights[t] = min(weights[t], constraints.max_position_pct)

        # 4. Sektör Konsantrasyonu Tavanı (%30 Sınırı)
        sector_totals: dict[str, float] = {}
        for t, w in weights.items():
            sec = sector_map.get(t, "OTHER")
            sector_totals[sec] = sector_totals.get(sec, 0.0) + w

        for sec, total in sector_totals.items():
            if total > constraints.max_sector_pct and total > 0:
                scale = constraints.max_sector_pct / total
                for t in weights:
                    if sector_map.get(t, "OTHER") == sec:
                        weights[t] *= scale
                warnings.append(f"{sec} sektörü %{round(total*100, 1)} tavanı aştı, %30'a sıkıştırıldı.")

        # 5. Hysteresis (Mevcut ağırlıktan fark %2'nin altındaysa mevcut ağırlığı koru)
        if current_weights:
            for t in list(weights.keys()):
                curr = current_weights.get(t, 0.0)
                if abs(weights[t] - curr) < constraints.hysteresis_threshold:
                    weights[t] = curr

        # 6. Rejime Göre Toplam Maruziyet (Exposure Cap & Cash Buffer)
        regime_exposure_caps = {
            "BULL": 0.95,  # %95 hisse, %5 nakit
            "SIDEWAYS": 0.80,  # %80 hisse, %20 nakit
            "BEAR": 0.45,  # %45 hisse, %55 nakit
            "CRISIS": 0.15,  # %15 hisse, %85 nakit
        }
        max_allowed_exp = regime_exposure_caps.get(regime.upper(), 0.80)
        max_allowed_exp = min(max_allowed_exp, 1.0 - constraints.min_cash_buffer_pct)

        total_weight = sum(weights.values())
        if total_weight > max_allowed_exp and total_weight > 0:
            scale = max_allowed_exp / total_weight
            weights = {k: v * scale for k, v in weights.items()}
            warnings.append(f"Piyasa rejimi [{regime}] maruziyet tavanı (%{round(max_allowed_exp*100)}) uygulandı.")

        # Final temizleme ve nakit oranı
        clean_weights = {k: float(v) for k, v in weights.items() if v >= constraints.min_position_pct}
        total_invested = sum(clean_weights.values())
        cash_weight = max(0.0, 1.0 - total_invested)

        return clean_weights, cash_weight

    def _empty_result(self, method: OptimizationMethod, warnings: list[str]) -> OptimizationResult:
        return OptimizationResult(
            weights={},
            method=method,
            expected_return=0.0,
            portfolio_volatility=0.0,
            sharpe_ratio=0.0,
            diversification_ratio=0.0,
            turnover_from_current=0.0,
            estimated_transaction_cost_tl=0.0,
            effective_positions_count=0,
            sector_exposures={},
            cash_weight=1.0,
            is_optimal=False,
            warnings=warnings,
        )


# Singleton
portfolio_optimizer = PortfolioOptimizer()
