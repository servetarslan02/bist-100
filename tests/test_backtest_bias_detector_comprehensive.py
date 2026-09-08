"""ALPHA BIST — Look-Ahead Bias Dedektörü Kapsamlı Test Paketi.

services/backtest/bias_detector.py modülünün tüm işlevlerini ve uç durumlarını sınar:
1. BiasViolation ve BiasReport dataclass serileştirme (to_dict, __repr__, add_violation).
2. LookAheadBiasDetector.validate_feature_timestamps (eksik timestamp sütunu, temiz veri, gelecek veri ihlali).
3. LookAheadBiasDetector.validate_rolling_window (shift(1).rolling_mean ile vektörel polars kontrolü, temiz ve sızan pencere).
4. LookAheadBiasDetector.validate_label_feature_alignment (purge_days < label_horizon_days ihlali ve temiz durum).
5. LookAheadBiasDetector.validate_fold_boundaries (test_start <= train_end, purge gap yetersizliği, label horizon ihlali).
6. LookAheadBiasDetector.validate_data_revision_integrity (as-reported vs birden fazla revizyon uyarısı).
7. LookAheadBiasDetector iş parçacığı güvenliği (_lock ve eşzamanlı _record).
8. BiasDetectorMiddleware (pre_scan_check, fold_check, strict_mode açık/kapalı davranışı).
"""

from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime, timedelta

import polars as pl

from services.backtest.bias_detector import (
    BiasDetectorMiddleware,
    BiasReport,
    BiasViolation,
    LookAheadBiasDetector,
    bias_detector_middleware,
)


def test_bias_violation_and_report_dataclass():
    """BiasViolation ve BiasReport veri modellerinin metot ve serileştirme doğrulaması."""
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
    violation = BiasViolation(
        violation_type="look_ahead",
        severity="critical",
        timestamp=now,
        feature_name="momentum_10d",
        description="Gelecek veri sızıntısı tespit edildi",
        data_point={"future_rows": 2},
    )

    # __repr__ ve to_dict
    rep_str = repr(violation)
    assert "look_ahead" in rep_str
    assert "critical" in rep_str
    assert "momentum_10d" in rep_str

    v_dict = violation.to_dict()
    assert v_dict["type"] == "look_ahead"
    assert v_dict["severity"] == "critical"
    assert v_dict["timestamp"] == now.isoformat()
    assert v_dict["feature"] == "momentum_10d"
    assert v_dict["description"] == "Gelecek veri sızıntısı tespit edildi"

    # BiasReport
    report = BiasReport()
    assert report.is_clean is True
    assert report.critical_count == 0
    assert report.warning_count == 0

    report.add_violation(violation)
    assert report.is_clean is False
    assert report.critical_count == 1
    assert len(report.violations) == 1

    # Warning violation
    warning_violation = BiasViolation(
        violation_type="data_revision",
        severity="warning",
        timestamp=now,
        feature_name="revenue",
        description="Çoklu revizyon bulundu",
    )
    report.add_violation(warning_violation)
    assert report.warning_count == 1
    assert len(report.violations) == 2

    report_dict = report.to_dict()
    assert report_dict["critical_count"] == 1
    assert report_dict["warning_count"] == 1
    assert report_dict["is_clean"] is False
    assert len(report_dict["violations"]) == 2
    assert "critical=1" in repr(report)


def test_validate_feature_timestamps_missing_column():
    """Zaman damgası sütunu eksikse kritik hata raporlanmalı."""
    detector = LookAheadBiasDetector()
    df = pl.DataFrame({"close": [10.0, 11.0, 12.0]})
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)

    report = detector.validate_feature_timestamps(
        feature_df=df,
        feature_name="alpha_signal",
        decision_timestamp=now,
        timestamp_col="timestamp",
    )

    assert report.is_clean is False
    assert report.critical_count == 1
    assert report.violations[0].violation_type == "look_ahead"
    assert "bulunamadı" in report.violations[0].description


