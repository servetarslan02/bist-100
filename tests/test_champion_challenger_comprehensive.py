"""ALPHA BIST — ChampionChallenger Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak ChampionChallenger motorunu ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (to_dict, from_dict, to_orjson_bytes).
2. Tekil ve toplu metrik kaydı, NaN/Inf guard kontrolleri.
3. Polars DataFrame üzerinden toplu metrik aktarımı.
4. İki örneklemli A/B t-testi, Cohen's d etki büyüklüğü, istatistiksel güç ve yetersiz örneklem durumları.
5. Çoklu metrik karşılaştırması ve katı terfi (PromotionDecision) kuralları (üstünlük, gerileme, eşitlik).
6. Geri alma (Rollback) ve sıfırlama (Reset) mekanizmaları.
7. DuckDB WAL denetim tablosu ihracı ve Polars DataFrame ile geri okuma.
8. Thread-safety: Çoklu iş parçacıkları ile eşzamanlı metrik kayıt ve okuma güvenliği.
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import numpy as np
import orjson
import polars as pl
import pytest

from services.ml.champion_challenger import (
    ABTestResult,
    ChampionChallenger,
    MultiMetricResult,
    PromotionDecision,
)


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    ab_orig = ABTestResult(
        champion_metric=0.12,
        challenger_metric=0.18,
        p_value=0.012,
        significant=True,
        winner="challenger",
        n_samples_champion=40,
        n_samples_challenger=40,
        confidence_level=0.95,
        effect_size=0.85,
        power=0.90,
    )
    ab_dict = ab_orig.to_dict()
    ab_bytes = ab_orig.to_orjson_bytes()
    assert isinstance(ab_bytes, bytes)
    ab_restored = ABTestResult.from_dict(orjson.loads(ab_bytes))
    assert ab_restored.winner == "challenger"
    assert ab_restored.significant is True
    assert "ABTestResult" in repr(ab_orig)

    mm_orig = MultiMetricResult(
        metric_name="sharpe",
        champion_value=1.5,
        challenger_value=2.1,
        winner="challenger",
        improvement_pct=40.0,
    )
    mm_bytes = mm_orig.to_orjson_bytes()
    mm_restored = MultiMetricResult.from_dict(orjson.loads(mm_bytes))
    assert mm_restored.metric_name == "sharpe"
    assert mm_restored.improvement_pct == 40.0
    assert "MultiMetricResult" in repr(mm_orig)

    promo_orig = PromotionDecision(
        should_promote=True,
        reason="Test terfisi",
        ab_results={"sharpe": ab_orig},
        multi_metric_results=[mm_orig],
        overall_winner="challenger",
        confidence=1.0,
    )
    promo_bytes = promo_orig.to_orjson_bytes()
    promo_restored = PromotionDecision.from_dict(orjson.loads(promo_bytes))
    assert promo_restored.should_promote is True
    assert promo_restored.ab_results["sharpe"].winner == "challenger"
    assert promo_restored.multi_metric_results[0].metric_name == "sharpe"
    assert "PromotionDecision" in repr(promo_orig)


def test_record_metrics_and_nan_guards() -> None:
    """Tekil ve toplu metrik kaydı ile geçersiz NaN/Inf değerlerinin guard edildiğini doğrular."""
    engine = ChampionChallenger(min_samples=10)

    # Geçerli kayıtlar
    engine.record_champion_result("return", 0.05)
    engine.record_shadow_result("catboost_v1", "return", 0.08)

    # Geçersiz değerler (NaN, Inf) atlanmalı
    engine.record_champion_result("return", float("nan"))
    engine.record_champion_result("return", float("inf"))
    engine.record_shadow_result("catboost_v1", "return", float("nan"))

    # Toplu kayıt
    engine.record_batch("catboost_v1", {"ic": 0.12, "sharpe": 1.8}, is_champion=False)
    engine.record_batch("champion", {"ic": 0.10, "sharpe": 1.5}, is_champion=True)

    c_summary = engine.get_champion_summary()
    assert c_summary["return"]["n_samples"] == 1
    assert c_summary["ic"]["n_samples"] == 1

    s_summary = engine.get_shadow_summary()
    assert "catboost_v1" in s_summary
    assert s_summary["catboost_v1"]["return"]["n_samples"] == 1
    assert s_summary["catboost_v1"]["ic"]["n_samples"] == 1


def test_record_metrics_polars() -> None:
    """Polars DataFrame üzerinden toplu metrik aktarımını test eder."""
    engine = ChampionChallenger(min_samples=10)

    df = pl.DataFrame(
        {
            "model_id": ["champion", "challenger_lgb", "challenger_lgb", "champion"],
            "ic": [0.05, 0.08, 0.09, 0.06],
            "return": [0.02, 0.04, 0.03, 0.025],
        }
    )

    engine.record_metrics_polars(
        df=df,
        model_column="model_id",
        metric_columns=["ic", "return"],
        champion_key="champion",
    )

    c_summary = engine.get_champion_summary()
    assert c_summary["ic"]["n_samples"] == 2
    assert c_summary["return"]["n_samples"] == 2

    s_summary = engine.get_shadow_summary()
    assert "challenger_lgb" in s_summary
    assert s_summary["challenger_lgb"]["ic"]["n_samples"] == 2
    assert s_summary["challenger_lgb"]["return"]["n_samples"] == 2


def test_ab_test_insufficient_samples() -> None:
    """Örneklem sayısı asgari eşiğin altındayken AB testinin insufficient_data döndürdüğünü doğrular."""
    engine = ChampionChallenger(min_samples=30)
    for _ in range(10):
        engine.record_champion_result("ic", 0.05)
        engine.record_shadow_result("challenger_1", "ic", 0.08)

    ab_res = engine.run_ab_test("challenger_1", "ic")
    assert ab_res.winner == "insufficient_data"
    assert ab_res.significant is False
    assert ab_res.p_value == 1.0


def test_ab_test_significant_difference() -> None:
    """Belirgin performans farkında t-test, Cohen's d ve power hesaplarının çalıştığını test eder."""
    np.random.seed(42)
    engine = ChampionChallenger(significance_level=0.05, min_samples=30)

    # Champion: ortalama 0.05, std 0.01
    champ_vals = np.random.normal(loc=0.05, scale=0.01, size=40)
    # Challenger: ortalama 0.08, std 0.01 (belirgin üstün)
    chall_vals = np.random.normal(loc=0.08, scale=0.01, size=40)

    for c, ch in zip(champ_vals, chall_vals, strict=True):
        engine.record_champion_result("return", float(c))
        engine.record_shadow_result("challenger_best", "return", float(ch))

    ab_res = engine.run_ab_test("challenger_best", "return")
    assert ab_res.winner == "challenger"
    assert ab_res.significant is True
    assert ab_res.p_value < 0.01
    assert ab_res.effect_size > 1.0  # Çok güçlü etki
    assert ab_res.power > 0.80  # Yüksek istatistiksel güç


