# Upside Capture Validator
# Validates model's ability to capture upside moves

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class UpsideCaptureResult:
    """Result of upside capture analysis."""

    upside_capture_ratio: float
    downside_capture_ratio: float
    capture_spread: float
    up_periods_total: int
    up_periods_correct: int
    down_periods_total: int
    down_periods_correct: int
    is_valid: bool


class UpsideCaptureValidator:
    """Validates model's ability to capture upside vs downside moves."""

    def __init__(self, min_capture_ratio: float = 0.5):
        self.min_capture_ratio = min_capture_ratio

    def validate(
        self,
        predictions: np.ndarray,
        actual_returns: np.ndarray,
        threshold: float = 0.0,
    ) -> UpsideCaptureResult:
        """Validate upside capture ratio.

        Args:
            predictions: Model predictions (positive = bullish)
            actual_returns: Actual returns
            threshold: Threshold for classification

        Returns:
            UpsideCaptureResult with capture metrics
        """
        # Up periods (actual return > 0)
        up_mask = actual_returns > threshold
        down_mask = actual_returns <= threshold

        up_total = int(np.sum(up_mask))
        down_total = int(np.sum(down_mask))

        # Correct predictions
        up_correct = int(np.sum(predictions[up_mask] > threshold)) if up_total > 0 else 0
        down_correct = int(np.sum(predictions[down_mask] <= threshold)) if down_total > 0 else 0

        # Capture ratios
        upside_capture = up_correct / up_total if up_total > 0 else 0.0
        downside_capture = down_correct / down_total if down_total > 0 else 0.0
        capture_spread = upside_capture - downside_capture

        is_valid = upside_capture >= self.min_capture_ratio

        result = UpsideCaptureResult(
            upside_capture_ratio=upside_capture,
            downside_capture_ratio=downside_capture,
            capture_spread=capture_spread,
            up_periods_total=up_total,
            up_periods_correct=up_correct,
            down_periods_total=down_total,
            down_periods_correct=down_correct,
            is_valid=is_valid,
        )

        if not is_valid:
            logger.warning(
                "Upside capture below threshold",
                upside_capture=upside_capture,
                threshold=self.min_capture_ratio,
            )

        return result


# Singleton
upside_capture_validator = UpsideCaptureValidator()


def detect_market_regime_v2(
    xu100_close: np.ndarray | object,
    current_date: object,
    short_window: int = 20,
    long_window: int = 60,
    vol_window: int = 20,
) -> str:
    """Detect market regime using trend and volatility analysis.

    V2: Includes V-Dip recovery detection.

    Args:
        xu100_close: XU100 closing prices (array or Series)
        current_date: Current date for filtering
        short_window: Short-term MA window
        long_window: Long-term MA window
        vol_window: Volatility calculation window

    Returns:
        Regime string: BULL_TREND, BEAR_TREND, SIDEWAYS, HIGH_VOL, LOW_VOL
    """
    try:

        if hasattr(xu100_close, "filter"):
            hist = xu100_close.filter(xu100_close.index <= current_date)
        else:
            hist = xu100_close

        if len(hist) < long_window:
            return "SIDEWAYS"

        prices = hist[-long_window:].to_numpy() if hasattr(hist, "to_numpy") else np.array(hist[-long_window:])
        if len(prices) < long_window:
            return "SIDEWAYS"

        # Moving averages
        sma_short = np.mean(prices[-short_window:])
        sma_long = np.mean(prices)
        current_price = prices[-1]

        # Volatility
        returns = np.diff(np.log(prices[-vol_window:]))
        volatility = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0.0

        # Trend detection
        trend_strength = (sma_short - sma_long) / sma_long if sma_long > 0 else 0.0

        # Regime classification
        if volatility > 0.35:
            return "HIGH_VOL"
        elif volatility < 0.12:
            return "LOW_VOL"
        elif trend_strength > 0.02 and current_price > sma_short:
            return "BULL_TREND"
        elif trend_strength < -0.02 and current_price < sma_short:
            return "BEAR_TREND"
        else:
            return "SIDEWAYS"

    except Exception as e:
        logger.warning("Regime detection failed", error=str(e))
        return "SIDEWAYS"
