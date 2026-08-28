"""
ALPHA BIST â€” Data Quality & Tradability Mask v3.0 (Great Expectations Style)

ROADMAP v3.0: Enterprise Grade Data Contracts
- Polars-native Expectations Suite yapÄ±sÄ±
- OpenTelemetry metrik ihracÄ±
- Devre kesici, tavan/taban, halt edilmiÅŸ fiyatlar kesin kontratlara tabidir
- KURAL: Execute edilemeyen fiyat kullanma!
"""

from __future__ import annotations

import copy as _copy
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from opentelemetry import metrics

try:
    import polars as pl
except ImportError:
    pl = None

logger = structlog.get_logger(__name__)
meter = metrics.get_meter("alpha.data.quality")

# OpenTelemetry Metrics
VIOLATIONS_COUNTER = meter.create_counter(
    "alpha.data.quality.violations.total",
    description="Total number of data quality expectation violations",
)
QUALITY_SCORE_GAUGE = meter.create_gauge(
    "alpha.data.quality.score",
    description="Overall data quality score (0-100) per check",
)


@dataclass
class TradabilityMask:
    """Hisse baÅŸÄ±na tradability durumu."""

    ticker: str
    timestamp: datetime
    is_tradable: bool
    reasons: list[str]
    price_mask: float = 1.0
    volume_mask: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "timestamp": self.timestamp.isoformat(),
            "is_tradable": self.is_tradable,
            "reasons": self.reasons,
            "price_mask": self.price_mask,
            "volume_mask": self.volume_mask,
        }


@dataclass
class ExpectationResult:
    """Tek bir kuralÄ±n sonucunu tutar."""

    expectation_name: str
    passed: bool
    details: str
    severity: str = "ERROR"  # ERROR, WARNING, INFO
    affected_rows: int = 0


class Expectation(ABC):
    """Base Expectation sÄ±nÄ±fÄ±."""

    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        """GerÃ§ek zamanlÄ± stream/row verisi iÃ§in."""
        pass

    @abstractmethod
    def validate_df(self, df: Any) -> ExpectationResult:
        """Toplu DataFrame iÃ§in (Polars)."""
        pass


class ExpectColumnValuesToBePositive(Expectation):
    def __init__(self, columns: list[str]):
        self.columns = columns

    def get_name(self) -> str:
        return f"ExpectColumnValuesToBePositive({','.join(self.columns)})"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        failed_cols = []
        for col in self.columns:
            val = data.get(col)
            if val is not None and val <= 0:
                failed_cols.append(col)

        if failed_cols:
            return ExpectationResult(self.get_name(), False, f"Columns <= 0: {','.join(failed_cols)}", "CRITICAL")
        return ExpectationResult(self.get_name(), True, "OK")

    def validate_df(self, df: Any) -> ExpectationResult:
        if pl is None or not isinstance(df, pl.DataFrame):
            return ExpectationResult(self.get_name(), True, "Not a Polars DF")

        affected = 0
        for col in self.columns:
            if col in df.columns:
                affected += (df[col] <= 0).sum()

        passed = affected == 0
        return ExpectationResult(
            self.get_name(),
            passed,
            f"{affected} rows failed" if not passed else "OK",
            "CRITICAL" if not passed else "INFO",
            affected,
        )


class ExpectOHLCGeometry(Expectation):
    def get_name(self) -> str:
        return "ExpectOHLCGeometry"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        h, l, o, c = data.get("high"), data.get("low"), data.get("open_price", data.get("open")), data.get("close")
        if any(x is None for x in (h, l, o, c)):
            return ExpectationResult(self.get_name(), True, "Missing OHLC, skipped", "INFO")

        if h < l or o > h or o < l or c > h or c < l:
            return ExpectationResult(self.get_name(), False, "Anormal fiyat yapÄ±sÄ± (H<L veya O/C dÄ±ÅŸarÄ±da)", "CRITICAL")

        return ExpectationResult(self.get_name(), True, "OK")

    def validate_df(self, df: Any) -> ExpectationResult:
        if pl is None or not isinstance(df, pl.DataFrame):
            return ExpectationResult(self.get_name(), True, "Not a Polars DF")

        h = "High" if "High" in df.columns else "high"
        l = "Low" if "Low" in df.columns else "low"
        if h not in df.columns or l not in df.columns:
            return ExpectationResult(self.get_name(), True, "Missing High/Low cols")

        affected = (df[h] < df[l]).sum()
        passed = affected == 0
        return ExpectationResult(
            self.get_name(), passed, f"{affected} rows failed" if not passed else "OK", "CRITICAL", affected
        )


