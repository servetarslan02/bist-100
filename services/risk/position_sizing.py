"""
ALPHA BIST — Position Sizing v3.0

ROADMAP v3.0 FAZ 5:
- Kelly Criterion (optimal pozisyon büyüklüğü)
- Volatility Targeting (portföy volatilitesini hedefle)
- Risk Parity (eşit risk katkısı)
- Max drawdown-based sizing

KURAL: Doğru hisseyi bulmak yeterli değil, doğru büyüklükte pozisyon açmak da şart.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PositionSize:
    ticker: str
    weight: float           # Portföy ağırlığı (0-1)
    shares: int             # Hisse adedi
    notional: float         # TL cinsinden
    risk_pct: float         # Portföyün %X'i risk altında
    kelly_fraction: float   # Kelly oranı
    vol_adjusted: float     # Volatilite düzeltilmiş
    max_position_pct: float # Maksimum pozisyon limiti


class PositionSizer:
    """Akıllı pozisyon büyüklüğü hesaplama."""

    def __init__(
        self,
        target_volatility: float = 0.15,  # Yıllık %15 volatilite hedefi
        max_position_pct: float = 0.10,   # Tek hisse max %10
        max_total_exposure: float = 1.0,  # Toplam exposure max %100
        kelly_fraction: float = 0.25,     # Kelly'nin 1/4'ü (yarım Kelly)
    ):
        self.target_volatility = target_volatility
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.kelly_fraction = kelly_fraction

        logger.info("PositionSizer initialized",
                   target_vol=target_volatility,
                   max_pos=max_position_pct,
                   kelly_frac=kelly_fraction)

    def calculate_kelly_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """Kelly Criterion pozisyon büyüklüğü.

        f* = (p*b - q) / b
        p = win rate, q = 1-p, b = avg_win/avg_loss
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        b = avg_win / avg_loss  # Odds
        q = 1 - win_rate

        kelly = (win_rate * b - q) / b
        kelly = max(0, min(1, kelly))

        # Yarım Kelly (daha konservatif)
        half_kelly = kelly * self.kelly_fraction

        return round(half_kelly, 4)

    def calculate_volatility_targeting(
        self,
        current_volatility: float,  # Yıllık volatilite
        target_volatility: Optional[float] = None,
    ) -> float:
        """Volatilite targeting kaldıraç oranı.

        Kaldıraç = Hedef Vol / Mevcut Vol
        """
        target = target_volatility or self.target_volatility
        if current_volatility <= 0:
            return 1.0

        leverage = target / current_volatility
        return round(max(0.5, min(2.0, leverage)), 4)  # 0.5x - 2.0x arası

    def calculate_position_sizes(
        self,
        opportunities: List[Dict],  # [{ticker, score, confidence, expected_return, volatility}]
        portfolio_value: float,
        current_volatility: float,
        regime: str = "UNKNOWN",
    ) -> List[PositionSize]:
        """Tüm pozisyon büyüklüklerini hesapla."""

        # Volatilite targeting kaldıraç oranı
        leverage = self.calculate_volatility_targeting(current_volatility)

        # Rejim bazlı ayarlar
        if regime == "BEAR":
            leverage *= 0.6
            max_pos = self.max_position_pct * 0.8
        elif regime == "BULL":
            leverage *= 1.2
            max_pos = self.max_position_pct * 1.0
        else:
            max_pos = self.max_position_pct

        positions = []
        total_weight = 0

        for opp in opportunities:
            ticker = opp.get("ticker", "")
            score = opp.get("score", 0)
            confidence = opp.get("confidence", 0.5)
            expected_return = opp.get("expected_return", 0)
            volatility = opp.get("volatility", 0.2)

            # Kelly oranı (confidence = win rate yaklaşımı)
            win_rate = confidence / 100 if confidence > 1 else confidence
            avg_win = expected_return if expected_return > 0 else 0.05
            avg_loss = volatility * 2  # 2 sigma loss

            kelly = self.calculate_kelly_size(win_rate, avg_win, avg_loss)

            # Skor bazlı ağırlık (yüksek skor = daha büyük pozisyon)
            score_weight = score / 100 if score > 1 else score

            # Volatilite düzeltmesi (yüksek vol = daha küçük pozisyon)
            vol_adjustment = 0.15 / max(volatility, 0.05)

            # Final ağırlık
            weight = kelly * score_weight * vol_adjustment * leverage
            weight = min(weight, max_pos)
            weight = max(0, weight)

            # Risk yüzdesi
            risk_pct = weight * volatility * 2  # 2 sigma risk

            positions.append(PositionSize(
                ticker=ticker,
                weight=round(weight, 4),
                shares=0,  # Sonradan hesaplanır
                notional=round(weight * portfolio_value, 2),
                risk_pct=round(risk_pct * 100, 2),
                kelly_fraction=round(kelly, 4),
                vol_adjusted=round(vol_adjustment, 4),
                max_position_pct=round(max_pos, 4),
            ))

            total_weight += weight

        # Normalize (toplam ağırlık max_total_exposure'u aşmasın)
        if total_weight > self.max_total_exposure:
            scale = self.max_total_exposure / total_weight
            for pos in positions:
                pos.weight = round(pos.weight * scale, 4)
                pos.notional = round(pos.weight * portfolio_value, 2)
                pos.risk_pct = round(pos.risk_pct * scale, 2)

        return positions

    def calculate_risk_parity_weights(
        self,
        cov_matrix: np.ndarray,
        tickers: List[str],
    ) -> Dict[str, float]:
        """Risk parity ağırlıkları (eşit risk katkısı).

        Her varlık portföy riskine eşit katkı sağlar.
        """
        n = len(tickers)
        if n == 0:
            return {}

        # Inverse volatility weights (basit risk parity)
        inv_vols = 1.0 / np.sqrt(np.diag(cov_matrix))
        weights = inv_vols / np.sum(inv_vols)

        return {ticker: round(float(w), 4) for ticker, w in zip(tickers, weights)}

    def calculate_max_drawdown_sizing(
        self,
        historical_returns: np.ndarray,
        max_acceptable_dd: float = 0.15,  # %15 max drawdown
    ) -> float:
        """Max drawdown bazlı pozisyon büyüklüğü.

        Pozisyon büyüklüğü = Max Acceptable DD / Historical Max DD
        """
        if len(historical_returns) < 20:
            return 1.0

        cumulative = np.cumsum(historical_returns)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (peak - cumulative) / peak
        historical_max_dd = np.max(drawdown)

        if historical_max_dd <= 0:
            return 1.0

        sizing = max_acceptable_dd / historical_max_dd
        return round(max(0.1, min(1.0, sizing)), 4)


# Singleton
position_sizer = PositionSizer()
