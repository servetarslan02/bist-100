"""
ALPHA BIST — VaR/CVaR Risk Metrics v1.0

Value at Risk (VaR) ve Conditional VaR (CVaR) hesaplama.
3 yöntem: Parametrik, Tarihsel, Monte Carlo.

Ek metrikler: Component VaR, Marginal VaR, VaR-based position limit.

Kaynaklar:
- CFA Institute — Measuring and Managing Market Risk (2026)
- ScienceDirect — Integrated Risk Management Framework (2026)
- arXiv 2605.19337 — Agentic Trading Meta-Analiz (2026)
"""

import numpy as np
import math
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import structlog

logger = structlog.get_logger()


class VaRMethod(str, Enum):
    PARAMETRIC = "parametric"
    HISTORICAL = "historical"
    MONTE_CARLO = "monte_carlo"


@dataclass
class VaRResult:
    """VaR/CVaR hesaplama sonucu."""
    var_95: float           # %95 güven VaR
    var_99: float           # %99 güven VaR
    cvar_95: float          # %95 CVaR (Expected Shortfall)
    cvar_99: float          # %99 CVaR
    method: str             # Kullanılan yöntem
    sample_size: int        # Örneklem büyüklüğü
    portfolio_value: float  # Portföy değeri
    var_95_amount: float    # %95 VaR (TL)
    var_99_amount: float    # %99 VaR (TL)
    cvar_95_amount: float   # %95 CVaR (TL)
    cvar_99_amount: float   # %99 CVaR (TL)


@dataclass
class ComponentVaRResult:
    """Component VaR sonucu."""
    ticker: str
    weight: float
    component_var_95: float     # Bu pozisyonun portföy VaR'ına katkısı
    marginal_var_95: float      # Yeni pozisyon eklenince risk değişimi
    pct_of_total_var: float     # Toplam VaR'ın yüzdesi


@dataclass
class MonteCarloResult:
    """Monte Carlo simülasyon sonucu."""
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    mean_return: float
    std_return: float
    worst_case: float
    best_case: float
    n_simulations: int
    n_days: int
    percentiles: Dict[int, float]  # percentile → return


