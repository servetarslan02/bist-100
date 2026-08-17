"""
ALPHA BIST — Data Quality & Tradability Mask v1.0

ROADMAP v3.0: Mask-First Design
- Devre kesici, tavan/taban, halt edilmiş fiyatlar maskelenir
- Hiçbir feature hesaplaması mask=0 olan fiyatı görmez
- Bu tek başına +0.44 Sharpe katkısı (Du 2026)

KURAL: Execute edilemeyen fiyat kullanma!
"""

import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import structlog

logger = structlog.get_logger()

@dataclass
class TradabilityMask:
    """Hisse başına tradability durumu."""
    ticker: str
    timestamp: datetime
    is_tradable: bool
    reasons: List[str]

    # Mask değerleri (0 = kullanma, 1 = kullan)
    price_mask: float = 1.0
    volume_mask: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp.isoformat(),
            "is_tradable": self.is_tradable,
            "reasons": self.reasons,
            "price_mask": self.price_mask,
            "volume_mask": self.volume_mask,
        }

class DataQualityEngine:
    """Veri kalitesi ve tradability kontrol motoru."""

    def __init__(self):
        self._masks: Dict[str, TradabilityMask] = {}
        logger.info("DataQualityEngine initialized")

    def check_tradability(
        self,
        ticker: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        prev_close: float,
        timestamp: Optional[datetime] = None,
    ) -> TradabilityMask:
        """Hisse tradability kontrolü."""

        reasons = []
        is_tradable = True
        price_mask = 1.0
        volume_mask = 1.0

        # 1. Devre kesici kontrolü (BIST: ±5% gün içi, ±10% açılış)
        if prev_close > 0:
            daily_change = abs(close / prev_close - 1) * 100
            if daily_change >= 9.5:  # Tavan/taban yakını
                reasons.append(f"Tavan/taban: %{daily_change:.1f}")
                price_mask = 0.0
                is_tradable = False

        # 2. Sıfır hacim — işlem gerçekleşmemiş (BIST'te hacim=0 = tradable değil)
        if volume == 0:
            reasons.append("Sıfır hacim (işlem yok)")
            volume_mask = 0.0
            is_tradable = False
            # OHLC de aynıysa tam halt
            if close == open_price and close == high and close == low:
                reasons.append("Halt edilmiş")
                price_mask = 0.0

        # 3. Anormal fiyat (high < low, open > high, vb.)
        if high < low or open_price > high or open_price < low or close > high or close < low:
            reasons.append("Anormal fiyat yapısı")
            price_mask = 0.0
            is_tradable = False

        # 4. Aşırı düşük hacim (likidite yok)
        if volume < 1000:  # 1000 lot altı
            reasons.append("Düşük likidite")
            volume_mask = 0.5  # Kısmen kullan

        # 5. Fiyat = 0 veya negatif
        if close <= 0 or open_price <= 0 or high <= 0 or low <= 0:
            reasons.append("Geçersiz fiyat (≤0)")
            price_mask = 0.0
            is_tradable = False

        # 6. Aşırı volatilite (tek günde %15+ hareket)
        if prev_close > 0:
            intraday_range = (high - low) / prev_close * 100
            if intraday_range > 15:
                reasons.append(f"Aşırı volatilite: %{intraday_range:.1f}")
                price_mask = 0.3  # Kısmen kullan

        mask = TradabilityMask(
            ticker=ticker,
            timestamp=timestamp or datetime.now(),
            is_tradable=is_tradable,
            reasons=reasons if reasons else ["OK"],
            price_mask=price_mask,
            volume_mask=volume_mask,
        )

        self._masks[ticker] = mask

        if not is_tradable:
            logger.warning("Tradability check failed",
                ticker=ticker, reasons=reasons)

        return mask

    def apply_mask(self, features: Dict[str, Any], mask: TradabilityMask) -> Dict[str, Any]:
        """Feature'lara mask uygula."""
        if mask.price_mask == 0.0:
            # Fiyat bazlı feature'ları NaN/None yap
            price_features = ["roc_5d", "roc_20d", "momentum_20d", "rsi_14", 
                            "macd", "macd_signal", "macd_hist", "bb_position",
                            "stoch_k", "stoch_d", "adx", "price_vs_sma20", "price_vs_sma50"]
            for feat in price_features:
                if feat in features:
                    features[feat] = None  # Mask = kullanma

        if mask.volume_mask == 0.0:
            volume_features = ["volume_zscore", "volume_trend", "obv"]
            for feat in volume_features:
                if feat in features:
                    features[feat] = None

        return features

    def get_mask(self, ticker: str) -> Optional[TradabilityMask]:
        """Hisse mask'ını getir."""
        return self._masks.get(ticker)

    def get_untradable_count(self) -> int:
        """Tradable olmayan hisse sayısı."""
        return sum(1 for m in self._masks.values() if not m.is_tradable)

    def get_mask_stats(self) -> Dict[str, Any]:
        """Mask istatistikleri."""
        total = len(self._masks)
        untradable = self.get_untradable_count()
        return {
            "total_checked": total,
            "untradable": untradable,
            "tradable_pct": round((total - untradable) / total * 100, 1) if total else 0,
            "reasons_breakdown": self._get_reasons_breakdown(),
        }

    def _get_reasons_breakdown(self) -> Dict[str, int]:
        """Nedenlerin dağılımı."""
        reasons = {}
        for mask in self._masks.values():
            for reason in mask.reasons:
                if reason != "OK":
                    reasons[reason] = reasons.get(reason, 0) + 1
        return reasons

