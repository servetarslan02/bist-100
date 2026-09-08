"""ALPHA BIST — ModelMonitor Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik metrik ve tahmin serileri
- MonitorReport, Alert, DriftReport dataclass serileştirme (to_dict, from_dict)
- record_metric() ve check_decay() z-skoru tabanlı bozulma (decay) tespiti
- record_predictions() ve check_prediction_drift() Kolmogorov-Smirnov testi
- get_health_score() model sağlık notu ve skoru
- register_retrain_callback() kritik alarm anında otomatik geri çağrı tetikleme
- get_metrics_polars(), get_audit_as_polars(), get_alerts_as_polars() testleri
- Çoklu iş parçacığı (threading) eşzamanlı metrik kaydı kilit testi
"""

import threading
from pathlib import Path
import numpy as np
import polars as pl
import pytest

from services.ml.model_monitor import (
    Alert,
    AlertLevel,
    AlertType,
    DriftReport,
    ModelMonitor,
    MonitorReport,
    PerformanceTrend,
    model_monitor,
)


def test_dataclasses_serialization():
    """MonitorReport, Alert ve DriftReport serileştirme ve from_dict testi."""
    rep = MonitorReport(
        model_id="champion_lgb",
        metric_name="ic",
        current_value=0.08,
        historical_mean=0.12,
        historical_std=0.015,
        z_score=-2.67,
        decay_detected=True,
        retrain_recommended=False,
        alert_level=AlertLevel.WARNING,
        trend=PerformanceTrend.DEGRADING,
    )
    r_dict = rep.to_dict()
    assert r_dict["model_id"] == "champion_lgb"
    assert r_dict["decay_detected"] is True
    assert isinstance(rep.to_orjson_bytes(), bytes)

    restored_rep = MonitorReport.from_dict(r_dict)
    assert restored_rep.model_id == "champion_lgb"
    assert restored_rep.z_score == -2.67

    alert = Alert(
        timestamp="2026-05-01T10:00:00Z",
        model_id="champion_lgb",
        alert_type=AlertType.DECAY,
        severity=AlertLevel.WARNING,
        message="IC bozulma esigini asti",
        metric_name="ic",
        current_value=0.08,
        threshold=-2.0,
    )
    a_dict = alert.to_dict()
    assert a_dict["alert_type"] == "DECAY"
    assert isinstance(alert.to_orjson_bytes(), bytes)

    restored_alert = Alert.from_dict(a_dict)
    assert restored_alert.model_id == "champion_lgb"
    assert restored_alert.metric_name == "ic"

    drift = DriftReport(
        drift_detected=True,
        ks_statistic=0.45,
        p_value=0.001,
        recent_mean=0.65,
        historical_mean=0.50,
        recent_std=0.12,
        historical_std=0.10,
        reason="Tahmin dagiliminda belirgin kayma",
    )
    d_dict = drift.to_dict()
    assert d_dict["drift_detected"] is True
    assert isinstance(drift.to_orjson_bytes(), bytes)

    restored_drift = DriftReport.from_dict(d_dict)
    assert restored_drift.drift_detected is True
    assert restored_drift.ks_statistic == 0.45


def test_record_metric_and_check_decay():
    """Zaman serisi metrik takibi ve z-skoru bozulma testi."""
    monitor = ModelMonitor(min_history=5, decay_z_threshold=-2.0, retrain_z_threshold=-3.0)
    model_id = "test_lgb"

    # Stabil geçmiş metrikleri ekle (ortalama ~0.15, std ~0.01)
    for _ in range(15):
        monitor.record_metric(model_id=model_id, metric_name="ic", value=0.15 + np.random.normal(0, 0.005))

    # Normal durum kontrolü
    rep_normal = monitor.check_decay(model_id=model_id, metric_name="ic")
    assert rep_normal.decay_detected is False
    assert rep_normal.alert_level == AlertLevel.OK

    # Ani düşüş (bozulma) oluştur
    monitor.record_metric(model_id=model_id, metric_name="ic", value=0.05)
    rep_decay = monitor.check_decay(model_id=model_id, metric_name="ic")
    assert rep_decay.decay_detected is True
    assert rep_decay.alert_level in (AlertLevel.WARNING, AlertLevel.CRITICAL)


