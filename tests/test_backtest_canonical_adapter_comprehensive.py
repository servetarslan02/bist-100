"""
ALPHA BIST — Backtest Canonical Adapter Comprehensive Test Suite

BacktestCanonicalAdapter, _scalar_features, lazy-loading, feature parity,
compute_score, compute_score_and_decision ve thread güvenliğini doğrular.
"""

from __future__ import annotations

import concurrent.futures

import numpy as np

from services.backtest.canonical_adapter import (
    BacktestCanonicalAdapter,
    _scalar_features,
    backtest_canonical_adapter,
)


def test_scalar_features_filtering() -> None:
    """_scalar_features fonksiyonunun sadece sonlu sayısal değerleri aldığını doğrular."""
    raw = {
        "f_finite": 12.5,
        "f_int": 42,
        "f_numpy_float": np.float64(3.14),
        "f_nan": float("nan"),
        "f_inf": float("inf"),
        "f_str": "string_val",
        "f_list": [1, 2, 3],
        "f_dict": {"a": 1},
    }

    filtered = _scalar_features(raw)
    assert "f_finite" in filtered
    assert "f_int" in filtered
    assert "f_numpy_float" in filtered
    assert "f_nan" not in filtered
    assert "f_inf" not in filtered
    assert "f_str" not in filtered
    assert "f_list" not in filtered
    assert "f_dict" not in filtered
    assert filtered["f_finite"] == 12.5
    assert filtered["f_int"] == 42


def test_scalar_features_empty() -> None:
    """Boş veya geçersiz girdi durumlarını test eder."""
    assert _scalar_features({}) == {}
    assert _scalar_features({"a": "none", "b": None}) == {}


def test_canonical_adapter_initialization_and_repr() -> None:
    """Adaptör ilklendirme ve repr çıktısını doğrular."""
    adapter = BacktestCanonicalAdapter()
    assert adapter._scoring is None
    assert adapter._decision_engine is None
    assert "scoring_loaded=False" in repr(adapter)
    assert repr(backtest_canonical_adapter).startswith("BacktestCanonicalAdapter")


def test_canonical_adapter_lazy_load() -> None:
    """_lazy_load metodu çağrıldığında servislerin başarıyla bağlandığını doğrular."""
    adapter = BacktestCanonicalAdapter()
    adapter._lazy_load()
    assert adapter._scoring is not None
    assert adapter._decision_engine is not None
    assert "scoring_loaded=True" in repr(adapter)


def test_enrich_features_for_canonical() -> None:
    """enrich_features_for_canonical metodunun sözlüğü kopyalayıp koruduğunu doğrular."""
    adapter = BacktestCanonicalAdapter()
    feats = {"f1": 1.0, "f2": 2.0}
    enriched = adapter.enrich_features_for_canonical(feats, ticker="THYAO", date_str="2025-01-01")
    assert enriched == feats
    assert enriched is not feats  # Yeni kopya olmalı


def test_compute_score_rule_based() -> None:
    """Kural tabanlı (ml_model=None) fırsat puanı hesaplamasını doğrular."""
    adapter = BacktestCanonicalAdapter()
    feats = {
        "rsi_14": 45.0,
        "macd_signal": 0.5,
        "momentum_10": 1.2,
        "volatility_20": 0.02,
    }

    score = adapter.compute_score(
        features=feats,
        regime="BULL",
        ticker="THYAO",
    )

    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_compute_score_and_decision() -> None:
    """Fırsat skoru ve işlem aksiyonu (BUY/HOLD/SELL) ikilisinin üretildiğini doğrular."""
    adapter = BacktestCanonicalAdapter()
    feats = {
        "rsi_14": 30.0,
        "macd_signal": 1.2,
        "momentum_10": 2.5,
        "volatility_20": 0.015,
    }

    score, action = adapter.compute_score_and_decision(
        features=feats,
        regime="BULL",
        price=150.0,
        ticker="ASELS",
    )

    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0
    assert isinstance(action, str)
    assert action in ["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL", "NO_ACTION"]


def test_apply_feature_parity_fallback_on_error() -> None:
    """Feature parity uygulanırken hata çıkarsa sistemin çökmeden ham feature'ları döndürdüğünü doğrular."""
    adapter = BacktestCanonicalAdapter()

    # Hatalı model nesnesi
    class BuggyModel:
        feature_names = ["f1", "f2"]
        cs_features = ["f1"]
        impute_values = None

    model = BuggyModel()
    feats = {"f1": 10.0, "f2": 20.0}

    # all_day_features eksik format verilse bile güvenle ham features döner
    res = adapter._apply_feature_parity(
        features=feats,
        ml_model=model,
        ticker="GARAN",
        all_day_features={"GARAN": feats},
        date_str="2025-01-01",
    )
    assert isinstance(res, dict)
    assert "f1" in res


def test_canonical_adapter_thread_safety() -> None:
    """Eşzamanlı thread'lerde adaptörün güvenle skor ürettiğini doğrular."""
    adapter = BacktestCanonicalAdapter()
    feats = {"rsi_14": 50.0, "macd_signal": 0.2}

    def _task(i: int) -> float:
        return adapter.compute_score(features=feats, ticker=f"TICKER_{i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_task, i) for i in range(8)]
        scores = [f.result() for f in futures]

    assert len(scores) == 8
    for s in scores:
        assert 0.0 <= s <= 100.0
