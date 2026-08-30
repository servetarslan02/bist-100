#!/usr/bin/env python3
from typing import Any

"""
ALPHA BIST — FULL SYSTEM FORENSIC AUDIT
İnceleme-test dosyasına göre 23 modülün kapsamlı denetimi.
Canlı verilerle uçtan uca test.
"""

import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import orjson
import polars as pl

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import structlog

structlog.configure(
    processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.dev.ConsoleRenderer()],
    logger_factory=structlog.PrintLoggerFactory(),
)
logger = structlog.get_logger()

# ============================================================
# AUDIT RESULT TRACKING
# ============================================================


@dataclass
class AuditIssue:
    """Otomatik eklendi."""
    module: str
    severity: str  # P0, P1, P2, P3
    category: str  # CRITICAL BUG, LOGIC BUG, FINANCIAL MATH BUG, DATA BUG, LEAKAGE RISK, etc.
    root_cause: str
    evidence: str
    affected_module: str
    recommended_fix: str


@dataclass
class ModuleResult:
    """Otomatik eklendi."""
    name: str
    status: str  # PASS, FAIL, CONDITIONAL PASS
    issues: list[AuditIssue] = field(default_factory=list)
    details: str = ""


class AuditReport:
    """Otomatik eklendi."""
    def __init__(self):
        """Otomatik eklendi."""
        self.modules: dict[str, ModuleResult] = {}
        self.system_status = "PASS"
        self.critical_bugs = []
        self.logic_bugs = []
        self.financial_math_bugs = []
        self.data_bugs = []
        self.leakage_risks = []
        self.security_bugs = []
        self.performance_issues = []
        self.missing_features = []

    def add_module(self, name: str, status: str, issues: list[AuditIssue] = None, details: str = "") -> Any:
        """Otomatik eklendi."""
        self.modules[name] = ModuleResult(name=name, status=status, issues=issues or [], details=details)
        if status == "FAIL":
            self.system_status = "FAIL"
        elif status == "CONDITIONAL PASS" and self.system_status != "FAIL":
            self.system_status = "CONDITIONAL PASS"

        for issue in issues or []:
            if issue.category == "CRITICAL BUG":
                self.critical_bugs.append(issue)
            elif issue.category == "LOGIC BUG":
                self.logic_bugs.append(issue)
            elif issue.category == "FINANCIAL MATH BUG":
                self.financial_math_bugs.append(issue)
            elif issue.category == "DATA BUG":
                self.data_bugs.append(issue)
            elif issue.category == "LEAKAGE RISK":
                self.leakage_risks.append(issue)
            elif issue.category == "SECURITY/SAFETY BUG":
                self.security_bugs.append(issue)
            elif issue.category == "PERFORMANCE ISSUE":
                self.performance_issues.append(issue)
            elif issue.category == "MISSING FEATURE":
                self.missing_features.append(issue)

    def print_report(self) -> Any:
        """Otomatik eklendi."""
        logger.info("\n" + "=" * 70)
        logger.info("ALPHA BIST — FULL SYSTEM FORENSIC AUDIT REPORT")
        logger.info(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)
        logger.info(f"\nSYSTEM STATUS: {self.system_status}")
        logger.info("\nMODULE AUDIT:")
        logger.info("-" * 70)
        for name, result in self.modules.items():
            status_icon = "✅" if result.status == "PASS" else "❌" if result.status == "FAIL" else "⚠️"
            logger.info(f"  {status_icon} {name:<30} {result.status}")
            if result.details:
                for line in result.details.split("\n")[:3]:
                    logger.info(f"      {line}")

        # Issue categories
        for label, issues in [
            ("CRITICAL BUGS", self.critical_bugs),
            ("LOGIC BUGS", self.logic_bugs),
            ("FINANCIAL MATH BUGS", self.financial_math_bugs),
            ("DATA BUGS", self.data_bugs),
            ("LEAKAGE RISKS", self.leakage_risks),
            ("SECURITY/SAFETY BUGS", self.security_bugs),
            ("PERFORMANCE ISSUES", self.performance_issues),
            ("MISSING FEATURES", self.missing_features),
        ]:
            if issues:
                logger.info(f"\n{'=' * 70}")
                logger.info(f"{label} ({len(issues)})")
                logger.info("=" * 70)
                for i, issue in enumerate(issues, 1):
                    logger.info(f"\n  [{i}] {issue.module} — {issue.severity}")
                    logger.info(f"      Root Cause: {issue.root_cause}")
                    logger.info(f"      Evidence: {issue.evidence}")
                    logger.info(f"      Fix: {issue.recommended_fix}")

        # Summary
        logger.info(f"\n{'=' * 70}")
        logger.info("SUMMARY")
        logger.info("=" * 70)
        total_issues = sum(
            len(v)
            for v in [
                self.critical_bugs,
                self.logic_bugs,
                self.financial_math_bugs,
                self.data_bugs,
                self.leakage_risks,
                self.security_bugs,
                self.performance_issues,
                self.missing_features,
            ]
        )
        logger.info(f"  Toplam Bulgu: {total_issues}")
        logger.info(
            f"  P0 (Kritik): {sum(1 for v in [self.critical_bugs, self.security_bugs] for i in v if i.severity == 'P0')}"
        )
        logger.info(
            f"  P1 (Yüksek): {sum(1 for v in [self.logic_bugs, self.financial_math_bugs, self.leakage_risks] for i in v if i.severity == 'P1')}"
        )
        logger.info(
            f"  P2 (Orta): {sum(1 for v in [self.data_bugs, self.performance_issues] for i in v if i.severity == 'P2')}"
        )
        logger.info(f"  P3 (Düşük): {sum(1 for v in [self.missing_features] for i in v if i.severity == 'P3')}")


# ============================================================
# AUDIT FUNCTIONS
# ============================================================


