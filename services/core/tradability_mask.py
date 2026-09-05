from typing import Any

"""
ALPHA BIST — Tradability Mask v1.0

Mask-First Design: Hiçbir feature hesaplaması execute edilemeyen fiyat görmemeli.

BIST'te execute edilemeyen fiyatlar:
- Devre kesici (circuit breaker) — işlem durdurulmuş
- Tavan fiyat (limit-up) — fiyat tavana ulaşmış, alım yapılamıyor
- Taban fiyat (limit-down) — fiyat tabana ulaşmış, satım yapılamaz
- Halt — işlem askıya alınmış
- Sıfır hacim — işlem gerçekleşmemiş
- Eksik veri — veri yok

Mask = 1 → Fiyat güvenilir, kullanılabilir
Mask = 0 → Fiyat güvenilir DEĞİL, feature hesaplamasından çıkar

Kaynak: Du (2026) — mask-first design tek başına +0.44 Sharpe katkısı
"""

import functools
from dataclasses import dataclass

import numpy as np
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.tradability_mask")


def otel_trace(span_name: str) -> Any:
    """Decorator to wrap a method in an OTel span."""

    def decorator(func) -> Any:
        """Hedef metodu OpenTelemetry span içine sarar."""
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> Any:
            """Span başlatır ve hedef fonksiyonu çalıştırır."""
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)

        return wrapper

    return decorator


@dataclass
class MaskResult:
    """Mask sonucu."""

    ticker: str
    mask: np.ndarray  # 1 = valid, 0 = invalid
    reason: dict[int, str]  # index → neden invalid
    valid_count: int
    total_count: int
    valid_pct: float


class TradabilityMask:
    """Execute edilemeyen fiyatları tespit eden mask."""

    # BIST limit-up/down eşiği (Eylül 2025 sonrası: tüm pazarlarda %10)
    LIMIT_UP_PCT = 0.10
    LIMIT_DOWN_PCT = 0.10
    # Alt pazar da artık %10 (Eylül 2025 güncel)
    LIMIT_UP_SMALL_PCT = 0.10
    LIMIT_DOWN_SMALL_PCT = 0.10

    # Devre kesici eşiği (BIST: %5, %10, %15, %20)
    CIRCUIT_BREAKER_PCTS = [0.05, 0.10, 0.15, 0.20]

    @otel_trace("tradability_mask.compute_mask")
    def compute_mask(
        self,
        ticker: str,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        prev_close: np.ndarray | None = None,
        is_small_cap: bool = False,
    ) -> MaskResult:
        """Fiyat serisi için tradability mask hesapla.

        Args:
            ticker: Hisse kodu
            open_, high, low, close: OHLCV dizileri
            volume: Hacim dizisi
            prev_close: Önceki kapanış (limit-up/down kontrolü için)
            is_small_cap: Alt pazar hissesi mi? (%20 limit)
        """
        n = len(close)
        mask = np.ones(n, dtype=int)
        reasons = {}

        limit_pct = self.LIMIT_UP_SMALL_PCT if is_small_cap else self.LIMIT_UP_PCT

        # Vektörize temel kontroller
        # 1. Sıfır veya negatif fiyat
        zero_price = close <= 0
        mask[zero_price] = 0
        for i in np.where(zero_price)[0]:
            reasons[i] = "zero_negative_price"

        # 2. Sıfır hacim
        zero_vol = volume <= 0
        mask[zero_vol & (mask == 1)] = 0
        for i in np.where(zero_vol & (mask == 0))[0]:
            if i not in reasons:
                reasons[i] = "zero_volume"

        # 3. OHLC tutarlılığı
        h_lt_l = high < low
        mask[h_lt_l & (mask == 1)] = 0
        for i in np.where(h_lt_l & (mask == 0))[0]:
            if i not in reasons:
                reasons[i] = "high_less_than_low"

        ohlc_incon = (high < close) | (low > close)
        mask[ohlc_incon & (mask == 1)] = 0
        for i in np.where(ohlc_incon & (mask == 0))[0]:
            if i not in reasons:
                reasons[i] = "ohlc_inconsistent"

        # Sıralı kontroller (limit-up/down, gap) — bağımlı olduğu için loop
        for i in range(n):
            if mask[i] == 0:
                continue

            # 4. Limit-up kontrolü
            if prev_close is not None and i > 0:
                prev = prev_close[i - 1] if i < len(prev_close) else prev_close[-1]
                if prev > 0:
                    daily_change = (close[i] - prev) / prev

                    if daily_change >= limit_pct - 0.001:
                        mask[i] = 0
                        reasons[i] = f"limit_up_{daily_change:.1%}"
                        continue

                    if daily_change <= -limit_pct + 0.001:
                        mask[i] = 0
                        reasons[i] = f"limit_down_{daily_change:.1%}"
                        continue

                    for cb_pct in self.CIRCUIT_BREAKER_PCTS:
                        if daily_change <= -cb_pct:
                            mask[i] = 0
                            reasons[i] = f"circuit_breaker_{cb_pct:.0%}"
                            break

            # 5. Ani fiyat sıçraması
            if i > 0 and close[i - 1] > 0:
                change = abs(close[i] / close[i - 1] - 1)
                if change > 0.30:
                    mask[i] = 0
                    reasons[i] = f"suspicious_jump_{change:.0%}"
                    continue

            # 6. Spread kontrolü
            if open_[i] > 0:
                gap = abs(close[i] / open_[i] - 1)
                if gap > 0.20:
                    mask[i] = 0
                    reasons[i] = f"large_gap_{gap:.0%}"
                    continue

        valid_count = int(np.sum(mask))
        valid_pct = valid_count / n * 100 if n > 0 else 0

        if valid_pct < 80:
            logger.warning("Low valid data percentage", ticker=ticker, valid_pct=f"{valid_pct:.1f}%", total=n)

        return MaskResult(
            ticker=ticker,
            mask=mask,
            reason=reasons,
            valid_count=valid_count,
            total_count=n,
            valid_pct=round(valid_pct, 1),
        )

    def apply_mask_to_features(
        self,
        features: dict[str, np.ndarray],
        mask: np.ndarray,
    ) -> dict[str, np.ndarray]:
        """Feature'lara mask uygula — invalid günleri NaN yap.

        Kritik: Mask=0 olan günler feature hesaplamasında KULLANILMAMALI.
        """
        masked = {}
        for name, values in features.items():
            if isinstance(values, np.ndarray) and len(values) == len(mask):
                masked[name] = np.where(mask == 1, values, np.nan)
            else:
                masked[name] = values
        return masked

    def apply_mask_to_prices(
        self,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Fiyat dizilerine mask uygula."""
        return (
            np.where(mask == 1, open_, np.nan),
            np.where(mask == 1, high, np.nan),
            np.where(mask == 1, low, np.nan),
            np.where(mask == 1, close, np.nan),
            np.where(mask == 1, volume, np.nan),
        )

    def get_mask_stats(self, mask: np.ndarray) -> dict:
        """Mask istatistikleri."""
        total = len(mask)
        valid = int(np.sum(mask))
        invalid = total - valid
        return {
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "valid_pct": round(valid / total * 100, 1) if total > 0 else 0,
        }


# Singleton
tradability_mask = TradabilityMask()
