"""
ALPHA BIST — Yukarı Yönlü Getiri Yakalama Doğrulayıcısı (Upside Capture Validator v2.0)

Model tahminlerinin yükseliş dönemlerindeki kazançları yakalama (upside capture)
ve düşüş dönemlerindeki kayıpları sınırlama (downside capture) yetkinliğini ölçer.
Ayrıca XU100 endeksi trend ve volatilite rejimlerini (BULL, BEAR, SIDEWAYS, HIGH_VOL, LOW_VOL)
point-in-time güvenliğiyle sınıflandıran pazar rejimi tespit motorunu barındırır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class UpsideCaptureResult:
    """Yukarı yönlü getiri yakalama analizi sonuç veri modeli."""

    upside_capture_ratio: float
    downside_capture_ratio: float
    capture_spread: float
    up_periods_total: int
    up_periods_correct: int
    down_periods_total: int
    down_periods_correct: int
    is_valid: bool

    def __repr__(self) -> str:
        """Yukarı yönlü yakalama sonucunun okunabilir metin temsili."""
        status = "GEÇERLİ" if self.is_valid else "EŞİK_ALTI"
        return (
            f"UpsideCaptureResult(upside={self.upside_capture_ratio:.1%}, "
            f"downside={self.downside_capture_ratio:.1%}, spread={self.capture_spread:+.1%}, "
            f"durum={status})"
        )


class UpsideCaptureValidator:
    """Modelin yükseliş ve düşüş hareketlerini yakalama kabiliyetini doğrulayan motor."""

    def __init__(self, min_capture_ratio: float = 0.5) -> None:
        """Yukarı yönlü getiri yakalama doğrulama motorunu başlatır.

        Args:
            min_capture_ratio: Asgari kabul edilebilir yukarı yönlü yakalama oranı (varsayılan: 0.50).
        """
        self.min_capture_ratio = min_capture_ratio

    def __repr__(self) -> str:
        """Doğrulayıcının okunabilir metin temsili."""
        return f"UpsideCaptureValidator(min_capture_ratio={self.min_capture_ratio:.1%})"

    def validate(
        self,
        predictions: np.ndarray,
        actual_returns: np.ndarray,
        threshold: float = 0.0,
    ) -> UpsideCaptureResult:
        """Yukarı ve aşağı yönlü getiri yakalama oranlarını hesaplar ve doğrular.

        Args:
            predictions: Model tahminleri (pozitif = yükseliş beklentisi).
            actual_returns: Gerçekleşen getiri dizisi.
            threshold: Yön sınıflandırması için referans eşik değeri (varsayılan: 0.0).

        Returns:
            UpsideCaptureResult: Yakalama oranları, dönem adetleri ve geçerlilik sonucu.
        """
        # Yükseliş ve düşüş maskeleri
        up_mask = actual_returns > threshold
        down_mask = actual_returns <= threshold

        up_total = int(np.sum(up_mask))
        down_total = int(np.sum(down_mask))

        # Doğru tahmin sayıları
        up_correct = int(np.sum(predictions[up_mask] > threshold)) if up_total > 0 else 0
        down_correct = int(np.sum(predictions[down_mask] <= threshold)) if down_total > 0 else 0

        # Yakalama oranları
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
                "Yukarı yönlü yakalama oranı eşiğin altında kaldı",
                upside_capture=round(upside_capture, 4),
                threshold=self.min_capture_ratio,
            )

        return result


# Global Tekil Örnek
upside_capture_validator = UpsideCaptureValidator()


def detect_market_regime_v2(
    xu100_close: np.ndarray | Any,
    current_date: Any,
    short_window: int = 20,
    long_window: int = 60,
    vol_window: int = 20,
) -> str:
    """Trend ve volatilite analizine dayalı olarak piyasa rejimini belirler.

    Args:
        xu100_close: XU100 kapanış fiyat dizisi veya serisi.
        current_date: Point-in-time filtreleme için referans tarih.
        short_window: Kısa vadeli hareketli ortalama penceresi (varsayılan: 20 gün).
        long_window: Uzun vadeli hareketli ortalama penceresi (varsayılan: 60 gün).
        vol_window: Volatilite hesaplama penceresi (varsayılan: 20 gün).

    Returns:
        str: Piyasa rejimi etiketi (BULL_TREND, BEAR_TREND, HIGH_VOL, LOW_VOL, SIDEWAYS).
    """
    try:
        if hasattr(xu100_close, "filter") and hasattr(xu100_close, "index"):
            hist = xu100_close.filter(xu100_close.index <= current_date)
        else:
            hist = xu100_close

        if len(hist) < long_window:
            return "SIDEWAYS"

        prices = hist[-long_window:].to_numpy() if hasattr(hist, "to_numpy") else np.array(hist[-long_window:])
        if len(prices) < long_window:
            return "SIDEWAYS"

        # Hareketli ortalamalar
        sma_short = float(np.mean(prices[-short_window:]))
        sma_long = float(np.mean(prices))
        current_price = float(prices[-1])

        # Yıllıklandırılmış volatilite
        returns = np.diff(np.log(prices[-vol_window:]))
        volatility = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0.0

        # Trend gücü
        trend_strength = (sma_short - sma_long) / sma_long if sma_long > 0 else 0.0

        # Rejim sınıflandırma hiyerarşisi
        if volatility > 0.35:
            return "HIGH_VOL"
        if volatility < 0.12:
            return "LOW_VOL"
        if trend_strength > 0.02 and current_price > sma_short:
            return "BULL_TREND"
        if trend_strength < -0.02 and current_price < sma_short:
            return "BEAR_TREND"
        return "SIDEWAYS"

    except Exception as e:
        logger.warning("Piyasa rejimi tespiti başarısız oldu, varsayılan SIDEWAYS döndürülüyor", hata=str(e))
        return "SIDEWAYS"