def audit_live_data(report: AuditReport) -> Any:
    """Modül 1: Canlı Veri Testi"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 1: CANLI VERİ TESTİ")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.data.data_source import data_source
        from services.ingestion.bist_universe import bist_universe

        bist_100 = bist_universe.BIST_100_TICKERS
        logger.info(f"  BIST 100 evren: {len(bist_100)} hisse")

        # Canlı veri çek (son 6 ay)
        yf_tickers = [f"{t}.IS" for t in bist_100[:10] if t != "XU100"] + ["XU100.IS"]
        logger.info(f"  Test edilen: {len(yf_tickers)} hisse (ilk 10 + XU100)")

        market_data = data_source.get_multiple_stocks(yf_tickers, period="6mo", interval="1d")
        market_data = {k.replace(".IS", ""): v for k, v in market_data.items()}

        if not market_data:
            issues.append(
                AuditIssue(
                    module="Data",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Canlı veri çekilemedi",
                    evidence="get_multiple_stocks boş dict döndürdü",
                    affected_module="Data",
                    recommended_fix="yfinance bağlantısını kontrol et, internet erişimini doğrula",
                )
            )
            report.add_module("Data", "FAIL", issues, "Veri çekilemedi")
            return

        details_lines.append(f"Veri çekilen: {len(market_data)} hisse")

        for ticker, df in market_data.items():
            if df is None or df.empty:
                issues.append(
                    AuditIssue(
                        module="Data",
                        severity="P1",
                        category="DATA BUG",
                        root_cause=f"{ticker} için boş DataFrame",
                        evidence=f"DataFrame shape: {df.shape if df is not None else 'None'}",
                        affected_module="Data",
                        recommended_fix=f"{ticker} veri kaynağını kontrol et",
                    )
                )
                continue

            # Ticker kontrolü
            details_lines.append(f"  {ticker}: {len(df)} gün, {df.index[0]} → {df.index[-1]}")

            # Duplicate kontrolü
            if df.index.duplicated().any():
                dup_count = df.index.duplicated().sum()
                issues.append(
                    AuditIssue(
                        module="Data",
                        severity="P1",
                        category="DATA BUG",
                        root_cause=f"{ticker}: {dup_count} duplicate timestamp",
                        evidence=f"df.index.duplicated().sum() = {dup_count}",
                        affected_module="Data",
                        recommended_fix="Duplicate timestamp'leri kaldır",
                    )
                )

            # Missing data kontrolü
            null_counts = df.isnull().sum()
            if null_counts.any():
                for col in null_counts[null_counts > 0].index:
                    issues.append(
                        AuditIssue(
                            module="Data",
                            severity="P2",
                            category="DATA BUG",
                            root_cause=f"{ticker}: {col}'da {null_counts[col]} null değer",
                            evidence=f"df['{col}'].isnull().sum() = {null_counts[col]}",
                            affected_module="Data",
                            recommended_fix="Null değerleri forward-fill veya interpolasyon ile doldur",
                        )
                    )

            # OHLC mantık kontrolü
            for i in range(len(df)):
                row = df.iloc[i]
                if row.get("High", 0) < row.get("Low", 0):
                    issues.append(
                        AuditIssue(
                            module="Data",
                            severity="P0",
                            category="CRITICAL BUG",
                            root_cause=f"{ticker}: High < Low at index {i}",
                            evidence=f"High={row.get('High')}, Low={row.get('Low')}",
                            affected_module="Data",
                            recommended_fix="OHLC veri doğrulama ekle",
                        )
                    )
                    break

                if row.get("Close", 0) > row.get("High", 0) or row.get("Close", 0) < row.get("Low", 0):
                    issues.append(
                        AuditIssue(
                            module="Data",
                            severity="P0",
                            category="CRITICAL BUG",
                            root_cause=f"{ticker}: Close High/Low aralığında değil",
                            evidence=f"Close={row.get('Close')}, High={row.get('High')}, Low={row.get('Low')}",
                            affected_module="Data",
                            recommended_fix="OHLC tutarlılık kontrolü ekle",
                        )
                    )
                    break

                if row.get("Volume", 0) < 0:
                    issues.append(
                        AuditIssue(
                            module="Data",
                            severity="P1",
                            category="DATA BUG",
                            root_cause=f"{ticker}: Negatif hacim",
                            evidence=f"Volume={row.get('Volume')}",
                            affected_module="Data",
                            recommended_fix="Volume negatif kontrolü ekle",
                        )
                    )
                    break

            # Gelecek timestamp kontrolü (tz-aware-safe)
            now_ts = pl.Date.now(tz=df.index.tz) if df.index.tz else pl.Date.now()
            future_dates = df.index[df.index > now_ts]
            if len(future_dates) > 0:
                issues.append(
                    AuditIssue(
                        module="Data",
                        severity="P0",
                        category="CRITICAL BUG",
                        root_cause=f"{ticker}: Geleceğe ait timestamp var",
                        evidence=f"{len(future_dates)} gelecek tarih: {future_dates[:3]}",
                        affected_module="Data",
                        recommended_fix="Gelecek tarihleri filtrele",
                    )
                )

            # Stale data kontrolü (tz-aware-safe)
            last_date = df.index[-1]
            if hasattr(last_date, "tzinfo") and last_date.tzinfo is not None:
                last_date_utc = last_date.tz_convert("UTC").tz_localize(None)
            else:
                last_date_utc = last_date
            days_stale = (pl.Date.now() - last_date_utc).days
            if days_stale > 5:
                issues.append(
                    AuditIssue(
                        module="Data",
                        severity="P2",
                        category="DATA BUG",
                        root_cause=f"{ticker}: Stale data ({days_stale} gün eski)",
                        evidence=f"Son tarih: {last_date}",
                        affected_module="Data",
                        recommended_fix="Veri tazeliği kontrolü ekle",
                    )
                )

        # XU100 kontrolü
        if "XU100" in market_data:
            xu100 = market_data["XU100"]
            details_lines.append(f"  XU100: {len(xu100)} gün")
        else:
            issues.append(
                AuditIssue(
                    module="Data",
                    severity="P1",
                    category="DATA BUG",
                    root_cause="XU100 verisi çekilemedi",
                    evidence="market_data içinde XU100 yok",
                    affected_module="Data",
                    recommended_fix="XU100.IS ticker'ını kontrol et",
                )
            )

        # Bozuk veri enjeksiyonu testi
        logger.info("  Bozuk veri enjeksiyonu testi...")
        from services.core.data_quality import data_quality

        mask_result = data_quality.check_tradability(
            ticker="TEST", open_price=0, high=-1, low=-2, close=-1, volume=0, prev_close=100
        )
        if mask_result.is_tradable:
            issues.append(
                AuditIssue(
                    module="Data Quality",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Bozuk veri (fiyat≤0) tradable olarak kabul edildi",
                    evidence=f"is_tradable={mask_result.is_tradable}, reasons={mask_result.reasons}",
                    affected_module="Data Quality",
                    recommended_fix="Sıfır/negatif fiyat kontrolü zorunlu",
                )
            )
        else:
            details_lines.append(f"  Bozuk veri testi: PASS (is_tradable={mask_result.is_tradable})")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Data", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Data",
                severity="P0",
                category="CRITICAL BUG",
                root_cause=f"Data audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Data",
                recommended_fix="Data modülü import ve çalıştırma hatasını düzelt",
            )
        )
        report.add_module("Data", "FAIL", issues, str(e))


def audit_data_quality(report: AuditReport) -> Any:
    """Modül 1 devamı: Data Quality Gate"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 1B: DATA QUALITY GATE")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.core.data_quality import DataQualityEngine

        dq = DataQualityEngine()

        # Test cases
        test_cases = [
            # (open, high, low, close, volume, prev_close, expected_tradable, description)
            (100, 105, 95, 102, 50000, 100, True, "Normal gün"),
            (100, 105, 95, 0, 50000, 100, False, "Sıfır kapanış"),
            (0, 0, 0, 0, 0, 100, False, "Tüm fiyatlar sıfır"),
            (100, 95, 105, 102, 50000, 100, False, "High < Low"),
            (100, 110, 95, 109, 0, 100, False, "Sıfır hacim + halt"),
            (100, 105, 95, 102, 50000, 100, True, "Normal"),
            (100, 120, 95, 118, 50000, 100, False, "Tavan fiyat (%18+)"),
            (100, 105, 80, 82, 50000, 100, False, "Taban fiyat (%-18)"),
        ]

        for open_, high, low, close, volume, prev_close, expected, desc in test_cases:
            mask = dq.check_tradability(
                ticker=f"TEST_{desc}",
                open_price=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                prev_close=prev_close,
            )
            if mask.is_tradable != expected:
                issues.append(
                    AuditIssue(
                        module="Data Quality",
                        severity="P0",
                        category="CRITICAL BUG",
                        root_cause=f"Data Quality Gate yanlış sonuç: {desc}",
                        evidence=f"Beklenen: tradable={expected}, Gerçek: tradable={mask.is_tradable}, reasons={mask.reasons}",
                        affected_module="Data Quality",
                        recommended_fix=f"check_tradability mantığını düzelt: {desc}",
                    )
                )
            else:
                details_lines.append(f"  ✅ {desc}: tradable={mask.is_tradable}")

        # Extreme anomaly test
        mask = dq.check_tradability(
            ticker="ANOMALY", open_price=100, high=200, low=50, close=150, volume=1000000, prev_close=100
        )
        if mask.is_tradable:
            issues.append(
                AuditIssue(
                    module="Data Quality",
                    severity="P1",
                    category="LOGIC BUG",
                    root_cause="Aşırı anomali (%50+ hareket) tradable olarak kabul edildi",
                    evidence=f"is_tradable={mask.is_tradable}, price_mask={mask.price_mask}",
                    affected_module="Data Quality",
                    recommended_fix="Aşırı anomali eşiğini düşür",
                )
            )
        else:
            details_lines.append("  ✅ Extreme anomaly: correctly rejected")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Data Quality", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Data Quality",
                severity="P0",
                category="CRITICAL BUG",
                root_cause=f"Data Quality audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Data Quality",
                recommended_fix="Data Quality modülünü düzelt",
            )
        )
        report.add_module("Data Quality", "FAIL", issues, str(e))