def test_multi_metric_and_promotion_decision_success() -> None:
    """Tüm koşullar sağlandığında modelin terfi (should_promote=True) aldığını doğrular."""
    np.random.seed(123)
    engine = ChampionChallenger(
        significance_level=0.05,
        min_samples=30,
        metrics_to_compare=["return", "ic", "sharpe"],
    )

    for _ in range(40):
        # Champion
        engine.record_champion_result("return", float(np.random.normal(0.04, 0.01)))
        engine.record_champion_result("ic", float(np.random.normal(0.05, 0.01)))
        engine.record_champion_result("sharpe", float(np.random.normal(1.2, 0.2)))

        # Challenger belirgin üstün
        engine.record_shadow_result("challenger_winner", "return", float(np.random.normal(0.07, 0.01)))
        engine.record_shadow_result("challenger_winner", "ic", float(np.random.normal(0.09, 0.01)))
        engine.record_shadow_result("challenger_winner", "sharpe", float(np.random.normal(2.0, 0.2)))

    decision = engine.should_promote("challenger_winner")
    assert decision.should_promote is True
    assert decision.overall_winner == "challenger"
    assert decision.confidence == 1.0
    assert "0 gerileme" in decision.reason

    history = engine.get_history()
    assert len(history) == 1
    assert history[0]["decision"] is True


