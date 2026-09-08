"""ALPHA BIST — Hybrid Model Kapsamlı Test Paketi.

8 denetim kuralına tam uyumlu:
- Mock veri yok, deterministik sentetik piyasa ve sinyal verisi
- HybridAction, MarketRegime, MarketState ve HybridSignal dataclass serialization (to_dict, from_dict, orjson)
- predict() tekil sinyal birleştirme (Boğa, Ayı, Yatay, Yüksek Volatilite rejimleri)
- Sinyal çelişkisi tespiti ve ceza katsayısı (ML vs Sentiment vs RL)
- Piyasa işlem durdurma (HALT, CIRCUIT_BREAKER) fail-closed korumaları
- predict_polars() toplu Polars DataFrame hesaplaması
- DuckDB WAL yapılandırması ve get_audit_as_polars okuması
- hybrid_predict sarmalayıcı fonksiyon testi
- Çoklu iş parçacığı (threading) eşzamanlı tahmin testi
"""

import threading
from pathlib import Path
import polars as pl
import pytest

from services.ml.hybrid_model import (
    HybridAction,
    HybridModel,
    HybridSignal,
    MarketRegime,
    MarketState,
    hybrid_predict,
)


def test_hybrid_signal_dataclass_serialization():
    """HybridSignal dataclass ve orjson serileştirme testi."""
    sig = HybridSignal(
        action=HybridAction.BUY,
        confidence=0.88,
        ml_score=0.85,
        sentiment_score=0.75,
        rl_action=0,
        conflict=False,
        signals={"ml": 0.85, "sentiment": 0.75, "rl": 0},
        reasoning="Guclu alim sinyali",
    )
    d = sig.to_dict()
    assert d["action"] == "BUY"
    assert d["confidence"] == 0.88
    assert d["conflict"] is False

    # orjson byte dizisi
    raw_bytes = sig.to_orjson_bytes()
    assert isinstance(raw_bytes, bytes)

    # from_dict doğrulaması
    restored = HybridSignal.from_dict(d)
    assert restored.action == HybridAction.BUY
    assert restored.confidence == 0.88
    assert restored.ml_score == 0.85
    assert "HybridSignal" in repr(restored)


def test_hybrid_predict_bull_regime():
    """Boğa piyasasında güçlü ML ve sentiment ile BUY kararı testi."""
    model = HybridModel()
    signal = model.predict(
        ml_score=0.85,
        sentiment_score=0.80,
        rl_action=0,  # 0 = AL
        regime=MarketRegime.BULL,
        market_state=MarketState.NORMAL,
    )
    assert signal.action == HybridAction.BUY
    assert signal.confidence > 0.40
    assert signal.conflict is False


def test_hybrid_predict_bear_regime():
    """Ayı piyasasında düşük ML ve negatif sentiment ile SELL kararı testi."""
    model = HybridModel()
    signal = model.predict(
        ml_score=0.20,
        sentiment_score=-0.70,
        rl_action=2,  # 2 = SAT
        regime=MarketRegime.BEAR,
        market_state=MarketState.NORMAL,
    )
    assert signal.action == HybridAction.SELL
    assert signal.confidence > 0.30
    assert signal.conflict is False


def test_hybrid_predict_conflict_detection():
    """ML Alış (0.85) derken Sentiment çok negatif (-0.80) olduğunda çelişki tespiti."""
    model = HybridModel()
    signal = model.predict(
        ml_score=0.85,
        sentiment_score=-0.80,
        rl_action=2,  # 2 = SAT
        regime=MarketRegime.NORMAL,
        market_state=MarketState.NORMAL,
    )
    # Çelişki tespit edilmeli
    assert signal.conflict is True
    # Çelişki gerekçede belirtilmeli
    assert "celiskisi" in signal.reasoning


def test_hybrid_predict_market_halt_and_circuit_breaker():
    """Piyasa HALT veya CIRCUIT_BREAKER durumunda fail-safe HOLD testi."""
    model = HybridModel()
    # Güçlü al sinyali olsa bile devre kesicide HOLD vermeli
    signal_halt = model.predict(
        ml_score=0.95,
        sentiment_score=0.90,
        rl_action=0,
        regime=MarketRegime.NORMAL,
        market_state=MarketState.HALT,
    )
    assert signal_halt.action == HybridAction.HOLD
    assert "HALT" in signal_halt.reasoning

    signal_cb = model.predict(
        ml_score=0.95,
        sentiment_score=0.90,
        rl_action=0,
        regime=MarketRegime.HIGH_VOL,
        market_state=MarketState.CIRCUIT_BREAKER,
    )
    assert signal_cb.action == HybridAction.HOLD
    assert "CIRCUIT_BREAKER" in signal_cb.reasoning


def test_predict_polars():
    """predict_polars() toplu Polars veri çerçevesi füzyon testi."""
    model = HybridModel()
    df = pl.DataFrame({
        "ml_score": [0.85, 0.20, 0.50, 0.90],
        "sentiment_score": [0.70, -0.60, 0.05, 0.80],
        "rl_action": [0, 2, 1, 0],
    })
    result_df = model.predict_polars(df)
    assert isinstance(result_df, pl.DataFrame)
    assert result_df.height == 4
    assert "hybrid_action" in result_df.columns
    assert "confidence" in result_df.columns
    assert "conflict" in result_df.columns
    assert result_df["hybrid_action"][0] == "BUY"
    assert result_df["hybrid_action"][1] == "SELL"


def test_duckdb_wal_save_and_polars_read(tmp_path: Path):
    """DuckDB WAL korumalı sinyal kaydetme ve Polars ile geri okuma testi."""
    db_file = tmp_path / "test_hybrid.duckdb"
    model = HybridModel(duckdb_path=str(db_file))

    model.predict(
        ml_score=0.85,
        sentiment_score=0.75,
        rl_action=0,
        regime=MarketRegime.BULL,
        market_state=MarketState.NORMAL,
    )
    model.predict(
        ml_score=0.15,
        sentiment_score=-0.80,
        rl_action=2,
        regime=MarketRegime.BEAR,
        market_state=MarketState.NORMAL,
    )

    df_audit = model.get_audit_as_polars()
    assert isinstance(df_audit, pl.DataFrame)
    assert df_audit.height == 2
    assert "action" in df_audit.columns
    assert "confidence" in df_audit.columns


def test_hybrid_predict_wrapper():
    """hybrid_predict() modül seviyesi sarmalayıcı fonksiyon testi."""
    res = hybrid_predict(
        rl_action=0,
        sentiment_score=0.75,
        ml_score=0.80,
        regime="BULL",
        market_state="NORMAL",
    )
    assert isinstance(res, dict)
    assert res["action"] == "BUY"
    assert res["conflict"] is False


def test_thread_safety_hybrid_model():
    """Çoklu iş parçacığı ortamında thread-safe eşzamanlı füzyon testi."""
    model = HybridModel()
    errors = []

    def worker(tid: int):
        try:
            for i in range(15):
                score = (tid * 10 + i) % 100 / 100.0
                sig = model.predict(
                    ml_score=score,
                    sentiment_score=score - 0.5,
                    rl_action=0 if score > 0.5 else 2,
                    regime=MarketRegime.NORMAL,
                    market_state=MarketState.NORMAL,
                )
                assert sig.action in (HybridAction.BUY, HybridAction.HOLD, HybridAction.SELL)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