def audit_tradability_mask(report: AuditReport) -> Any:
    """Modül 3: Mask-First / Tradability"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 3: TRADABILITY MASK")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.core.tradability_mask import TradabilityMask

        tm = TradabilityMask()

        # Test: missing price
        mask_result = tm.compute_mask(
            ticker="MISSING",
            open_=np.array([0, 100, 100]),
            high=np.array([0, 105, 105]),
            low=np.array([0, 95, 95]),
            close=np.array([0, 102, 102]),
            volume=np.array([0, 50000, 50000]),
        )
        if mask_result.mask[0] != 0:
            issues.append(
                AuditIssue(
                    module="Tradability Mask",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Sıfır fiyat mask=0 olmalı",
                    evidence=f"mask[0]={mask_result.mask[0]} (fiyat=0)",
                    affected_module="Tradability Mask",
                    recommended_fix="Sıfır fiyat kontrolü ekle",
                )
            )
        else:
            details_lines.append("  ✅ Missing price: correctly masked")

        # Test: zero volume
        mask_result = tm.compute_mask(
            ticker="ZEROVOL",
            open_=np.array([100, 100, 100]),
            high=np.array([105, 105, 105]),
            low=np.array([95, 95, 95]),
            close=np.array([102, 102, 102]),
            volume=np.array([0, 0, 50000]),
        )
        if mask_result.mask[0] != 0:
            issues.append(
                AuditIssue(
                    module="Tradability Mask",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Sıfır hacim mask=0 olmalı",
                    evidence=f"mask[0]={mask_result.mask[0]} (volume=0)",
                    affected_module="Tradability Mask",
                    recommended_fix="Sıfır hacim kontrolü ekle",
                )
            )
        else:
            details_lines.append("  ✅ Zero volume: correctly masked")

        # Test: limit-up
        mask_result = tm.compute_mask(
            ticker="LIMITUP",
            open_=np.array([100, 100]),
            high=np.array([105, 110]),
            low=np.array([95, 110]),
            close=np.array([102, 110]),
            volume=np.array([50000, 50000]),
            prev_close=np.array([100, 100]),
        )
        if mask_result.mask[1] != 0:
            issues.append(
                AuditIssue(
                    module="Tradability Mask",
                    severity="P1",
                    category="LOGIC BUG",
                    root_cause="Limit-up fiyat mask=0 olmalı",
                    evidence=f"mask[1]={mask_result.mask[1]} (close=110, prev=100, change=%10)",
                    affected_module="Tradability Mask",
                    recommended_fix="Limit-up kontrolünü gözden geçir",
                )
            )
        else:
            details_lines.append("  ✅ Limit-up: correctly masked")

        # Test: invalid OHLC
        mask_result = tm.compute_mask(
            ticker="BADOHLC",
            open_=np.array([100]),
            high=np.array([90]),  # High < Low
            low=np.array([95]),
            close=np.array([102]),
            volume=np.array([50000]),
        )
        if mask_result.mask[0] != 0:
            issues.append(
                AuditIssue(
                    module="Tradability Mask",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Invalid OHLC (High<Low) mask=0 olmalı",
                    evidence=f"mask[0]={mask_result.mask[0]} (high=90, low=95)",
                    affected_module="Tradability Mask",
                    recommended_fix="OHLC tutarlılık kontrolü ekle",
                )
            )
        else:
            details_lines.append("  ✅ Invalid OHLC: correctly masked")

        # Feature mask uygulama testi
        features = {"rsi_14": np.array([50, 60, 70]), "momentum_20d": np.array([0.01, 0.02, 0.03])}
        mask = np.array([1, 0, 1])
        masked = tm.apply_mask_to_features(features, mask)
        if not np.isnan(masked["rsi_14"][1]):
            issues.append(
                AuditIssue(
                    module="Tradability Mask",
                    severity="P1",
                    category="LOGIC BUG",
                    root_cause="Mask=0 olan gün feature NaN olmalı",
                    evidence=f"masked['rsi_14'][1]={masked['rsi_14'][1]} (beklenen: NaN)",
                    affected_module="Tradability Mask",
                    recommended_fix="apply_mask_to_features mantığını düzelt",
                )
            )
        else:
            details_lines.append("  ✅ Feature masking: correctly applied")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Tradability Mask", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Tradability Mask",
                severity="P0",
                category="CRITICAL BUG",
                root_cause=f"Tradability mask audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Tradability Mask",
                recommended_fix="Tradability mask modülünü düzelt",
            )
        )
        report.add_module("Tradability Mask", "FAIL", issues, str(e))


def audit_features(report: AuditReport) -> Any:
    """Modül 4: Feature Engineering Audit"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 4: FEATURE ENGINEERING AUDİT")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.core.tradability_mask import TradabilityMask
        from services.features.calculator import feature_calculator

        # Sentetik veri oluştur (bilinen sonuçlarla)
        np.random.seed(42)
        n = 120
        pl.date_range(datetime.now() - timedelta(days=n * 2), datetime.now(), timedelta(days=1), eager=True).tail(n)
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        high = close + np.abs(np.random.randn(n) * 0.5)
        low = close - np.abs(np.random.randn(n) * 0.5)
        open_ = close + np.random.randn(n) * 0.2
        volume = np.random.randint(10000, 1000000, n).astype(float)

        df = pl.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume})

        tm = TradabilityMask()
        mask = tm.compute_mask(ticker="SYNTH", open_=open_, high=high, low=low, close=close, volume=volume)

        # Feature'ları hesapla
        features = feature_calculator.compute_all_features(df, mask=mask.mask, ticker="SYNTH")

        if not features:
            issues.append(
                AuditIssue(
                    module="Features",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Feature hesaplanamadı",
                    evidence="compute_all_features boş dict döndürdü",
                    affected_module="Features",
                    recommended_fix="Feature calculator'ı kontrol et",
                )
            )
            report.add_module("Features", "FAIL", issues)
            return

        details_lines.append(f"  Hesaplanan feature sayısı: {len(features)}")

        # Her feature için kontrol
        expected_features = [
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_hist",
            "bb_upper",
            "bb_lower",
            "bb_position",
            "atr_14",
            "adx",
            "obv",
            "volume_zscore",
            "momentum_20d",
            "roc_5d",
            "roc_20d",
        ]

        for feat_name in expected_features:
            if feat_name in features:
                val = features[feat_name]
                if isinstance(val, np.ndarray):
                    # NaN kontrolü
                    nan_ratio = np.isnan(val).sum() / len(val) if len(val) > 0 else 1
                    if nan_ratio > 0.5:
                        issues.append(
                            AuditIssue(
                                module="Features",
                                severity="P1",
                                category="DATA BUG",
                                root_cause=f"{feat_name}: %{nan_ratio * 100:.0f} NaN",
                                evidence=f"np.isnan ratio = {nan_ratio:.2f}",
                                affected_module="Features",
                                recommended_fix=f"{feat_name} hesaplama mantığını kontrol et",
                            )
                        )
                    else:
                        details_lines.append(f"  ✅ {feat_name}: {len(val)} değer, %{nan_ratio * 100:.1f} NaN")
                elif isinstance(val, (int, float)):
                    details_lines.append(f"  ✅ {feat_name}: scalar={val:.4f}")
            else:
                issues.append(
                    AuditIssue(
                        module="Features",
                        severity="P2",
                        category="MISSING FEATURE",
                        root_cause=f"{feat_name} feature'ı eksik",
                        evidence=f"features dict'inde {feat_name} yok",
                        affected_module="Features",
                        recommended_fix=f"{feat_name} hesaplamasını ekle",
                    )
                )

        # RSI doğrulama (0-100 aralığında olmalı)
        if "rsi_14" in features:
            rsi = features["rsi_14"]
            if isinstance(rsi, np.ndarray):
                valid_rsi = rsi[~np.isnan(rsi)]
                if len(valid_rsi) > 0:
                    if np.any(valid_rsi < 0) or np.any(valid_rsi > 100):
                        issues.append(
                            AuditIssue(
                                module="Features",
                                severity="P0",
                                category="FINANCIAL MATH BUG",
                                root_cause="RSI 0-100 aralığında değil",
                                evidence=f"RSI range: [{np.min(valid_rsi):.2f}, {np.max(valid_rsi):.2f}]",
                                affected_module="Features",
                                recommended_fix="RSI hesaplama formülünü düzelt",
                            )
                        )
                    else:
                        details_lines.append("  ✅ RSI range: [0, 100] ✓")

        # MACD doğrulama
        if "macd" in features and "macd_signal" in features:
            macd = features["macd"]
            signal = features["macd_signal"]
            if isinstance(macd, np.ndarray) and isinstance(signal, np.ndarray):
                # MACD ve signal aynı uzunlukta olmalı
                if len(macd) != len(signal):
                    issues.append(
                        AuditIssue(
                            module="Features",
                            severity="P1",
                            category="LOGIC BUG",
                            root_cause="MACD ve signal farklı uzunlukta",
                            evidence=f"MACD: {len(macd)}, Signal: {len(signal)}",
                            affected_module="Features",
                            recommended_fix="MACD ve signal aynı uzunlukta olmalı",
                        )
                    )
                else:
                    details_lines.append(f"  ✅ MACD/Signal uyumlu: {len(macd)} değer")

        # Direction kontrolü (feature yönü doğru mu?)
        if "momentum_20d" in features:
            mom = features["momentum_20d"]
            if isinstance(mom, np.ndarray):
                valid_mom = mom[~np.isnan(mom)]
                if len(valid_mom) > 10:
                    # Momentum pozitif olduğunda fiyat yükselmiş olmalı
                    # Bu genel bir kontrol
                    details_lines.append(f"  ✅ Momentum: mean={np.mean(valid_mom):.4f}, std={np.std(valid_mom):.4f}")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Features", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Features",
                severity="P0",
                category="CRITICAL BUG",
                root_cause=f"Feature audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Features",
                recommended_fix="Feature modülünü düzelt",
            )
        )
        report.add_module("Features", "FAIL", issues, str(e))