def test_validate_feature_timestamps_clean_and_leakage():
    """Geleceğe ait veri varsa yakalanmalı, yoksa temiz raporlanmalı."""
    detector = LookAheadBiasDetector()
    t0 = datetime(2026, 9, 8, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 9, 8, 11, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 9, 8, 13, 0, 0, tzinfo=UTC)

    # Temiz veri (karar anı t2, veriler t0, t1, t2)
    clean_df = pl.DataFrame({
        "timestamp": [t0, t1, t2],
        "feature_score": [0.1, 0.2, 0.3],
    })
    clean_report = detector.validate_feature_timestamps(
        clean_df, "feature_score", decision_timestamp=t2
    )
    assert clean_report.is_clean is True
    assert clean_report.critical_count == 0
    assert clean_report.total_checks == 3

    # Sızıntılı veri (karar anı t2, ancak veri t3 içeriyor)
    leaked_df = pl.DataFrame({
        "timestamp": [t0, t1, t2, t3],
        "feature_score": [0.1, 0.2, 0.3, 0.4],
    })
    leaked_report = detector.validate_feature_timestamps(
        leaked_df, "feature_score", decision_timestamp=t2
    )
    assert leaked_report.is_clean is False
    assert leaked_report.critical_count == 1
    assert "karar anından sonra 1 veri noktası" in leaked_report.violations[0].description


def test_validate_rolling_window_calculation():
    """Rolling pencerede geleceğe bakıp bakılmadığının Polars vektörel testi."""
    detector = LookAheadBiasDetector()
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    n_rows = 15
    timestamps = [base_time + timedelta(days=i) for i in range(n_rows)]
    closes = [100.0 + float(i) for i in range(n_rows)]

    # 1. Doğru hesaplama (shift(1).rolling_mean(3))
    # Her satır t anında t-1, t-2, t-3 değerlerinin ortalamasını alır
    window = 3
    df_clean = pl.DataFrame({
        "timestamp": timestamps,
        "close": closes,
    }).with_columns(
        pl.col("close").shift(1).rolling_mean(window).alias("rolling_mean")
    )

    clean_report = detector.validate_rolling_window(
        data=df_clean,
        window_size=window,
        feature_name="ma_3d",
        value_col="close",
    )
    assert clean_report.is_clean is True
    assert clean_report.critical_count == 0

    # 2. Hatalı/Sızan hesaplama (shift(0) - t anındaki mevcut veya gelecek veriyi kullanmış)
    df_leaked = pl.DataFrame({
        "timestamp": timestamps,
        "close": closes,
    }).with_columns(
        pl.col("close").rolling_mean(window).alias("rolling_mean")
    )

    leaked_report = detector.validate_rolling_window(
        data=df_leaked,
        window_size=window,
        feature_name="ma_3d_leaked",
        value_col="close",
    )
    assert leaked_report.is_clean is False
    assert leaked_report.critical_count > 0
    assert "Rolling window gelecek veri kullanıyor" in leaked_report.violations[0].description

    # Yetersiz veri durumu
    short_df = pl.DataFrame({"timestamp": timestamps[:2], "close": closes[:2]})
    short_report = detector.validate_rolling_window(short_df, 5, "short_ma")
    assert short_report.is_clean is True


def test_validate_label_feature_alignment():
    """Label ufku ile purge günleri uyumu kontrolü."""
    detector = LookAheadBiasDetector()

    # Hatalı durum: purge_days (3) < label_horizon (5)
    fail_report = detector.validate_label_feature_alignment(
        label_horizon_days=5,
        feature_window_days=20,
        purge_days=3,
    )
    assert fail_report.is_clean is False
    assert fail_report.critical_count == 1
    assert "Purge günleri (3) < label ufku (5)" in fail_report.violations[0].description

    # Başarılı durum: purge_days (5) >= label_horizon (5)
    pass_report = detector.validate_label_feature_alignment(
        label_horizon_days=5,
        feature_window_days=20,
        purge_days=5,
    )
    assert pass_report.is_clean is True
    assert pass_report.critical_count == 0


def test_validate_fold_boundaries():
    """Walk-forward fold sınırları kontrolleri."""
    detector = LookAheadBiasDetector()
    train_end = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    # 1. Test başlangıcı train bitişinden önce veya aynı gün
    bad_start = train_end - timedelta(days=1)
    rep1 = detector.validate_fold_boundaries(
        train_end=train_end,
        test_start=bad_start,
        purge_days=5,
        embargo_days=2,
        label_horizon_days=5,
    )
    assert rep1.is_clean is False
    assert any("Test başlangıcı" in v.description for v in rep1.violations)

    # 2. Gerçek boşluk < purge_days
    test_start_short = train_end + timedelta(days=3)  # gap = 3 < purge=5
    rep2 = detector.validate_fold_boundaries(
        train_end=train_end,
        test_start=test_start_short,
        purge_days=5,
        embargo_days=2,
        label_horizon_days=5,
    )
    assert rep2.is_clean is False
    assert any("Gerçek boşluk (3 gün) < gerekli purge (5 gün)" in v.description for v in rep2.violations)

    # 3. Temiz fold sınırı
    test_start_clean = train_end + timedelta(days=10)
    rep3 = detector.validate_fold_boundaries(
        train_end=train_end,
        test_start=test_start_clean,
        purge_days=5,
        embargo_days=2,
        label_horizon_days=5,
    )
    assert rep3.is_clean is True
    assert rep3.critical_count == 0


