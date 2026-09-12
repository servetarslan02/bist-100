"""ALPHA BIST — Labels Service Audit & Hardening Tests.

LabelResult, LabelGenerator, forward getiri hesaplamaları, purge gap,
cross-sectional rank ve fail-closed davranışları canlı olarak test edilir.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.labels.generator import (
    LabelGenerator,
    LabelResult,
    label_generator,
)


def test_label_result_representation():
    """LabelResult dataclass ve __repr__ metodu doğrulaması."""
    labels = {
        "y_5d": np.array([1.5, 2.0, -0.5, 3.2]),
        "y_20d": np.array([4.5, 5.0, 1.2, 8.0]),
    }
    valid_mask = np.array([True, True, True, False])
    stats = {
        "y_5d": {"mean": 1.55, "std": 1.35, "min": -0.5, "max": 3.2, "count": 4},
    }

    result = LabelResult(
        ticker="THYAO",
        labels=labels,
        valid_mask=valid_mask,
        stats=stats,
    )
    assert "LabelResult" in repr(result)
    assert "THYAO" in repr(result)
    assert "labels_count=2" in repr(result)
    assert "valid_ratio=75.0%" in repr(result)


def test_label_generator_initialization_and_names():
    """LabelGenerator initialization, __repr__ ve get_label_names doğrulaması."""
    gen = LabelGenerator()
    assert "LabelGenerator" in repr(gen)
    assert "periods=[1, 5, 10, 20]" in repr(gen)

    names = gen.get_label_names()
    assert len(names) > 0
    assert "y_1d" in names
    assert "y_5d" in names
    assert "y_20d" in names
    assert "y_max_dd_20d" in names
    assert "y_volatility_20d" in names
    assert "y_5d_binary" in names
    assert "y_20d_vs_sector" in names


def test_generate_labels_basic_and_purge():
    """generate_labels temel hesaplama, purge_days ve istatistik doğrulaması."""
    gen = LabelGenerator()

    n = 60
    close = np.linspace(100.0, 130.0, n)
    mask = np.ones(n, dtype=int)
    sector = np.full(n, 0.001)
    benchmark = np.full(n, 0.0008)

    # Purge days olmadan
    res = gen.generate_labels(
        ticker="GARAN",
        close=close,
        mask=mask,
        sector_returns=sector,
        benchmark_returns=benchmark,
        purge_days=0,
    )
    assert res.ticker == "GARAN"
    assert "y_5d" in res.labels
    assert "y_20d" in res.labels
    assert "y_max_dd_20d" in res.labels
    assert "y_volatility_20d" in res.labels
    assert "y_5d_vs_sector" in res.labels
    assert "y_5d_vs_benchmark" in res.labels
    assert "y_5d_outperform" in res.labels
    assert len(res.stats) > 0

    # Purge days ile (son 5 bar NaN olmalı)
    res_purged = gen.generate_labels(
        ticker="GARAN",
        close=close,
        mask=mask,
        purge_days=5,
    )
    for label_name, arr in res_purged.labels.items():
        assert np.all(np.isnan(arr[-5:])), f"{label_name} son 5 barı NaN olmalıdır."
    assert np.all(~res_purged.valid_mask[-5:]), "valid_mask son 5 barı False olmalıdır."


def test_generate_labels_fail_closed_validation():
    """generate_labels fail-closed sınır ve boyut kontrolleri doğrulaması."""
    gen = LabelGenerator()

    # Boyut uyuşmazlığı
    with pytest.raises(ValueError, match="boyutları eşleşmelidir"):
        gen.generate_labels("AKBNK", np.array([10.0, 11.0]), np.array([1]))

    # Boş dizi
    with pytest.raises(ValueError, match="boş olamaz"):
        gen.generate_labels("AKBNK", np.array([]), np.array([]))


def test_generate_cross_sectional_ranks():
    """generate_cross_sectional_ranks hesaplama ve sınır doğrulaması."""
    gen = LabelGenerator()

    # İki hisse için label dict'i
    all_labels = {
        "THYAO": {"y_5d": np.array([2.5, 3.0, 1.0, 5.0, 2.0])},
        "GARAN": {"y_5d": np.array([1.5, 4.0, 0.5, 6.0, 1.0])},
        "KCHOL": {"y_5d": np.array([0.5, 2.0, 2.0, 4.0, 3.0])},
    }

    ranks = gen.generate_cross_sectional_ranks(all_labels, label_name="y_5d")
    assert len(ranks) == 3
    assert "THYAO" in ranks
    assert "GARAN" in ranks
    assert "KCHOL" in ranks

    # Rank değerleri 0 ile 1 arasında olmalıdır
    for ticker, rank_arr in ranks.items():
        valid_ranks = rank_arr[~np.isnan(rank_arr)]
        assert np.all(valid_ranks >= 0.0)
        assert np.all(valid_ranks <= 1.0)

    # İlk günde: KCHOL(0.5) < GARAN(1.5) < THYAO(2.5)
    assert ranks["KCHOL"][0] < ranks["GARAN"][0] < ranks["THYAO"][0]

    # Boş giriş kontrolü
    assert gen.generate_cross_sectional_ranks({}) == {}


def test_singleton_label_generator():
    """label_generator singleton nesnesi doğrulaması."""
    assert isinstance(label_generator, LabelGenerator)
    assert len(label_generator.FORWARD_PERIODS) == 4