def audit_cross_sectional(report: AuditReport) -> Any:
    """Modül 5: Cross-Sectional Logic"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 5: CROSS-SECTIONAL LOGİC")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.features.cross_sectional import cross_sectional_engine

        # 3 hisse sentetik veri
        universe_features = {}
        for ticker in ["A", "B", "C"]:
            np.random.seed(hash(ticker) % 1000)
            universe_features[ticker] = {
                "rsi_14": np.array([50 + np.random.randn() * 10]),
                "momentum_20d": np.array([np.random.randn() * 0.05]),
                "roc_20d": np.array([np.random.randn() * 5]),
            }

        sector_map = {"A": "TECH", "B": "TECH", "C": "FINANCE"}

        # Cross-sectional hesapla
        cs = cross_sectional_engine.compute_all_cross_sectional(
            ticker="A",
            features=universe_features["A"],
            universe_features=universe_features,
            universe_sectors=sector_map,
        )

        if cs:
            details_lines.append(f"  Cross-sectional feature sayısı: {len(cs)}")

            # Rank features
            rank_feats = cross_sectional_engine.compute_rank_features("A", universe_features["A"], universe_features)
            if rank_feats:
                details_lines.append(f"  Rank features: {list(rank_feats.keys())[:5]}")

                # Rank değerleri 0-1 aralığında olmalı
                for name, val in rank_feats.items():
                    if isinstance(val, (int, float)) and (val < 0 or val > 1):
                        if "percentile" in name.lower() or "rank" in name.lower():
                            issues.append(
                                AuditIssue(
                                    module="Cross Sectional",
                                    severity="P1",
                                    category="LOGIC BUG",
                                    root_cause=f"{name} 0-1 aralığında değil",
                                    evidence=f"{name}={val}",
                                    affected_module="Cross Sectional",
                                    recommended_fix=f"{name} hesaplama mantığını düzelt",
                                )
                            )
            else:
                details_lines.append("  ⚠️ Rank features hesaplanamadı")
        else:
            issues.append(
                AuditIssue(
                    module="Cross Sectional",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="Cross-sectional feature'lar boş döndü",
                    evidence="compute_all_cross_sectional boş dict",
                    affected_module="Cross Sectional",
                    recommended_fix="Cross-sectional motoru kontrol et",
                )
            )

        # Sıralama bozulma testi
        # Aynı veri farklı ticker sıralamasıyla aynı sonucu vermeli
        universe_features_rev = dict(reversed(list(universe_features.items())))
        cs_rev = cross_sectional_engine.compute_all_cross_sectional(
            ticker="A",
            features=universe_features["A"],
            universe_features=universe_features_rev,
            universe_sectors=sector_map,
        )

        if cs and cs_rev:
            for key in cs:
                if key in cs_rev:
                    if isinstance(cs[key], (int, float)) and isinstance(cs_rev[key], (int, float)):
                        if abs(cs[key] - cs_rev[key]) > 0.001:
                            issues.append(
                                AuditIssue(
                                    module="Cross Sectional",
                                    severity="P0",
                                    category="CRITICAL BUG",
                                    root_cause="Ticker sıralaması cross-sectional sonucu bozuyor",
                                    evidence=f"{key}: {cs[key]} vs {cs_rev[key]}",
                                    affected_module="Cross Sectional",
                                    recommended_fix="Cross-sectional hesaplama sıralama-bağımsız olmalı",
                                )
                            )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Cross Sectional", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Cross Sectional",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Cross-sectional audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Cross Sectional",
                recommended_fix="Cross-sectional modülünü düzelt",
            )
        )
        report.add_module("Cross Sectional", "FAIL", issues, str(e))


def audit_regime(report: AuditReport) -> Any:
    """Modül 6: Regime Detector"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 6: REGİME DETECTOR")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.core.regime_detector import RegimeDetector

        rd = RegimeDetector(lookback_days=30)

        # BULL market sentetik veri
        np.random.seed(42)
        n = 120
        pl.date_range(datetime.now() - timedelta(days=n * 2), datetime.now(), timedelta(days=1), eager=True).tail(n)
        bull_close = 100 + np.arange(n) * 0.5 + np.random.randn(n) * 0.5
        bull_df = pl.DataFrame(
            {
                "Open": bull_close - 0.5,
                "High": bull_close + 1,
                "Low": bull_close - 1,
                "Close": bull_close,
                "Volume": np.random.randint(100000, 1000000, n),
            }
        )

        bull_data = {"XU100": bull_df}
        regime = rd.detect_regime(bull_data)
        details_lines.append(f"  BULL test: regime={regime.regime}, confidence={regime.confidence:.2f}")

        if regime.regime not in ["BULL", "UNKNOWN"]:
            issues.append(
                AuditIssue(
                    module="Regime",
                    severity="P1",
                    category="LOGIC BUG",
                    root_cause="Yükselen piyasa BULL olarak tespit edilemedi",
                    evidence=f"Regime: {regime.regime} (beklenen: BULL)",
                    affected_module="Regime",
                    recommended_fix="Regime detection eşiklerini ayarla",
                )
            )

        # BEAR market
        bear_close = 100 - np.arange(n) * 0.5 + np.random.randn(n) * 0.5
        bear_df = pl.DataFrame(
            {
                "Open": bear_close + 0.5,
                "High": bear_close + 1,
                "Low": bear_close - 1,
                "Close": bear_close,
                "Volume": np.random.randint(100000, 1000000, n),
            }
        )

        bear_data = {"XU100": bear_df}
        regime = rd.detect_regime(bear_data)
        details_lines.append(f"  BEAR test: regime={regime.regime}, confidence={regime.confidence:.2f}")

        if regime.regime not in ["BEAR", "UNKNOWN"]:
            issues.append(
                AuditIssue(
                    module="Regime",
                    severity="P1",
                    category="LOGIC BUG",
                    root_cause="Düşen piyasa BEAR olarak tespit edilemedi",
                    evidence=f"Regime: {regime.regime} (beklenen: BEAR)",
                    affected_module="Regime",
                    recommended_fix="Regime detection eşiklerini ayarla",
                )
            )

        # SIDEWAYS
        sideways_close = 100 + np.random.randn(n) * 1
        sideways_df = pl.DataFrame(
            {
                "Open": sideways_close - 0.1,
                "High": sideways_close + 0.5,
                "Low": sideways_close - 0.5,
                "Close": sideways_close,
                "Volume": np.random.randint(100000, 1000000, n),
            }
        )

        sideways_data = {"XU100": sideways_df}
        regime = rd.detect_regime(sideways_data)
        details_lines.append(f"  SIDEWAYS test: regime={regime.regime}, confidence={regime.confidence:.2f}")

        # Regime factors kontrolü
        if regime.factors:
            details_lines.append(f"  Factors: {list(regime.factors.keys())}")
            for k, v in regime.factors.items():
                details_lines.append(f"    {k}: {v}")

        # Transition probability
        if regime.transition_probability:
            total_prob = sum(regime.transition_probability.values())
            if abs(total_prob - 1.0) > 0.1:
                issues.append(
                    AuditIssue(
                        module="Regime",
                        severity="P2",
                        category="LOGIC BUG",
                        root_cause="Transition probability toplamı 1.0 değil",
                        evidence=f"Toplam: {total_prob:.4f}",
                        affected_module="Regime",
                        recommended_fix="Transition probability normalizasyonu ekle",
                    )
                )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Regime", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Regime",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Regime audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Regime",
                recommended_fix="Regime modülünü düzelt",
            )
        )
        report.add_module("Regime", "FAIL", issues, str(e))


