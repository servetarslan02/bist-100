"""
ALPHA BIST — Faktör Bazlı Portföy Optimizasyon Motoru

Fama-French 5 faktör modelinden ilham alınarak BIST'e özelleştirilmiş
çok faktörlü portföy yapım ve optimizasyon motoru.

Faktörler:
  - Momentum (MOM): 12-1 ay getiri
  - Value (VAL): P/B, P/E oranı bazlı ucuzluk
  - Quality (QUA): ROE, düşük borç, kar kararlılığı
  - Low Volatility (LVOL): Gerçekleşen volatilite tersine
  - Size (SIZ): Piyasa değeri inversine (küçük > büyük premium)
  - Liquidity (LIQ): ADV/Piyasa değeri

Optimizasyon:
  - Mean-Variance (Markowitz)
  - Eşit Ağırlık (Equal Weight — güçlü benchmark)
  - Risk Parite (Risk Parity — volatilite normalize)
  - Faktör-ağırlıklı (Factor-Weighted — faktör skora orantılı)
  - Maximum Diversification
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DEFAULT_LOOKBACK: int = 252          # Kovaryans penceresi (1 yıl)
DEFAULT_N_ASSETS: int = 30           # Varsayılan portföy büyüklüğü
MAX_WEIGHT: float = 0.10             # Maksimum tekil hisse ağırlığı
MIN_WEIGHT: float = 0.005            # Minimum tekil hisse ağırlığı (0.5%)
REGULARIZATION: float = 1e-5        # Kovaryans matris düzeltmesi
BIST_SECTOR_LIMIT: float = 0.30      # Tek sektöre maksimum ağırlık
FACTOR_NAMES: list[str] = ["momentum", "value", "quality", "low_vol", "size", "liquidity"]

# Faktör yükleme ağırlıkları (BIST'e özgü tarihsel çalışmalar baz alınarak)
DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    "momentum": 0.25,
    "value": 0.20,
    "quality": 0.20,
    "low_vol": 0.15,
    "size": 0.10,
    "liquidity": 0.10,
}


class PortfolioMethod(Enum):
    """Portföy yapım yöntemi.

    Attributes:
        EQUAL_WEIGHT: Eşit ağırlık dağılımı.
        MEAN_VARIANCE: Markowitz mean-variance optimizasyonu.
        RISK_PARITY: Risk parite (volatilite eşitleme).
        FACTOR_WEIGHTED: Faktör skora orantılı ağırlık.
        MAX_DIVERSIFICATION: Maksimum çeşitlendirme oranı.
    """

    EQUAL_WEIGHT = auto()
    MEAN_VARIANCE = auto()
    RISK_PARITY = auto()
    FACTOR_WEIGHTED = auto()
    MAX_DIVERSIFICATION = auto()


@dataclass
class FactorScores:
    """Tekil hisse için faktör skorları (0-100, yüksek = çekici).

    Attributes:
        ticker: Hisse senedi kodu.
        momentum: Momentum skoru.
        value: Değer skoru.
        quality: Kalite skoru.
        low_vol: Düşük volatilite skoru.
        size: Büyüklük skoru (küçük = yüksek skor).
        liquidity: Likidite skoru.
        composite: Ağırlıklı bileşik faktör skoru.
    """

    ticker: str
    momentum: float = 50.0
    value: float = 50.0
    quality: float = 50.0
    low_vol: float = 50.0
    size: float = 50.0
    liquidity: float = 50.0
    composite: float = 50.0

    def __repr__(self) -> str:
        """FactorScores kısa temsili."""
        return (
            f"FactorScores({self.ticker}, "
            f"MOM={self.momentum:.1f}, VAL={self.value:.1f}, "
            f"QUA={self.quality:.1f}, composite={self.composite:.1f})"
        )


@dataclass
class PortfolioWeights:
    """Portföy ağırlık sonucu.

    Attributes:
        method: Kullanılan optimizasyon yöntemi.
        weights: {ticker: ağırlık} sözlüğü.
        expected_return: Beklenen portföy getirisi (yıllık).
        expected_volatility: Beklenen portföy volatilitesi (yıllık).
        sharpe_ratio: Tahmini Sharpe oranı.
        diversification_ratio: Çeşitlendirme oranı (port vol / ağırlıklı bireysel vol ortalaması).
        factor_exposures: Portföy faktör yüklemeleri.
        n_assets: Portföydeki hisse sayısı.
    """

    method: PortfolioMethod
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    diversification_ratio: float
    factor_exposures: dict[str, float] = field(default_factory=dict)
    n_assets: int = 0

    def __repr__(self) -> str:
        """PortfolioWeights kısa temsili."""
        return (
            f"PortfolioWeights({self.method.name}, "
            f"n={self.n_assets}, "
            f"E[ret]={self.expected_return:.2%}, "
            f"vol={self.expected_volatility:.2%}, "
            f"Sharpe={self.sharpe_ratio:.2f})"
        )


class FactorScoreCalculator:
    """BIST hisseleri için faktör skoru hesaplama motoru.

    Her faktörü 0-100 arasına normalleştirir (cross-sectional rank).
    Bileşik skor ağırlıklı ortalama ile hesaplanır.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        """FactorScoreCalculator başlatıcı.

        Args:
            weights: Faktör ağırlıkları (None ise DEFAULT_FACTOR_WEIGHTS).
        """
        self.weights = weights or DEFAULT_FACTOR_WEIGHTS.copy()

    def __repr__(self) -> str:
        """FactorScoreCalculator kısa temsili."""
        return f"FactorScoreCalculator(weights={self.weights})"

    @staticmethod
    def _cross_sectional_rank(values: np.ndarray) -> np.ndarray:
        """Kesitsel sıralama ile 0-100 normalleştirme.

        Args:
            values: Hisse bazlı faktör değerleri dizisi.

        Returns:
            0-100 arası normalleştirilmiş rank skoru.
        """
        n = len(values)
        if n == 0:
            return np.array([])
        valid_mask = ~np.isnan(values)
        ranks = np.full(n, 50.0)  # NaN için medyan (50)
        if valid_mask.sum() > 0:
            temp = np.zeros(n)
            temp[valid_mask] = values[valid_mask]
            sorted_idx = np.argsort(temp[valid_mask])
            rank_vals = np.linspace(0, 100, valid_mask.sum())
            full_ranks = np.full(n, 50.0)
            full_ranks[np.where(valid_mask)[0][sorted_idx]] = rank_vals
            ranks = full_ranks
        return ranks

    def compute(
        self,
        tickers: list[str],
        returns_12m: np.ndarray,
        returns_1m: np.ndarray,
        pb_ratios: np.ndarray,
        roe: np.ndarray,
        volatility_1y: np.ndarray,
        market_cap: np.ndarray,
        adv: np.ndarray,
    ) -> list[FactorScores]:
        """Tüm hisseler için faktör skorlarını hesaplar.

        Args:
            tickers: Hisse senedi kodu listesi.
            returns_12m: 12 aylık toplam getiri (momentum proxy).
            returns_1m: Son 1 aylık getiri (reversal sinyal — momentum'dan çıkarılır).
            pb_ratios: P/B oranları (düşük = değer hissesi).
            roe: Return on Equity (kalite proxy).
            volatility_1y: 1 yıllık gerçekleşen volatilite.
            market_cap: Piyasa değeri (TL).
            adv: Ortalama günlük hacim (TL).

        Returns:
            Faktör skorları listesi (tickers sırasına göre).

        Raises:
            ValueError: Dizi uzunlukları uyuşmuyorsa.
        """
        n = len(tickers)
        for name, arr in [("returns_12m", returns_12m), ("pb_ratios", pb_ratios),
                          ("roe", roe), ("volatility_1y", volatility_1y),
                          ("market_cap", market_cap), ("adv", adv)]:
            if len(arr) != n:
                raise ValueError(f"{name} uzunluğu ({len(arr)}) tickers ({n}) ile eşleşmeli.")

        # Faktör hesaplama (yüksek skor = daha çekici)
        # Momentum: 12m - 1m (reversal kontrolü)
        mom_raw = returns_12m - returns_1m
        mom_scores = self._cross_sectional_rank(mom_raw)

        # Value: P/B düşük = değer hissesi → ters sıralama
        val_raw = -pb_ratios  # Negatif P/B → düşük P/B → yüksek skor
        val_scores = self._cross_sectional_rank(val_raw)

        # Quality: ROE yüksek = kalite hissesi
        qua_scores = self._cross_sectional_rank(roe)

        # Low Volatility: düşük vol = yüksek skor → ters sıralama
        lvol_scores = self._cross_sectional_rank(-volatility_1y)

        # Size: küçük piyasa değeri = yüksek skor → ters sıralama
        siz_scores = self._cross_sectional_rank(-market_cap)

        # Liquidity: yüksek ADV/piyasa değeri = daha likit
        liq_raw = np.where(market_cap > 0, adv / np.maximum(market_cap, 1.0), np.nan)
        liq_scores = self._cross_sectional_rank(liq_raw)

        result: list[FactorScores] = []
        for i, ticker in enumerate(tickers):
            composite = (
                mom_scores[i] * self.weights.get("momentum", 0.0)
                + val_scores[i] * self.weights.get("value", 0.0)
                + qua_scores[i] * self.weights.get("quality", 0.0)
                + lvol_scores[i] * self.weights.get("low_vol", 0.0)
                + siz_scores[i] * self.weights.get("size", 0.0)
                + liq_scores[i] * self.weights.get("liquidity", 0.0)
            )
            total_w = sum(self.weights.values())
            composite = composite / max(total_w, 1e-10)

            result.append(FactorScores(
                ticker=ticker,
                momentum=float(mom_scores[i]),
                value=float(val_scores[i]),
                quality=float(qua_scores[i]),
                low_vol=float(lvol_scores[i]),
                size=float(siz_scores[i]),
                liquidity=float(liq_scores[i]),
                composite=float(composite),
            ))

        return result