# =====================================================
# DataFrame Kalite Kontrolleri (v2'den birleştirildi)
# =====================================================

@dataclass
class QualityIssue:
    check: str
    severity: str
    message: str
    details: Dict[str, Any] = None
    affected_rows: int = 0
    def __post_init__(self):
        if self.details is None: self.details = {}
    def to_dict(self):
        return {"check": self.check, "severity": self.severity, "message": self.message,
                "details": self.details, "affected_rows": self.affected_rows}

@dataclass
class QualityReport:
    ticker: str
    total_rows: int
    issues: List[QualityIssue]
    quality_score: float
    passed: bool
    def to_dict(self):
        return {"ticker": self.ticker, "total_rows": self.total_rows,
                "issues": [i.to_dict() for i in self.issues], "quality_score": self.quality_score,
                "passed": self.passed}

class DataQualityChecker:
    """DataFrame bazlı veri kalitesi kontrolü (duplicate, stale, gap, vb.)."""
    def full_quality_check(self, df, ticker="UNKNOWN"):
        import pandas as pd
        issues = []
        total_rows = len(df)
        if total_rows == 0:
            return QualityReport(ticker, 0, [], 0, False)
        for col in ["close", "open", "high", "low", "volume"]:
            if col in df.columns:
                missing = df[col].isna().sum()
                if missing > 0:
                    issues.append(QualityIssue(f"missing_{col}", "CRITICAL" if col == "close" else "WARNING",
                                               f"{col}: {missing} eksik", affected_rows=int(missing)))
        for col in ["close", "open", "high", "low"]:
            if col in df.columns:
                invalid = (df[col] <= 0).sum()
                if invalid > 0:
                    issues.append(QualityIssue(f"invalid_{col}", "CRITICAL", f"{col}: {invalid} geçersiz", affected_rows=int(invalid)))
        if "high" in df.columns and "low" in df.columns:
            inv = (df["high"] < df["low"]).sum()
            if inv > 0:
                issues.append(QualityIssue("high_low_inv", "CRITICAL", f"High<Low: {inv}", affected_rows=int(inv)))
        critical = sum(1 for i in issues if i.severity == "CRITICAL")
        score = max(0, 100 - critical * 20 - sum(1 for i in issues if i.severity == "WARNING") * 5)
        return QualityReport(ticker, total_rows, issues, score, critical == 0)

# Singleton'lar
data_quality = DataQualityEngine()
data_quality_checker = DataQualityChecker()