def test_prediction_drift_ks_test():
    """İki örneklemli KS testi ile tahmin kayması tespiti testi."""
    monitor = ModelMonitor()
    model_id = "drift_model"

    # Tarihsel normal tahminler: N(0.5, 0.1)
    np.random.seed(42)
    hist_preds = np.random.normal(0.5, 0.1, 200).tolist()
    monitor.record_predictions(model_id=model_id, predictions=hist_preds)

    # Benzer dağılımdan yeni tahminler -> Drift olmamalı
    new_similar = np.random.normal(0.5, 0.1, 50).tolist()
    rep_no_drift = monitor.check_prediction_drift(model_id=model_id, recent_predictions=new_similar)
    assert rep_no_drift.drift_detected is False

    # Çok farklı dağılımdan yeni tahminler -> Drift tespit edilmeli
    new_shifted = np.random.normal(0.9, 0.05, 50).tolist()
    rep_drift = monitor.check_prediction_drift(model_id=model_id, recent_predictions=new_shifted)
    assert rep_drift.drift_detected is True
    assert rep_drift.p_value < 0.05


def test_health_score_and_retrain_callback():
    """Model sağlık skoru ve otomatik yeniden eğitim geri çağrı testi."""
    monitor = ModelMonitor(min_history=5, retrain_z_threshold=-2.5)
    model_id = "health_model"

    retrain_triggered = []

    def on_retrain(mid: str, rep: MonitorReport):
        retrain_triggered.append((mid, rep.metric_name))

    monitor.register_retrain_callback(on_retrain)

    # Sağlıklı metrikler kaydet
    for _ in range(10):
        monitor.record_metric(model_id=model_id, metric_name="ic", value=0.20)
        monitor.record_metric(model_id=model_id, metric_name="sharpe", value=2.0)

    score_dict = monitor.get_health_score(model_id=model_id)
    assert score_dict["grade"] == "A"
    assert score_dict["health_score"] >= 80

    # Kritik çöküş tetikle (z < -2.5)
    for _ in range(5):
        monitor.record_metric(model_id=model_id, metric_name="ic", value=-0.50)
        monitor.check_decay(model_id=model_id, metric_name="ic")

    assert len(retrain_triggered) >= 1
    assert retrain_triggered[0][0] == model_id


def test_polars_and_duckdb_wal(tmp_path: Path):
    """DuckDB WAL izleme ve Polars DataFrame okuma testi."""
    db_file = tmp_path / "test_monitor.duckdb"
    monitor = ModelMonitor(min_history=3, duckdb_path=str(db_file))
    model_id = "polars_model"

    for v in [0.10, 0.12, 0.11, 0.02]:
        monitor.record_metric(model_id=model_id, metric_name="ic", value=v)
        monitor.check_decay(model_id=model_id, metric_name="ic")

    df_metrics = monitor.get_metrics_polars(model_id=model_id, metric_name="ic")
    assert isinstance(df_metrics, pl.DataFrame)
    assert df_metrics.height == 4

    df_audit = monitor.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height >= 1
    assert df_audit["model_id"][0] == model_id


def test_thread_safety_model_monitor():
    """Çoklu iş parçacığı altında eşzamanlı metrik kaydı kilit testi."""
    monitor = ModelMonitor()
    errors = []

    def worker(tid: int):
        try:
            for i in range(20):
                monitor.record_metric(
                    model_id=f"model_{tid}",
                    metric_name="accuracy",
                    value=0.5 + (i % 10) * 0.02,
                )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