class VaRCalculator:
    """VaR/CVaR hesaplama motoru.

    3 yöntem destekler:
    1. Parametrik (Normal dağılım varsayımı)
    2. Tarihsel (Dağılım varsayımı yok)
    3. Monte Carlo (Stokastik simülasyon)
    """

    def __init__(self, trading_days_per_year: int = 252):
        self.trading_days_per_year = trading_days_per_year

    @staticmethod
    def _historical_percentile_index(confidence: float, n: int) -> int:
        """Tarihsel VaR/CVaR için sıralı dizideki eşik indeksini hesaplar.

        'Nearest-rank' yöntemi kullanılır: seçilen eşiğin altında/eşit
        kalan veri oranı HER ZAMAN hedef (1-confidence) oranına eşit
        veya üstünde olur — yani risk hiçbir zaman olduğundan az
        gösterilmez (documentation/06 — 'hayatta kalma birincil' ilkesi).

        Kayan nokta hassasiyeti (örn. (1-0.95)*20 tam 1.0 değil,
        1.0000000000000009 çıkabilir) yüzünden yanlış yuvarlamayı
        önlemek için küçük bir epsilon toleransı kullanılır.
        """
        if n <= 0:
            return 0
        x = (1 - confidence) * n
        idx = math.ceil(x - 1e-9) - 1
        return max(0, min(idx, n - 1))

    # =====================================================
    # 1. PARAMETRİK VaR/CVaR
    # =====================================================

    def calculate_parametric_var(
        self,
        returns: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
        holding_period_days: int = 1,
    ) -> float:
        """Parametrik VaR (Normal dağılım varsayımı).

        VaR = max(0, -(μt + σ × z_(1-α) × √t)) × V

        Args:
            returns: Günlük getiri dizisi
            confidence: Güven seviyesi (0.95 veya 0.99)
            portfolio_value: Portföy değeri (TL)
            holding_period_days: Tutma süresi (gün)

        Returns:
            VaR (pozitif değer, TL)
        """
        if len(returns) < 2 or holding_period_days < 1:
            return 0.0

        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))

        if sigma <= 0:
            return float(max(0.0, -mu * holding_period_days * portfolio_value))

        try:
            from scipy.stats import norm
            z_alpha = float(norm.ppf(1 - confidence))
        except (ImportError, Exception):
            if confidence >= 0.99:
                z_alpha = -2.326348
            elif confidence >= 0.95:
                z_alpha = -1.644853
            elif confidence >= 0.90:
                z_alpha = -1.281552
            else:
                z_alpha = -1.644853

        horizon_quantile = mu * holding_period_days + sigma * z_alpha * np.sqrt(holding_period_days)
        var_amount = max(0.0, -horizon_quantile * portfolio_value)

        return float(var_amount)

    def calculate_parametric_cvar(
        self,
        returns: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
        holding_period_days: int = 1,
    ) -> float:
        """Parametrik CVaR (Normal dağılım — Expected Shortfall).

        CVaR = max(0, -(μt - σ × φ(z_(1-α)) × √t / (1-α))) × V

        Args:
            returns: Günlük getiri dizisi
            confidence: Güven seviyesi
            portfolio_value: Portföy değeri
            holding_period_days: Tutma süresi

        Returns:
            CVaR (pozitif değer, TL)
        """
        if len(returns) < 2 or holding_period_days < 1:
            return 0.0

        mu = np.mean(returns)
        sigma = np.std(returns, ddof=1)

        if sigma <= 0:
            return float(max(0.0, -mu * holding_period_days * portfolio_value))

        try:
            from scipy.stats import norm
            z_alpha = float(norm.ppf(1 - confidence))
            phi_z = float(norm.pdf(z_alpha))
        except (ImportError, Exception):
            if confidence >= 0.99:
                z_alpha = -2.326348
            elif confidence >= 0.95:
                z_alpha = -1.644853
            elif confidence >= 0.90:
                z_alpha = -1.281552
            else:
                z_alpha = -1.644853
            phi_z = (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z_alpha * z_alpha)

        tail_mean = (
            mu * holding_period_days
            - sigma * np.sqrt(holding_period_days) * phi_z / (1 - confidence)
        )
        cvar_amount = max(0.0, -tail_mean * portfolio_value)

        return float(cvar_amount)

    # =====================================================
    # 2. TARİHSEL VaR/CVaR
    # =====================================================

    def calculate_historical_var(
        self,
        returns: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
        holding_period_days: int = 1,
    ) -> float:
        """Tarihsel VaR (Dağılım varsayımı yok).

        En kötü (1-confidence) getirilerin yüzdelik değeri.

        Args:
            returns: Günlük getiri dizisi
            confidence: Güven seviyesi
            portfolio_value: Portföy değeri
            holding_period_days: Tutma süresi (basit √t scaling)

        Returns:
            VaR (pozitif değer, TL)
        """
        if len(returns) < 10:
            return 0.0

        sorted_returns = np.sort(returns)
        index = self._historical_percentile_index(confidence, len(sorted_returns))

        # Do not turn an all-positive return history into a loss with abs().
        var_pct = max(0.0, -float(sorted_returns[index]))
        var_amount = var_pct * portfolio_value * np.sqrt(holding_period_days)

        return float(var_amount)

    def calculate_historical_cvar(
        self,
        returns: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
        holding_period_days: int = 1,
    ) -> float:
        """Tarihsel CVaR (Expected Shortfall).

        VaR'ı aşan kayıpların ortalaması.

        Args:
            returns: Günlük getiri dizisi
            confidence: Güven seviyesi
            portfolio_value: Portföy değeri
            holding_period_days: Tutma süresi

        Returns:
            CVaR (pozitif değer, TL)
        """
        if len(returns) < 10:
            return 0.0

        sorted_returns = np.sort(returns)
        index = self._historical_percentile_index(confidence, len(sorted_returns))

        var_threshold = float(sorted_returns[index])
        if var_threshold >= 0:
            return 0.0

        tail_returns = sorted_returns[sorted_returns <= var_threshold]

        if len(tail_returns) == 0:
            return abs(float(var_threshold)) * portfolio_value * np.sqrt(holding_period_days)

        cvar_pct = max(0.0, -float(np.mean(tail_returns)))
        cvar_amount = cvar_pct * portfolio_value * np.sqrt(holding_period_days)

        return float(cvar_amount)

    # =====================================================
    # 3. MONTE CARLO VaR/CVaR
    # =====================================================

    def calculate_monte_carlo_var(
        self,
        returns: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
        n_simulations: int = 10000,
        holding_period_days: int = 1,
        seed: Optional[int] = None,
    ) -> MonteCarloResult:
        """Monte Carlo VaR simülasyonu.

        Geçmiş getiri dağılımından rastgele örnekleme ile
        gelecek getiri dağılımını simüle eder.

        Args:
            returns: Günlük getiri dizisi
            confidence: Güven seviyesi
            portfolio_value: Portföy değeri
            n_simulations: Simülasyon sayısı
            holding_period_days: Tutma süresi
            seed: Rastgele tohum (reproducibility için)

        Returns:
            MonteCarloResult
        """
        if seed is not None:
            rng = np.random.default_rng(seed)
        else:
            rng = np.random.default_rng()

        if len(returns) < 2 or holding_period_days < 1:
            return MonteCarloResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                    n_simulations, holding_period_days, {})

        mu = np.mean(returns)
        sigma = np.std(returns, ddof=1)

        # GPU / CUDA Hızlandırmalı Stokastik Simülasyon (NumPy fallback ile)
        simulated_returns = None
        try:
            import torch
            if torch.cuda.is_available():
                if sigma <= 0:
                    simulated_returns = np.full(n_simulations, mu * holding_period_days)
                else:
                    mean_val = float(mu * holding_period_days)
                    std_val = float(sigma * np.sqrt(holding_period_days))
                    t_samples = torch.normal(mean=mean_val, std=std_val, size=(n_simulations,), device='cuda')
                    simulated_returns = t_samples.cpu().numpy()
        except Exception:
            logger.warning("Caught Exception in calculate_monte_carlo_var", exc_info=True)

        if simulated_returns is None:
            if sigma <= 0:
                simulated_returns = np.full(n_simulations, mu * holding_period_days)
            else:
                simulated_returns = rng.normal(
                    mu * holding_period_days,
                    sigma * np.sqrt(holding_period_days),
                    n_simulations,
                )

        # VaR/CVaR hesapla
        q_95 = float(np.percentile(simulated_returns, 5))
        q_99 = float(np.percentile(simulated_returns, 1))
        var_95 = max(0.0, -q_95)
        var_99 = max(0.0, -q_99)

        # CVaR: VaR'ı aşan kayıpların ortalaması
        tail_95 = simulated_returns[simulated_returns <= q_95]
        cvar_95 = max(0.0, -float(np.mean(tail_95))) if len(tail_95) > 0 else var_95

        tail_99 = simulated_returns[simulated_returns <= q_99]
        cvar_99 = max(0.0, -float(np.mean(tail_99))) if len(tail_99) > 0 else var_99

        # Percentiles
        percentiles = {
            1: float(np.percentile(simulated_returns, 1)),
            5: float(np.percentile(simulated_returns, 5)),
            10: float(np.percentile(simulated_returns, 10)),
            25: float(np.percentile(simulated_returns, 25)),
            50: float(np.percentile(simulated_returns, 50)),
            75: float(np.percentile(simulated_returns, 75)),
            90: float(np.percentile(simulated_returns, 90)),
            95: float(np.percentile(simulated_returns, 95)),
            99: float(np.percentile(simulated_returns, 99)),
        }

        return MonteCarloResult(
            var_95=var_95 * portfolio_value,
            var_99=var_99 * portfolio_value,
            cvar_95=cvar_95 * portfolio_value,
            cvar_99=cvar_99 * portfolio_value,
            mean_return=float(np.mean(simulated_returns)),
            std_return=float(np.std(simulated_returns)),
            worst_case=float(np.min(simulated_returns)) * portfolio_value,
            best_case=float(np.max(simulated_returns)) * portfolio_value,
            n_simulations=n_simulations,
            n_days=holding_period_days,
            percentiles={k: v * portfolio_value for k, v in percentiles.items()},
        )

    # =====================================================
    # 4. COMPONENT VaR ve MARGINAL VaR
    # =====================================================

    def calculate_component_var(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
        tickers: Optional[List[str]] = None,
    ) -> List[ComponentVaRResult]:
        """Component VaR — her pozisyonun portföy VaR'ına katkısı.

        Component VaR_i = w_i × (Σw)_i / σ_p × z_α × portfolio_value

        Args:
            weights: Pozisyon ağırlıkları (n_assets,)
            cov_matrix: Kovaryans matrisi (n_assets × n_assets)
            confidence: Güven seviyesi
            portfolio_value: Portföy değeri
            tickers: Hisse kodları

        Returns:
            ComponentVaRResult listesi
        """
        try:
            from scipy.stats import norm
            z_alpha = float(norm.ppf(confidence))
        except ImportError:
            # scipy yoksa sabit z-skorları kullan
            z_map = {0.90: 1.281552, 0.95: 1.644853, 0.99: 2.326348}
            z_alpha = z_map.get(round(confidence, 2), 1.644853)

        portfolio_vol = np.sqrt(weights @ cov_matrix @ weights)
        if portfolio_vol <= 0:
            return []
        marginal_var = cov_matrix @ weights / portfolio_vol * z_alpha
        component_var = weights * marginal_var

        results = []
        for i in range(len(weights)):
            ticker = tickers[i] if tickers and i < len(tickers) else f"asset_{i}"
            results.append(ComponentVaRResult(
                ticker=ticker,
                weight=float(weights[i]),
                component_var_95=float(component_var[i] * portfolio_value),
                marginal_var_95=float(marginal_var[i] * portfolio_value),
                pct_of_total_var=float(component_var[i] / np.sum(np.abs(component_var)) * 100)
                if np.sum(np.abs(component_var)) > 0 else 0.0,
            ))

        return results

    def calculate_marginal_var(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
        confidence: float = 0.95,
        portfolio_value: float = 100000.0,
    ) -> np.ndarray:
        """Marginal VaR — yeni pozisyon eklenince risk değişimi.

        MVaR_i = (Σw)_i / σ_p × z_α × portfolio_value
        """
        try:
            from scipy.stats import norm
            z_alpha = float(norm.ppf(confidence))
        except ImportError:
            # Fallback: invert normal CDF via math.erf
            # z = sqrt(2) * erfinv(2*p - 1), erfinv approximated by series
            p = confidence
            # Rational approximation (Abramowitz & Stegun 26.2.23)
            if p <= 0 or p >= 1:
                z_alpha = 0.0
            else:
                t = math.sqrt(-2.0 * math.log(1.0 - p))
                c0, c1, c2 = 2.515517, 0.802853, 0.010328
                d1, d2, d3 = 1.432788, 0.189269, 0.001308
                z_alpha = t - (c0 + c1*t + c2*t*t) / (1.0 + d1*t + d2*t*t + d3*t*t*t)

        portfolio_vol = np.sqrt(weights @ cov_matrix @ weights)
        if portfolio_vol <= 0:
            return np.zeros(len(weights))

        return cov_matrix @ weights / portfolio_vol * z_alpha * portfolio_value

    # =====================================================
    # 5. KAPSAMLI RİSK RAPORU
    # =====================================================

    def calculate_full_var_report(
        self,
        returns: np.ndarray,
        portfolio_value: float = 100000.0,
        holding_period_days: int = 1,
        weights: Optional[np.ndarray] = None,
        cov_matrix: Optional[np.ndarray] = None,
        tickers: Optional[List[str]] = None,
        n_monte_carlo: int = 10000,
    ) -> Dict[str, Any]:
        """Kapsamlı VaR/CVaR raporu — tüm yöntemler.

        Args:
            returns: Günlük getiri dizisi
            portfolio_value: Portföy değeri
            holding_period_days: Tutma süresi
            weights: Pozisyon ağırlıkları (opsiyonel)
            cov_matrix: Kovaryans matrisi (opsiyonel)
            tickers: Hisse kodları (opsiyonel)
            n_monte_carlo: Monte Carlo simülasyon sayısı

        Returns:
            Kapsamlı risk raporu
        """
        report = {
            "portfolio_value": portfolio_value,
            "holding_period_days": holding_period_days,
            "sample_size": len(returns),
            "mean_daily_return": float(np.mean(returns)),
            "daily_volatility": float(np.std(returns, ddof=1)),
            "annualized_volatility": float(np.std(returns, ddof=1) * np.sqrt(self.trading_days_per_year)),
        }

        # Parametrik VaR/CVaR
        report["parametric"] = {
            "var_95": self.calculate_parametric_var(returns, 0.95, portfolio_value, holding_period_days),
            "var_99": self.calculate_parametric_var(returns, 0.99, portfolio_value, holding_period_days),
            "cvar_95": self.calculate_parametric_cvar(returns, 0.95, portfolio_value, holding_period_days),
            "cvar_99": self.calculate_parametric_cvar(returns, 0.99, portfolio_value, holding_period_days),
        }

        # Tarihsel VaR/CVaR
        report["historical"] = {
            "var_95": self.calculate_historical_var(returns, 0.95, portfolio_value, holding_period_days),
            "var_99": self.calculate_historical_var(returns, 0.99, portfolio_value, holding_period_days),
            "cvar_95": self.calculate_historical_cvar(returns, 0.95, portfolio_value, holding_period_days),
            "cvar_99": self.calculate_historical_cvar(returns, 0.99, portfolio_value, holding_period_days),
        }

        # Monte Carlo VaR/CVaR
        mc_result = self.calculate_monte_carlo_var(
            returns, 0.95, portfolio_value, n_monte_carlo, holding_period_days
        )
        report["monte_carlo"] = {
            "var_95": mc_result.var_95,
            "var_99": mc_result.var_99,
            "cvar_95": mc_result.cvar_95,
            "cvar_99": mc_result.cvar_99,
            "worst_case": mc_result.worst_case,
            "best_case": mc_result.best_case,
            "n_simulations": n_monte_carlo,
        }

        # Component VaR (eğer ağırlıklar ve kovaryans verilmişse)
        if weights is not None and cov_matrix is not None:
            component_var = self.calculate_component_var(
                weights, cov_matrix, 0.95, portfolio_value, tickers
            )
            report["component_var"] = [
                {
                    "ticker": cv.ticker,
                    "weight": cv.weight,
                    "component_var_95": cv.component_var_95,
                    "pct_of_total_var": cv.pct_of_total_var,
                }
                for cv in component_var
            ]

        # Konsensüs VaR (3 yöntemin ortalaması)
        var_95_values = [
            report["parametric"]["var_95"],
            report["historical"]["var_95"],
            report["monte_carlo"]["var_95"],
        ]
        report["consensus"] = {
            "var_95": float(np.mean(var_95_values)),
            "var_95_min": float(np.min(var_95_values)),
            "var_95_max": float(np.max(var_95_values)),
            "method_agreement": float(1 - np.std(var_95_values) / np.mean(var_95_values))
            if np.mean(var_95_values) > 0 else 0.0,
        }

        logger.info("VaR report generated",
                    var_95_consensus=round(report["consensus"]["var_95"], 2),
                    portfolio_value=portfolio_value)

        return report

    # =====================================================
    # 6. VaR-BASED POZİSYON LİMİTİ
    # =====================================================

    def calculate_var_based_position_limit(
        self,
        returns: np.ndarray,
        max_var_pct: float = 5.0,
        portfolio_value: float = 100000.0,
        confidence: float = 0.95,
    ) -> float:
        """VaR bazlı pozisyon limiti.

        Belirli bir VaR hedefine göre maksimum pozisyon boyutu.

        Args:
            returns: Hisse getiri dizisi
            max_var_pct: Maksimum VaR yüzdesi (portföyün %'si)
            portfolio_value: Portföy değeri
            confidence: Güven seviyesi

        Returns:
            Maksimum pozisyon değeri (TL)
        """
        from scipy.stats import norm

        sigma = np.std(returns, ddof=1)
        if sigma <= 0:
            return portfolio_value * (max_var_pct / 100)

        z_alpha = norm.ppf(confidence)
        max_loss_pct = max_var_pct / 100
        max_position_pct = max_loss_pct / (sigma * z_alpha)
        max_position_pct = min(max_position_pct, 1.0)  # Max %100

        return float(max_position_pct * portfolio_value)


# Singleton
var_calculator = VaRCalculator()
