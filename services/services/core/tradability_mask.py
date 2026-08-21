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

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class MaskResult:
    """Mask sonucu."""
    ticker: str
    mask: np.ndarray        # 1 = valid, 0 = invalid
    reason: Dict[int, str]  # index → neden invalid
    valid_count: int
    total_count: int
    valid_pct: float


class TradabilityMask:
    """Execute edilemeyen fiyatları tespit eden mask."""

    # BIST limit-up/down eşiği (%10 ana pazar, %20 alt pazar)
    LIMIT_UP_PCT = 0.10
    LIMIT_DOWN_PCT = 0.10
    # Küçük hisseler için
    LIMIT_UP_SMALL_PCT = 0.20
    LIMIT_DOWN_SMALL_PCT = 0.20

    # Devre kesici eşiği (BIST: %5, %10, %15, %20)
    CIRCUIT_BREAKER_PCTS = [0.05, 0.10, 0.15, 0.20]

    def compute_mask(
        self,
        ticker: str,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        volume: np.ndarray,
        prev_close: Optional[np.ndarray] = None,
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

        for i in range(n):
            # 1. Sıfır veya negatif fiyat
            if close[i] <= 0:
                mask[i] = 0
                reasons[i] = "zero_negative_price"
                continue

            # 2. Sıfır hacim (işlem gerçekleşmemiş)
            if volume[i] <= 0:
                mask[i] = 0
                reasons[i] = "zero_volume"
                continue

            # 3. OHLC tutarlılığı
            if high[i] < low[i]:
                mask[i] = 0
                reasons[i] = "high_less_than_low"
                continue

            if high[i] < close[i] or low[i] > close[i]:
                mask[i] = 0
                reasons[i] = "ohlc_inconsistent"
                continue

            # 4. Limit-up kontrolü (tavan fiyat)
            if prev_close is not None and i > 0:
                prev = prev_close[i - 1] if i < len(prev_close) else prev_close[-1]
                if prev > 0:
                    daily_change = (close[i] - prev) / prev

                    # Limit-up: fiyat tavana ulaşmış
                    if daily_change >= limit_pct - 0.001:  # %0.1 tolerans
                        mask[i] = 0
                        reasons[i] = f"limit_up_{daily_change:.1%}"
                        continue

                    # Limit-down: fiyat tabana ulaşmış
                    if daily_change <= -limit_pct + 0.001:
                        mask[i] = 0
                        reasons[i] = f"limit_down_{daily_change:.1%}"
                        continue

                    # Devre kesici kontrolü (ani düşüş)
                    for cb_pct in self.CIRCUIT_BREAKER_PCTS:
                        if daily_change <= -cb_pct:
                            mask[i] = 0
                            reasons[i] = f"circuit_breaker_{cb_pct:.0%}"
                            break

            # 5. Ani fiyat sıçraması (veri hatası)
            if i > 0 and close[i - 1] > 0:
                change = abs(close[i] / close[i - 1] - 1)
                if change > 0.30:  # %30+ tek gün hareketi şüpheli
                    mask[i] = 0
                    reasons[i] = f"suspicious_jump_{change:.0%}"
                    continue

            # 6. Spread kontrolü (açılış-kapanış aşırı farklı)
            if open_[i] > 0:
                gap = abs(close[i] / open_[i] - 1)
                if gap > 0.20:  # %20+ gap şüpheli
                    mask[i] = 0
                    reasons[i] = f"large_gap_{gap:.0%}"
                    continue

        valid_count = int(np.sum(mask))
        valid_pct = valid_count / n * 100 if n > 0 else 0

        if valid_pct < 80:
            logger.warning("Low valid data percentage",
                         ticker=ticker,
                         valid_pct=f"{valid_pct:.1f}%",
                         total=n)

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
        features: Dict[str, np.ndarray],
        mask: np.ndarray,
    ) -> Dict[str, np.ndarray]:
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
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Fiyat dizilerine mask uygula."""
        return (
            np.where(mask == 1, open_, np.nan),
            np.where(mask == 1, high, np.nan),
            np.where(mask == 1, low, np.nan),
            np.where(mask == 1, close, np.nan),
            np.where(mask == 1, volume, np.nan),
        )

    def get_mask_stats(self, mask: np.ndarray) -> Dict:
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
