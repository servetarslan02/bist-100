"""AdjustedMSELoss Kapsamlı ve Çok Senaryolu Test Paketi.

Bu test paketi; GEMINI.md Kural 1-8 standartlarına göre asimetrik kayıp motorunu,
yön ceza mekanizmalarını, gradient/hessian hesaplamalarını, Polars entegrasyonunu,
eşzamanlılık (thread-safety) ve sınır durumlarını doğrular.
"""

from __future__ import annotations

import concurrent.futures

import numpy as np
import polars as pl
import pytest

from services.ml.adjusted_loss import (
    DEFAULT_WRONG_DIRECTION_PENALTY,
    AdjustedMSELoss,
    adjusted_loss,
)


def test_initialization_and_properties() -> None:
    """Başlatma, varsayılan parametreler ve kısıt kontrolleri."""
    loss = AdjustedMSELoss()
    assert loss.penalty == DEFAULT_WRONG_DIRECTION_PENALTY
    assert "AdjustedMSELoss" in repr(loss)

    # Geçerli özel katsayı
    custom_loss = AdjustedMSELoss(wrong_direction_penalty=5.0)
    assert custom_loss.penalty == 5.0
    assert "5.0x" in repr(custom_loss)

    # 1.0'dan küçük geçersiz ceza çarpanı hatası
    with pytest.raises(ValueError, match="Ceza çarpanı 1.0'dan küçük olamaz"):
        AdjustedMSELoss(wrong_direction_penalty=0.5)

    # Serileştirme kontrolleri
    d = custom_loss.to_dict()
    assert d["name"] == "AdjustedMSELoss"
    assert d["wrong_direction_penalty"] == 5.0

    b = custom_loss.to_orjson_bytes()
    assert isinstance(b, bytes)
    assert b"AdjustedMSELoss" in b


def test_calculate_basic_and_symmetric() -> None:
    """Temel kayıp hesaplaması ve doğru yön ile asimetrik yön ayrımı."""
    loss = AdjustedMSELoss(wrong_direction_penalty=10.0)

    # 1. Mükemmel tahminler (Sıfır hata)
    preds = np.array([0.05, -0.02, 0.01])
    acts = np.array([0.05, -0.02, 0.01])
    res = loss.calculate(preds, acts)
    assert res["simple_mse"] == 0.0
    assert res["adjusted_mse"] == 0.0
    assert res["wrong_direction_count"] == 0.0
    assert res["direction_accuracy"] == 100.0

    # 2. Tamamen ters yön tahminleri (Tümü 10x cezalandırılmalı)
    # pred: +1.0, actual: -1.0 -> diff = 2.0 -> sq_err = 4.0 -> adjusted = 40.0
    preds_wrong = np.array([1.0, -1.0])
    acts_wrong = np.array([-1.0, 1.0])
    res_wrong = loss.calculate(preds_wrong, acts_wrong)
    assert res_wrong["simple_mse"] == 4.0
    assert res_wrong["adjusted_mse"] == 40.0
    assert res_wrong["wrong_direction_count"] == 2.0
    assert res_wrong["wrong_direction_pct"] == 100.0
    assert res_wrong["direction_accuracy"] == 0.0

    # 3. Karışık durum: 1 doğru, 1 yanlış
    preds_mix = np.array([1.0, 1.0])
    acts_mix = np.array([1.0, -1.0])
    # Doğru: diff = 0.0 -> err = 0.0
    # Yanlış: diff = 2.0 -> err = 4.0 -> adj = 40.0
    # Mean adj = (0 + 40) / 2 = 20.0
    res_mix = loss.calculate(preds_mix, acts_mix)
    assert res_mix["simple_mse"] == 2.0
    assert res_mix["adjusted_mse"] == 20.0
    assert res_mix["wrong_direction_count"] == 1.0
    assert res_mix["direction_accuracy"] == 50.0


def test_calculate_edge_cases() -> None:
    """Boş dizi, boyut uyuşmazlığı ve NaN/Inf filtreleme sınır durumları."""
    loss = AdjustedMSELoss()

    # Boş dizi
    res_empty = loss.calculate([], [])
    assert res_empty["simple_mse"] == 0.0
    assert res_empty["adjusted_mse"] == 0.0

    # Boyut uyuşmazlığı
    with pytest.raises(ValueError, match="boyutları uyuşmuyor"):
        loss.calculate([1.0, 2.0], [1.0])

    # NaN ve Inf verileri güvenle filtreleme
    preds_dirty = np.array([0.05, np.nan, 0.02, np.inf])
    acts_dirty = np.array([0.05, 0.01, -0.02, 0.03])
    res_dirty = loss.calculate(preds_dirty, acts_dirty)
    # Sadece 0.05 vs 0.05 (doğru) ve 0.02 vs -0.02 (yanlış) işlenmeli
    assert res_dirty["wrong_direction_count"] == 1.0
    assert res_dirty["direction_accuracy"] == 50.0

    # Tümü kirli ise
    res_all_dirty = loss.calculate([np.nan], [np.nan])
    assert res_all_dirty["simple_mse"] == 0.0


