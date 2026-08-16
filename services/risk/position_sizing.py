"""
ALPHA BIST — Position Sizing v3.1 (Debug + NaN/Inf/Zero Fix)

ROADMAP v3.0 FAZ 5:
- Kelly Criterion (optimal pozisyon buyuklugu)
- Volatility Targeting (portfoy volatilitesini hedefle)
- Risk Parity (esit risk katkisi)
- Max drawdown-based sizing

KURAL: Dogru hisseyi bulmak yeterli degil, dogru buyuklukte pozisyon acmak da sart.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PositionSize:
    ticker: str
    weight: float           # Portfoy agirligi (0-1)
    shares: int             # Hisse adedi
    notional: float         # TL cinsinden
    risk_pct: float         # Portfoyun %X'i risk altinda
    kelly_fraction: float   # Kelly orani
    vol_adjusted: float     # Volatilite duzeltilmis
    max_position_pct: float # Maksimum pozisyon limiti


class PositionSizer:
    """Akilli pozisyon buyuklugu hesaplama."""

    def __init__(
        self,
        target_volatility: float = 0.15,  # Yillik %15 volatilite hedefi
        max_position_pct: float = 0.10,   # Tek hisse max %10
        max_total_exposure: float = 1.0,  # Toplam exposure max %100
        kelly_fraction: float = 0.25,     # Kelly'nin 1/4'u (yarim Kelly)
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
        """Kelly Criterion pozisyon buyuklugu.

        f* = (p*b - q) / b
        p = win rate, q = 1-p, b = avg_win/avg_loss
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        b = avg_win / avg_loss  # Odds
        q = 1 - win_rate

        kelly = (win_rate * b - q) / b
        kelly = max(0, min(1, kelly))

        # Yarim Kelly (daha konservatif)
        half_kelly = kelly * self.kelly_fraction

        return round(half_kelly, 4)

    def calculate_volatility_targeting(
        self,
        current_volatility: float,  # Yillik volatilite
        target_volatility: Optional[float] = None,
    ) -> float:
        """Volatilite targeting kaldirac orani.

        Kaldirac = Hedef Vol / Mevcut Vol
        """
        target = target_volatility or self.target_volatility
        if current_volatility <= 0:
            return 1.0

        leverage = target / current_volatility
        return round(max(0.5, min(2.0, leverage)), 4)  # 0.5x - 2.0x arasi

    def calculate_position_sizes(
        self,
        opportunities: List[Dict],  # [{ticker, score, confidence, expected_return, volatility}]
        portfolio_value: float,
        current_volatility: float,
        regime: str = "UNKNOWN",
    ) -> List[PositionSize]:
        """Tum pozisyon buyukluklerini hesapla."""

        print(f"\n[POSITION SIZING DEBUG] opportunities={len(opportunities)}, portfolio={portfolio_value:,.0f}, regime={regime}")

        # Volatilite targeting kaldirac orani
        leverage = self.calculate_volatility_targeting(current_volatility)
        print(f"  leverage={leverage:.4f} (current_vol={current_volatility:.4f})")

        # Rejim bazli ayarlar
        if regime == "BEAR":
            leverage *= 0.6
            max_pos = self.max_position_pct * 0.8
        elif regime == "BULL":
            leverage *= 1.2
            max_pos = self.max_position_pct * 1.0
        else:
            max_pos = self.max_position_pct

        print(f"  max_pos={max_pos:.4f}, leverage_after_regime={leverage:.4f}")

        positions = []
        total_weight = 0

        for opp in opportunities:
            ticker = opp.get("ticker", "")
            score = opp.get("score", 0)
            confidence = opp.get("confidence", 0.5)
            expected_return = opp.get("expected_return", 0)
            volatility = opp.get("volatility", 0.2)

            print(f"\n  [{ticker}] score={score}, conf={confidence}, exp_ret={expected_return}, vol={volatility}")

            # NaN/Inf/Zero kontrolu
            if np.isnan(score) or np.isinf(score):
                print(f"    -> SKIP: score NaN/Inf")
                continue
            if np.isnan(confidence) or np.isinf(confidence):
                print(f"    -> SKIP: confidence NaN/Inf")
                continue
            if np.isnan(expected_return) or np.isinf(expected_return):
                print(f"    -> SKIP: expected_return NaN/Inf")
                continue
            if np.isnan(volatility) or np.isinf(volatility) or volatility <= 0:
                print(f"    -> SKIP: volatility NaN/Inf/<=0")
                continue

            # Kelly orani (confidence = win rate yaklasimi)
            win_rate = confidence / 100 if confidence > 1 else confidence
            avg_win = expected_return if expected_return > 0 else 0.05
            avg_loss = volatility * 2  # 2 sigma loss

            print(f"    win_rate={win_rate:.4f}, avg_win={avg_win:.4f}, avg_loss={avg_loss:.4f}")

            kelly = self.calculate_kelly_size(win_rate, avg_win, avg_loss)
            print(f"    kelly={kelly:.4f}")

            # Skor bazli agirlik (yuksek skor = daha buyuk pozisyon)
            score_weight = score / 100 if score > 1 else score
            print(f"    score_weight={score_weight:.4f}")

            # Volatilite duzeltmesi (yuksek vol = daha kucuk pozisyon)
            vol_adjustment = 0.15 / max(volatility, 0.05)
            print(f"    vol_adjustment={vol_adjustment:.4f}")

            # Final agirlik
            weight = kelly * score_weight * vol_adjustment * leverage
            print(f"    weight_raw={weight:.6f}")

            weight = min(weight, max_pos)
            weight = max(0, weight)
            print(f"    weight_clamped={weight:.6f} (max_pos={max_pos})")

            if weight <= 0:
                print(f"    -> SKIP: weight=0 after clamping")
                continue

            # Risk yuzdesi
            risk_pct = weight * volatility * 2  # 2 sigma risk

            positions.append(PositionSize(
                ticker=ticker,
                weight=round(weight, 4),
                shares=0,  # Sonradan hesaplanir
                notional=round(weight * portfolio_value, 2),
                risk_pct=round(risk_pct * 100, 2),
                kelly_fraction=round(kelly, 4),
                vol_adjusted=round(vol_adjustment, 4),
                max_position_pct=round(max_pos, 4),
            ))

            total_weight += weight

        print(f"\n  total_weight={total_weight:.4f}, positions={len(positions)}")

        # Normalize (toplam agirlik max_total_exposure'u asmasin)
        if total_weight > self.max_total_exposure:
            scale = self.max_total_exposure / total_weight
            print(f"  NORMALIZE: scale={scale:.4f} (total_weight > max_exposure)")
            for pos in positions:
                pos.weight = round(pos.weight * scale, 4)
                pos.notional = round(pos.weight * portfolio_value, 2)
                pos.risk_pct = round(pos.risk_pct * scale, 2)

        if not positions:
            print(f"  WARNING: 0 pozisyon uretildi!")

        return positions

    def calculate_risk_parity_weights(
        self,
        cov_matrix: np.ndarray,
        tickers: List[str],
    ) -> Dict[str, float]:
        """Risk parity agirliklari (esit risk katkisi).

        Her varlik portfoy riskine esit katki saglar.
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
        """Max drawdown bazli pozisyon buyuklugu.

        Pozisyon buyuklugu = Max Acceptable DD / Historical Max DD
        """
        if len(historical_returns) == 0:
            return 1.0

        # Historical max drawdown
        cumulative = np.cumprod(1 + historical_returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        historical_max_dd = np.min(drawdowns)

        if historical_max_dd >= 0:
            return 1.0

        sizing = max_acceptable_dd / abs(historical_max_dd)
        return round(min(1.0, sizing), 4)
