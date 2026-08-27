"""
ALPHA BIST — Data Quality & Tradability Mask v2.0 (Polars-Native)

ROADMAP v3.0: Mask-First Design
- Devre kesici, tavan/taban, halt edilmiş fiyatlar maskelenir
- Hiçbir feature hesaplaması mask=0 olan fiyatı görmez
- Bu tek başına +0.44 Sharpe katkısı (Du 2026)

KURAL: Execute edilemeyen fiyat kullanma!
"""

import copy as _copy
import polars as pl
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class TradabilityMask:
    """Hisse başına tradability durumu."""
    ticker: str
    timestamp: datetime
    is_tradable: bool
    reasons: List[str]
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

        # 1. Devre kesici kontrolü
        if prev_close > 0:
            daily_change = abs(close / prev_close - 1) * 100
            if daily_change >= 9.5:
                reasons.append(f"Tavan/taban: %{daily_change:.1f}")
                price_mask = 0.0
                is_tradable = False

        # 2. Sıfır hacim
        if volume == 0:
            reasons.append("Sıfır hacim (işlem yok)")
            volume_mask = 0.0
            is_tradable = False
            if close == open_price and close == high and close == low:
                reasons.append("Halt edilmiş")
                price_mask = 0.0

        # 3. Anormal fiyat
        if high < low or open_price > high or open_price < low or close > high or close < low:
            reasons.append("Anormal fiyat yapısı")
            price_mask = 0.0
            is_tradable = False

        # 4. Düşük likidite
        if 0 < volume < 1000:
            reasons.append("Düşük likidite")
            volume_mask = 0.5

        # 5. Geçersiz fiyat
        if close <= 0 or open_price <= 0 or high <= 0 or low <= 0:
            reasons.append("Geçersiz fiyat (≤0)")
            price_mask = 0.0
            is_tradable = False

        # 6. Aşırı volatilite
        if prev_close > 0:
            intraday_range = (high - low) / prev_close * 100
            if intraday_range > 15:
                reasons.append(f"Aşırı volatilite: %{intraday_range:.1f}")
                if price_mask > 0.3:
                    price_mask = 0.3

        mask = TradabilityMask(
            ticker=ticker,
            timestamp=timestamp or datetime.now(timezone.utc),
            is_tradable=is_tradable,
            reasons=reasons if reasons else ["OK"],
            price_mask=price_mask,
            volume_mask=volume_mask,
        )
        self._masks[ticker] = mask

        if not is_tradable:
            logger.warning("Tradability check failed", ticker=ticker, reasons=reasons)

        return mask

    def apply_mask(self, raw_data: Dict[str, Any], mask: TradabilityMask, *, copy: bool = False) -> Dict[str, Any]:
        """Ham veriye mask uygula."""
        if copy:
            raw_data = _copy.deepcopy(raw_data)
        if mask.price_mask == 0.0:
            for col in ["open", "high", "low", "close"]:
                if col in raw_data:
                    raw_data[col] = None
        if mask.volume_mask == 0.0:
            if "volume" in raw_data:
                raw_data["volume"] = None
        return raw_data

    def get_mask(self, ticker: str) -> Optional[TradabilityMask]:
        return self._masks.get(ticker)

    def get_untradable_count(self) -> int:
        return sum(1 for m in self._masks.values() if not m.is_tradable)

    def get_mask_stats(self) -> Dict[str, Any]:
        total = len(self._masks)
        untradable = self.get_untradable_count()
        return {
            "total_checked": total,
            "untradable": untradable,
            "tradable_pct": round((total - untradable) / total * 100, 1) if total else 0,
            "reasons_breakdown": self._get_reasons_breakdown(),
        }

    def _get_reasons_breakdown(self) -> Dict[str, int]:
        reasons = {}
        for mask in self._masks.values():
            for reason in mask.reasons:
                if reason != "OK":
                    reasons[reason] = reasons.get(reason, 0) + 1
        return reasons


# =====================================================
# DataFrame Kalite Kontrolleri (Polars-Native)
# =====================================================