class ExpectCircuitBreakerLimits(Expectation):
    def __init__(self, limit_pct: float = 9.5):
        self.limit_pct = limit_pct

    def get_name(self) -> str:
        return f"ExpectCircuitBreakerLimits(pct={self.limit_pct})"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        c, p = data.get("close"), data.get("prev_close")
        if c is not None and p is not None and p > 0:
            change = abs(c / p - 1) * 100
            if change >= self.limit_pct:
                return ExpectationResult(
                    self.get_name(), False, f"Tavan/taban sÄ±nÄ±rÄ± aÅŸÄ±ldÄ±: %{change:.1f}", "CRITICAL"
                )
        return ExpectationResult(self.get_name(), True, "OK")

    def validate_df(self, df: Any) -> ExpectationResult:
        return ExpectationResult(
            self.get_name(), True, "DF checks not fully supported yet for prev_close without shift"
        )


class ExpectVolumeLiquidityProfile(Expectation):
    def __init__(self, min_volume: float = 1000):
        self.min_volume = min_volume

    def get_name(self) -> str:
        return f"ExpectVolumeLiquidityProfile(min={self.min_volume})"

    def validate_row(self, data: dict[str, Any]) -> ExpectationResult:
        vol = data.get("volume")
        if vol is not None:
            if vol == 0:
                h, l, c, o = (
                    data.get("high"),
                    data.get("low"),
                    data.get("close"),
                    data.get("open_price", data.get("open")),
                )
                if c == o and c == h and c == l:
                    return ExpectationResult(self.get_name(), False, "SÄ±fÄ±r hacim ve Halt edilmiÅŸ", "CRITICAL")
                return ExpectationResult(self.get_name(), False, "SÄ±fÄ±r hacim", "ERROR")
            if 0 < vol < self.min_volume:
                return ExpectationResult(self.get_name(), False, "DÃ¼ÅŸÃ¼k likidite", "WARNING")
        return ExpectationResult(self.get_name(), True, "OK")

    def validate_df(self, df: Any) -> ExpectationResult:
        if pl is None or not isinstance(df, pl.DataFrame):
            return ExpectationResult(self.get_name(), True, "Not a Polars DF")

        v = "Volume" if "Volume" in df.columns else "volume"
        if v not in df.columns:
            return ExpectationResult(self.get_name(), True, "Missing volume col")

        affected_zero = (df[v] == 0).sum()
        affected_low = ((df[v] > 0) & (df[v] < self.min_volume)).sum()

        if affected_zero > 0:
            return ExpectationResult(
                self.get_name(), False, f"{affected_zero} rows zero volume", "ERROR", affected_zero
            )
        if affected_low > 0:
            return ExpectationResult(self.get_name(), False, f"{affected_low} rows low volume", "WARNING", affected_low)

        return ExpectationResult(self.get_name(), True, "OK")


class ExpectationsSuite:
    """Kural setini yÃ¶neten ve Ã§alÄ±ÅŸtÄ±ran Suit."""

    def __init__(self, name: str):
        self.name = name
        self.expectations: list[Expectation] = []

    def add_expectation(self, exp: Expectation):
        self.expectations.append(exp)

    def validate_row(self, ticker: str, data: dict[str, Any]) -> list[ExpectationResult]:
        results = []
        for exp in self.expectations:
            res = exp.validate_row(data)
            results.append(res)
            if not res.passed:
                VIOLATIONS_COUNTER.add(
                    1, {"ticker": ticker, "expectation": res.expectation_name, "severity": res.severity}
                )
        return results

    def validate_df(self, ticker: str, df: Any) -> list[ExpectationResult]:
        results = []
        for exp in self.expectations:
            res = exp.validate_df(df)
            results.append(res)
            if not res.passed:
                VIOLATIONS_COUNTER.add(
                    1, {"ticker": ticker, "expectation": res.expectation_name, "severity": res.severity}
                )
        return results


