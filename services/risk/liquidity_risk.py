"""
ALPHA BIST — Liquidity Risk Engine v1.0

Canlı ve Simüle Edilmiş Piyasalarda Likidite Riski Yönetimi:
1. Bid-Ask Spread Riski (L-VaR — Liquidity-Adjusted Value at Risk)
2. Kyle's Lambda & Piyasa Etkisi (Market Impact / Slippage Modeli)
3. ADV (Average Daily Volume) Katılım Limiti & Tasfiye Süresi (Liquidation Horizon)
4. BIST Pazar Grupları & Brüt Takas Likidite Skoru
5. Likiditeye Duyarlı Dinamik Pozisyon Boyutlandırma Katsayısı (Liquidity Haircut)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class LiquidityMetrics:
    """Tekil enstrüman likidite risk değerlendirmesi."""

    ticker: str
    order_value: float
    adv_tl: float  # Günlük ortalama işlem hacmi (TL)
    participation_rate_pct: float  # Emir tutarının ADV'ye oranı (%)
    effective_spread_bps: float  # Efektif alış-satış makası (baz puan, 1 bps = 0.01%)
    expected_market_impact_pct: float  # Beklenen piyasa etkisi (%)
    expected_slippage_tl: float  # Beklenen kayma maliyeti (TL)
    liquidation_days: float  # Piyasayı bozmadan tasfiye süresi (gün)
    liquidity_score: float  # 0-100 (100: Mükemmel likidite BIST30, <30: Düşük likidite)
    liquidity_sizing_multiplier: float  # 0.10 - 1.00 arası pozisyon ölçekleme çarpanı
    is_tradable: bool
    warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class PortfolioLiquidityReport:
    """Tüm portföy likidite riski özeti."""

    portfolio_value: float
    portfolio_liquidity_score: float  # 0-100
    weighted_spread_bps: float
    total_liquidation_cost_tl: float
    total_liquidation_cost_pct: float
    max_liquidation_days: float
    weighted_liquidation_days: float
    base_var_95: float
    liquidity_adjusted_var_95: float  # L-VaR = VaR + 0.5 * Spread + Market Impact
    lvar_increment_pct: float  # L-VaR'ın standart VaR'a göre artış yüzdesi
    illiquid_positions_count: int
    position_details: dict[str, LiquidityMetrics]
    recommendations: list[str] = field(default_factory=list)


class LiquidityRiskEngine:
    """BIST Likidite Riski ve Piyasa Etkisi Hesaplama Motoru."""

    def __init__(
        self,
        max_adv_participation_pct: float = 5.0,  # Tek emirde maksimum ADV katılımı (%)
        max_acceptable_spread_bps: float = 50.0,  # 50 bps (%0.50) üzeri yüksek makas
        default_adv_fallback: float = 20_000_000.0,  # Veri yoksa güvenli default ADV (20M TL)
        kyle_lambda_factor: float = 0.15,  # Piyasa etkisi katsayısı
    ):
        """Otomatik eklendi."""
        self.max_adv_participation_pct = max_adv_participation_pct
        self.max_acceptable_spread_bps = max_acceptable_spread_bps
        self.default_adv_fallback = default_adv_fallback
        self.kyle_lambda_factor = kyle_lambda_factor
        logger.info(
            "LiquidityRiskEngine initialized",
            max_participation=max_adv_participation_pct,
            max_spread_bps=max_acceptable_spread_bps,
        )

    def evaluate_order_liquidity(
        self,
        ticker: str,
        order_value: float,
        price: float,
        adv_tl: float | None = None,
        spread_bps: float | None = None,
        daily_volatility: float = 0.02,
        is_gross_settlement: bool = False,
    ) -> LiquidityMetrics:
        """Bir emir için likidite riskini ve piyasa etkisini değerlendirir.

        Args:
            ticker: Hisse kodu
            order_value: İşlem büyüklüğü (TL)
            price: Hisse fiyatı
            adv_tl: 20-günlük Ortalama Günlük Hacim (TL)
            spread_bps: Alış-satış makası (baz puan)
            daily_volatility: Günlük volatilite (ör: 0.02 = %2)
            is_gross_settlement: Brüt takas durumu
        """
        effective_adv = adv_tl if (adv_tl is not None and adv_tl > 0) else self.default_adv_fallback
        effective_spread = spread_bps if (spread_bps is not None and spread_bps >= 0) else 10.0

        warnings = []
        is_tradable = True

        # 1. ADV Katılım Oranı
        participation_pct = (order_value / effective_adv * 100.0) if effective_adv > 0 else 100.0

        if participation_pct > self.max_adv_participation_pct * 2:
            warnings.append(
                f"Aşırı hacim katılımı: %{participation_pct:.2f} > %{self.max_adv_participation_pct:.1f} limit"
            )
            if participation_pct > 25.0:
                is_tradable = False

        # 2. Piyasa Etkisi (Kyle's Square-Root Market Impact Model)
        # Impact = kyle_factor * volatility * sqrt(order_value / adv)
        order_fraction = max(order_value / effective_adv, 1e-6) if effective_adv > 0 else 1.0
        impact_pct = self.kyle_lambda_factor * daily_volatility * np.sqrt(order_fraction) * 100.0
        # Spread cost (half spread)
        half_spread_pct = (effective_spread / 10000.0) / 2.0 * 100.0
        total_slippage_pct = impact_pct + half_spread_pct
        expected_slippage_tl = order_value * (total_slippage_pct / 100.0)

        # 3. Tasfiye Süresi (Liquidation Horizon in days)
        # Günde en fazla max_adv_participation_pct işlem yapılabilirse:
        max_daily_tradable = effective_adv * (self.max_adv_participation_pct / 100.0)
        liquidation_days = (order_value / max_daily_tradable) if max_daily_tradable > 0 else 999.0
        liquidation_days = round(float(liquidation_days), 2)

        if liquidation_days > 3.0:
            warnings.append(f"Tasfiye süresi uzun: {liquidation_days:.1f} gün")

        # 4. Likidite Skoru Hesaplama (0-100)
        # BIST ADV kriteri: >200M TL = 100, 50M-200M = 80-99, 10M-50M = 50-79, <10M = <50
        adv_score = min(100.0, max(10.0, np.log10(max(effective_adv, 1000.0) / 1000.0) * 20.0))
        spread_penalty = min(40.0, (effective_spread / 10.0) * 5.0)
        impact_penalty = min(30.0, impact_pct * 15.0)
        gross_penalty = 25.0 if is_gross_settlement else 0.0

        liquidity_score = max(0.0, min(100.0, adv_score - spread_penalty - impact_penalty - gross_penalty))
        liquidity_score = round(float(liquidity_score), 1)

        # 5. Pozisyon Ölçekleme Çarpanı (Sizing Multiplier)
        # Likidite skoru 80+ -> 1.0 (tam boyut)
        # 50-80 -> 0.70 - 0.95
        # 30-50 -> 0.40 - 0.70
        # <30 -> 0.10 - 0.40
        if liquidity_score >= 80.0:
            sizing_mult = 1.0
        elif liquidity_score >= 50.0:
            sizing_mult = 0.70 + (liquidity_score - 50.0) / 30.0 * 0.30
        elif liquidity_score >= 20.0:
            sizing_mult = 0.30 + (liquidity_score - 20.0) / 30.0 * 0.40
        else:
            sizing_mult = max(0.10, liquidity_score / 20.0 * 0.30)
        sizing_mult = round(float(sizing_mult), 2)

        if is_gross_settlement:
            warnings.append("Brüt takas kısıtı mevcut: Aynı gün satış yapılamaz.")

        if effective_spread > self.max_acceptable_spread_bps:
            warnings.append(f"Yüksek alış-satış makası: {effective_spread:.1f} bps")

        return LiquidityMetrics(
            ticker=ticker,
            order_value=float(order_value),
            adv_tl=float(effective_adv),
            participation_rate_pct=round(float(participation_pct), 2),
            effective_spread_bps=round(float(effective_spread), 1),
            expected_market_impact_pct=round(float(impact_pct), 3),
            expected_slippage_tl=round(float(expected_slippage_tl), 2),
            liquidation_days=liquidation_days,
            liquidity_score=liquidity_score,
            liquidity_sizing_multiplier=sizing_mult,
            is_tradable=is_tradable,
            warnings=warnings,
        )

    def calculate_portfolio_liquidity(
        self,
        positions: list[dict[str, Any]],  # [{"ticker", "value", "adv_tl", "spread_bps"}]
        total_portfolio_value: float,
        base_var_95: float = 0.0,
    ) -> PortfolioLiquidityReport:
        """Tüm portföy için likidite riski ve Likiditeye Uyarlanmış VaR (L-VaR) hesaplar."""
        if not positions or total_portfolio_value <= 0:
            return PortfolioLiquidityReport(
                portfolio_value=total_portfolio_value,
                portfolio_liquidity_score=100.0,
                weighted_spread_bps=0.0,
                total_liquidation_cost_tl=0.0,
                total_liquidation_cost_pct=0.0,
                max_liquidation_days=0.0,
                weighted_liquidation_days=0.0,
                base_var_95=base_var_95,
                liquidity_adjusted_var_95=base_var_95,
                lvar_increment_pct=0.0,
                illiquid_positions_count=0,
                position_details={},
                recommendations=[],
            )

        position_details = {}
        total_cost_tl = 0.0
        weighted_spread = 0.0
        weighted_score = 0.0
        weighted_days = 0.0
        max_days = 0.0
        illiquid_count = 0
        recommendations = []

        for pos in positions:
            ticker = pos.get("ticker", "UNKNOWN")
            val = float(pos.get("value", 0.0))
            if val <= 0:
                continue

            weight = val / total_portfolio_value
            adv = pos.get("adv_tl")
            spread = pos.get("spread_bps", 10.0)
            is_gross = pos.get("is_gross_settlement", False)

            metrics = self.evaluate_order_liquidity(
                ticker=ticker,
                order_value=val,
                price=float(pos.get("price", 100.0)),
                adv_tl=adv,
                spread_bps=spread,
                is_gross_settlement=is_gross,
            )
            position_details[ticker] = metrics

            total_cost_tl += metrics.expected_slippage_tl
            weighted_spread += metrics.effective_spread_bps * weight
            weighted_score += metrics.liquidity_score * weight
            weighted_days += metrics.liquidation_days * weight
            max_days = max(max_days, metrics.liquidation_days)

            if metrics.liquidity_score < 40.0:
                illiquid_count += 1
                recommendations.append(
                    f"{ticker} düşük likiditeye sahip (Skor: {metrics.liquidity_score}). Pozisyon boyutu küçültülmeli."
                )

        cost_pct = (total_cost_tl / total_portfolio_value * 100.0) if total_portfolio_value > 0 else 0.0

        # L-VaR (Bangia et al., 1999 & Ernst et al., 2012 L-VaR standard):
        # L-VaR = Base VaR + 0.5 * Liquidation Cost
        lvar_95 = base_var_95 + (total_cost_tl * 0.5)
        lvar_increment = ((lvar_95 - base_var_95) / max(base_var_95, 1e-4) * 100.0) if base_var_95 > 0 else 0.0

        if max_days > 2.0:
            recommendations.append(f"Maksimum tasfiye süresi {max_days:.1f} gün. Hızlı kriz çıkışında kayma artabilir.")

        return PortfolioLiquidityReport(
            portfolio_value=round(total_portfolio_value, 2),
            portfolio_liquidity_score=round(float(weighted_score), 1),
            weighted_spread_bps=round(float(weighted_spread), 1),
            total_liquidation_cost_tl=round(float(total_cost_tl), 2),
            total_liquidation_cost_pct=round(float(cost_pct), 3),
            max_liquidation_days=round(float(max_days), 2),
            weighted_liquidation_days=round(float(weighted_days), 2),
            base_var_95=round(float(base_var_95), 2),
            liquidity_adjusted_var_95=round(float(lvar_95), 2),
            lvar_increment_pct=round(float(lvar_increment), 2),
            illiquid_positions_count=illiquid_count,
            position_details=position_details,
            recommendations=recommendations,
        )


# Singleton
liquidity_risk_engine = LiquidityRiskEngine()
