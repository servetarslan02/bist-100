"""ALPHA BIST — EnsembleModel Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak EnsembleModel motorunu ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (DiversityReport, BenefitReport, EnsembleDiagnostics, EnsembleState).
2. Ağırlıklı topluluk tahmini, NaN/Inf guard kontrolleri ve boyutsal doğrulamalar.
3. Polars DataFrame girdisi ile topluluk tahmini.
4. Model tahmin mutabakatı (confidence) skoru üretimi.
5. Piyasa rejimine duyarlı dinamik ağırlıklandırma (BULL, BEAR, SIDEWAYS, HIGH_VOL).
6. Model çeşitliliği (diversity) ve korelasyon analizi.
7. Topluluk fayda kapısı (Benefit Gate) ve yüksek korelasyonlu modellerin budanması (Auto-Prune).
8. Durum saklama ve geri yükleme (Save/Load State via safe_pickle).
9. DuckDB WAL denetim tablosu kaydı ve Polars DataFrame ile geri okuma.
10. Thread-safety: Çoklu iş parçacıkları ile eşzamanlı topluluk tahmini güvenliği.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.ensemble import (
    BenefitReport,
    DiversityReport,
    EnsembleDiagnostics,
    EnsembleModel,
    EnsembleState,
)


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    div_orig = DiversityReport(
        correlation_matrix={"m1": {"m1": 1.0, "m2": 0.4}, "m2": {"m1": 0.4, "m2": 1.0}},
        mean_correlation=0.4,
        diversity_score=0.6,
        redundant_models=[],
        recommendation="Yüksek çeşitlilik",
    )
    div_bytes = div_orig.to_orjson_bytes()
    div_restored = DiversityReport.from_dict(orjson.loads(div_bytes))
    assert div_restored.diversity_score == 0.6
    assert "DiversityReport" in repr(div_orig)

    ben_orig = BenefitReport(
        ensemble_ic=0.12,
        best_individual_ic=0.09,
        best_individual_name="lightgbm",
        ic_improvement=0.03,
        is_beneficial=True,
        recommendation="Ensemble faydalı",
    )
    ben_bytes = ben_orig.to_orjson_bytes()
    ben_restored = BenefitReport.from_dict(orjson.loads(ben_bytes))
    assert ben_restored.is_beneficial is True
    assert ben_restored.best_individual_name == "lightgbm"
    assert "BenefitReport" in repr(ben_orig)

    diag_orig = EnsembleDiagnostics(
        model_weights={"m1": 0.6, "m2": 0.4},
        model_ics={"m1": 0.08, "m2": 0.07},
        diversity=div_orig,
        benefit=ben_orig,
        n_models=2,
        n_successful=2,
        timestamp="2026-09-08T12:00:00Z",
    )
    diag_bytes = diag_orig.to_orjson_bytes()
    diag_restored = EnsembleDiagnostics.from_dict(orjson.loads(diag_bytes))
    assert diag_restored.n_successful == 2
    assert diag_restored.diversity.diversity_score == 0.6
    assert "EnsembleDiagnostics" in repr(diag_orig)

    state_orig = EnsembleState(
        weights={"m1": 0.5, "m2": 0.5},
        model_names=["m1", "m2"],
        diversity_scores={"m1": 0.7, "m2": 0.7},
        benefit_report=ben_orig,
        training_history=[{"epoch": 1, "loss": 0.02}],
        created_at="2026-09-08T12:00:00Z",
        version=1,
    )
    state_bytes = state_orig.to_orjson_bytes()
    state_restored = EnsembleState.from_dict(orjson.loads(state_bytes))
    assert state_restored.model_names == ["m1", "m2"]
    assert state_restored.benefit_report is not None
    assert state_restored.benefit_report.is_beneficial is True
    assert "EnsembleState" in repr(state_orig)


def test_predict_weighted_average_and_nan_handling() -> None:
    """Ağırlıklı tahmin ve NaN/Inf korumalarını test eder."""
    model = EnsembleModel()
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    # 2 model: m1 sabit 2.0 döndürür, m2 sabit 4.0 döndürür
    models = {
        "m1": lambda x: np.full(len(x), 2.0),
        "m2": lambda x: np.full(len(x), 4.0),
    }
    weights = {"m1": 1.0, "m2": 1.0}

    preds = model.predict(models=models, weights=weights, X=X)
    np.testing.assert_allclose(preds, [3.0, 3.0, 3.0])

    # Farklı ağırlıklar
    weights_unequal = {"m1": 3.0, "m2": 1.0}  # (2*3 + 4*1)/4 = 10/4 = 2.5
    preds_unequal = model.predict(models=models, weights=weights_unequal, X=X)
    np.testing.assert_allclose(preds_unequal, [2.5, 2.5, 2.5])

    # Model NaN döndürdüğünde nan_to_num guard devreye girmeli
    models_with_nan = {
        "m1": lambda x: np.full(len(x), 2.0),
        "m_nan": lambda x: np.array([np.nan, 4.0, np.inf]),
    }
    preds_nan = model.predict(models=models_with_nan, weights={"m1": 1.0, "m_nan": 1.0}, X=X)
    assert np.all(np.isfinite(preds_nan))

    # Boş veri veya model listesi boşken NaN dizisi dönmeli
    empty_preds = model.predict(models={}, weights={}, X=X)
    assert len(empty_preds) == len(X)
    assert np.all(np.isnan(empty_preds))


def test_predict_polars() -> None:
    """Polars DataFrame üzerinden tahmin yürütmeyi test eder."""
    model = EnsembleModel()
    df = pl.DataFrame(
        {
            "feat_1": [1.0, 2.0, 3.0],
            "feat_2": [10.0, 20.0, 30.0],
            "other_col": ["a", "b", "c"],
        }
    )

    models = {
        "m1": lambda x: x[:, 0] + x[:, 1],
    }
    preds = model.predict_polars(
        models=models,
        weights={"m1": 1.0},
        df=df,
        feature_columns=["feat_1", "feat_2"],
    )
    np.testing.assert_allclose(preds, [11.0, 22.0, 33.0])


def test_predict_with_confidence() -> None:
    """Model tahmin mutabakatı ve güven skorunun üretildiğini doğrular."""
    model = EnsembleModel()
    X = np.ones((5, 2))

    # Modeller tamamen hemfikir olduğunda
    models_agree = {
        "m1": lambda x: np.full(len(x), 5.0),
        "m2": lambda x: np.full(len(x), 5.0),
    }
    preds, conf = model.predict_with_confidence(models=models_agree, weights={"m1": 1.0, "m2": 1.0}, X=X)
    np.testing.assert_allclose(preds, np.full(5, 5.0))
    # Mutabakat tam -> güven 1.0 olmalı
    assert np.all(conf >= 0.99)

    # Modeller zıt görüşte olduğunda
    models_diverge = {
        "m1": lambda x: np.full(len(x), 1.0),
        "m2": lambda x: np.full(len(x), 10.0),
    }
    _, conf_div = model.predict_with_confidence(models=models_diverge, weights={"m1": 1.0, "m2": 1.0}, X=X)
    assert np.all(conf_div < conf)


def test_predict_dynamic_regimes() -> None:
    """Piyasa rejimine duyarlı dinamik ağırlıklandırmayı doğrular."""
    model = EnsembleModel()
    X = np.ones((2, 2))

    models = {
        "bull_specialist": lambda x: np.full(len(x), 10.0),
        "bear_specialist": lambda x: np.full(len(x), -10.0),
    }

    regime_weights = {
        "BULL": {"bull_specialist": 1.0, "bear_specialist": 0.0},
        "BEAR": {"bull_specialist": 0.0, "bear_specialist": 1.0},
    }

    bull_pred = model.predict_dynamic(models=models, X=X, regime="BULL", regime_weights=regime_weights)
    np.testing.assert_allclose(bull_pred, [10.0, 10.0])

    bear_pred = model.predict_dynamic(models=models, X=X, regime="BEAR", regime_weights=regime_weights)
    np.testing.assert_allclose(bear_pred, [-10.0, -10.0])


def test_diversity_analysis_and_pruning() -> None:
    """Çeşitlilik analizi ve gereksiz modellerin otomatik budanmasını test eder."""
    model = EnsembleModel(diversity_threshold=0.85)

    # m1 ve m2 neredeyse aynı (yüksek korelasyon)
    t = np.linspace(0, 10, 50)
    m1_preds = np.sin(t)
    m2_preds = np.sin(t) + np.random.normal(0, 0.01, size=50)  # corr ~ 0.99
    # m3 zıt ve bağımsız
    m3_preds = np.cos(t)

    predictions = {
        "lgb": m1_preds,
        "lgb_duplicate": m2_preds,
        "catboost": m3_preds,
    }

    report = model.analyze_diversity(predictions)
    assert isinstance(report, DiversityReport)
    # lgb ve lgb_duplicate korelasyonu > 0.85 olmalı
    assert report.correlation_matrix["lgb"]["lgb_duplicate"] > 0.85
    assert len(report.redundant_models) > 0

    # Auto-prune testi: IC'si düşük olan elenmeli
    model_ics = {"lgb": 0.08, "lgb_duplicate": 0.04, "catboost": 0.07}
    pruned_preds, removed = model.auto_prune_redundant(
        model_predictions=predictions,
        model_ics=model_ics,
    )
    assert "lgb_duplicate" in removed
    assert "lgb_duplicate" not in pruned_preds
    assert "lgb" in pruned_preds
    assert "catboost" in pruned_preds


def test_diagnose_method() -> None:
    """Diagnose metodunun model teşhis raporunu doğru oluşturduğunu test eder."""
    model = EnsembleModel()
    X = np.linspace(0, 10, 30).reshape(-1, 1)
    y_true = np.sin(X.ravel())

    models = {
        "m_good": lambda x: np.sin(x.ravel()) + np.random.normal(0, 0.01, size=len(x)),
        "m_poor": lambda x: np.cos(x.ravel()),
    }
    weights = {"m_good": 0.7, "m_poor": 0.3}

    diag = model.diagnose(models=models, weights=weights, X=X, y_true=y_true)
    assert isinstance(diag, EnsembleDiagnostics)
    assert diag.n_models == 2
    assert diag.n_successful == 2
    assert "m_good" in diag.model_ics
    assert "m_poor" in diag.model_ics
    assert diag.model_ics["m_good"] > diag.model_ics["m_poor"]


def test_should_use_ensemble_decision() -> None:
    """Çeşitlilik ve fayda kapısı kontrollerine göre kullanım kararını doğrular."""
    model = EnsembleModel()

    # 1. Düşük çeşitlilik -> Reddedilmeli
    div_bad = DiversityReport(
        correlation_matrix={},
        mean_correlation=0.95,
        diversity_score=0.05,
        redundant_models=["m1-m2"],
        recommendation="Düşük",
    )
    ben_good = BenefitReport(
        ensemble_ic=0.10,
        best_individual_ic=0.08,
        best_individual_name="m1",
        ic_improvement=0.02,
        is_beneficial=True,
        recommendation="Faydalı",
    )
    use_1, reason_1 = model.should_use_ensemble(div_bad, ben_good)
    assert use_1 is False
    assert "Düşük çeşitlilik" in reason_1

    # 2. Faydasız -> Reddedilmeli
    div_good = DiversityReport(
        correlation_matrix={},
        mean_correlation=0.3,
        diversity_score=0.7,
        redundant_models=[],
        recommendation="İyi",
    )
    ben_bad = BenefitReport(
        ensemble_ic=0.07,
        best_individual_ic=0.09,
        best_individual_name="m1",
        ic_improvement=-0.02,
        is_beneficial=False,
        recommendation="Faydasız",
    )
    use_2, reason_2 = model.should_use_ensemble(div_good, ben_bad)
    assert use_2 is False
    assert "tekil en iyi modelden daha düşük" in reason_2

    # 3. Hem çeşitlilik hem fayda var -> Kabul edilmeli
    use_3, reason_3 = model.should_use_ensemble(div_good, ben_good)
    assert use_3 is True
    assert "faydalı" in reason_3.lower()


def test_save_and_load_state(tmp_path: Path) -> None:
    """Ensemble model durumunun diske güvenle kaydedilip yüklendiğini test eder."""
    model = EnsembleModel()
    state_file = str(tmp_path / "ensemble_state.pkl")

    ben = BenefitReport(
        ensemble_ic=0.12,
        best_individual_ic=0.09,
        best_individual_name="m1",
        ic_improvement=0.03,
        is_beneficial=True,
        recommendation="İyi",
    )

    success_save = model.save_state(
        path=state_file,
        weights={"m1": 0.6, "m2": 0.4},
        model_names=["m1", "m2"],
        diversity_scores={"m1": 0.8, "m2": 0.8},
        benefit_report=ben,
    )
    assert success_save is True
    assert model.is_loaded is True

    # Yeni bir örnekte yükleme
    new_model = EnsembleModel()
    assert new_model.is_loaded is False
    success_load = new_model.load_state(state_file)
    assert success_load is True
    assert new_model.is_loaded is True
    assert new_model.state is not None
    assert new_model.state.model_names == ["m1", "m2"]
    assert new_model.state.weights["m1"] == 0.6


def test_duckdb_wal_export_and_polars_read(tmp_path: Path) -> None:
    """Teşhis verisinin DuckDB WAL ile kaydedilip Polars ile okunduğunu test eder."""
    model = EnsembleModel()
    db_file = str(tmp_path / "ensemble_audit.duckdb")

    div = DiversityReport({}, 0.3, 0.7, [], "İyi")
    ben = BenefitReport(0.12, 0.09, "lgb", 0.03, True, "Faydalı")
    diag = EnsembleDiagnostics(
        model_weights={"lgb": 0.7, "cat": 0.3},
        model_ics={"lgb": 0.09, "cat": 0.08},
        diversity=div,
        benefit=ben,
        n_models=2,
        n_successful=2,
        timestamp="2026-09-08T12:00:00Z",
    )

    model.export_diagnostics_duckdb(diagnostics=diag, db_path=db_file, table_name="test_diag")

    df_diag = model.read_diagnostics_polars(db_path=db_file, table_name="test_diag")
    assert isinstance(df_diag, pl.DataFrame)
    assert df_diag.height == 1
    assert df_diag["best_individual_name"][0] == "lgb"
    assert df_diag["is_beneficial"][0] is True


def test_thread_safety_concurrent_predict() -> None:
    """Çoklu thread eşzamanlı predict çalıştırdığında yarış durumu olmadığını doğrular."""
    model = EnsembleModel()
    X = np.ones((10, 2))
    models = {
        "m1": lambda x: np.full(len(x), 1.0),
        "m2": lambda x: np.full(len(x), 2.0),
    }
    weights = {"m1": 0.5, "m2": 0.5}

    def worker(idx: int) -> float:
        preds = model.predict(models=models, weights=weights, X=X * idx)
        return float(np.mean(preds))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futs = [executor.submit(worker, i + 1) for i in range(16)]
        for f in concurrent.futures.as_completed(futs):
            val = f.result()
            assert val == 1.5