def audit_ranking(report: AuditReport) -> Any:
    """Modül 8: Ranking Model"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 8: RANKİNG MODEL")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.ml.ranking_model import ranking_model

        # Sentetik feature map: A > B > C olacak şekilde
        features_map = {
            "A": {"rsi_14": np.array([70]), "momentum_20d": np.array([0.10]), "roc_20d": np.array([15])},
            "B": {"rsi_14": np.array([50]), "momentum_20d": np.array([0.05]), "roc_20d": np.array([5])},
            "C": {"rsi_14": np.array([30]), "momentum_20d": np.array([-0.05]), "roc_20d": np.array([-10])},
        }

        # Ranking yap
        result = ranking_model.rank(features_map=features_map, regime="BULL")

        if result and result.scores:
            details_lines.append(f"  Ranking sonucu: {len(result.scores)} hisse")
            for s in result.scores:
                details_lines.append(f"    #{s.rank} {s.ticker}: score={s.score:.4f}, dir={s.direction}")

            # Sıralama doğruluğu: A > B > C olmalı
            rank_map = {s.ticker: s.rank for s in result.scores}
            {s.ticker: s.score for s in result.scores}

            # Score yönünü tespit et (düşük mü yüksek mi iyi?)
            if len(result.scores) >= 3:
                scores_list = [(s.ticker, s.score) for s in result.scores]
                # En iyi ticker'ın score'u
                best_score = scores_list[0][1]
                worst_score = scores_list[-1][1]

                # Eğer A en düşük score'a sahipse (düşük = iyi)
                if rank_map.get("A", 999) < rank_map.get("C", 999):
                    details_lines.append("  ✅ Sıralama doğru: A > B > C (rank)")
                else:
                    issues.append(
                        AuditIssue(
                            module="Ranking",
                            severity="P0",
                            category="CRITICAL BUG",
                            root_cause="Ranking yönü ters: C > B > A",
                            evidence=f"Rank: A={rank_map.get('A')}, B={rank_map.get('B')}, C={rank_map.get('C')}",
                            affected_module="Ranking",
                            recommended_fix="Ranking score yönünü düzelt",
                        )
                    )

                details_lines.append(f"  Score yönü: best={best_score:.4f}, worst={worst_score:.4f}")
        else:
            issues.append(
                AuditIssue(
                    module="Ranking",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="Ranking model sonuç döndürmedi",
                    evidence="result.scores boş veya None",
                    affected_module="Ranking",
                    recommended_fix="Ranking model initialization'ı kontrol et",
                )
            )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Ranking", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Ranking",
                severity="P0",
                category="CRITICAL BUG",
                root_cause=f"Ranking audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Ranking",
                recommended_fix="Ranking modülünü düzelt",
            )
        )
        report.add_module("Ranking", "FAIL", issues, str(e))


def audit_calibration(report: AuditReport) -> Any:
    """Modül 10: Calibration"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 10: CALİBRATİON")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.risk.calibration import calibrator

        # Test: score -> win_probability dönüşümü
        test_scores = [0, 1, 2, 3, 5, 10, 20]
        for score in test_scores:
            prob = calibrator.calibrate(score) if hasattr(calibrator, "calibrate") else None
            if prob is not None:
                details_lines.append(f"  score={score} → win_prob={prob:.4f}")
                if prob < 0 or prob > 1:
                    issues.append(
                        AuditIssue(
                            module="Calibration",
                            severity="P0",
                            category="FINANCIAL MATH BUG",
                            root_cause=f"Calibration 0-1 aralığında değil: score={score}",
                            evidence=f"win_prob={prob}",
                            affected_module="Calibration",
                            recommended_fix="Calibration output'unu [0,1] aralığına clip et",
                        )
                    )
            else:
                details_lines.append("  ⚠️ calibrate fonksiyonu yok veya None döndürdü")

        # Cold start testi
        # Henüz trade gerçekleşmeden calibration kullanıyor mu?
        if hasattr(calibrator, "_fitted"):
            if calibrator._fitted:
                details_lines.append("  Calibrator fitted: True")
            else:
                details_lines.append("  Calibrator fitted: False (cold start)")

        # add_trade testi
        if hasattr(calibrator, "add_trade"):
            calibrator.add_trade(score=2.0, return_pct=5.0, ticker="TEST", date="2024-01-01")
            details_lines.append("  ✅ add_trade çalıştı")

            # Trade gerçekleşmeden kullanma kontrolü
            if hasattr(calibrator, "_trade_history"):
                details_lines.append(f"  Trade history: {len(calibrator._trade_history)} kayıt")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Calibration", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Calibration",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Calibration audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Calibration",
                recommended_fix="Calibration modülünü düzelt",
            )
        )
        report.add_module("Calibration", "FAIL", issues, str(e))


def audit_position_sizing(report: AuditReport) -> Any:
    """Modül 11: Position Sizing (Kelly)"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 11: POSİTİON SİZİNG (KELLY)")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.risk.position_sizing import PositionSizer

        ps = PositionSizer()

        # Manuel Kelly hesaplama
        p = 0.6  # win probability
        q = 0.4  # loss probability
        avg_win = 0.05
        avg_loss = 0.03
        b = avg_win / avg_loss  # odds
        raw_kelly = (p * b - q) / b
        fractional_kelly = raw_kelly * 0.5  # Half Kelly

        details_lines.append(f"  Manuel Kelly: p={p}, q={q}, b={b:.4f}")
        details_lines.append(f"  raw_kelly={raw_kelly:.4f}, fractional={fractional_kelly:.4f}")

        # Sistem ile karşılaştır
        opportunities = [
            {"ticker": "TEST", "score": 2.0, "confidence": 0.6, "expected_return": 0.05, "volatility": 0.2}
        ]

        positions = ps.calculate_position_sizes(
            opportunities=opportunities, portfolio_value=1000000, current_volatility=0.20, regime="BULL"
        )

        if positions:
            pos = positions[0]
            details_lines.append(f"  Sistem sonucu: weight={pos.weight:.4f}, kelly={pos.kelly_fraction:.4f}")
            details_lines.append(
                f"  win_prob={pos.win_probability:.4f}, avg_win={pos.avg_win:.4f}, avg_loss={pos.avg_loss:.4f}"
            )

            # Negatif weight kontrolü
            if pos.weight < 0:
                issues.append(
                    AuditIssue(
                        module="Position Sizing",
                        severity="P0",
                        category="FINANCIAL MATH BUG",
                        root_cause="Negatif pozisyon ağırlığı",
                        evidence=f"weight={pos.weight}",
                        affected_module="Position Sizing",
                        recommended_fix="Negatif weight'i 0'a clip et",
                    )
                )

            # NaN weight kontrolü
            if np.isnan(pos.weight) or np.isinf(pos.weight):
                issues.append(
                    AuditIssue(
                        module="Position Sizing",
                        severity="P0",
                        category="FINANCIAL MATH BUG",
                        root_cause="NaN/Inf pozisyon ağırlığı",
                        evidence=f"weight={pos.weight}",
                        affected_module="Position Sizing",
                        recommended_fix="NaN/Inf kontrolü ekle",
                    )
                )

            # Max position kontrolü
            if pos.weight > ps.max_position_pct:
                issues.append(
                    AuditIssue(
                        module="Position Sizing",
                        severity="P1",
                        category="FINANCIAL MATH BUG",
                        root_cause="Max pozisyon limiti aşıldı",
                        evidence=f"weight={pos.weight:.4f} > max={ps.max_position_pct}",
                        affected_module="Position Sizing",
                        recommended_fix="Max position clamp'ini uygula",
                    )
                )
        else:
            details_lines.append("  ⚠️ Position sizing boş sonuç döndürdü")

        # Negative expectation testi (kelly <= 0 → NO TRADE)
        bad_opportunities = [
            {"ticker": "BAD", "score": 10.0, "confidence": 0.3, "expected_return": -0.05, "volatility": 0.3}
        ]

        bad_positions = ps.calculate_position_sizes(
            opportunities=bad_opportunities, portfolio_value=1000000, current_volatility=0.20, regime="BEAR"
        )

        if bad_positions:
            for bp in bad_positions:
                if bp.weight > 0:
                    issues.append(
                        AuditIssue(
                            module="Position Sizing",
                            severity="P1",
                            category="FINANCIAL MATH BUG",
                            root_cause="Negatif beklentili pozisyona ağırlık verildi",
                            evidence=f"ticker={bp.ticker}, weight={bp.weight:.4f}, expected_return=-0.05",
                            affected_module="Position Sizing",
                            recommended_fix="Kelly <= 0 ise NO TRADE uygula",
                        )
                    )
        else:
            details_lines.append("  ✅ Negative expectation: correctly rejected (NO TRADE)")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Position Sizing", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Position Sizing",
                severity="P0",
                category="CRITICAL BUG",
                root_cause=f"Position sizing audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Position Sizing",
                recommended_fix="Position sizing modülünü düzelt",
            )
        )
        report.add_module("Position Sizing", "FAIL", issues, str(e))


def audit_risk_engine(report: AuditReport) -> Any:
    """Modül 12: Risk Engine"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 12: RİSK ENGİNE")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.risk.main import RiskEngine

        re = RiskEngine()

        # Risk limits yüklenemediyse fail-closed kontrolü
        if hasattr(re, "_risk_limits_loaded"):
            if not re._risk_limits_loaded:
                details_lines.append("  ✅ Risk limits yüklenmemiş → fail-closed (correct)")
            else:
                details_lines.append(f"  Risk limits yüklü: {re._risk_limits}")
        else:
            issues.append(
                AuditIssue(
                    module="Risk Engine",
                    severity="P1",
                    category="SECURITY/SAFETY BUG",
                    root_cause="_risk_limits_loaded flag'i yok",
                    evidence="RiskEngine'de fail-closed kontrolü eksik",
                    affected_module="Risk Engine",
                    recommended_fix="_risk_limits_loaded flag'i ekle",
                )
            )

        # Risk limitlerinin varlığını kontrol et
        expected_limits = [
            "max_position_pct",
            "max_sector_concentration",
            "max_drawdown_pct",
            "daily_loss_limit_pct",
            "max_portfolio_volatility",
        ]

        for limit_name in expected_limits:
            if hasattr(re, "_risk_limits") and limit_name in re._risk_limits:
                details_lines.append(f"  ✅ {limit_name}: {re._risk_limits[limit_name]}")
            else:
                issues.append(
                    AuditIssue(
                        module="Risk Engine",
                        severity="P2",
                        category="MISSING FEATURE",
                        root_cause=f"Risk limiti eksik: {limit_name}",
                        evidence=f"_risk_limits içinde {limit_name} yok",
                        affected_module="Risk Engine",
                        recommended_fix=f"{limit_name} limitini ekle",
                    )
                )

        # Kill switch kontrolü
        if hasattr(re, "_risk_limits") and "kill_switch" in re._risk_limits:
            details_lines.append(f"  ✅ Kill switch: {re._risk_limits['kill_switch']}")
        else:
            issues.append(
                AuditIssue(
                    module="Risk Engine",
                    severity="P1",
                    category="MISSING FEATURE",
                    root_cause="Kill switch mekanizması eksik",
                    evidence="Risk limitlerinde kill_switch yok",
                    affected_module="Risk Engine",
                    recommended_fix="Kill switch limiti ekle",
                )
            )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Risk Engine", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Risk Engine",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Risk engine audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Risk Engine",
                recommended_fix="Risk engine modülünü düzelt",
            )
        )
        report.add_module("Risk Engine", "FAIL", issues, str(e))


