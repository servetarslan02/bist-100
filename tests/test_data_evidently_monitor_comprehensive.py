"""ALPHA BIST — Veri Kalitesi ve Sürüklenme İzleme (Evidently Data Monitor) Kapsamlı Test Paketi.

services/data/evidently_monitor.py modülünün OHLCV bütünlük denetimleri (High >= Low,
pozitif fiyat, negatif olmayan hacim), Polars DataFrame denetimi (audit_ohlcv_polars),
Kolmogorov-Smirnov (KS) ve Population Stability Index (PSI) drift hesaplamaları,
tam rapor üretimi (Data Quality Gate), Polars dışa aktarımı ve DuckDB denetim tablosu kayıtlarını test eder.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import numpy as np
import orjson
import polars as pl
import pytest

from services.data.evidently_monitor import (
    DEFAULT_CHECKPOINT_SIZE,
    DEFAULT_KS_ALPHA,
    DEFAULT_PSI_THRESHOLD,
    DEFAULT_WAL_SIZE,
    DataQualityReport,
    DriftCheckResult,
    EvidentlyDataMonitor,
    QualityCheckResult,
    clear_evidently_audit_duckdb,
    configure_duckdb_wal,
    export_report_to_duckdb,
    read_evidently_audit_from_duckdb,
    to_orjson_bytes,
)


class TestEvidentlyBasics:
    """Sabitler, serileştirme ve DuckDB WAL testleri."""

    def test_constants(self) -> None:
        """Sabitlerin ve eşik değerlerinin doğruluğunu kontrol eder."""
        assert DEFAULT_CHECKPOINT_SIZE == "4MB"
        assert DEFAULT_WAL_SIZE == "2MB"
        assert DEFAULT_PSI_THRESHOLD == 0.20
        assert DEFAULT_KS_ALPHA == 0.05

    def test_configure_duckdb_wal(self) -> None:
        """DuckDB WAL pragma fonksiyonunun doğruluğunu test eder."""
        conn = duckdb.connect(":memory:")
        configure_duckdb_wal(conn)
        conn.close()

    def test_to_orjson_bytes_helper(self) -> None:
        """to_orjson_bytes fonksiyonunun nesne ve sözlük dönüşümünü test eder."""
        res = QualityCheckResult(
            check_name="test_check",
            status="PASS",
            metric_value=0.0,
            threshold=0.0,
            message="Sorun yok",
        )
        raw = to_orjson_bytes(res)
        assert isinstance(raw, bytes)
        assert orjson.loads(raw)["check_name"] == "test_check"


class TestDataModels:
    """QualityCheckResult, DriftCheckResult ve DataQualityReport modelleri testleri."""

    def test_quality_check_result(self) -> None:
        """QualityCheckResult to_dict, to_orjson_bytes ve __repr__ testleri."""
        q = QualityCheckResult("high_low", "PASS", 0.0, 0.0, "Tum barlar gecerli")
        assert "high_low" in repr(q)

        as_dict = q.to_dict()
        assert as_dict["status"] == "PASS"

        raw = q.to_orjson_bytes()
        assert isinstance(raw, bytes)

    def test_drift_check_result(self) -> None:
        """DriftCheckResult to_dict, to_orjson_bytes ve __repr__ testleri."""
        d = DriftCheckResult(
            feature_name="fcf_yield",
            drift_score=0.012,
            method="KS_TEST",
            is_drifted=True,
            severity="SEVERE",
            reference_mean=4.5,
            current_mean=2.1,
        )
        assert "fcf_yield" in repr(d)
        assert d.is_drifted is True

        as_dict = d.to_dict()
        assert as_dict["severity"] == "SEVERE"

    def test_data_quality_report_and_polars_export(self) -> None:
        """DataQualityReport oluşturma, Polars DataFrame aktarımı ve orjson dönüşümü."""
        report = DataQualityReport(
            is_pipeline_allowed=True,
            overall_score=95.0,
            quality_checks=[QualityCheckResult("c1", "PASS", 0.0, 0.0, "ok")],
            drift_checks=[DriftCheckResult("f1", 0.05, "PSI", False, "NONE", 1.0, 1.0)],
            failed_checks_count=0,
            drifted_features_count=0,
        )
        assert "ONAYLANDI" in repr(report)

        df = report.export_to_polars()
        assert isinstance(df, pl.DataFrame)
        assert df.height == 1
        assert df["is_pipeline_allowed"][0] is True
        assert df["overall_score"][0] == 95.0


class TestEvidentlyDataMonitorLogic:
    """EvidentlyDataMonitor sınıfının bütünlük ve drift algoritmaları testleri."""

    @pytest.fixture
    def monitor(self):
        """Monitor fixture'ı."""
        return EvidentlyDataMonitor(psi_threshold=0.20, ks_alpha=0.05)

    def test_monitor_init_and_repr(self, monitor) -> None:
        """Monitor nesnesinin başlatılması ve __repr__ testi."""
        assert "EvidentlyDataMonitor" in repr(monitor)
        as_dict = monitor.to_dict()
        assert as_dict["psi_threshold"] == 0.20
        assert as_dict["ks_alpha"] == 0.05

    def test_audit_ohlcv_integrity_valid(self, monitor) -> None:
        """Geçerli OHLCV verisinde tüm kontrollerin PASS dönmesi testi."""
        ohlcv = {
            "open": [100.0, 102.0],
            "high": [105.0, 106.0],
            "low": [98.0, 101.0],
            "close": [103.0, 104.0],
            "volume": [50000.0, 60000.0],
        }
        results = monitor.audit_ohlcv_integrity(ohlcv)
        assert len(results) == 5
        assert all(r.status == "PASS" for r in results)

    def test_audit_ohlcv_integrity_invalid(self, monitor) -> None:
        """Hatalı verilerde (High < Low, negatif hacim, sıfır fiyat) FAIL yakalanması testi."""
        ohlcv = {
            "open": [100.0],
            "high": [90.0],  # High < Low hatası
            "low": [95.0],
            "close": [0.0],  # Sıfır fiyat hatası
            "volume": [-10.0],  # Negatif hacim hatası
        }
        results = monitor.audit_ohlcv_integrity(ohlcv)
        failed_checks = [r.check_name for r in results if r.status == "FAIL"]
        assert "high_greater_equal_low" in failed_checks
        assert "positive_price" in failed_checks
        assert "non_negative_volume" in failed_checks

    def test_audit_ohlcv_polars(self, monitor) -> None:
        """Polars DataFrame ile doğrudan denetim fonksiyonu testi."""
        df = pl.DataFrame(
            {
                "Open": [10.0, 11.0],
                "High": [12.0, 13.0],
                "Low": [9.5, 10.5],
                "Close": [11.5, 12.5],
                "Volume": [1000, 2000],
            }
        )
        results = monitor.audit_ohlcv_polars(df)
        assert all(r.status == "PASS" for r in results)

        # Boş DataFrame
        results_empty = monitor.audit_ohlcv_polars(pl.DataFrame())
        assert results_empty[0].status == "FAIL"

    def test_compute_ks_drift(self, monitor) -> None:
        """Kolmogorov-Smirnov testi ile veri sürüklenmesi tespiti."""
        np.random.seed(42)
        ref = np.random.normal(loc=0.0, scale=1.0, size=100)
        cur_same = np.random.normal(loc=0.0, scale=1.0, size=100)
        cur_drifted = np.random.normal(loc=5.0, scale=1.0, size=100)

        # Aynı dağılımda drift olmamalı
        res_same = monitor.compute_ks_drift(ref, cur_same, "feat_same")
        assert res_same.is_drifted is False

        # Belirgin farklı dağılımda drift yakalanmalı
        res_drifted = monitor.compute_ks_drift(ref, cur_drifted, "feat_drift")
        assert res_drifted.is_drifted is True
        assert res_drifted.severity == "SEVERE"

    def test_compute_psi(self, monitor) -> None:
        """Population Stability Index (PSI) testi."""
        np.random.seed(42)
        ref = np.random.normal(loc=10.0, scale=2.0, size=1000)
        cur_same = np.random.normal(loc=10.0, scale=2.0, size=1000)
        cur_drifted = np.random.normal(loc=20.0, scale=2.0, size=1000)

        res_same = monitor.compute_psi(ref, cur_same, "psi_same")
        assert res_same.is_drifted is False

        res_drifted = monitor.compute_psi(ref, cur_drifted, "psi_drift")
        assert res_drifted.is_drifted is True
        assert res_drifted.severity == "SEVERE"

    def test_generate_full_audit(self, monitor) -> None:
        """Kapsamlı kalite ve drift karar kapısı (Quality Gate) rapor üretimi."""
        np.random.seed(42)
        ohlcv = {
            "open": [10.0, 11.0, 12.0],
            "high": [12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0],
            "close": [11.0, 12.0, 13.0],
            "volume": [100.0, 200.0, 300.0],
        }
        ref_features = {"f1": np.random.normal(0, 1, 50)}
        cur_features = {"f1": np.random.normal(0, 1, 50)}

        report = monitor.generate_full_audit(ohlcv, ref_features, cur_features)
        assert report.is_pipeline_allowed is True
        assert report.overall_score == 100.0


class TestEvidentlyAuditDuckDB:
    """export_report_to_duckdb, read_evidently_audit_from_duckdb ve temizleme testleri."""

    def test_export_and_read_audit_flow(self) -> None:
        """DuckDB denetim tablosuna kayıt, Polars okuma ve tablo temizleme testi."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db = str(Path(tmpdir) / "test_evidently_audit.duckdb")

            report = DataQualityReport(
                is_pipeline_allowed=True,
                overall_score=92.5,
                quality_checks=[QualityCheckResult("c1", "PASS", 0.0, 0.0, "ok")],
                drift_checks=[],
                failed_checks_count=0,
                drifted_features_count=0,
            )

            res = export_report_to_duckdb(report, db_path=test_db)
            assert res == 1

            df = read_evidently_audit_from_duckdb(db_path=test_db, limit=5)
            assert isinstance(df, pl.DataFrame)
            assert df.height == 1
            assert df["is_pipeline_allowed"][0] is True
            assert df["overall_score"][0] == 92.5

            clear_evidently_audit_duckdb(db_path=test_db)
            df_after = read_evidently_audit_from_duckdb(db_path=test_db)
            assert df_after.height == 0
