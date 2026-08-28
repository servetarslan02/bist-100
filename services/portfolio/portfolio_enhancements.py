"""ALPHA BIST — Portfolio Enhancements v1.0

Portföy yönetimi geliştirmeleri:
- Turnover penalty (aşırı ticareti önleme)
- Transaction cost-aware optimization
- Sector constraints
- Liquidity constraints
- Minimum position
- Hysteresis (pozisyon değişim eşiği)
- Regime constraints

Kullanım:
    from services.portfolio.portfolio_enhancements import portfolio_enhancements

    # Turnover penalty ile ağırlık optimizasyonu
    adjusted = portfolio_enhancements.apply_turnover_penalty(
        target_weights, current_weights, penalty=0.01
    )

    # Transaction cost-aware rebalance
    should_rebalance = portfolio_enhancements.should_rebalance(
        current_weights, target_weights, transaction_cost_pct=0.001
    )

    # Hysteresis kontrolü
    filtered = portfolio_enhancements.apply_hysteresis(
        target_weights, current_weights, threshold=0.02
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class RebalanceDecision:
    """Rebalance karar sonucu."""

    should_rebalance: bool
    reason: str
    estimated_cost: float
    estimated_benefit: float
    net_benefit: float
    turnover: float


@dataclass
class PortfolioConstraints:
    """Portföy kısıtları."""

    max_position_pct: float = 0.10
    min_position_pct: float = 0.01
    max_sector_pct: float = 0.30
    max_total_exposure: float = 1.0
    min_liquidity_score: float = 0.3
    turnover_penalty: float = 0.005
    hysteresis_threshold: float = 0.02
    transaction_cost_pct: float = 0.001


class PortfolioEnhancements:
    """Portföy yönetimi geliştirmeleri.

    Özellikler:
    - Turnover penalty (aşırı ticareti önleme)
    - Transaction cost-aware rebalance kararı
    - Sector constraints
    - Liquidity constraints
    - Minimum position
    - Hysteresis (pozisyon değişim eşiği)
    """

    def __init__(self, constraints: PortfolioConstraints | None = None):
        self.constraints = constraints or PortfolioConstraints()
        self._rebalance_history: list[RebalanceDecision] = []

    def apply_turnover_penalty(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        penalty: float | None = None,
    ) -> dict[str, float]:
        """Turnover penalty ile ağırlık optimizasyonu.

        Aşırı ticareti önlemek için hedef ağırlıkları mevcut ağırlıklara doğru çeker.

        Args:
            target_weights: {ticker: target_weight}
            current_weights: {ticker: current_weight}
            penalty: Turnover penalty (None = constraints'tan)

        Returns:
            Adjusted weights
        """
        if penalty is None:
            penalty = self.constraints.turnover_penalty

        adjusted: dict[str, float] = {}
        all_tickers = set(target_weights.keys()) | set(current_weights.keys())

        for ticker in all_tickers:
            target = target_weights.get(ticker, 0.0)
            current = current_weights.get(ticker, 0.0)
            diff = target - current

            # Penalty: büyük değişimleri daha fazla cezalandır
            adjustment = diff * (1.0 - penalty * abs(diff) * 10)
            adjusted[ticker] = current + adjustment

        # Normalize
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}

        return adjusted

    def should_rebalance(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        transaction_cost_pct: float | None = None,
    ) -> RebalanceDecision:
        """Rebalance yapılmalı mı?

        Transaction cost-aware karar: Eğer rebalance maliyeti
        beklenen faydadan büyükse yapma.

        Args:
            current_weights: Mevcut ağırlıklar
            target_weights: Hedef ağırlıklar
            transaction_cost_pct: İşlem maliyeti %

        Returns:
            RebalanceDecision
        """
        if transaction_cost_pct is None:
            transaction_cost_pct = self.constraints.transaction_cost_pct

        # Turnover hesapla
        all_tickers = set(current_weights.keys()) | set(target_weights.keys())
        turnover = sum(
            abs(target_weights.get(t, 0) - current_weights.get(t, 0))
            for t in all_tickers
        ) / 2  # Tek yön

        # Estimated cost
        estimated_cost = turnover * transaction_cost_pct * 2  # Round-trip

        # Estimated benefit (basitleştirilmiş — ağırlık farkının mutlak değeri)
        estimated_benefit = turnover * 0.01  # %1 beklenen iyileştirme varsayımı

        net_benefit = estimated_benefit - estimated_cost

        should = net_benefit > 0 and turnover > self.constraints.hysteresis_threshold

        if should:
            reason = f"Net fayda pozitif: {net_benefit:.4f} (fayda={estimated_benefit:.4f}, maliyet={estimated_cost:.4f})"
        elif turnover <= self.constraints.hysteresis_threshold:
            reason = f"Turnover çok düşük: {turnover:.4f} < {self.constraints.hysteresis_threshold}"
        else:
            reason = f"Net fayda negatif: {net_benefit:.4f} — rebalance maliyetli"

        decision = RebalanceDecision(
            should_rebalance=should,
            reason=reason,
            estimated_cost=round(estimated_cost, 6),
            estimated_benefit=round(estimated_benefit, 6),
            net_benefit=round(net_benefit, 6),
            turnover=round(turnover, 4),
        )

        self._rebalance_history.append(decision)
        if len(self._rebalance_history) > 500:
            self._rebalance_history = self._rebalance_history[-500:]

        return decision

    def apply_hysteresis(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        threshold: float | None = None,
    ) -> dict[str, float]:
        """Hysteresis uygula — küçük değişimleri filtrele.

        Pozisyon değişimleri eşik değerinin altındaysa.IGNORE.

        Args:
            target_weights: Hedef ağırlıklar
            current_weights: Mevcut ağırlıklar
            threshold: Değişim eşiği (None = constraints'tan)

        Returns:
            Filtrelenmiş ağırlıklar
        """
        if threshold is None:
            threshold = self.constraints.hysteresis_threshold

        filtered: dict[str, float] = {}
        all_tickers = set(target_weights.keys()) | set(current_weights.keys())

        for ticker in all_tickers:
            target = target_weights.get(ticker, 0.0)
            current = current_weights.get(ticker, 0.0)
            diff = abs(target - current)

            if diff < threshold:
                # Küçük değişim — mevcut ağırlığı koru
                filtered[ticker] = current
            else:
                filtered[ticker] = target

        return filtered

    def apply_sector_constraints(
        self,
        weights: dict[str, float],
        sector_map: dict[str, str],
        max_sector_pct: float | None = None,
    ) -> dict[str, float]:
        """Sektör kısıtlarını uygula.

        Args:
            weights: Ağırlıklar
            sector_map: {ticker: sector}
            max_sector_pct: Sektör max % (None = constraints'tan)

        Returns:
            Düzeltilmiş ağırlıklar
        """
        if max_sector_pct is None:
            max_sector_pct = self.constraints.max_sector_pct

        # Sektör bazlı toplam
        sector_weights: dict[str, float] = {}
        for ticker, weight in weights.items():
            sector = sector_map.get(ticker, "UNKNOWN")
            sector_weights[sector] = sector_weights.get(sector, 0.0) + weight

        # Aşan sektörleri düzelt
        adjusted = weights.copy()
        for sector, total in sector_weights.items():
            if total > max_sector_pct:
                scale = max_sector_pct / total
                for ticker, weight in adjusted.items():
                    if sector_map.get(ticker, "UNKNOWN") == sector:
                        adjusted[ticker] = weight * scale

                logger.info(
                    "sector_constraint_applied",
                    sector=sector,
                    original=round(total, 4),
                    limit=max_sector_pct,
                    scale=round(scale, 4),
                )

        return adjusted

    def apply_liquidity_constraints(
        self,
        weights: dict[str, float],
        liquidity_scores: dict[str, float],
        min_score: float | None = None,
    ) -> dict[str, float]:
        """Likidite kısıtlarını uygula.

        Args:
            weights: Ağırlıklar
            liquidity_scores: {ticker: liquidity_score [0,1]}
            min_score: Minimum likidite skoru (None = constraints'tan)

        Returns:
            Düzeltilmiş ağırlıklar
        """
        if min_score is None:
            min_score = self.constraints.min_liquidity_score

        adjusted: dict[str, float] = {}
        removed: list[str] = []

        for ticker, weight in weights.items():
            score = liquidity_scores.get(ticker, 0.0)
            if score < min_score:
                removed.append(ticker)
                adjusted[ticker] = 0.0
            else:
                adjusted[ticker] = weight

        if removed:
            logger.warning("liquidity_constraint_removed", tickers=removed, min_score=min_score)

        # Normalize
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}

        return adjusted

    def apply_min_position(
        self,
        weights: dict[str, float],
        min_pct: float | None = None,
    ) -> dict[str, float]:
        """Minimum pozisyon filtresi — çok küçük pozisyonları çıkar.

        Args:
            weights: Ağırlıklar
            min_pct: Minimum pozisyon % (None = constraints'tan)

        Returns:
            Filtrelenmiş ağırlıklar
        """
        if min_pct is None:
            min_pct = self.constraints.min_position_pct

        filtered = {t: w for t, w in weights.items() if w >= min_pct}

        # Normalize
        total = sum(filtered.values())
        if total > 0:
            filtered = {k: v / total for k, v in filtered.items()}

        return filtered

    def apply_position_limits(
        self,
        weights: dict[str, float],
        max_pct: float | None = None,
    ) -> dict[str, float]:
        """Pozisyon limitlerini uygula.

        Args:
            weights: Ağırlıklar
            max_pct: Tek hisse max % (None = constraints'tan)

        Returns:
            Düzeltilmiş ağırlıklar
        """
        if max_pct is None:
            max_pct = self.constraints.max_position_pct

        adjusted = {t: min(w, max_pct) for t, w in weights.items()}

        # Normalize
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}

        return adjusted

    def get_rebalance_history(self, limit: int = 20) -> list[RebalanceDecision]:
        """Rebalance geçmişi."""
        return self._rebalance_history[-limit:]


# Singleton
portfolio_enhancements = PortfolioEnhancements()
