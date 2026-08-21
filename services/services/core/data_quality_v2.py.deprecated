"""
ALPHA BIST — Data Quality v2.0 [DEPRECATED → data_quality.py'ye birleştirildi]

Gelişmiş veri kalitesi kontrolleri.

Kontroller:
- Duplicate veri tespiti
- Veri gecikmesi (stale data)
- Ani veri kopması (gap detection)
- Anormal hacim tespiti
- Fiyat boşlukları (price gaps)
- Veri tutarlılık kontrolü

Kullanım:
    dq = DataQualityV2()
    report = dq.full_quality_check(df, ticker="THYAO")
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


@dataclass
class QualityIssue:
    check: str
    severity: str  # CRITICAL, WARNING, INFO
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    affected_rows: int = 0

    def to_dict(self) -> Dict[str, Any]:
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
    issues: List[QualityIssue]
    quality_score: float  # 0-100
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "total_rows": self.total_rows,
            "issues": [i.to_dict() for i in self.issues],
            "quality_score": self.quality_score,
            "passed": self.passed,
            "critical_count": sum(1 for i in self.issues if i.severity == "CRITICAL"),
            "warning_count": sum(1 for i in self.issues if i.severity == "WARNING"),
        }


class DataQualityV2:
    """Gelişmiş veri kalitesi kontrol motoru."""

    def __init__(
        self,
        max_gap_days: int = 5,
        volume_spike_threshold: float = 5.0,
        price_gap_threshold: float = 0.10,
        stale_days_threshold: int = 3,
    ):
        self._max_gap_days = max_gap_days
        self._volume_spike_threshold = volume_spike_threshold
        self._price_gap_threshold = price_gap_threshold
        self._stale_days_threshold = stale_days_threshold

    def full_quality_check(self, df: pd.DataFrame, ticker: str = "") -> QualityReport:
        """Tüm kalite kontrollerini çalıştır."""
        issues = []

        if df is None or df.empty:
            return QualityReport(ticker=ticker, total_rows=0,
                               issues=[QualityIssue("empty_data", "CRITICAL", "Boş veri")],
                               quality_score=0, passed=False)

        # Kontroller
        issues.extend(self._check_duplicates(df))
        issues.extend(self._check_staleness(df))
        issues.extend(self._check_gaps(df))
        issues.extend(self._check_volume_anomalies(df))
        issues.extend(self._check_price_gaps(df))
        issues.extend(self._check_ohlc_consistency(df))
        issues.extend(self._check_missing_data(df))
        issues.extend(self._check_future_dates(df))

        # Kalite skoru hesapla
        score = self._calculate_score(issues, len(df))

        return QualityReport(
            ticker=ticker,
            total_rows=len(df),
            issues=issues,
            quality_score=score,
            passed=score >= 70 and not any(i.severity == "CRITICAL" for i in issues),
        )

    def _check_duplicates(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Duplicate timestamp kontrolü."""
        issues = []
        dup_count = df.index.duplicated().sum()
        if dup_count > 0:
            issues.append(QualityIssue(
                check="duplicates", severity="WARNING",
                message=f"{dup_count} duplicate timestamp",
                affected_rows=dup_count,
            ))
        return issues

    def _check_staleness(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Veri gecikmesi kontrolü."""
        issues = []
        if len(df) == 0:
            return issues

        last_date = df.index[-1]
        if hasattr(last_date, 'tzinfo') and last_date.tzinfo:
            last_date = last_date.tz_localize(None)

        days_stale = (datetime.now() - last_date).days
        if days_stale > self._stale_days_threshold:
            issues.append(QualityIssue(
                check="staleness", severity="WARNING",
                message=f"Veri {days_stale} gün gecikmeli",
                details={"last_date": str(last_date), "days_stale": days_stale},
            ))
        return issues

    def _check_gaps(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Veri kopması (gap) kontrolü."""
        issues = []
        if len(df) < 2:
            return issues

        dates = pd.Series(df.index)
        gaps = dates.diff().dt.days
        large_gaps = gaps[gaps > self._max_gap_days]

        if len(large_gaps) > 0:
            issues.append(QualityIssue(
                check="gaps", severity="WARNING",
                message=f"{len(large_gaps)} büyük veri boşluğu (>{self._max_gap_days} gün)",
                details={"max_gap_days": int(gaps.max()), "gap_count": len(large_gaps)},
                affected_rows=len(large_gaps),
            ))
        return issues

    def _check_volume_anomalies(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Anormal hacim tespiti."""
        issues = []
        if 'Volume' not in df.columns or len(df) < 10:
            return issues

        vol = df['Volume'].values
        vol_clean = vol[vol > 0]

        if len(vol_clean) < 5:
            return issues

        median_vol = np.median(vol_clean)
        spikes = vol > (median_vol * self._volume_spike_threshold)
        spike_count = np.sum(spikes)

        if spike_count > 0:
            issues.append(QualityIssue(
                check="volume_spike", severity="INFO",
                message=f"{spike_count} anormal hacim artışı (>{self._volume_spike_threshold}x medyan)",
                details={"median_volume": float(median_vol), "spike_count": int(spike_count)},
                affected_rows=int(spike_count),
            ))

        # Sıfır hacim
        zero_vol = np.sum(vol == 0)
        if zero_vol > 0:
            issues.append(QualityIssue(
                check="zero_volume", severity="WARNING",
                message=f"{zero_vol} sıfır hacimli gün",
                affected_rows=int(zero_vol),
            ))

        return issues

    def _check_price_gaps(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Fiyat boşlukları kontrolü."""
        issues = []
        if 'Close' not in df.columns or len(df) < 2:
            return issues

        close = df['Close'].values
        returns = np.abs(np.diff(close) / close[:-1])
        gaps = returns > self._price_gap_threshold
        gap_count = np.sum(gaps)

        if gap_count > 0:
            issues.append(QualityIssue(
                check="price_gaps", severity="INFO",
                message=f"{gap_count} büyük fiyat boşluğu (>%{self._price_gap_threshold*100:.0f})",
                details={"max_gap": float(np.max(returns)), "gap_count": int(gap_count)},
                affected_rows=int(gap_count),
            ))
        return issues

    def _check_ohlc_consistency(self, df: pd.DataFrame) -> List[QualityIssue]:
        """OHLC tutarlılık kontrolü."""
        issues = []
        required = ['Open', 'High', 'Low', 'Close']
        if not all(c in df.columns for c in required):
            return issues

        # High >= Low
        violations = df['High'] < df['Low']
        if violations.any():
            count = violations.sum()
            issues.append(QualityIssue(
                check="ohlc_consistency", severity="CRITICAL",
                message=f"{count} satırda High < Low",
                affected_rows=int(count),
            ))

        # Close High/Low aralığında
        close_outside = (df['Close'] > df['High']) | (df['Close'] < df['Low'])
        if close_outside.any():
            count = close_outside.sum()
            issues.append(QualityIssue(
                check="ohlc_consistency", severity="CRITICAL",
                message=f"{count} satırda Close High/Low aralığında değil",
                affected_rows=int(count),
            ))

        # Negatif fiyat
        for col in required:
            neg = (df[col] < 0).sum()
            if neg > 0:
                issues.append(QualityIssue(
                    check="negative_price", severity="CRITICAL",
                    message=f"{col}'da {neg} negatif değer",
                    affected_rows=int(neg),
                ))

        return issues

    def _check_missing_data(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Eksik veri kontrolü."""
        issues = []
        for col in df.columns:
            null_count = df[col].isnull().sum()
            if null_count > 0:
                pct = null_count / len(df) * 100
                severity = "CRITICAL" if pct > 20 else "WARNING" if pct > 5 else "INFO"
                issues.append(QualityIssue(
                    check="missing_data", severity=severity,
                    message=f"{col}'da {null_count} eksik değer (%{pct:.1f})",
                    affected_rows=int(null_count),
                ))
        return issues

    def _check_future_dates(self, df: pd.DataFrame) -> List[QualityIssue]:
        """Gelecek tarih kontrolü."""
        issues = []
        now = pd.Timestamp.now()
        if df.index.tz:
            now = now.tz_localize(df.index.tz)

        future = df.index[df.index > now]
        if len(future) > 0:
            issues.append(QualityIssue(
                check="future_dates", severity="CRITICAL",
                message=f"{len(future)} gelecek tarihli veri",
                affected_rows=len(future),
            ))
        return issues

    def _calculate_score(self, issues: List[QualityIssue], total_rows: int) -> float:
        """Kalite skoru hesapla (0-100)."""
        score = 100.0
        for issue in issues:
            if issue.severity == "CRITICAL":
                score -= 20
            elif issue.severity == "WARNING":
                score -= 5
            elif issue.severity == "INFO":
                score -= 1
        return max(0, min(100, score))


# Singleton
data_quality_v2 = DataQualityV2()