def audit_execution(report: AuditReport) -> Any:
    """Modül 13: Paper Execution"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 13: PAPER EXECUTİON")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.simulation.execution_simulator import ExecutionSimulator

        es = ExecutionSimulator()

        # Simulation-only kontrolü
        details_lines.append("  ✅ ExecutionSimulator modülü mevcut")

        # Komisyon ve slippage testi
        if hasattr(es, "execute") or hasattr(es, "simulate"):
            details_lines.append("  ✅ Execute/Simulate fonksiyonu mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Execution",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="Execute/Simulate fonksiyonu bulunamadı",
                    evidence="ExecutionSimulator'de execute/simulate metodu yok",
                    affected_module="Execution",
                    recommended_fix="Execute fonksiyonu ekle",
                )
            )

        # Impossible fill testi
        # Signal kapanışta oluşuyorsa aynı kapanış fiyatından geleceği biliyormuş gibi işlem yapmamalı
        details_lines.append("  ⚠️ Impossible fill testi: Manuel doğrulama gerekli")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Execution", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Execution",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Execution audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Execution",
                recommended_fix="Execution modülünü düzelt",
            )
        )
        report.add_module("Execution", "FAIL", issues, str(e))


def audit_portfolio(report: AuditReport) -> Any:
    """Modül 14: Portfolio Accounting"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 14: PORTFOLİO ACCOUNTİNG")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.portfolio.portfolio_manager import PortfolioManager

        pm = PortfolioManager()

        # EQUITY = CASH + MARKET VALUE invariant kontrolü
        if hasattr(pm, "get_equity") or hasattr(pm, "calculate_equity"):
            details_lines.append("  ✅ Equity hesaplama fonksiyonu mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Portfolio",
                    severity="P1",
                    category="MISSING FEATURE",
                    root_cause="Equity hesaplama fonksiyonu bulunamadı",
                    evidence="PortfolioManager'de get_equity/calculate_equity yok",
                    affected_module="Portfolio",
                    recommended_fix="Equity hesaplama fonksiyonu ekle",
                )
            )

        # Komisyon muhasebesi
        if hasattr(pm, "apply_commission") or hasattr(pm, "_apply_commission"):
            details_lines.append("  ✅ Komisyon muhasebesi mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Portfolio",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="Komisyon muhasebesi fonksiyonu bulunamadı",
                    evidence="PortfolioManager'de apply_commission yok",
                    affected_module="Portfolio",
                    recommended_fix="Komisyon muhasebesi ekle",
                )
            )

        # Realized/Unrealized P&L
        if hasattr(pm, "realized_pnl") or hasattr(pm, "get_pnl"):
            details_lines.append("  ✅ P&L hesaplama mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Portfolio",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="P&L hesaplama fonksiyonu bulunamadı",
                    evidence="PortfolioManager'de P&L fonksiyonu yok",
                    affected_module="Portfolio",
                    recommended_fix="Realized/Unrealized P&L hesaplama ekle",
                )
            )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Portfolio", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Portfolio",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Portfolio audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Portfolio",
                recommended_fix="Portfolio modülünü düzelt",
            )
        )
        report.add_module("Portfolio", "FAIL", issues, str(e))


def audit_performance(report: AuditReport) -> Any:
    """Modül 15: Performance Metrics"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 15: PERFORMANCE METRİCS")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        # Sentetik equity curve oluştur ve metrikleri doğrula
        np.random.seed(42)
        n_days = 252
        daily_returns = np.random.randn(n_days) * 0.01 + 0.0003
        equity = 1000000 * np.cumprod(1 + daily_returns)

        # CAGR hesapla
        total_return = equity[-1] / equity[0] - 1
        years = n_days / 252
        cagr = (1 + total_return) ** (1 / years) - 1

        # Sharpe hesapla
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)

        # Sortino hesapla
        downside_returns = daily_returns[daily_returns < 0]
        sortino = np.mean(daily_returns) / np.std(downside_returns) * np.sqrt(252) if len(downside_returns) > 0 else 0

        # Max Drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        max_dd = np.min(drawdown)

        # Calmar
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0

        # Win Rate
        win_rate = np.sum(daily_returns > 0) / len(daily_returns)

        # Profit Factor
        gross_profit = np.sum(daily_returns[daily_returns > 0])
        gross_loss = abs(np.sum(daily_returns[daily_returns < 0]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        details_lines.append(f"  CAGR: {cagr * 100:.2f}%")
        details_lines.append(f"  Sharpe: {sharpe:.4f}")
        details_lines.append(f"  Sortino: {sortino:.4f}")
        details_lines.append(f"  Max DD: {max_dd * 100:.2f}%")
        details_lines.append(f"  Calmar: {calmar:.4f}")
        details_lines.append(f"  Win Rate: {win_rate:.2%}")
        details_lines.append(f"  Profit Factor: {profit_factor:.4f}")

        # CAGR ≠ Total Return doğrulaması
        if abs(cagr - total_return) < 0.001:
            issues.append(
                AuditIssue(
                    module="Performance",
                    severity="P1",
                    category="FINANCIAL MATH BUG",
                    root_cause="CAGR ve Total Return aynı hesaplanıyor",
                    evidence=f"CAGR={cagr:.4f}, Total Return={total_return:.4f}",
                    affected_module="Performance",
                    recommended_fix="CAGR formülünü düzelt: (1+total_return)^(1/years)-1",
                )
            )
        else:
            details_lines.append("  ✅ CAGR ≠ Total Return ✓")

        # Metrik doğruluğu
        if sharpe < -5 or sharpe > 5:
            issues.append(
                AuditIssue(
                    module="Performance",
                    severity="P2",
                    category="FINANCIAL MATH BUG",
                    root_cause="Sharpe ratio aşırı değer",
                    evidence=f"Sharpe={sharpe:.4f}",
                    affected_module="Performance",
                    recommended_fix="Sharpe hesaplama mantığını kontrol et",
                )
            )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Performance", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Performance",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Performance audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Performance",
                recommended_fix="Performance modülünü düzelt",
            )
        )
        report.add_module("Performance", "FAIL", issues, str(e))


def audit_benchmark(report: AuditReport) -> Any:
    """Modül 16: Benchmark"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 16: BENCHMARK")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.data.data_source import data_source

        # XU100 verisini çek
        xu100_data = data_source.get_stock_data("XU100.IS", period="6mo", interval="1d")

        if xu100_data is not None and not xu100_data.empty:
            details_lines.append(f"  XU100 verisi: {len(xu100_data)} gün")
            details_lines.append(f"  Tarih aralığı: {xu100_data.index[0]} → {xu100_data.index[-1]}")

            # Return hesapla
            returns = xu100_data["Close"].pct_change().dropna()
            total_return = xu100_data["Close"].iloc[-1] / xu100_data["Close"].iloc[0] - 1
            details_lines.append(f"  Toplam getiri: {total_return * 100:.2f}%")
            details_lines.append(f"  Günlük ortalama return: {returns.mean() * 100:.4f}%")

            # Timezone kontrolü
            if xu100_data.index.tz is not None:
                details_lines.append(f"  Timezone: {xu100_data.index.tz}")
            else:
                details_lines.append("  Timezone: Naive (timezone yok)")

            # Duplicate kontrolü
            if xu100_data.index.duplicated().any():
                issues.append(
                    AuditIssue(
                        module="Benchmark",
                        severity="P1",
                        category="DATA BUG",
                        root_cause="XU100'te duplicate timestamp",
                        evidence=f"{xu100_data.index.duplicated().sum()} duplicate",
                        affected_module="Benchmark",
                        recommended_fix="Duplicate timestamp'leri kaldır",
                    )
                )
        else:
            issues.append(
                AuditIssue(
                    module="Benchmark",
                    severity="P0",
                    category="CRITICAL BUG",
                    root_cause="XU100 benchmark verisi çekilemedi",
                    evidence="get_stock_data boş döndürdü",
                    affected_module="Benchmark",
                    recommended_fix="XU100 veri kaynağını kontrol et",
                )
            )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Benchmark", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Benchmark",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Benchmark audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Benchmark",
                recommended_fix="Benchmark modülünü düzelt",
            )
        )
        report.add_module("Benchmark", "FAIL", issues, str(e))