def test_calculate_per_sample() -> None:
    """Tekil örnek bazında kayıp hesaplama mantığı."""
    loss = AdjustedMSELoss(wrong_direction_penalty=5.0)

    # Doğru yön (pred: 0.1, act: 0.2 -> diff: -0.1, sq: 0.01)
    s_ok = loss.calculate_per_sample(0.1, 0.2)
    assert pytest.approx(s_ok["error"], 1e-6) == 0.01
    assert s_ok["is_wrong_direction"] == 0.0
    assert s_ok["penalty_applied"] == 1.0

    # Yanlış yön (pred: 0.1, act: -0.1 -> diff: 0.2, sq: 0.04 -> penalty 5x -> 0.20)
    s_wrong = loss.calculate_per_sample(0.1, -0.1)
    assert pytest.approx(s_wrong["error"], 1e-6) == 0.20
    assert s_wrong["is_wrong_direction"] == 1.0
    assert s_wrong["penalty_applied"] == 5.0

    # NaN koruması
    s_nan = loss.calculate_per_sample(float("nan"), 0.5)
    assert s_nan["error"] == 0.0


def test_gradient_and_hessian() -> None:
    """Gradient boosting (LightGBM/XGBoost) özel amaç fonksiyonu türevleri."""
    loss = AdjustedMSELoss(wrong_direction_penalty=10.0)

    preds = np.array([0.2, -0.2])
    acts = np.array([0.1, 0.2])  # 1. doğru yön (+ / +), 2. ters yön (- / +)

    grad = loss.get_gradient(preds, acts)
    hess = loss.get_hessian(preds, acts)

    # 1. Doğru yön: dL/dy = 2 * (0.2 - 0.1) = 0.2
    assert pytest.approx(grad[0], 1e-6) == 0.2
    assert pytest.approx(hess[0], 1e-6) == 2.0

    # 2. Ters yön: dL/dy = 2 * (-0.2 - 0.2) * 10 = -8.0
    assert pytest.approx(grad[1], 1e-6) == -8.0
    # Hessian: 2 * 10 = 20.0
    assert pytest.approx(hess[1], 1e-6) == 20.0

    # custom_objective tuple testi
    g, h = loss.custom_objective(preds, acts)
    np.testing.assert_array_almost_equal(g, grad)
    np.testing.assert_array_almost_equal(h, hess)

    # Boyut uyuşmazlığı hatası
    with pytest.raises(ValueError, match="boyutları uyuşmuyor"):
        loss.get_gradient(np.array([1.0]), np.array([1.0, 2.0]))

    with pytest.raises(ValueError, match="boyutları uyuşmuyor"):
        loss.get_hessian(np.array([1.0]), np.array([1.0, 2.0]))


def test_calculate_polars() -> None:
    """Polars DataFrame entegrasyonu ve sütun doğrulama."""
    loss = AdjustedMSELoss(wrong_direction_penalty=4.0)

    df = pl.DataFrame({
        "pred": [0.05, -0.03, 0.02],
        "actual": [0.04, 0.02, 0.01],  # 2. satır yanlış yön
    })

    res = loss.calculate_polars(df, pred_col="pred", actual_col="actual")
    assert res["wrong_direction_count"] == 1.0
    assert pytest.approx(res["direction_accuracy"], 0.1) == 66.67

    # Olmayan sütun kontrolü
    with pytest.raises(KeyError, match="Sütunlar bulunamadı"):
        loss.calculate_polars(df, pred_col="non_existent", actual_col="actual")


def test_thread_safety_concurrent_execution() -> None:
    """Eşzamanlı iş parçacıklarında yarış durumu (race condition) koruması."""
    loss = AdjustedMSELoss(wrong_direction_penalty=3.0)

    def worker(i: int) -> float:
        preds = np.array([0.1 * i, -0.05 * i])
        acts = np.array([0.1 * i, 0.05 * i])
        res = loss.calculate(preds, acts)
        return res["adjusted_mse"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, i) for i in range(1, 50)]
        results = [f.result() for f in futures]

    assert len(results) == 49
    assert all(r > 0.0 for r in results)


def test_singleton_instance() -> None:
    """Varsayılan singleton örneğinin doğruluğu."""
    assert isinstance(adjusted_loss, AdjustedMSELoss)
    assert adjusted_loss.penalty == DEFAULT_WRONG_DIRECTION_PENALTY
    res = adjusted_loss.calculate([0.01], [0.01])
    assert res["direction_accuracy"] == 100.0