@dataclass
class QualityIssue:
    check: str
    severity: str
    message: str
    details: Dict[str, Any] = None
    affected_rows: int = 0

    def __post_init__(self):
        if self.details is None:
            self.details = {}

    def to_dict(self):
        return {
            "check": self.check, "severity": self.severity,
            "message": self.message, "details": self.details,
            "affected_rows": self.affected_rows,
        }


@dataclass
class QualityReport:
    ticker: str
    total_rows: int
    issues: List[QualityIssue]
    quality_score: float
    passed: bool

    def to_dict(self):
        return {
            "ticker": self.ticker, "total_rows": self.total_rows,
            "issues": [i.to_dict() for i in self.issues],
            "quality_score": self.quality_score, "passed": self.passed,
        }


class DataQualityChecker:
    """Polars DataFrame bazlı veri kalitesi kontrolü."""

    def full_quality_check(self, df: pl.DataFrame, ticker: str = "UNKNOWN") -> QualityReport:
        issues = []
        total_rows = len(df)
        if total_rows == 0:
            return QualityReport(ticker, 0, [], 0, False)

        # Date/Timestamp sütunu kontrolü
        date_col = None
        for col_name in ["Date", "date", "timestamp", "Timestamp"]:
            if col_name in df.columns:
                date_col = col_name
                break

        if date_col is not None:
            # Duplicate kontrolü
            dup_count = df[date_col].is_duplicated().sum()
            if dup_count > 0:
                issues.append(QualityIssue(
                    "duplicate_dates", "CRITICAL",
                    f"{dup_count} duplike tarih", affected_rows=int(dup_count),
                ))
            # Sıralama kontrolü
            if not df[date_col].is_sorted():
                issues.append(QualityIssue(
                    "unsorted_timestamps", "WARNING",
                    "Timestamp sıralı değil",
                ))
            # Gap kontrolü (> 5 gün)
            if total_rows > 1:
                try:
                    date_diffs = df[date_col].diff().dt.total_days()
                    large_gaps = (date_diffs > 5).sum()
                    if large_gaps > 0:
                        issues.append(QualityIssue(
                            "large_gaps", "WARNING",
                            f"{large_gaps} büyük zaman aralığı (>5 gün)",
                        ))
                except Exception:
                    pass  # Date diff hesaplanamazsa atla

        # Eksik değer kontrolü
        for col_name in ["close", "Close", "open", "Open", "high", "High", "low", "Low", "volume", "Volume"]:
            if col_name in df.columns:
                missing = df[col_name].null_count()
                if missing > 0:
                    severity = "CRITICAL" if col_name.lower() == "close" else "WARNING"
                    issues.append(QualityIssue(
                        f"missing_{col_name}", severity,
                        f"{col_name}: {missing} eksik", affected_rows=int(missing),
                    ))

        # Geçersiz fiyat kontrolü (≤0)
        for col_name in ["close", "Close", "open", "Open", "high", "High", "low", "Low"]:
            if col_name in df.columns:
                invalid = (df[col_name] <= 0).sum()
                if invalid > 0:
                    issues.append(QualityIssue(
                        f"invalid_{col_name}", "CRITICAL",
                        f"{col_name}: {invalid} geçersiz", affected_rows=int(invalid),
                    ))

        # High < Low kontrolü
        high_col = "High" if "High" in df.columns else "high"
        low_col = "Low" if "Low" in df.columns else "low"
        if high_col in df.columns and low_col in df.columns:
            inv = (df[high_col] < df[low_col]).sum()
            if inv > 0:
                issues.append(QualityIssue(
                    "high_low_inv", "CRITICAL",
                    f"High<Low: {inv}", affected_rows=int(inv),
                ))

        critical = sum(1 for i in issues if i.severity == "CRITICAL")
        warnings = sum(1 for i in issues if i.severity == "WARNING")
        score = max(0, 100 - critical * 20 - warnings * 5)
        return QualityReport(ticker, total_rows, issues, score, critical == 0)


# Singleton'lar
data_quality = DataQualityEngine()
data_quality_checker = DataQualityChecker()