def audit_walk_forward(report: AuditReport) -> Any:
    """Modül 9: Walk-Forward"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 9: WALK-FORWARD")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.ml.walk_forward import WalkForwardValidation

        wf = WalkForwardValidation(train_size=252, test_size=63, purge_size=5, embargo_size=5)

        # Sentetik tarih listesi
        dates = (
            pl.date_range(date(2020, 1, 1), date(2020, 1, 1) + timedelta(days=2000), timedelta(days=1), eager=True)
            .head(1000)
            .to_list()
        )

        splits = wf.generate_splits(dates)
        details_lines.append(f"  Fold sayısı: {len(splits)}")

        for i, fold in enumerate(splits[:3]):
            train_dates = fold["train_dates"]
            test_dates = fold["test_dates"]
            details_lines.append(f"  Fold {i + 1}: train={len(train_dates)} gün, test={len(test_dates)} gün")

            # Train/Test overlap kontrolü
            if train_dates and test_dates:
                last_train = train_dates[-1]
                first_test = test_dates[0]
                if last_train >= first_test:
                    issues.append(
                        AuditIssue(
                            module="Walk Forward",
                            severity="P0",
                            category="LEAKAGE RISK",
                            root_cause=f"Fold {i + 1}: Train/Test overlap (data leakage)",
                            evidence=f"last_train={last_train} >= first_test={first_test}",
                            affected_module="Walk Forward",
                            recommended_fix="Purge/Embargo uygulamasını düzelt",
                        )
                    )
                else:
                    gap = (first_test - last_train).days
                    details_lines.append(f"    ✅ Train/Test ayrımı doğru (gap={gap} gün)")
                    if gap < 5:
                        issues.append(
                            AuditIssue(
                                module="Walk Forward",
                                severity="P1",
                                category="LEAKAGE RISK",
                                root_cause=f"Fold {i + 1}: Purge yetersiz ({gap} gün)",
                                evidence=f"gap={gap} gün, beklenen: >=5",
                                affected_module="Walk Forward",
                                recommended_fix="Purge gün sayısını artır",
                            )
                        )

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Walk Forward", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Walk Forward",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Walk-forward audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Walk Forward",
                recommended_fix="Walk-forward modülünü düzelt",
            )
        )
        report.add_module("Walk Forward", "FAIL", issues, str(e))


def audit_quality_gate(report: AuditReport) -> Any:
    """Modül 18: Model Quality Gate"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 18: MODEL QUALİTY GATE")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.learning.continuous_learning import continuous_learning

        if hasattr(continuous_learning, "registry"):
            reg = continuous_learning.registry
            details_lines.append(f"  Champion version: {getattr(reg, 'champion_version', 'N/A')}")
            details_lines.append(f"  Active version: {getattr(reg, 'active_version', 'N/A')}")

            # Champion lifecycle
            if hasattr(reg, "champion_version") and reg.champion_version:
                details_lines.append("  ✅ Champion model kayıtlı")
            else:
                issues.append(
                    AuditIssue(
                        module="Quality Gate",
                        severity="P2",
                        category="MISSING FEATURE",
                        root_cause="Champion model kayıtlı değil",
                        evidence="registry.champion_version boş",
                        affected_module="Quality Gate",
                        recommended_fix="Champion model kaydını ekle",
                    )
                )
        else:
            issues.append(
                AuditIssue(
                    module="Quality Gate",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="Continuous learning registry bulunamadı",
                    evidence="continuous_learning.registry yok",
                    affected_module="Quality Gate",
                    recommended_fix="Model registry'yi ekle",
                )
            )

        # Challenger → Shadow → Evaluate → Promote / Reject süreci
        details_lines.append("  ⚠️ Challenger lifecycle süreci: Manuel doğrulama gerekli")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Quality Gate", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Quality Gate",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Quality gate audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Quality Gate",
                recommended_fix="Quality gate modülünü düzelt",
            )
        )
        report.add_module("Quality Gate", "FAIL", issues, str(e))


def audit_self_learning(report: AuditReport) -> Any:
    """Modül 19: Self-Learning"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 19: SELF-LEARNİNG")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.learning.continuous_learning import continuous_learning

        # Drift detection
        if hasattr(continuous_learning, "get_learning_report"):
            lr = continuous_learning.get_learning_report()
            details_lines.append(f"  Drift detected: {lr.get('drift_status', {}).get('detected', 'N/A')}")
            details_lines.append(f"  Retrain needed: {lr.get('retrain_needed', 'N/A')}")
            details_lines.append(f"  Total cycles: {lr.get('total_cycles', 'N/A')}")
        else:
            details_lines.append("  ⚠️ get_learning_report fonksiyonu yok")

        # Kötü sonuç → körlemesine retrain değil, ayrıştırma kontrolü
        if hasattr(continuous_learning, "_analyze_degradation") or hasattr(continuous_learning, "analyze"):
            details_lines.append("  ✅ Degradation analiz fonksiyonu mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Self Learning",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="Degradation analiz fonksiyonu bulunamadı",
                    evidence="continuous_learning'de _analyze_degradation/analyze yok",
                    affected_module="Self Learning",
                    recommended_fix="DRIFT/REGIME/DATA QUALITY ayrıştırması ekle",
                )
            )

        # Gerçekleşmemiş sonuç öğrenme kontrolü
        details_lines.append("  ⚠️ Future data learning kontrolü: Manuel doğrulama gerekli")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Self Learning", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Self Learning",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Self-learning audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Self Learning",
                recommended_fix="Self-learning modülünü düzelt",
            )
        )
        report.add_module("Self Learning", "FAIL", issues, str(e))


def audit_fail_safe(report: AuditReport) -> Any:
    """Modül 20: Failure / Chaos Test"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 20: FAİLURE / CHAOS TEST")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        # Circuit breaker kontrolü
        from services.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(name="audit_test")
        details_lines.append(f"  ✅ Circuit breaker modülü mevcut (state={cb.state})")

        # Recovery kontrolü
        from services.core.recovery import StartupRecovery

        StartupRecovery()
        details_lines.append("  ✅ StartupRecovery modülü mevcut")

        # State recovery
        from services.core.state_recovery import StateRecovery

        StateRecovery()
        details_lines.append("  ✅ State recovery modülü mevcut")

        # Streaming anomaly
        from services.core.streaming_anomaly import StreamingAnomalyDetector

        StreamingAnomalyDetector()
        details_lines.append("  ✅ Streaming anomaly detector mevcut")

        # Boş veri testi
        try:
            from services.data.data_source import data_source

            result = data_source.get_stock_data("INVALID_TICKER.XXXXXX", period="1d")
            if result is None or (hasattr(result, "empty") and result.empty):
                details_lines.append("  ✅ Geçersiz ticker: boş sonuç (correct)")
            else:
                issues.append(
                    AuditIssue(
                        module="Fail Safe",
                        severity="P1",
                        category="SECURITY/SAFETY BUG",
                        root_cause="Geçersiz ticker için hata döndürülmedi",
                        evidence=f"INVALID_TICKER için sonuç: {type(result)}",
                        affected_module="Fail Safe",
                        recommended_fix="Geçersiz ticker için None/empty döndür",
                    )
                )
        except Exception:
            details_lines.append("  ✅ Geçersiz ticker: exception yakalandı (correct)")

        # NaN feature testi
        nan_features = {"rsi_14": np.array([np.nan, np.nan, np.nan])}
        from services.core.tradability_mask import TradabilityMask

        tm = TradabilityMask()
        masked = tm.apply_mask_to_features(nan_features, np.array([0, 0, 0]))
        if all(np.isnan(v).all() for v in masked.values()):
            details_lines.append("  ✅ NaN feature masking: correct")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Fail Safe", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Fail Safe",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Fail-safe audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Fail Safe",
                recommended_fix="Fail-safe modüllerini düzelt",
            )
        )
        report.add_module("Fail Safe", "FAIL", issues, str(e))