def test_validate_data_revision_integrity():
    """Mali tablo ve revize verilerde as-reported bütünlük kontrolü."""
    detector = LookAheadBiasDetector()

    # Tekil revizyon (temiz durum)
    df_clean = pl.DataFrame({
        "report_date": ["2026-03-31", "2026-06-30"],
        "revision_version": [1, 1],
        "net_income": [100.0, 120.0],
    })
    rep_clean = detector.validate_data_revision_integrity(df_clean)
    assert rep_clean.is_clean is True
    assert rep_clean.warning_count == 0

    # Çoklu revizyon (uyarı üretilmeli)
    df_multiple_rev = pl.DataFrame({
        "report_date": ["2026-03-31", "2026-03-31"],
        "revision_version": [1, 2],
        "net_income": [100.0, 110.0],
    })
    rep_warn = detector.validate_data_revision_integrity(df_multiple_rev)
    assert rep_warn.warning_count == 1
    assert "birden fazla revizyon bulundu" in rep_warn.violations[0].description


def test_look_ahead_bias_detector_concurrency():
    """Çoklu iş parçacığında eşzamanlı kayıt yapıldığında veri bütünlüğü korunmalı."""
    detector = LookAheadBiasDetector()
    n_threads = 8
    items_per_thread = 50

    def worker(thread_id: int):
        for i in range(items_per_thread):
            violation = BiasViolation(
                violation_type="look_ahead",
                severity="warning" if i % 2 == 0 else "critical",
                timestamp=datetime.now(UTC),
                feature_name=f"thread_{thread_id}_feat_{i}",
                description="Eşzamanlı test kaydı",
            )
            report = BiasReport()
            detector._record(report, violation)

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        for f in futures:
            f.result()

    summary = detector.get_summary()
    total_expected = n_threads * items_per_thread
    assert summary["total_violations"] == total_expected
    assert summary["critical"] == total_expected // 2
    assert summary["warnings"] == total_expected // 2
    assert summary["is_clean"] is False
    assert len(detector.violations) == total_expected


def test_bias_detector_middleware():
    """Middleware'in pre_scan_check ve fold_check işleyişi ile strict_mode mekanizması."""
    mw = BiasDetectorMiddleware(strict_mode=True)
    assert repr(mw).startswith("BiasDetectorMiddleware")

    t0 = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 9, 5, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 10, 0, 0, 0, tzinfo=UTC)

    # 1. Gelecek veri içeren DataFrame ile pre_scan_check
    df = pl.DataFrame({
        "timestamp": [t0, t1, t2],
        "momentum_score": [1.0, 2.0, 3.0],
    })
    # Karar anı t1 iken veri t2 içeriyor -> sızıntı
    is_safe, report = mw.pre_scan_check(
        available_data=df,
        decision_timestamp=t1,
        label_horizon_days=5,
        feature_window_days=10,
        purge_days=5,
    )
    assert is_safe is False
    assert report.critical_count > 0

    # strict_mode=False iken kritik ihlale rağmen is_safe=True dönmeli
    mw_lenient = BiasDetectorMiddleware(strict_mode=False)
    is_safe_lenient, _ = mw_lenient.pre_scan_check(
        available_data=df,
        decision_timestamp=t1,
    )
    assert is_safe_lenient is True

    # Middleware devre dışıyken (enabled=False)
    mw.enabled = False
    is_safe_disabled, empty_rep = mw.pre_scan_check(df, t1)
    assert is_safe_disabled is True
    assert empty_rep.total_checks == 0

    is_safe_fold, empty_fold_rep = mw.fold_check(t0, t2, 5, 2, 5)
    assert is_safe_fold is True
    assert empty_fold_rep.total_checks == 0

    # Global singleton varlığı
    assert isinstance(bias_detector_middleware, BiasDetectorMiddleware)