def _build_financial_suite() -> ExpectationsSuite:
    suite = ExpectationsSuite("BIST_Financial_Contracts")
    suite.add_expectation(
        ExpectColumnValuesToBePositive(["close", "open_price", "high", "low", "open", "High", "Low", "Close"])
    )
    suite.add_expectation(ExpectOHLCGeometry())
    suite.add_expectation(ExpectCircuitBreakerLimits(9.5))
    suite.add_expectation(ExpectVolumeLiquidityProfile(1000))
    return suite


class DataQualityEngine:
    """Veri kalitesi ve tradability kontrol motoru (Expectations tabanlÄ±)."""

    def __init__(self):
        self._masks: dict[str, TradabilityMask] = {}
        self.suite = _build_financial_suite()
        logger.info("DataQualityEngine initialized with ExpectationsSuite")

    def check_tradability(
        self,
        ticker: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        prev_close: float,
        timestamp: datetime | None = None,
    ) -> TradabilityMask:
        """Hisse tradability kontrolÃ¼."""

        data = {
            "open_price": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "prev_close": prev_close,
        }

        results = self.suite.validate_row(ticker, data)

        reasons = []
        is_tradable = True
        price_mask = 1.0
        volume_mask = 1.0

        for res in results:
            if not res.passed:
                reasons.append(res.details)
                if res.severity == "CRITICAL":
                    is_tradable = False
                    price_mask = 0.0
                    if "SÄ±fÄ±r hacim" in res.details:
                        volume_mask = 0.0
                elif res.severity == "ERROR":
                    is_tradable = False
                    if "SÄ±fÄ±r hacim" in res.details:
                        volume_mask = 0.0
                    else:
                        price_mask = 0.0
                elif res.severity == "WARNING":
                    if "DÃ¼ÅŸÃ¼k likidite" in res.details:
                        volume_mask = 0.5

        # Ekstrem volatilite check
        if prev_close > 0:
            intraday_range = (high - low) / prev_close * 100
            if intraday_range > 15:
                reasons.append(f"AÅŸÄ±rÄ± volatilite: %{intraday_range:.1f}")
                if price_mask > 0.3:
                    price_mask = 0.3

        mask = TradabilityMask(
            ticker=ticker,
            timestamp=timestamp or datetime.now(UTC),
            is_tradable=is_tradable,
            reasons=reasons if reasons else ["OK"],
            price_mask=price_mask,
            volume_mask=volume_mask,
        )
        self._masks[ticker] = mask

        if not is_tradable:
            logger.warning("Tradability check failed", ticker=ticker, reasons=reasons)

        return mask

    def apply_mask(self, raw_data: dict[str, Any], mask: TradabilityMask, *, copy: bool = False) -> dict[str, Any]:
        """Ham veriye mask uygula."""
        if copy:
            raw_data = _copy.deepcopy(raw_data)
        if mask.price_mask == 0.0:
            for col in ["open", "high", "low", "close"]:
                if col in raw_data:
                    raw_data[col] = None
        if mask.volume_mask == 0.0 and "volume" in raw_data:
            raw_data["volume"] = None
        return raw_data

    def get_mask(self, ticker: str) -> TradabilityMask | None:
        return self._masks.get(ticker)

    def get_untradable_count(self) -> int:
        return sum(1 for m in self._masks.values() if not m.is_tradable)

    def get_mask_stats(self) -> dict[str, Any]:
        total = len(self._masks)
        untradable = self.get_untradable_count()
        return {
            "total_checked": total,
            "untradable": untradable,
            "tradable_pct": round((total - untradable) / total * 100, 1) if total else 0,
            "reasons_breakdown": self._get_reasons_breakdown(),
        }

    def _get_reasons_breakdown(self) -> dict[str, int]:
        reasons = {}
        for mask in self._masks.values():
            for reason in mask.reasons:
                if reason != "OK":
                    reasons[reason] = reasons.get(reason, 0) + 1
        return reasons


