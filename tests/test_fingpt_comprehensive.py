"""ALPHA BIST — FinGPTSentiment Kapsamlı Test Paketi.

Bu test paketi 8 denetim kuralına tam uyumlu olarak FinGPTSentiment motorunu ve veri modellerini test eder:
1. Veri modelleri ve orjson serileştirme/deserileştirme (SentimentResult, AggregatedSentiment).
2. Kural tabanlı (rule-based fallback) finansal duygu analizi (BIST pozitif/negatif anahtar kelimeler, boş metin nötr guard).
3. Çoklu metin toplu analizi (analyze_batch).
4. Hisse bazlı zaman pencereli ağırlıklı toplulaştırma (get_ticker_sentiment: KAP vs News kaynak ağırlıkları ve momentum).
5. Polars DataFrame üzerinde doğrudan duygu analizi ve metrik sütunlarının eklenmesi (analyze_polars).
6. DuckDB SSD korumalı WAL denetim izi kaydı ve Polars DataFrame ile geri okuma.
7. Eşzamanlı iş parçacığı güvenliği (thread-safety).
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING

import orjson
import polars as pl

from services.ml.fingpt import (
    AggregatedSentiment,
    FinGPTSentiment,
    SentimentResult,
    SentimentSource,
    SentimentType,
    analyze_polars,
    read_sentiment_history_polars,
    save_aggregated_sentiment_to_duckdb,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_dataclasses_serialization() -> None:
    """Veri modellerinin to_dict, from_dict ve orjson serileştirmesini test eder."""
    res_orig = SentimentResult(
        text="Şirket rekor net kâr açıkladı",
        sentiment=SentimentType.POSITIVE.value,
        score=0.85,
        confidence=0.90,
        source=SentimentSource.KAP.value,
        ticker="THYAO",
        timestamp="2026-09-08T12:00:00Z",
    )
    r_bytes = res_orig.to_orjson_bytes()
    r_restored = SentimentResult.from_dict(orjson.loads(r_bytes))
    assert r_restored.ticker == "THYAO"
    assert r_restored.score == 0.85
    assert r_restored.sentiment == SentimentType.POSITIVE.value
    assert "SentimentResult" in repr(res_orig)

    agg_orig = AggregatedSentiment(
        ticker="THYAO",
        avg_score=0.65,
        weighted_score=0.72,
        sentiment=SentimentType.POSITIVE.value,
        n_sources=5,
        confidence=0.85,
        latest_score=0.80,
        momentum=0.15,
        calculated_at="2026-09-08T12:00:00Z",
    )
    a_bytes = agg_orig.to_orjson_bytes()
    a_restored = AggregatedSentiment.from_dict(orjson.loads(a_bytes))
    assert a_restored.ticker == "THYAO"
    assert a_restored.weighted_score == 0.72
    assert a_restored.momentum == 0.15
    assert "AggregatedSentiment" in repr(agg_orig)


def test_rule_based_sentiment_positive_and_negative() -> None:
    """Kural tabanlı duygu analizinde pozitif, negatif ve nötr metin tespitini test eder."""
    engine = FinGPTSentiment()

    # Pozitif BIST haberi
    pos_res = engine.analyze("Şirketimiz yeni iş ilişkisi ve rekor büyüme kaydetti.", source="kap", ticker="EREGL")
    assert pos_res.sentiment == SentimentType.POSITIVE.value
    assert pos_res.score > 0.0
    assert pos_res.confidence > 0.0

    # Negatif BIST haberi
    neg_res = engine.analyze("Operasyonel zarar ve konkordato riski bildirildi.", source="news", ticker="XYZ")
    assert neg_res.sentiment == SentimentType.NEGATIVE.value
    assert neg_res.score < 0.0

    # Nötr / Boş metin guard
    neutral_res = engine.analyze("Olağan genel kurul toplantısı yapıldı.")
    assert neutral_res.sentiment == SentimentType.NEUTRAL.value

    empty_res = engine.analyze("")
    assert empty_res.sentiment == SentimentType.NEUTRAL.value
    assert empty_res.score == 0.0


def test_analyze_batch() -> None:
    """Toplu metin analizini test eder."""
    engine = FinGPTSentiment()
    texts = [
        "Güçlü büyüme ve temettü dağıtımı",
        "Zarar ve ceza uygulandı",
        "Toplantı tarihi belirlendi",
    ]
    results = engine.analyze_batch(texts, source="kap", ticker="SISE")
    assert len(results) == 3
    assert results[0].sentiment == SentimentType.POSITIVE.value
    assert results[1].sentiment == SentimentType.NEGATIVE.value
    assert results[2].sentiment == SentimentType.NEUTRAL.value


def test_aggregated_sentiment_and_momentum() -> None:
    """Hisse bazlı ağırlıklı toplulaştırma ve momentum hesabını test eder."""
    engine = FinGPTSentiment()

    # Önce pozitif KAP haberi, sonra güçlü pozitif haberler
    res1 = engine.analyze("Kâr artışı sağlandı", source="kap", ticker="THYAO")
    res2 = engine.analyze("Yeni sipariş ve yatırım anlaşması", source="kap", ticker="THYAO")
    res3 = engine.analyze("Hedef fiyat yükseltildi ve al tavsiyesi", source="news", ticker="THYAO")

    # Manuel geçmiş kaydı simülasyonu
    engine._sentiment_history["THYAO"] = [res1, res2, res3]

    agg = engine.get_ticker_sentiment("THYAO", window_hours=24)
    assert agg is not None
    assert agg.ticker == "THYAO"
    assert agg.sentiment == SentimentType.POSITIVE.value
    assert agg.weighted_score > 0.10
    assert agg.n_sources == 3

    # Olmayan hisse için None dönmeli
    assert engine.get_ticker_sentiment("NON_EXISTENT") is None


def test_analyze_polars() -> None:
    """Polars DataFrame üzerinde doğrudan duygu analizi kolonları üretimini test eder."""
    df = pl.DataFrame(
        {
            "ticker": ["GARAN", "AKBNK", "KCHOL"],
            "text": [
                "Net kâr rekor kırdı ve temettü kararı alındı",
                "Operasyonel zarar, tedbir ve ceza uygulandı",
                "Genel kurul duyurusu",
            ],
        }
    )

    enriched_df = analyze_polars(df, text_col="text", ticker_col="ticker", source="kap")
    assert isinstance(enriched_df, pl.DataFrame)
    assert "sentiment" in enriched_df.columns
    assert "sentiment_score" in enriched_df.columns
    assert "sentiment_conf" in enriched_df.columns
    assert enriched_df["sentiment"][0] == SentimentType.POSITIVE.value
    assert enriched_df["sentiment"][1] == SentimentType.NEGATIVE.value

    # Boş DataFrame
    assert analyze_polars(pl.DataFrame()).is_empty()


def test_duckdb_wal_save_and_polars_read(tmp_path: Path) -> None:
    """Toplu hisse duygu sonucunun DuckDB WAL ile yazılıp Polars ile okunduğunu test eder."""
    db_file = str(tmp_path / "sentiment_audit.duckdb")

    agg = AggregatedSentiment(
        ticker="GARAN",
        avg_score=0.55,
        weighted_score=0.62,
        sentiment=SentimentType.POSITIVE.value,
        n_sources=4,
        confidence=0.88,
        latest_score=0.70,
        momentum=0.10,
    )

    save_aggregated_sentiment_to_duckdb(agg, db_path=db_file)

    df_hist = read_sentiment_history_polars(db_path=db_file, ticker="GARAN")
    assert isinstance(df_hist, pl.DataFrame)
    assert df_hist.height == 1
    assert df_hist["ticker"][0] == "GARAN"
    assert df_hist["weighted_score"][0] == 0.62


def test_thread_safety_fingpt() -> None:
    """Çoklu thread ile eşzamanlı duygu analizi çalıştırma güvenliğini test eder."""
    engine = FinGPTSentiment()

    def worker(idx: int) -> str:
        text = f"Hisse {idx} için rekor kâr ve yeni sipariş anlaşması"
        res = engine.analyze(text, source="news", ticker=f"TICKER_{idx}")
        return res.sentiment

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futs = [executor.submit(worker, i) for i in range(12)]
        for f in concurrent.futures.as_completed(futs):
            assert f.result() == SentimentType.POSITIVE.value