def test_promotion_decision_rejected_on_regression() -> None:
    """Bir metrikte gerileme olduğunda terfinin reddedildiğini (Fail-Closed) doğrular."""
    np.random.seed(999)
    engine = ChampionChallenger(
        significance_level=0.05,
        min_samples=30,
        metrics_to_compare=["return", "drawdown"],
    )

    for _ in range(40):
        # Return'da challenger iyi ama drawdown'da şampiyon belirgin iyi (challenger gerileme)
        engine.record_champion_result("return", float(np.random.normal(0.04, 0.01)))
        engine.record_champion_result("drawdown", float(np.random.normal(0.10, 0.01)))

        engine.record_shadow_result("challenger_bad", "return", float(np.random.normal(0.06, 0.01)))
        engine.record_shadow_result("challenger_bad", "drawdown", float(np.random.normal(0.02, 0.01)))

    decision = engine.should_promote("challenger_bad")
    # Drawdown'da şampiyon üstün olduğu için anlamlı gerileme var
    assert decision.should_promote is False
    assert "gerileme" in decision.reason or "kaybı" in decision.reason


def test_rollback_and_reset() -> None:
    """Geri alma ve sıfırlama işlemlerinin doğruluğunu test eder."""
    engine = ChampionChallenger()
    engine.record_shadow_result("c1", "ic", 0.05)
    engine.record_shadow_result("c2", "ic", 0.06)
    engine.record_champion_result("ic", 0.04)

    assert engine.rollback("c1") is True
    assert "c1" not in engine.get_shadow_summary()
    assert "c2" in engine.get_shadow_summary()

    # Sıfırlama
    engine.reset()
    assert len(engine.get_shadow_summary()) == 0
    assert len(engine.get_champion_summary()) == 0
    assert len(engine.get_history()) == 0


def test_duckdb_wal_export_and_polars_read(tmp_path: Path) -> None:
    """Geçmiş kararların DuckDB WAL ile kaydedilip Polars ile hatasız okunduğunu test eder."""
    db_file = str(tmp_path / "champion_audit.duckdb")
    engine = ChampionChallenger(min_samples=5, metrics_to_compare=["ic"])

    for _ in range(10):
        engine.record_champion_result("ic", 0.05)
        engine.record_shadow_result("challenger_duck", "ic", 0.08)

    engine.should_promote("challenger_duck")
    engine.export_decision_history_duckdb(db_path=db_file, table_name="test_audit")

    df_history = engine.read_decision_history_polars(db_path=db_file, table_name="test_audit")
    assert isinstance(df_history, pl.DataFrame)
    assert df_history.height == 1
    assert df_history["challenger_key"][0] == "challenger_duck"
    assert "decision" in df_history.columns


def test_thread_safety_concurrent_access() -> None:
    """Çoklu thread eşzamanlı metrik yazma ve okuma durumunda race condition oluşmadığını doğrular."""
    engine = ChampionChallenger(min_samples=10)

    def worker_shadow(idx: int) -> None:
        for i in range(50):
            engine.record_shadow_result(f"model_{idx % 3}", "return", 0.01 * (idx + i))

    def worker_champ(idx: int) -> None:
        for i in range(50):
            engine.record_champion_result("return", 0.01 * (idx + i))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futs = []
        for i in range(8):
            if i % 2 == 0:
                futs.append(executor.submit(worker_shadow, i))
            else:
                futs.append(executor.submit(worker_champ, i))
        for f in concurrent.futures.as_completed(futs):
            f.result()

    c_summary = engine.get_champion_summary()
    assert c_summary["return"]["n_samples"] == 200