# =====================================================
# DataFrame Kalite Kontrolleri (Polars-Native & Expectations)
# =====================================================


@dataclass
class QualityIssue:
    check: str
    severity: str
    message: str
    details: dict[str, Any] = None
    affected_rows: int = 0

    def __post_init__(self):
        if self.details is None:
            self.details = {}

    def to_dict(self):
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "affected_rows": self.affected_rows,
        }


@dataclass
class QualityReport:
    ticker: str
    total_rows: int
    issues: list[QualityIssue]
    quality_score: float
    passed: bool

    def to_dict(self):
        return {
            "ticker": self.ticker,
            "total_rows": self.total_rows,
            "issues": [i.to_dict() for i in self.issues],
            "quality_score": self.quality_score,
            "passed": self.passed,
        }


class DataQualityChecker:
    """Polars DataFrame bazlÄ± veri kalitesi kontrolÃ¼ (Expectations kullanan)."""

    def __init__(self):
        self.suite = _build_financial_suite()

    def full_quality_check(self, df: Any, ticker: str = "UNKNOWN") -> QualityReport:
        issues = []
        total_rows = len(df) if hasattr(df, "__len__") else 0
        if total_rows == 0:
            return QualityReport(ticker, 0, [], 0, False)

        results = self.suite.validate_df(ticker, df)
        for res in results:
            if not res.passed:
                issues.append(
                    QualityIssue(res.expectation_name, res.severity, res.details, affected_rows=res.affected_rows)
                )

        if pl is not None and isinstance(df, pl.DataFrame):
            # Date/Timestamp sÃ¼tunu kontrolÃ¼
            date_col = None
            for col_name in ["Date", "date", "timestamp", "Timestamp"]:
                if col_name in df.columns:
                    date_col = col_name
                    break

            if date_col is not None:
                # Duplicate kontrolÃ¼
                dup_count = df[date_col].is_duplicated().sum()
                if dup_count > 0:
                    issues.append(
                        QualityIssue(
                            "duplicate_dates",
                            "CRITICAL",
                            f"{dup_count} duplike tarih",
                            affected_rows=int(dup_count),
                        )
                    )
                # SÄ±ralama kontrolÃ¼
                if not df[date_col].is_sorted():
                    issues.append(
                        QualityIssue(
                            "unsorted_timestamps",
                            "WARNING",
                            "Timestamp sÄ±ralÄ± deÄŸil",
                        )
                    )
                # Gap kontrolÃ¼ (> 5 gÃ¼n)
                if total_rows > 1:
                    try:
                        date_diffs = df[date_col].diff().dt.total_days()
                        large_gaps = (date_diffs > 5).sum()
                        if large_gaps > 0:
                            issues.append(
                                QualityIssue(
                                    "large_gaps",
                                    "WARNING",
                                    f"{large_gaps} bÃ¼yÃ¼k zaman aralÄ±ÄŸÄ± (>5 gÃ¼n)",
                                )
                            )
                    except Exception:
                        pass  # Date diff hesaplanamazsa atla

            # Eksik deÄŸer kontrolÃ¼
            for col_name in ["close", "Close", "open", "Open", "high", "High", "low", "Low", "volume", "Volume"]:
                if col_name in df.columns:
                    missing = df[col_name].null_count()
                    if missing > 0:
                        severity = "CRITICAL" if col_name.lower() == "close" else "WARNING"
                        issues.append(
                            QualityIssue(
                                f"missing_{col_name}",
                                severity,
                                f"{col_name}: {missing} eksik",
                                affected_rows=int(missing),
                            )
                        )

        critical = sum(1 for i in issues if i.severity == "CRITICAL")
        warnings = sum(1 for i in issues if i.severity == "WARNING")
        score = max(0.0, 100.0 - critical * 20.0 - warnings * 5.0)

        QUALITY_SCORE_GAUGE.set(score, {"ticker": ticker})

        return QualityReport(ticker, total_rows, issues, score, critical == 0)


# Singleton'lar
data_quality = DataQualityEngine()
data_quality_checker = DataQualityChecker()