class FactorPortfolioOptimizer:
    """Faktör bazlı portföy optimizasyon motoru (thread-safe).

    Birden fazla optimizasyon yöntemi destekler. Kovaryans tahmini
    Ledoit-Wolf benzeri shrinkage ile stabilize edilir.
    """

    def __init__(
        self,
        max_weight: float = MAX_WEIGHT,
        min_weight: float = MIN_WEIGHT,
        risk_free_rate: float = 0.30,
        regularization: float = REGULARIZATION,
    ) -> None:
        """FactorPortfolioOptimizer başlatıcı.

        Args:
            max_weight: Maksimum tekil hisse ağırlığı.
            min_weight: Minimum tekil hisse ağırlığı.
            risk_free_rate: Risksiz faiz oranı (Sharpe hesabı için).
            regularization: Kovaryans matris regularizasyon katsayısı.

        Raises:
            ValueError: Parametreler geçersizse.
        """
        if not (0.0 < min_weight < max_weight <= 1.0):
            raise ValueError(
                f"0 < min_weight < max_weight <= 1.0 olmalıdır: {min_weight}, {max_weight}"
            )

        self.max_weight = max_weight
        self.min_weight = min_weight
        self.risk_free_rate = risk_free_rate
        self.regularization = regularization
        self._factor_calc = FactorScoreCalculator()
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        """FactorPortfolioOptimizer kısa temsili."""
        return (
            f"FactorPortfolioOptimizer("
            f"max_w={self.max_weight:.1%}, min_w={self.min_weight:.1%}, "
            f"rf={self.risk_free_rate:.2%})"
        )

    def _estimate_covariance(self, returns_matrix: np.ndarray) -> np.ndarray:
        """Ledoit-Wolf shrinkage ile kovaryans tahmini.

        Args:
            returns_matrix: (T, N) boyutlu getiri matrisi.

        Returns:
            (N, N) boyutlu regularize kovaryans matrisi.
        """
        t, n = returns_matrix.shape
        cov = np.cov(returns_matrix.T)
        # Shrinkage target: diyagonal kovaryans
        diag_cov = np.diag(np.diag(cov))
        # Ledoit-Wolf shrinkage katsayısı (basit tahmin)
        shrink = min(1.0, (n + 2) / ((t - 1) * n))
        shrunk_cov = (1 - shrink) * cov + shrink * diag_cov
        # Regularizasyon: sayısal stabilite
        shrunk_cov += np.eye(n) * self.regularization
        return shrunk_cov

    def _portfolio_stats(
        self,
        weights: np.ndarray,
        expected_returns: np.ndarray,
        cov: np.ndarray,
    ) -> tuple[float, float, float]:
        """Portföy istatistiklerini hesaplar.

        Args:
            weights: Portföy ağırlıkları.
            expected_returns: Beklenen hisse getirileri (yıllık).
            cov: Kovaryans matrisi (yıllık).

        Returns:
            (beklenen_getiri, volatilite, sharpe) demeti.
        """
        port_return = float(np.dot(weights, expected_returns))
        port_var = float(weights @ cov @ weights)
        port_vol = float(np.sqrt(max(port_var, 1e-10)))
        sharpe = (port_return - self.risk_free_rate) / port_vol if port_vol > 0 else 0.0
        return port_return, port_vol, sharpe

    def _apply_constraints(
        self,
        raw_weights: np.ndarray,
        n: int,
    ) -> np.ndarray:
        """Min/max ağırlık kısıtlarını uygular ve normalize eder.

        Args:
            raw_weights: Ham ağırlıklar.
            n: Varlık sayısı.

        Returns:
            Kısıt uygulanmış ve toplamı 1'e normalize edilmiş ağırlıklar.
        """
        # Clip to [min, max]
        w = np.clip(raw_weights, self.min_weight, self.max_weight)
        # Normalize
        total = w.sum()
        if total > 1e-10:
            w /= total
        else:
            w = np.ones(n) / n
        return w

    def equal_weight(
        self,
        tickers: list[str],
        returns_matrix: np.ndarray,
        expected_returns: np.ndarray,
    ) -> PortfolioWeights:
        """Eşit ağırlık portföy oluşturur.

        Args:
            tickers: Hisse senedi kodları.
            returns_matrix: (T, N) getiri matrisi.
            expected_returns: Beklenen yıllık getiriler.

        Returns:
            Eşit ağırlıklı portföy.
        """
        n = len(tickers)
        weights = np.ones(n) / n
        weights = self._apply_constraints(weights, n)
        cov = self._estimate_covariance(returns_matrix)
        ret, vol, sharpe = self._portfolio_stats(weights, expected_returns, cov)

        # Çeşitlendirme oranı
        individual_vols = np.sqrt(np.diag(cov))
        weighted_vol = float(np.dot(weights, individual_vols))
        div_ratio = weighted_vol / max(vol, 1e-10)

        return PortfolioWeights(
            method=PortfolioMethod.EQUAL_WEIGHT,
            weights=dict(zip(tickers, weights.tolist(), strict=True)),
            expected_return=ret,
            expected_volatility=vol,
            sharpe_ratio=sharpe,
            diversification_ratio=div_ratio,
            n_assets=n,
        )

    def risk_parity(
        self,
        tickers: list[str],
        returns_matrix: np.ndarray,
        expected_returns: np.ndarray,
        n_iter: int = 100,
    ) -> PortfolioWeights:
        """Risk parite portföy oluşturur (her hisse eşit risk katkısı).

        Iteratif Newton yöntemi ile risk katkılarını eşitler.

        Args:
            tickers: Hisse senedi kodları.
            returns_matrix: (T, N) getiri matrisi.
            expected_returns: Beklenen yıllık getiriler.
            n_iter: İterasyon sayısı.

        Returns:
            Risk parite portföy.
        """
        n = len(tickers)
        cov = self._estimate_covariance(returns_matrix)
        weights = np.ones(n) / n
        target_risk = 1.0 / n

        for _ in range(n_iter):
            port_var = float(weights @ cov @ weights)
            port_vol = max(np.sqrt(port_var), 1e-10)
            marginal_risk = cov @ weights / port_vol
            risk_contrib = weights * marginal_risk / port_vol
            # Iteratif güncelleme
            weights = weights * target_risk / np.maximum(risk_contrib, 1e-15)
            weights = self._apply_constraints(weights, n)

        ret, vol, sharpe = self._portfolio_stats(weights, expected_returns, cov)
        individual_vols = np.sqrt(np.diag(cov))
        div_ratio = float(np.dot(weights, individual_vols)) / max(vol, 1e-10)

        return PortfolioWeights(
            method=PortfolioMethod.RISK_PARITY,
            weights=dict(zip(tickers, weights.tolist(), strict=True)),
            expected_return=ret,
            expected_volatility=vol,
            sharpe_ratio=sharpe,
            diversification_ratio=div_ratio,
            n_assets=n,
        )

    def factor_weighted(
        self,
        tickers: list[str],
        factor_scores: list[FactorScores],
        returns_matrix: np.ndarray,
        expected_returns: np.ndarray,
    ) -> PortfolioWeights:
        """Faktör skora orantılı ağırlık portföy oluşturur.

        Bileşik faktör skoru (0-100) ağırlık olarak kullanılır.
        Düşük skorlu hisseler portföyden dışlanabilir.

        Args:
            tickers: Hisse senedi kodları.
            factor_scores: Her hisse için faktör skorları.
            returns_matrix: (T, N) getiri matrisi.
            expected_returns: Beklenen yıllık getiriler.

        Returns:
            Faktör-ağırlıklı portföy.
        """
        n = len(tickers)
        scores = np.array([s.composite for s in factor_scores])
        # Negatif skor olmamasını sağla
        scores = np.maximum(scores - 30.0, 0.0)  # Alt kesim: skor < 30 = 0 ağırlık
        total = scores.sum()
        if total < 1e-10:
            weights = np.ones(n) / n
        else:
            weights = scores / total

        weights = self._apply_constraints(weights, n)
        cov = self._estimate_covariance(returns_matrix)
        ret, vol, sharpe = self._portfolio_stats(weights, expected_returns, cov)
        individual_vols = np.sqrt(np.diag(cov))
        div_ratio = float(np.dot(weights, individual_vols)) / max(vol, 1e-10)

        # Faktör maruziyetleri
        exposures: dict[str, float] = {}
        for factor in FACTOR_NAMES:
            factor_vals = np.array([getattr(s, factor if factor != "low_vol" else "low_vol", 50.0) for s in factor_scores])
            exposures[factor] = float(np.dot(weights, factor_vals))

        return PortfolioWeights(
            method=PortfolioMethod.FACTOR_WEIGHTED,
            weights=dict(zip(tickers, weights.tolist(), strict=True)),
            expected_return=ret,
            expected_volatility=vol,
            sharpe_ratio=sharpe,
            diversification_ratio=div_ratio,
            factor_exposures=exposures,
            n_assets=n,
        )

    def optimize(
        self,
        tickers: list[str],
        returns_matrix: np.ndarray,
        expected_returns: np.ndarray,
        method: PortfolioMethod = PortfolioMethod.RISK_PARITY,
        factor_scores: list[FactorScores] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PortfolioWeights:
        """İstenilen yöntemle portföy optimizasyonu yapar.

        Args:
            tickers: Hisse senedi kodları.
            returns_matrix: (T, N) boyutlu günlük getiri matrisi.
            expected_returns: Beklenen yıllık getiriler.
            method: Optimizasyon yöntemi.
            factor_scores: Faktör-ağırlıklı yöntem için gereklidir.
            metadata: Opsiyonel meta-veri.

        Returns:
            Optimize edilmiş portföy ağırlıkları.

        Raises:
            ValueError: Eksik parametre veya boyut uyuşmazlığı varsa.
        """
        n = len(tickers)
        t, n2 = returns_matrix.shape
        if n != n2:
            raise ValueError(
                f"tickers ({n}) ve returns_matrix sütunları ({n2}) eşleşmeli."
            )
        if len(expected_returns) != n:
            raise ValueError(
                f"expected_returns ({len(expected_returns)}) tickers ({n}) ile eşleşmeli."
            )
        if t < 20:
            raise ValueError(f"Yeterli getiri verisi yok: {t} < 20 günlük veri.")

        with self._lock:
            if method == PortfolioMethod.EQUAL_WEIGHT:
                result = self.equal_weight(tickers, returns_matrix, expected_returns)
            elif method == PortfolioMethod.RISK_PARITY:
                result = self.risk_parity(tickers, returns_matrix, expected_returns)
            elif method == PortfolioMethod.FACTOR_WEIGHTED:
                if factor_scores is None or len(factor_scores) != n:
                    raise ValueError("FACTOR_WEIGHTED için factor_scores sağlanmalı.")
                result = self.factor_weighted(tickers, factor_scores, returns_matrix, expected_returns)
            else:
                # Fallback: equal weight
                logger.warning("Desteklenmeyen yöntem, equal weight kullanılıyor.", method=method.name)
                result = self.equal_weight(tickers, returns_matrix, expected_returns)

            logger.info(
                "Portföy optimizasyonu tamamlandı.",
                method=method.name,
                n_assets=n,
                sharpe=round(result.sharpe_ratio, 3),
                vol=round(result.expected_volatility, 3),
                div_ratio=round(result.diversification_ratio, 3),
            )
            return result


__all__: list[str] = [
    "DEFAULT_FACTOR_WEIGHTS",
    "FACTOR_NAMES",
    "FactorPortfolioOptimizer",
    "FactorScoreCalculator",
    "FactorScores",
    "PortfolioMethod",
    "PortfolioWeights",
    "factor_optimizer",
    "factor_score_calculator",
]

# Singletonlar
factor_score_calculator = FactorScoreCalculator()
factor_optimizer = FactorPortfolioOptimizer()