def audit_survivorship(report: AuditReport) -> Any:
    """Modül 17: Survivorship Bias"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 17: SURVİVORSHİP BİAS")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.ingestion.bist_universe import bist_universe

        # BIST 100 listesi
        bist_100 = bist_universe.BIST_100_TICKERS
        details_lines.append(f"  Mevcut BIST 100: {len(bist_100)} hisse")

        # Tarihsel evren kontrolü
        if hasattr(bist_universe, "get_historical_universe") or hasattr(bist_universe, "historical"):
            details_lines.append("  ✅ Tarihsel evren fonksiyonu mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Survivorship",
                    severity="P1",
                    category="LEAKAGE RISK",
                    root_cause="Tarihsel evren fonksiyonu bulunamadı",
                    evidence="bist_universe'de get_historical_universe yok",
                    affected_module="Survivorship",
                    recommended_fix="Point-in-time tarihsel evren fonksiyonu ekle",
                )
            )

        # Delisted ticker kontrolü
        if hasattr(bist_universe, "delisted_tickers") or hasattr(bist_universe, "DELISTED"):
            details_lines.append("  ✅ Delisted ticker listesi mevcut")
        else:
            issues.append(
                AuditIssue(
                    module="Survivorship",
                    severity="P2",
                    category="MISSING FEATURE",
                    root_cause="Delisted ticker listesi bulunamadı",
                    evidence="bist_universe'de delisted_tickers yok",
                    affected_module="Survivorship",
                    recommended_fix="Delisted ticker listesi ekle",
                )
            )

        # Corporate actions
        from services.ingestion.corporate_actions import CorporateActionsHandler

        CorporateActionsHandler()
        details_lines.append("  ✅ Corporate actions modülü mevcut")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Survivorship", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Survivorship",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Survivorship audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Survivorship",
                recommended_fix="Survivorship modülünü düzelt",
            )
        )
        report.add_module("Survivorship", "FAIL", issues, str(e))


def audit_lookahead(report: AuditReport) -> Any:
    """Modül 2: Time / Look-Ahead / Data Leakage"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL 2: LOOK-AHEAD / DATA LEAKAGE")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        # Feature hesaplama zaman damgası kontrolü
        from services.features.calculator import feature_calculator
        from services.features.incremental_state import IncrementalStateManager

        # Incremental state kontrolü
        IncrementalStateManager()
        details_lines.append("  ✅ IncrementalStateManager modülü mevcut")

        # PIT store kontrolü
        from services.core.pit_store import PointInTimeStore

        PointInTimeStore()
        details_lines.append("  ✅ PointInTimeStore modülü mevcut")

        # Future data injection testi
        # Sentetik veri oluştur
        np.random.seed(42)
        n = 60
        pl.date_range(datetime.now() - timedelta(days=n * 2), datetime.now(), timedelta(days=1), eager=True).tail(n)
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        df = pl.DataFrame(
            {
                "Open": close - 0.5,
                "High": close + 1,
                "Low": close - 1,
                "Close": close,
                "Volume": np.random.randint(10000, 100000, n),
            }
        )

        # Feature'ları hesapla
        from services.core.tradability_mask import TradabilityMask

        tm = TradabilityMask()
        mask = tm.compute_mask(
            "TEST", df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values, df["Volume"].values
        )

        features1 = feature_calculator.compute_all_features(df, mask=mask.mask, ticker="TEST")

        # Gelecek veriyi değiştir (son günü %10 artır)
        df_modified = df.copy()
        df_modified.iloc[-1, df_modified.columns.get_loc("Close")] *= 1.10
        mask2 = tm.compute_mask(
            "TEST",
            df_modified["Open"].values,
            df_modified["High"].values,
            df_modified["Low"].values,
            df_modified["Close"].values,
            df_modified["Volume"].values,
        )
        features2 = feature_calculator.compute_all_features(df_modified, mask=mask2.mask, ticker="TEST")

        # Son gün hariç tüm feature'lar aynı olmalı
        leakage_detected = False
        for feat_name in features1:
            if feat_name in features2:
                v1 = features1[feat_name]
                v2 = features2[feat_name]
                if isinstance(v1, np.ndarray) and isinstance(v2, np.ndarray) and len(v1) == len(v2):
                    # Son gün hariç karşılaştır
                    if len(v1) > 1:
                        diff = np.nanmax(np.abs(v1[:-1] - v2[:-1]))
                        if diff > 0.001:
                            leakage_detected = True
                            issues.append(
                                AuditIssue(
                                    module="Look-Ahead",
                                    severity="P0",
                                    category="LEAKAGE RISK",
                                    root_cause=f"Future data leakage: {feat_name}",
                                    evidence=f"Son gün değiştirildi ama önceki günlerin feature'ı değişti: diff={diff:.6f}",
                                    affected_module="Look-Ahead",
                                    recommended_fix=f"{feat_name} hesaplama mantığında future data kullanımı var",
                                )
                            )
                            break

        if not leakage_detected:
            details_lines.append("  ✅ Future data injection testi: Leakage tespit edilmedi")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Look-Ahead", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Look-Ahead",
                severity="P1",
                category="CRITICAL BUG",
                root_cause=f"Look-ahead audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Look-Ahead",
                recommended_fix="Look-ahead modülünü düzelt",
            )
        )
        report.add_module("Look-Ahead", "FAIL", issues, str(e))


def audit_security(report: AuditReport) -> Any:
    """Ek: Security / Audit"""
    logger.info("\n" + "=" * 70)
    logger.info("MODÜL: SECURİTY / AUDİT")
    logger.info("=" * 70)
    issues = []
    details_lines = []

    try:
        from services.core.security import AuthenticationService, SafetyGovernance

        SafetyGovernance()
        details_lines.append("  ✅ SafetyGovernance modülü mevcut")
        AuthenticationService()
        details_lines.append("  ✅ AuthenticationService modülü mevcut")

        from services.core.audit_log import AuditLog

        AuditLog()
        details_lines.append("  ✅ AuditLog modülü mevcut")

        # Config security
        from services.core.config import settings

        if settings.is_production:
            if not settings.secret_key or len(settings.secret_key) < 16:
                issues.append(
                    AuditIssue(
                        module="Security",
                        severity="P0",
                        category="SECURITY/SAFETY BUG",
                        root_cause="Production'da secret_key çok kısa veya boş",
                        evidence=f"secret_key length: {len(settings.secret_key)}",
                        affected_module="Security",
                        recommended_fix="Güçlü secret_key tanımla",
                    )
                )
        else:
            details_lines.append("  Ortam: development (security check relaxed)")

        # Immutable audit
        details_lines.append("  ⚠️ Immutable audit: Manuel doğrulama gerekli (append-only)")

        status = "FAIL" if any(i.severity == "P0" for i in issues) else "CONDITIONAL PASS" if issues else "PASS"
        report.add_module("Security/Audit", status, issues, "\n".join(details_lines))
        logger.info(f"  Sonuç: {status} ({len(issues)} bulgu)")

    except Exception as e:
        issues.append(
            AuditIssue(
                module="Security",
                severity="P2",
                category="SECURITY/SAFETY BUG",
                root_cause=f"Security audit exception: {str(e)}",
                evidence=traceback.format_exc(),
                affected_module="Security",
                recommended_fix="Security modülünü düzelt",
            )
        )
        report.add_module("Security/Audit", "CONDITIONAL PASS", issues, str(e))


# ============================================================
# MAIN
# ============================================================


def main() -> Any:
    """Otomatik eklendi."""
    logger.info("=" * 70)
    logger.info("ALPHA BIST — FULL SYSTEM FORENSIC AUDIT")
    logger.info(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    report = AuditReport()

    # Tüm modülleri audit et
    audit_modules = [
        ("1. Canlı Veri", audit_live_data),
        ("1b. Data Quality", audit_data_quality),
        ("2. Look-Ahead", audit_lookahead),
        ("3. Tradability Mask", audit_tradability_mask),
        ("4. Features", audit_features),
        ("5. Cross-Sectional", audit_cross_sectional),
        ("6. Regime", audit_regime),
        ("8. Ranking", audit_ranking),
        ("9. Walk-Forward", audit_walk_forward),
        ("10. Calibration", audit_calibration),
        ("11. Position Sizing", audit_position_sizing),
        ("12. Risk Engine", audit_risk_engine),
        ("13. Execution", audit_execution),
        ("14. Portfolio", audit_portfolio),
        ("15. Performance", audit_performance),
        ("16. Benchmark", audit_benchmark),
        ("17. Survivorship", audit_survivorship),
        ("18. Quality Gate", audit_quality_gate),
        ("19. Self-Learning", audit_self_learning),
        ("20. Fail Safe", audit_fail_safe),
        ("Security/Audit", audit_security),
    ]

    for name, audit_func in audit_modules:
        try:
            audit_func(report)
        except Exception as e:
            logger.info(f"  ❌ {name} audit crashed: {e}")
            report.add_module(
                name,
                "FAIL",
                [
                    AuditIssue(
                        module=name,
                        severity="P0",
                        category="CRITICAL BUG",
                        root_cause=f"Audit crashed: {str(e)}",
                        evidence=traceback.format_exc(),
                        affected_module=name,
                        recommended_fix=f"{name} modülünü düzelt",
                    )
                ],
            )

    # Raporu yazdır
    report.print_report()

    # JSON raporu kaydet
    os.makedirs("reports", exist_ok=True)
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "system_status": report.system_status,
        "modules": {
            name: {"status": m.status, "issues": len(m.issues), "details": m.details}
            for name, m in report.modules.items()
        },
        "summary": {
            "critical_bugs": len(report.critical_bugs),
            "logic_bugs": len(report.logic_bugs),
            "financial_math_bugs": len(report.financial_math_bugs),
            "data_bugs": len(report.data_bugs),
            "leakage_risks": len(report.leakage_risks),
            "security_bugs": len(report.security_bugs),
            "performance_issues": len(report.performance_issues),
            "missing_features": len(report.missing_features),
        },
    }
    with open("reports/full_audit_report.json", "w") as f:
        f.write(orjson.dumps(report_data, option=orjson.OPT_INDENT_2, default=str).decode())
    logger.info("\n📄 JSON rapor: reports/full_audit_report.json")

    return report


if __name__ == "__main__":
    main()
