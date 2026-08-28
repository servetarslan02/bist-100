"""ALPHA BIST — Portfolio Enhancements v2.0

Portföy yönetimi geliştirmeleri:
- Turnover penalty (aşırı ticareti önleme, matematiksel stabil shrinkage)
- Transaction cost-aware optimization
- Sector constraints
- Liquidity constraints
- Minimum position
- Hysteresis (pozisyon değişim eşiği)
- Dynamic Regime Constraints
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
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class PortfolioConstraints:
    """Portföy kısıtları."""

    max_position_pct: float = 0.10
    min_position_pct: float = 0.015
    max_sector_pct: float = 0.30
    max_total_exposure: float = 1.0
    min_liquidity_score: float = 0.30
    turnover_penalty: float = 0.01
    hysteresis_threshold: float = 0.02
    transaction_cost_pct: float = 0.0015


class PortfolioEnhancements:
    """Portföy yönetimi geliştirmeleri."""

    def __init__(self, constraints: PortfolioConstraints | None = None):
        self.constraints = constraints or PortfolioConstraints()
        self._rebalance_history: list[RebalanceDecision] = []

    def apply_turnover_penalty(
        self,
        target_weights: dict[str, float],
        current_weights: dict[str, float],
        penalty: float | None = None,
    ) -> dict[str, float]:
        """Turnover penalty ile ağırlık optimizasyonu (Stabil Bounded Shrinkage).

        Aşırı ticareti önlemek için hedef ağırlıkları mevcut ağırlıklara doğru çeker.
        """
        if penalty is None:
            penalty = self.constraints.turnover_penalty

        adjusted: dict[str, float] = {}
        all_tickers = set(target_weights.keys()) | set(current_weights.keys())

        for ticker in all_tickers:
            target = target_weights.get(ticker, 0.0)
            current = current_weights.get(ticker, 0.0)
            diff = target - current

            # Shrinkage katsayısı daima [0.0, 1.0] aralığında tutulur
            shrinkage = max(0.0, min(1.0, 1.0 - penalty * (1.0 + abs(diff) * 5.0)))
            new_w = max(0.0, current + diff * shrinkage)
            adjusted[ticker] = new_w

        # Normalize
        total = sum(adjusted.values())
        if total > 1e-6:
            adjusted = {k: v / total for k, v in adjusted.items()}

        return adjusted

    def should_rebalance(
        self,
        current_weights: dict[str, float],
        target_weights: dict[str, float],
        transaction_cost_pct: float | None = None,
        portfolio_value: float = 100000.0,
    ) -> RebalanceDecision:
        """Rebalance yapılmalı mı? (Cost-Benefit Analizi)."""
        if transaction_cost_pct is None:
            transaction_cost_pct = self.constraints.transaction_cost_pct

        all_tickers = set(current_weights.keys()) | set(target_weights.keys())
        turnover = sum(abs(target_weights.get(t, 0.0) - current_weights.get(t, 0.0)) for t in all_tickers) / 2.0

        # Estimated cost (round-trip + spread)
        estimated_cost = turnover * transaction_cost_pct * 2.0

        # Estimated benefit (beklenen portföy iyileşmesi)
        estimated_benefit = turnover * 0.015

        net_benefit = estimated_benefit - estimated_cost
        should = net_benefit > 0 and turnover >= self.constraints.hysteresis_threshold

        if should:
            reason = f"Net fayda pozitif: {net_benefit:.4f} (fayda={estimated_benefit:.4f}, maliyet={estimated_cost:.4f}, turnover={turnover:.4f})"
        elif turnover < self.constraints.hysteresis_threshold:
            reason = f"Turnover eşik altında: {turnover:.4f} < {self.constraints.hysteresis_threshold}"
        else:
            reason = f"Net fayda negatif: {net_benefit:.4f} — rebalance işlem maliyetini kurtarmıyor"

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
        """Hysteresis uygula — eşik altındaki küçük oynamaları koru."""
        if threshold is None:
            threshold = self.constraints.hysteresis_threshold

        filtered: dict[str, float] = {}
        all_tickers = set(target_weights.keys()) | set(current_weights.keys())

        for ticker in all_tickers:
            target = target_weights.get(ticker, 0.0)
            current = current_weights.get(ticker, 0.0)
            diff = abs(target - current)

            if diff < threshold:
                filtered[ticker] = current
            else:
                filtered[ticker] = target

        total = sum(filtered.values())
        if total > 1e-6:
            filtered = {k: v / total for k, v in filtered.items()}

        return filtered

    def apply_sector_constraints(
        self,
        weights: dict[str, float],
        sector_map: dict[str, str],
        max_sector_pct: float | None = None,
    ) -> dict[str, float]:
        """Sektör konsantrasyon sınırını uygular."""
        if max_sector_pct is None:
            max_sector_pct = self.constraints.max_sector_pct

        sector_weights: dict[str, float] = {}
        for ticker, weight in weights.items():
            sector = sector_map.get(ticker, "UNKNOWN")
            sector_weights[sector] = sector_weights.get(sector, 0.0) + weight

        adjusted = weights.copy()
        for sector, total in sector_weights.items():
            if total > max_sector_pct and total > 0:
                scale = max_sector_pct / total
                for ticker in adjusted:
                    if sector_map.get(ticker, "UNKNOWN") == sector:
                        adjusted[ticker] = adjusted[ticker] * scale

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
        """Likidite kısıtlarını uygular."""
        if min_score is None:
            min_score = self.constraints.min_liquidity_score

        adjusted: dict[str, float] = {}
        for ticker, weight in weights.items():
            score = liquidity_scores.get(ticker, 1.0)
            if score < min_score:
                adjusted[ticker] = 0.0
            else:
                adjusted[ticker] = weight

        total = sum(adjusted.values())
        if total > 1e-6:
            adjusted = {k: v / total for k, v in adjusted.items()}

        return adjusted

    def apply_min_position(
        self,
        weights: dict[str, float],
        min_pct: float | None = None,
    ) -> dict[str, float]:
        """Minimum pozisyon filtresi — tozluluk pozisyonları temizler."""
        if min_pct is None:
            min_pct = self.constraints.min_position_pct

        filtered = {t: w for t, w in weights.items() if w >= min_pct}
        total = sum(filtered.values())
        if total > 1e-6:
            filtered = {k: v / total for k, v in filtered.items()}

        return filtered

    def apply_position_limits(
        self,
        weights: dict[str, float],
        max_pct: float | None = None,
    ) -> dict[str, float]:
        """Pozisyon limitlerini uygula."""
        if max_pct is None:
            max_pct = self.constraints.max_position_pct

        return {t: min(w, max_pct) for t, w in weights.items()}

    def get_rebalance_history(self, limit: int = 20) -> list[RebalanceDecision]:
        """Rebalance geçmişi."""
        return self._rebalance_history[-limit:]


# Singleton
portfolio_enhancements = PortfolioEnhancements()
