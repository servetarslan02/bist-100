"""ALPHA BIST — FeatureStabilityAnalyzer Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak FeatureStabilityAnalyzer motorunu ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (FeatureStabilityReport, StabilitySummary).
2. Başlatma parametre sınır kontrolleri ve geçersiz eşiklerde fail-closed ValueError doğrulaması.
3. Dağılım geçmişi kaydı, PSI ve iki örneklem Kolmogorov-Smirnov (KS) testi ile kararlılık analizi.
4. Öznitelikler arası korelasyon yapısı kayması (correlation shift) tespiti.
5. Kararsız (unstable) özniteliklerin filtrelenmesi ve tekil öznitelik detay raporu sorgulama.
6. Polars DataFrame üzerinde doğrudan kararlılık analizi (check_stability_polars).
7. DuckDB SSD korumalı WAL denetim izi kaydı ve Polars DataFrame ile geçmiş okuma.
8. Eşzamanlı iş parçacığı güvenliği (thread-safety).
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.feature_stability import (
    FeatureStabilityAnalyzer,
    FeatureStabilityReport,
    StabilitySeverity,
    StabilitySummary,
    check_stability_polars,
    read_stability_history_polars,
    save_stability_summary_to_duckdb,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    report_orig = FeatureStabilityReport(
        feature_name="rsi_14",
        psi=0.15,
        ks_statistic=0.12,
        ks_p_value=0.04,
        distribution_shifted=True,
        correlation_stable=True,
        stability_score=0.85,
        severity=StabilitySeverity.WARNING.value,
        details="PSI=0.15, KS=0.12 [KAYMA TESPİT EDİLDİ]",
    )
    r_bytes = report_orig.to_orjson_bytes()
    r_restored = FeatureStabilityReport.from_dict(orjson.loads(r_bytes))
    assert r_restored.feature_name == "rsi_14"
    assert r_restored.psi == 0.15
    assert r_restored.distribution_shifted is True
    assert r_restored.severity == StabilitySeverity.WARNING.value
    assert "FeatureStabilityReport" in repr(report_orig)

    summary_orig = StabilitySummary(
        total_features=10,
        stable_features=8,
        warning_features=1,
        alert_features=1,
        critical_features=0,
        overall_stability_score=0.88,
        unstable_features=["rsi_14"],
    )
    s_bytes = summary_orig.to_orjson_bytes()
    s_restored = StabilitySummary.from_dict(orjson.loads(s_bytes))
    assert s_restored.total_features == 10
    assert s_restored.unstable_features == ["rsi_14"]
    assert "StabilitySummary" in repr(summary_orig)


def test_feature_stability_analyzer_initialization_validation() -> None:
    """Geçersiz parametrelerde fail-closed ValueError fırlatıldığını test eder."""
    with pytest.raises(ValueError, match="Gecersiz esik degerleri"):
        FeatureStabilityAnalyzer(psi_warning=0.30, psi_alert=0.20)  # alert <= warning

    with pytest.raises(ValueError, match="Gecersiz esik degerleri"):
        FeatureStabilityAnalyzer(ks_alpha=-0.05)

    analyzer = FeatureStabilityAnalyzer()
    assert "FeatureStabilityAnalyzer" in repr(analyzer)


def test_record_distribution_and_check_stability() -> None:
    """Dağılım kaydı, PSI/KS analizi ve StabilitySummary üretimini test eder."""
    analyzer = FeatureStabilityAnalyzer(min_samples=20, psi_warning=0.15, psi_alert=0.30)
    np.random.seed(42)

    # Başlangıçta 2'den az dağılım varken boş özet dönmeli
    empty_summary = analyzer.check_stability()
    assert empty_summary.total_features == 0

    # Referans dönem (yeterli örneklem ile istatistiksel kararlılık)
    ref = {
        "feat_stable": np.random.normal(0, 1, 500),
        "feat_shift": np.random.normal(0, 1, 500),
    }
    analyzer.record_distribution(ref)

    # Güncel dönem: feat_stable aynı dağılımdan, feat_shift ise belirgin kaymış N(3, 1)
    cur = {
        "feat_stable": np.random.normal(0, 1, 500),
        "feat_shift": np.random.normal(3, 1, 500),
    }
    analyzer.record_distribution(cur)

    summary = analyzer.check_stability()
    assert summary.total_features == 2
    assert summary.stable_features >= 1
    assert "feat_shift" in summary.unstable_features

    # Tekil rapor sorgusu
    rep_shift = analyzer.get_feature_report("feat_shift")
    assert rep_shift is not None
    assert rep_shift.distribution_shifted is True
    assert rep_shift.psi > 0.30


def test_record_correlation_structure() -> None:
    """Öznitelikler arası korelasyon yapısının kaydedilip analiz edildiğini test eder."""
    analyzer = FeatureStabilityAnalyzer()
    np.random.seed(123)

    data1 = {
        "f1": np.random.normal(0, 1, 50),
        "f2": np.random.normal(0, 1, 50),
    }
    analyzer.record_correlation(data1)
    assert len(analyzer._correlation_matrices) == 1

    # Yetersiz elemanlı dizi atlanmalı
    analyzer.record_correlation({"f1": np.ones(5)})
    assert len(analyzer._correlation_matrices) == 1


def test_get_unstable_features() -> None:
    """get_unstable_features metodunun kararsız öznitelikleri doğru süzdüğünü test eder."""
    analyzer = FeatureStabilityAnalyzer(min_samples=20, psi_warning=0.15, psi_alert=0.30)
    np.random.seed(77)

    ref = {"f_ok": np.random.normal(0, 1, 500), "f_bad": np.random.normal(0, 1, 500)}
    cur = {"f_ok": np.random.normal(0, 1, 500), "f_bad": np.random.normal(4, 1, 500)}

    analyzer.record_distribution(ref)
    analyzer.record_distribution(cur)

    unstable = analyzer.get_unstable_features()
    assert "f_bad" in unstable
    assert "f_ok" not in unstable


def test_check_stability_polars() -> None:
    """Polars DataFrame üzerinde doğrudan kararlılık denetimini test eder."""
    np.random.seed(88)
    n = 100

    df_ref = pl.DataFrame(
        {
            "f1": np.random.normal(0, 1, n),
            "f2": np.random.normal(0, 1, n),
        }
    )
    df_cur = pl.DataFrame(
        {
            "f1": np.random.normal(0, 1, n),
            "f2": np.random.normal(3, 1, n),
        }
    )

    reports = check_stability_polars(reference_df=df_ref, current_df=df_cur)
    assert len(reports) == 2

    f2_rep = next(r for r in reports if r.feature_name == "f2")
    assert f2_rep.distribution_shifted is True
    assert f2_rep.severity in [StabilitySeverity.ALERT.value, StabilitySeverity.CRITICAL.value]

    # Boş DataFrame girdisi
    assert check_stability_polars(None, df_cur) == []


def test_duckdb_wal_save_and_polars_read(tmp_path: Path) -> None:
    """Kararlılık özetinin DuckDB WAL ile kaydedilip Polars ile hatasız okunduğunu test eder."""
    db_file = str(tmp_path / "stability_audit.duckdb")

    summary = StabilitySummary(
        total_features=25,
        stable_features=20,
        warning_features=3,
        alert_features=2,
        critical_features=0,
        overall_stability_score=0.85,
        unstable_features=["feat_vol", "feat_mom"],
    )

    save_stability_summary_to_duckdb(summary, db_path=db_file)

    df_hist = read_stability_history_polars(db_path=db_file, limit=10)
    assert isinstance(df_hist, pl.DataFrame)
    assert df_hist.height == 1
    assert df_hist["total_features"][0] == 25
    assert df_hist["stable_features"][0] == 20


def test_thread_safety_analyzer() -> None:
    """Çoklu thread ile eşzamanlı dağılım kaydetme ve kararlılık kontrolü güvenliğini test eder."""
    analyzer = FeatureStabilityAnalyzer(min_samples=10)

    def worker(idx: int) -> None:
        for _ in range(15):
            arr = np.random.normal(idx * 0.1, 1, 30)
            analyzer.record_distribution({f"feat_{idx}": arr})
            _ = analyzer.check_stability()

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [executor.submit(worker, i) for i in range(12)]
        for f in concurrent.futures.as_completed(futs):
            f.result()

    assert len(analyzer._distributions) > 0
