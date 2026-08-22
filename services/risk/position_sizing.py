"""
ALPHA BIST — Position Sizing v4.0 (Calibrated Kelly + Historical OOS)

Mimari:
1. Calibration: ranking score -> win_probability (Platt scaling)
2. Historical OOS: gecmis trades'ten avg_win, avg_loss
3. Fractional Kelly: f* = (p*b - q) / b, yarim Kelly uygula
4. Volatility Target: portfoy volatilitesini hedefle
5. Risk Limits: max position, max total exposure

KURAL: confidence != win_probability. Ayri degiskenler.
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PositionSize:
    ticker: str
    weight: float
    shares: int
    notional: float
    risk_pct: float
    kelly_fraction: float
    win_probability: float
    avg_win: float
    avg_loss: float
    vol_adjusted: float
    max_position_pct: float


class PositionSizer:
    """Kalibre edilmis Kelly + Historical OOS + Vol Targeting."""

    def __init__(
        self,
        target_volatility: float = 0.15,
        max_position_pct: float = 0.10,
        max_total_exposure: float = 1.0,
        kelly_fraction: float = 0.5,  # Yarim Kelly
    ):
        self.target_volatility = target_volatility
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.kelly_fraction = kelly_fraction

    def calculate_position_sizes(
        self,
        opportunities: List[Dict],
        portfolio_value: float,
        current_volatility: float,
        regime: str = "UNKNOWN",
        calibrator=None,  # ScoreCalibrator instance
    ) -> List[PositionSize]:
        """Tum pozisyon buyukluklerini hesapla."""

        logger.info("debug_output", message=f"\n[POSITION SIZING v4.0] opportunities={len(opportunities)}, portfolio={portfolio_value:,.0f}, regime={regime}")

        # Volatilite targeting kaldirac orani
        leverage = self._volatility_leverage(current_volatility)
        logger.info("debug_output", message=f"  leverage={leverage:.4f} (target_vol={self.target_volatility}, current_vol={current_volatility:.4f})")

        # Rejim bazli ayarlar
        if regime == "BEAR":
            leverage *= 0.6
            max_pos = self.max_position_pct * 0.8
        elif regime == "BULL":
            leverage *= 1.2
            max_pos = self.max_position_pct * 1.0
        else:
            max_pos = self.max_position_pct

        logger.info("debug_output", message=f"  max_pos={max_pos:.4f}, leverage_after_regime={leverage:.4f}")

        # Historical OOS avg_win/avg_loss (varsa)
        hist_avg_win, hist_avg_loss = (0.05, 0.05)
        if calibrator:
            hist_avg_win, hist_avg_loss = calibrator.get_avg_win_loss()
            logger.info("debug_output", message=f"  historical_avg_win={hist_avg_win:.4f}, historical_avg_loss={hist_avg_loss:.4f}")

        positions = []
        total_weight = 0

        for opp in opportunities:
            ticker = opp.get("ticker", "")
            score = opp.get("score", 0)
            confidence = opp.get("confidence", 0.5)
            expected_return = opp.get("expected_return", 0)
            volatility = opp.get("volatility", 0.2)

            logger.info("debug_output", message=f"\n  [{ticker}] score={score:.4f}, conf={confidence:.4f}, exp_ret={expected_return:.4f}, vol={volatility:.4f}")

            # NaN/Inf/Zero kontrolu
            if not self._is_valid(score) or not self._is_valid(confidence) or not self._is_valid(volatility):
                logger.info("debug_output", message=f"    -> SKIP: invalid input")
                continue

            # === CALIBRATION: score -> win_probability ===
            if calibrator:
                win_prob = calibrator.calibrate(score)
            else:
                # Fallback: score semantiği yüksek=iyi (0-100 skala,
                # ranking_model.py ile ve aşağıdaki cold-start bloğuyla
                # tutarlı). score=50 (nötr) -> p~0.5; score=70 -> p~0.85;
                # score=30 -> p~0.15.
                win_prob = 1.0 / (1.0 + np.exp(-0.08 * (score - 50)))
                win_prob = float(np.clip(win_prob, 0.05, 0.95))

            logger.info("debug_output", message=f"    win_probability={win_prob:.4f} (calibrated from score={score:.4f})")

            # === HISTORICAL OOS: avg_win, avg_loss ===
            # Ticker-spesifik historical performance (varsa)
            ticker_avg_win = hist_avg_win
            ticker_avg_loss = hist_avg_loss

            # Eger expected_return varsa, bunu da kullan
            if expected_return > 0:
                ticker_avg_win = max(expected_return, hist_avg_win)

            logger.info("debug_output", message=f"    avg_win={ticker_avg_win:.4f}, avg_loss={ticker_avg_loss:.4f}")

            # === COLD-START POLICY ===
            # Historical OOS trade yoksa Kelly devre disi, score-based weight kullan
            has_history = calibrator is not None and calibrator._fitted
            logger.info("debug_output", message=f"    has_history={has_history}")

            if has_history:
                # === FRACTIONAL KELLY (historical data varsa) ===
                # Regime-conditioned: fraction rejime göre değişir
                kelly = self._fractional_kelly(win_prob, ticker_avg_win, ticker_avg_loss, regime=regime)
                logger.info("debug_output", message=f"    kelly={kelly:.4f} (regime={regime})")

                if kelly <= 0:
                    logger.info("debug_output", message=f"    -> SKIP: kelly<=0 (negative expectation, NO TRADE is correct)")
                    continue

                base_weight = kelly
            else:
                # Cold-start: Kelly devre disi
                # Negatif expected_return → NO TRADE
                if expected_return < 0:
                    logger.info("debug_output", message=f"    -> SKIP: expected_return<0 (NO TRADE)")
                    continue

                logger.info("debug_output", message=f"    COLD-START: Kelly disabled, using score-based weight")
                # Score semantigi: yuksek = iyi. En iyi score = 1.0, en kotu = 0.1
                base_weight = max(0.1, min(1.0, score / 20.0))
                kelly = 0.0  # Kelly uygulanmadi
                logger.info("debug_output", message=f"    base_weight={base_weight:.4f}")

            # === SCORE WEIGHT ===
            # Score semantigi: yuksek = iyi (ranking_model ile tutarli)
            score_weight = max(0.1, score / 100.0)  # score=100 -> 1.0, score=0 -> 0.1
            logger.info("debug_output", message=f"    score_weight={score_weight:.4f}")

            # === VOLATILITY ADJUSTMENT ===
            vol_adj = self.target_volatility / max(volatility, 0.01)
            vol_adj = min(vol_adj, 3.0)  # Cap at 3x
            logger.info("debug_output", message=f"    vol_adjustment={vol_adj:.4f}")

            # === FINAL WEIGHT ===
            weight = base_weight * score_weight * vol_adj * leverage
            logger.info("debug_output", message=f"    weight_raw={weight:.6f}")

            weight = min(weight, max_pos)
            weight = max(0, weight)
            logger.info("debug_output", message=f"    weight_clamped={weight:.6f} (max_pos={max_pos})")

            if weight <= 0.001:
                logger.info("debug_output", message=f"    -> SKIP: weight too small")
                continue

            # Risk yuzdesi
            risk_pct = weight * volatility * 2

            positions.append(PositionSize(
                ticker=ticker,
                weight=round(weight, 4),
                shares=0,
                notional=round(weight * portfolio_value, 2),
                risk_pct=round(risk_pct * 100, 2),
                kelly_fraction=round(kelly, 4),
                win_probability=round(win_prob, 4),
                avg_win=round(ticker_avg_win, 4),
                avg_loss=round(ticker_avg_loss, 4),
                vol_adjusted=round(vol_adj, 4),
                max_position_pct=round(max_pos, 4),
            ))

            total_weight += weight

        logger.info("debug_output", message=f"\n  total_weight={total_weight:.4f}, positions={len(positions)}")

        # Normalize
        if total_weight > self.max_total_exposure:
            scale = self.max_total_exposure / total_weight
            logger.info("debug_output", message=f"  NORMALIZE: scale={scale:.4f}")
            for pos in positions:
                pos.weight = round(pos.weight * scale, 4)
                pos.notional = round(pos.weight * portfolio_value, 2)
                pos.risk_pct = round(pos.risk_pct * scale, 2)

        if not positions:
            logger.info("debug_output", message=f"  WARNING: 0 pozisyon uretildi!")

        return positions

    # Rejime göre Kelly fraction (SSRN Regime-Conditioned Kelly 2026)
    REGIME_KELLY_FRACTIONS = {
        "BULL": 0.6,              # Agresif
        "BEAR": 0.3,              # Muhafazakar
        "SIDEWAYS": 0.4,          # Orta
        "HIGH_VOLATILITY": 0.25,  # Çok muhafazakar
        "LOW_VOLATILITY": 0.5,    # Normal
        "RISK_ON": 0.55,          # Biraz agresif
        "RISK_OFF": 0.3,          # Muhafazakar
        "CRISIS": 0.15,           # Çok muhafazakar
        "RECOVERY": 0.45,         # Orta-agresif
        "MOMENTUM_EXPANSION": 0.55,
        "MOMENTUM_CONTRACTION": 0.25,
        "PANIC": 0.15,
    }

    def _fractional_kelly(self, win_prob: float, avg_win: float, avg_loss: float,
                          regime: str = "SIDEWAYS") -> float:
        """Fractional Kelly: f* = (p*b - q) / b * fraction.

        Regime-conditioned: fraction rejime göre değişir.
        SSRN Regime-Conditioned Kelly (2026) araştırmasına dayalı.
        """
        logger.info("debug_output", message=f"      [KELLY] p={win_prob:.4f}, avg_win={avg_win:.4f}, avg_loss={avg_loss:.4f}, regime={regime}")

        if avg_loss <= 0:
            logger.info("debug_output", message=f"      -> avg_loss<=0, kelly=0")
            return 0.0
        if win_prob <= 0 or win_prob >= 1:
            logger.info("debug_output", message=f"      -> win_prob out of range, kelly=0")
            return 0.0

        q = 1 - win_prob
        b = avg_win / avg_loss  # Odds

        logger.info("debug_output", message=f"      [KELLY] q={q:.4f}, b={b:.4f}")

        raw_kelly = (win_prob * b - q) / b
        logger.info("debug_output", message=f"      [KELLY] raw_kelly={raw_kelly:.4f}")

        # raw_kelly negatifse expectation negatif -> NO TRADE (dogru davranis)
        if raw_kelly <= 0:
            logger.info("debug_output", message=f"      -> raw_kelly<=0 (negative expectation, NO TRADE)")
            return 0.0

        kelly = max(0, min(1, raw_kelly))

        # Regime-conditioned fraction (SSRN 2026)
        regime_fraction = self.REGIME_KELLY_FRACTIONS.get(regime, self.kelly_fraction)
        fractional = kelly * regime_fraction
        logger.info("debug_output", message=f"      [KELLY] clamped={kelly:.4f}, regime_fraction={regime_fraction}, fractional={fractional:.4f}")

        return fractional

    def _volatility_leverage(self, current_vol: float) -> float:
        """Volatilite targeting kaldirac orani."""
        if current_vol <= 0:
            return 1.0
        leverage = self.target_volatility / current_vol
        return round(max(0.5, min(2.0, leverage)), 4)

    @staticmethod
    def _is_valid(val) -> bool:
        """NaN/Inf/None kontrolu."""
        if val is None:
            return False
        if np.isnan(val) or np.isinf(val):
            return False
        return True

    def calculate_var_based_position_limit(
        self,
        returns: np.ndarray,
        max_var_pct: float = 5.0,
        portfolio_value: float = 100000.0,
        confidence: float = 0.95,
    ) -> float:
        """VaR bazlı pozisyon limiti.

        Belirli bir VaR hedefine göre maksimum pozisyon boyutu.
        services/risk/var_cvar.py'deki VaRCalculator.calculate_var_based_position_limit() kullanır.

        Args:
            returns: Hisse getiri dizisi
            max_var_pct: Maksimum VaR yüzdesi (portföyün %'si)
            portfolio_value: Portföy değeri
            confidence: Güven seviyesi

        Returns:
            Maksimum pozisyon değeri (TL)
        """
        try:
            from services.risk.var_cvar import VaRCalculator
            calc = VaRCalculator()
            return calc.calculate_var_based_position_limit(
                returns=returns,
                max_var_pct=max_var_pct,
                portfolio_value=portfolio_value,
                confidence=confidence,
            )
        except ImportError:
            # Fallback: basit VaR bazlı limit
            from scipy.stats import norm
            sigma = np.std(returns, ddof=1) if len(returns) > 1 else 0.2
            if sigma <= 0:
                return portfolio_value * (max_var_pct / 100)
            z_alpha = norm.ppf(confidence)
            max_loss_pct = max_var_pct / 100
            max_position_pct = max_loss_pct / (sigma * z_alpha)
            max_position_pct = min(max_position_pct, 1.0)
            return float(max_position_pct * portfolio_value)


@dataclass
class _CalcResult:
    """Geriye uyumlu calculate() sonuç tipi."""
    shares: int = 0
    position_value: float = 0.0
    position_pct: float = 0.0
    risk_pct: float = 0.0
    method: str = "INVALID"


class _PositionSizerCompat(PositionSizer):
    """Geriye uyumlu calculate() metodu ekler."""

    def calculate(
        self,
        ticker: str,
        entry_price: float,
        stop_price: float,
        portfolio_value: float = 100000,
        max_position_pct: float = 10.0,
        max_risk_per_trade_pct: float = 2.0,
        confidence: float = 0.5,
        volatility: float = 0.2,
        correlation_to_portfolio: float = 0.0,
        var_based_limit: float = 0.0,
        returns: Optional[np.ndarray] = None,
    ) -> _CalcResult:
        """Tek pozisyon boyutu — risk bütçesi yöntemi.

        Geriye uyumlu API: test_phase11_12 tarafından çağrılır.
        """
        # Geçersiz giriş
        if entry_price <= 0 or stop_price <= 0:
            return _CalcResult(method="INVALID")

        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return _CalcResult(method="INVALID")

        stop_pct = stop_distance / entry_price

        # Risk bütçesi
        risk_budget = portfolio_value * (max_risk_per_trade_pct / 100)
        shares_by_risk = int(risk_budget / stop_distance)

        # Max position limit
        max_notional = portfolio_value * (max_position_pct / 100)
        shares_by_max = int(max_notional / entry_price)

        # Korelasyon ayarlaması (yüksek korelasyon → daha az pay)
        corr_factor = max(0.3, 1.0 - correlation_to_portfolio * 0.5)

        # Confidence ayarlaması
        conf_factor = max(0.5, min(1.0, confidence))

        # Minimum hisse
        shares = max(0, min(shares_by_risk, shares_by_max))
        shares = int(shares * corr_factor * conf_factor)

        # VaR bazlı pozisyon limiti (opsiyonel)
        if var_based_limit > 0 or returns is not None:
            try:
                if returns is not None and len(returns) > 10:
                    var_limit = self.calculate_var_based_position_limit(
                        returns=returns,
                        max_var_pct=var_based_limit if var_based_limit > 0 else 5.0,
                        portfolio_value=portfolio_value,
                    )
                    shares_by_var = int(var_limit / entry_price) if entry_price > 0 else 0
                    shares = min(shares, shares_by_var)
            except Exception as e:
                pass  # VaR limit hesaplanamazsa mevcut shares kullan

        if shares <= 0:
            return _CalcResult(method="RISK_BUDGET")

        position_value = shares * entry_price
        position_pct = (position_value / portfolio_value) * 100 if portfolio_value > 0 else 0
        risk_pct = (shares * stop_distance / portfolio_value) * 100 if portfolio_value > 0 else 0

        return _CalcResult(
            shares=shares,
            position_value=round(position_value, 2),
            position_pct=round(position_pct, 2),
            risk_pct=round(risk_pct, 2),
            method="RISK_BUDGET",
        )


# Singleton (geriye uyumlu)
position_sizer = _PositionSizerCompat()
