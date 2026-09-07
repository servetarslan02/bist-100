"""ALPHA BIST — Canonical Scoring Pipeline v1.0 (Kanonik Skorlama Motoru)

TEK KARAR MİMARİSİ:
Tüm scoring mekanizmalarını tek bir canonical pipeline altında birleştirir.

EĞİTİM VE ÇALIŞMA MİMARİSİ:
VERİ → FEATURE CONTRACT → 9 MOTOR → CROSS-SECTIONAL → CANONICAL SCORE → DECISION → RİSK → PORTFÖY

Bu modül:
- 9 analitik motorun çıktısını tek bir tip-güvenli `ScoreVector` içinde birleştirir.
- Eksik, STALE veya MISSING veriyi körü körüne 0'a çevirmez; güven ve kalite metriği ile işaretler.
- Risk ve fırsat boyutlarını kesin olarak ayrı tutar.
- Sayısal taşma (NaN / Inf) ve sıfıra bölme risklerine karşı fail-safe guard'lar uygular.
- Polars vektörizasyonu ve DuckDB analitik saklama desteği sunar.
- Decision Engine'e ve portföy tahsisatına tam yapılandırılmış girdi sağlar.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

from services.core.otel import otel_trace

logger = structlog.get_logger(__name__)

# =====================================================
# YAPILANDIRMA SABİTLERİ (DEFAULT CONSTANTS)
# =====================================================
DEFAULT_ML_WEIGHT: float = 0.7
DEFAULT_RULE_WEIGHT: float = 0.3
DEFAULT_NEUTRAL_SCORE: float = 50.0
DEFAULT_RISK_BASELINE_SCORE: float = 70.0
DEFAULT_LONG_THRESHOLD: float = 60.0
DEFAULT_SHORT_THRESHOLD: float = 40.0
DEFAULT_MAX_HISTORY: int = 1000
DEFAULT_DUCKDB_PATH: Path = Path("data/canonical_scores.duckdb")

# Ağırlık Sabitleri (Rejim Bazlı - services/ml/ranking_model.py ile uyumlu)
REGIME_WEIGHTS_MAP: dict[str, dict[str, float]] = {
    "BULL": {
        "technical": 0.15,
        "momentum": 0.20,
        "relative_strength": 0.10,
        "volume": 0.08,
        "fundamental": 0.10,
        "news_sentiment": 0.08,
        "catalyst": 0.05,
        "mean_reversion": 0.02,
        "seasonality": 0.02,
        "market_regime": 0.10,
        "risk": 0.10,
    },
    "BEAR": {
        "technical": 0.10,
        "momentum": 0.05,
        "relative_strength": 0.05,
        "volume": 0.08,
        "fundamental": 0.15,
        "news_sentiment": 0.05,
        "catalyst": 0.05,
        "mean_reversion": 0.10,
        "seasonality": 0.02,
        "market_regime": 0.10,
        "risk": 0.25,
    },
    "SIDEWAYS": {
        "technical": 0.12,
        "momentum": 0.08,
        "relative_strength": 0.08,
        "volume": 0.06,
        "fundamental": 0.15,
        "news_sentiment": 0.05,
        "catalyst": 0.05,
        "mean_reversion": 0.12,
        "seasonality": 0.02,
        "market_regime": 0.10,
        "risk": 0.17,
    },
    "HIGH_VOL": {
        "technical": 0.10,
        "momentum": 0.08,
        "relative_strength": 0.06,
        "volume": 0.08,
        "fundamental": 0.12,
        "news_sentiment": 0.06,
        "catalyst": 0.05,
        "mean_reversion": 0.15,
        "seasonality": 0.02,
        "market_regime": 0.08,
        "risk": 0.20,
    },
    "UNKNOWN": {
        "technical": 0.12,
        "momentum": 0.12,
        "relative_strength": 0.08,
        "volume": 0.06,
        "fundamental": 0.10,
        "news_sentiment": 0.06,
        "catalyst": 0.05,
        "mean_reversion": 0.06,
        "seasonality": 0.02,
        "market_regime": 0.10,
        "risk": 0.22,
    },
}


# =====================================================
# VERİ MODELLERİ (DATA MODELS)
# =====================================================


@dataclass(slots=True)
class ScoreVector:
    """Çok boyutlu kantitatif skor vektörü (0-100 ölçeğinde).

    Her bir boyut, sisteme entegre analitik motorların normalize edilmiş
    skorlarını temsil eder. Risk ve veri kalitesi boyutları fırsat skorundan
    izole edilmiştir.

    Attributes:
        technical: Teknik indikatör skoru (RSI, MACD, Bollinger vb.).
        momentum: Momentum ve ivme skoru (ROC, breakout).
        relative_strength: BIST ve sektör karşısında göreceli güç skoru.
        volume: Hacim ve mikroyapı skoru (z-score, trend, tick rule).
        fundamental: Temel analiz skoru (değerleme, FCF, bilanço kalitesi).
        news_sentiment: Haber ve KAP duyuruları duygu skoru.
        catalyst: Yaklaşan olay ve katalizör skoru.
        mean_reversion: Ortalamaya dönüş fırsat skoru.
        seasonality: Mevsimsellik ve takvim döngüleri skoru.
        market_regime: Piyasa rejimi ile hisse davranışı uyum skoru.
        risk: Risk ve oynaklık skoru (yüksek değer = daha güvenli/düşük risk).
        data_quality: Girdi feature'larının doluluk ve tazelik kalitesi (0-100).
        ticker: Hisse senedi sembolü.
        timestamp: Vektörün üretildiği UTC zaman damgası.
        regime: Değerlendirmede kullanılan piyasa rejimi.
    """

    technical: float = 0.0
    momentum: float = 0.0
    relative_strength: float = 0.0
    volume: float = 0.0
    fundamental: float = 0.0
    news_sentiment: float = 0.0
    catalyst: float = 0.0
    mean_reversion: float = 0.0
    seasonality: float = 0.0
    market_regime: float = 0.0
    risk: float = 0.0
    data_quality: float = 0.0
    ticker: str = ""
    timestamp: str = ""
    regime: str = "UNKNOWN"

    def to_dict(self) -> dict[str, float]:
        """Sadece sayısal boyutları içeren sözlük döndürür."""
        return {
            "technical": self.technical,
            "momentum": self.momentum,
            "relative_strength": self.relative_strength,
            "volume": self.volume,
            "fundamental": self.fundamental,
            "news_sentiment": self.news_sentiment,
            "catalyst": self.catalyst,
            "mean_reversion": self.mean_reversion,
            "seasonality": self.seasonality,
            "market_regime": self.market_regime,
            "risk": self.risk,
            "data_quality": self.data_quality,
        }

    def to_full_dict(self) -> dict[str, Any]:
        """Metadata dahil tüm alanları içeren sözlük döndürür."""
        d = self.to_dict()
        d.update({
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "regime": self.regime,
        })
        return d

    def to_orjson_bytes(self) -> bytes:
        """Vektörü orjson formatında bayt dizisine serileştirir."""
        return orjson.dumps(self.to_full_dict())

    def to_json(self) -> str:
        """Vektörü JSON metnine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoreVector:
        """Sözlükten ScoreVector nesnesi oluşturur."""
        return cls(
            technical=float(data.get("technical", 0.0)),
            momentum=float(data.get("momentum", 0.0)),
            relative_strength=float(data.get("relative_strength", 0.0)),
            volume=float(data.get("volume", 0.0)),
            fundamental=float(data.get("fundamental", 0.0)),
            news_sentiment=float(data.get("news_sentiment", 0.0)),
            catalyst=float(data.get("catalyst", 0.0)),
            mean_reversion=float(data.get("mean_reversion", 0.0)),
            seasonality=float(data.get("seasonality", 0.0)),
            market_regime=float(data.get("market_regime", 0.0)),
            risk=float(data.get("risk", 0.0)),
            data_quality=float(data.get("data_quality", 0.0)),
            ticker=str(data.get("ticker", "")),
            timestamp=str(data.get("timestamp", "")),
            regime=str(data.get("regime", "UNKNOWN")),
        )

    @classmethod
    def from_json(cls, json_str: str | bytes) -> ScoreVector:
        """JSON metninden veya baytından ScoreVector nesnesi yükler."""
        data = orjson.loads(json_str)
        return cls.from_dict(data)

    def get_opportunity_dimensions(self) -> dict[str, float]:
        """Fırsat hesaplamasında kullanılan boyutları döndürür (risk ve kalite hariç)."""
        return {k: v for k, v in self.to_dict().items() if k not in ("risk", "data_quality")}

    def get_nonzero_count(self) -> int:
        """Sıfır olmayan boyut sayısını döndürür."""
        return sum(1 for v in self.to_dict().values() if abs(v) > 1e-6)

    def __repr__(self) -> str:
        return (
            f"<ScoreVector ticker='{self.ticker}' regime='{self.regime}' "
            f"tech={self.technical:.1f} mom={self.momentum:.1f} fund={self.fundamental:.1f} "
            f"risk={self.risk:.1f} quality={self.data_quality:.1f}>"
        )


@dataclass(slots=True)
class CanonicalScore:
    """Nihai kanonik karar ve skorlama çıktısı.

    Attributes:
        vector: Detaylı alt motor skor vektörü.
        opportunity_score: Birleşik fırsat skoru (0-100).
        risk_score: Risk ve oynaklık skoru (0-100, yüksek = güvenli).
        confidence: Kararın genel güven derecesi (0.0 - 1.0).
        direction: İşlem yönü önerisi ('LONG', 'SHORT', 'NEUTRAL').
        decomposition: Ağırlıklı alt boyut katkı dökümü.
        ticker: Hisse senedi sembolü.
        timestamp: Skorun üretildiği UTC zaman damgası.
        regime: Piyasa rejimi.
        feature_count: Değerlendirmeye giren ham feature sayısı.
        nonzero_dimensions: Aktif (0 olmayan) boyut sayısı.
        ml_score: ML model tahmin skoru (varsa 0-100).
        ml_confidence: ML model güven skoru (0.0 - 1.0).
        rule_score: Kural tabanlı ağırlıklı skor (0-100).
    """

    vector: ScoreVector = field(default_factory=ScoreVector)
    opportunity_score: float = 0.0
    risk_score: float = 0.0
    confidence: float = 0.0
    direction: str = "NEUTRAL"
    decomposition: dict[str, float] = field(default_factory=dict)
    ticker: str = ""
    timestamp: str = ""
    regime: str = ""
    feature_count: int = 0
    nonzero_dimensions: int = 0
    ml_score: float | None = None
    ml_confidence: float = 0.0
    rule_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Kanonik skoru sözlük formatına dönüştürür."""
        return {
            "vector": self.vector.to_full_dict(),
            "opportunity_score": self.opportunity_score,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "direction": self.direction,
            "decomposition": self.decomposition,
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "regime": self.regime,
            "feature_count": self.feature_count,
            "nonzero_dimensions": self.nonzero_dimensions,
            "ml_score": self.ml_score,
            "ml_confidence": self.ml_confidence,
            "rule_score": self.rule_score,
        }

    def to_orjson_bytes(self) -> bytes:
        """Kanonik skoru orjson bayt dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    def to_json(self) -> str:
        """Kanonik skoru JSON metnine dönüştürür."""
        return self.to_orjson_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalScore:
        """Sözlükten CanonicalScore nesnesi oluşturur."""
        vec_data = data.get("vector", {})
        vector = ScoreVector.from_dict(vec_data) if isinstance(vec_data, dict) else ScoreVector()
        return cls(
            vector=vector,
            opportunity_score=float(data.get("opportunity_score", 0.0)),
            risk_score=float(data.get("risk_score", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            direction=str(data.get("direction", "NEUTRAL")),
            decomposition=dict(data.get("decomposition", {})),
            ticker=str(data.get("ticker", "")),
            timestamp=str(data.get("timestamp", "")),
            regime=str(data.get("regime", "")),
            feature_count=int(data.get("feature_count", 0)),
            nonzero_dimensions=int(data.get("nonzero_dimensions", 0)),
            ml_score=float(data["ml_score"]) if data.get("ml_score") is not None else None,
            ml_confidence=float(data.get("ml_confidence", 0.0)),
            rule_score=float(data.get("rule_score", 0.0)),
        )

    @classmethod
    def from_json(cls, json_str: str | bytes) -> CanonicalScore:
        """JSON metninden CanonicalScore nesnesi yükler."""
        data = orjson.loads(json_str)
        return cls.from_dict(data)

    def __repr__(self) -> str:
        ml_str = f"{self.ml_score:.1f}" if self.ml_score is not None else "None"
        return (
            f"<CanonicalScore ticker='{self.ticker}' dir='{self.direction}' "
            f"opp={self.opportunity_score:.1f} risk={self.risk_score:.1f} conf={self.confidence:.2f} "
            f"rule={self.rule_score:.1f} ml={ml_str}>"
        )


# =====================================================
# CANONICAL SCORING PIPELINE
# =====================================================


class CanonicalScoringPipeline:
    """BIST hisseleri için tek ve yetkili kanonik skorlama motoru.

    Bu motor, heterojen piyasa özelliklerini (features) 9 farklı kantitatif
    boyuta normalize eder; ML model tahminleri ve rejim bazlı kural ağırlıkları
    ile birleştirerek tekil karar ve risk skorları üretir.
    """

    def __init__(self, regime_weights: dict[str, dict[str, float]] | None = None) -> None:
        """Pipeline yapılandırmasını başlatır.

        Args:
            regime_weights: İsteğe bağlı özel rejim ağırlık haritası.
        """
        self.REGIME_WEIGHTS: dict[str, dict[str, float]] = regime_weights or REGIME_WEIGHTS_MAP
        self._lock: threading.RLock = threading.RLock()
        self._history: list[CanonicalScore] = []

    @otel_trace("canonical_scoring.compute_score_vector")
    def compute_score_vector(
        self,
        ticker: str,
        features: dict[str, Any],
        regime: str = "UNKNOWN",
    ) -> ScoreVector:
        """Verilen feature sözlüğünden çok boyutlu ScoreVector üretir.

        Her bir analitik boyut bağımsız olarak hesaplanır. Eksik feature'lar
        0'a çevrilmez, veri kalitesi metriğinde düşük güven olarak kaydedilir.

        Args:
            ticker: Değerlendirilen hisse senedi sembolü.
            features: Ham veya zenginleştirilmiş feature sözlüğü.
            regime: Güncel piyasa rejimi ('BULL', 'BEAR', 'SIDEWAYS', 'HIGH_VOL', 'UNKNOWN').

        Returns:
            Normalize edilmiş ScoreVector nesnesi.
        """
        clean_ticker = str(ticker).strip().upper() if ticker else "UNKNOWN"
        clean_regime = str(regime).strip().upper() if regime else "UNKNOWN"
        now_ts = datetime.now(UTC).isoformat()

        sv = ScoreVector(
            ticker=clean_ticker,
            timestamp=now_ts,
            regime=clean_regime,
        )

        sv.technical = self._score_technical(features)
        sv.momentum = self._score_momentum(features)
        sv.relative_strength = self._score_relative_strength(features)
        sv.volume = self._score_volume(features)
        sv.fundamental = self._score_fundamental(features)
        sv.news_sentiment = self._score_news_sentiment(features)
        sv.catalyst = self._score_catalyst(features)
        sv.mean_reversion = self._score_mean_reversion(features)
        sv.seasonality = self._score_seasonality(features)
        sv.market_regime = self._score_regime_fit(features, regime)
        sv.risk = self._score_risk(features)
        sv.data_quality = self._score_data_quality(features)

        return sv

    @otel_trace("canonical_scoring.compute_canonical_score")
    def compute_canonical_score(
        self,
        ticker: str,
        features: dict[str, Any],
        regime: str = "UNKNOWN",
        ml_model: Any = None,
    ) -> CanonicalScore:
        """Hisse için nihai kanonik fırsat, risk ve yön skorunu hesaplar.

        Args:
            ticker: Hisse senedi sembolü.
            features: Özellik sözlüğü.
            regime: Piyasa rejimi.
            ml_model: Eğitilmiş model nesnesi (predict metoduna sahip olmalı).

        Returns:
            CanonicalScore nesnesi.
        """
        clean_ticker = str(ticker).strip().upper() if ticker else "UNKNOWN"
        clean_regime = str(regime).strip().upper() if regime else "UNKNOWN"
        vector = self.compute_score_vector(clean_ticker, features, clean_regime)
        weights = self.REGIME_WEIGHTS.get(clean_regime, self.REGIME_WEIGHTS["UNKNOWN"])

        # Fırsat boyutlarının ağırlıklı toplamı
        opportunity_dims = vector.get_opportunity_dimensions()
        weighted_sum = sum(opportunity_dims[dim] * weights.get(dim, 0.0) for dim in opportunity_dims)
        total_weight = sum(weights.get(dim, 0.0) for dim in opportunity_dims)

        rule_score = (weighted_sum / total_weight) if total_weight > 1e-6 else DEFAULT_NEUTRAL_SCORE
        rule_score = max(0.0, min(100.0, rule_score))

        # ML model tahmini
        ml_score: float | None = None
        ml_confidence: float = 0.0
        if ml_model is not None and hasattr(ml_model, "predict"):
            try:
                raw_pred = ml_model.predict(features)
                if isinstance(raw_pred, (np.ndarray, list)):
                    ml_pred = float(raw_pred[0]) if len(raw_pred) > 0 else 0.0
                else:
                    ml_pred = float(raw_pred)

                if np.isfinite(ml_pred):
                    ml_score = max(0.0, min(100.0, 50.0 + ml_pred * 10.0))
                    ml_confidence = min(1.0, max(0.0, abs(ml_pred) / 2.0))
                else:
                    ml_score = None
                    ml_confidence = 0.0
            except Exception as e:
                logger.warning("canonical_scoring_ml_prediction_failed", ticker=clean_ticker, error=str(e))
                ml_score = None
                ml_confidence = 0.0

        # Ensemble entegrasyonu: Şampiyon model LightGBM/ML varsa ağırlıklandır
        if ml_score is not None:
            # Model güvenine bağlı dinamik blend (güven arttıkça ML ağırlığı DEFAULT_ML_WEIGHT'a yaklaşır)
            eff_ml_weight = DEFAULT_ML_WEIGHT * max(0.5, ml_confidence)
            eff_rule_weight = 1.0 - eff_ml_weight
            opportunity_score = eff_ml_weight * ml_score + eff_rule_weight * rule_score
        else:
            opportunity_score = rule_score

        opportunity_score = max(0.0, min(100.0, opportunity_score))
        risk_score = max(0.0, min(100.0, vector.risk))

        # Güven skoru veri kalitesi ile orantılıdır
        confidence = min(1.0, max(0.0, vector.data_quality / 100.0))

        # Yön tayini (LONG / SHORT / NEUTRAL)
        direction = self._determine_direction(vector, opportunity_score, regime)

        # Ayrıştırma (Decomposition)
        decomposition = {
            dim: round(opportunity_dims[dim] * weights.get(dim, 0.0), 2)
            for dim in opportunity_dims
        }

        res = CanonicalScore(
            vector=vector,
            opportunity_score=round(opportunity_score, 2),
            risk_score=round(risk_score, 2),
            confidence=round(confidence, 4),
            direction=direction,
            decomposition=decomposition,
            ticker=clean_ticker,
            timestamp=datetime.now(UTC).isoformat(),
            regime=regime,
            feature_count=len(features),
            nonzero_dimensions=vector.get_nonzero_count(),
            ml_score=round(ml_score, 2) if ml_score is not None else None,
            ml_confidence=round(ml_confidence, 4),
            rule_score=round(rule_score, 2),
        )

        with self._lock:
            self._history.append(res)
            if len(self._history) > DEFAULT_MAX_HISTORY:
                self._history = self._history[-DEFAULT_MAX_HISTORY:]

        return res

    def score(
        self,
        ticker: str,
        features: dict[str, Any],
        regime: str = "UNKNOWN",
        ml_model: Any = None,
    ) -> CanonicalScore:
        """Geriye uyumlu kanonik skor hesaplama arayüzü."""
        model = ml_model if ml_model is not None else getattr(self, "_ml_model", None)
        return self.compute_canonical_score(ticker, features, regime=regime, ml_model=model)

    def score_batch(
        self,
        batch_features: dict[str, dict[str, Any]],
        regime: str = "UNKNOWN",
        ml_model: Any = None,
    ) -> list[CanonicalScore]:
        """Birden çok hisse senedini toplu olarak skorlar.

        Args:
            batch_features: {ticker: feature_dict} eşlemesi.
            regime: Piyasa rejimi.
            ml_model: İsteğe bağlı ML model nesnesi.

        Returns:
            CanonicalScore listesi.
        """
        results: list[CanonicalScore] = []
        for ticker, features in batch_features.items():
            results.append(self.compute_canonical_score(ticker, features, regime=regime, ml_model=ml_model))
        return results

    def score_batch_polars(
        self,
        df: pl.DataFrame,
        ticker_col: str = "ticker",
        regime: str = "UNKNOWN",
        ml_model: Any = None,
    ) -> pl.DataFrame:
        """Polars DataFrame içindeki hisseleri toplu skorlar ve sonuçları DataFrame olarak döner.

        Args:
            df: Feature sütunlarını içeren Polars DataFrame.
            ticker_col: Hisse senedi sembol sütunu.
            regime: Piyasa rejimi.
            ml_model: İsteğe bağlı ML modeli.

        Returns:
            Skorlama sonuçlarını barındıran Polars DataFrame.
        """
        if df.is_empty():
            return self.export_scores_to_polars([])

        scores: list[CanonicalScore] = []
        rows = df.to_dicts()
        for row in rows:
            ticker = str(row.get(ticker_col, "UNKNOWN"))
            scores.append(self.compute_canonical_score(ticker, row, regime=regime, ml_model=ml_model))

        return self.export_scores_to_polars(scores)

    def get_history(self) -> list[CanonicalScore]:
        """Kayıtlı skorlama geçmişinin kopyasını thread-safe olarak döndürür."""
        with self._lock:
            return list(self._history)

    def clear_history(self) -> None:
        """Kayıtlı skorlama geçmişini thread-safe olarak temizler."""
        with self._lock:
            self._history.clear()

    def export_scores_to_polars(self, scores: list[CanonicalScore] | None = None) -> pl.DataFrame:
        """Kanonik skorları katı tipli Polars DataFrame formatına dönüştürür.

        Args:
            scores: Skor listesi (None verilirse hafızadaki geçmiş kullanılır).

        Returns:
            Polars DataFrame.
        """
        if scores is not None:
            target_scores = scores
        else:
            with self._lock:
                target_scores = list(self._history)
        if not target_scores:
            schema = {
                "ticker": pl.Utf8,
                "timestamp": pl.Utf8,
                "regime": pl.Utf8,
                "direction": pl.Utf8,
                "opportunity_score": pl.Float64,
                "risk_score": pl.Float64,
                "confidence": pl.Float64,
                "rule_score": pl.Float64,
                "ml_score": pl.Float64,
                "ml_confidence": pl.Float64,
                "technical": pl.Float64,
                "momentum": pl.Float64,
                "relative_strength": pl.Float64,
                "volume": pl.Float64,
                "fundamental": pl.Float64,
                "news_sentiment": pl.Float64,
                "catalyst": pl.Float64,
                "mean_reversion": pl.Float64,
                "seasonality": pl.Float64,
                "market_regime": pl.Float64,
                "risk": pl.Float64,
                "data_quality": pl.Float64,
            }
            return pl.DataFrame(schema=schema)

        data = []
        for s in target_scores:
            v = s.vector
            data.append({
                "ticker": s.ticker,
                "timestamp": s.timestamp,
                "regime": s.regime,
                "direction": s.direction,
                "opportunity_score": float(s.opportunity_score),
                "risk_score": float(s.risk_score),
                "confidence": float(s.confidence),
                "rule_score": float(s.rule_score),
                "ml_score": float(s.ml_score) if s.ml_score is not None else None,
                "ml_confidence": float(s.ml_confidence),
                "technical": float(v.technical),
                "momentum": float(v.momentum),
                "relative_strength": float(v.relative_strength),
                "volume": float(v.volume),
                "fundamental": float(v.fundamental),
                "news_sentiment": float(v.news_sentiment),
                "catalyst": float(v.catalyst),
                "mean_reversion": float(v.mean_reversion),
                "seasonality": float(v.seasonality),
                "market_regime": float(v.market_regime),
                "risk": float(v.risk),
                "data_quality": float(v.data_quality),
            })

        return pl.DataFrame(data)

    def export_scores_to_duckdb(
        self,
        scores: list[CanonicalScore] | None = None,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_canonical_scores",
    ) -> int:
        """Kanonik skorları DuckDB tablosuna kaydeder.

        Args:
            scores: Kaydedilecek skorlar (None ise hafıza geçmişi).
            db_path: DuckDB dosya yolu.
            table_name: Hedef tablo adı.

        Returns:
            Yazılan kayıt sayısı.
        """
        df = self.export_scores_to_polars(scores)
        if df.is_empty():
            return 0

        path_obj = Path(db_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        if path_obj.exists() and path_obj.stat().st_size == 0:
            with contextlib.suppress(OSError):
                path_obj.unlink()

        try:
            with duckdb.connect(str(path_obj)) as conn:
                conn.register("df_scores", df.to_arrow())
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df_scores WHERE 1=0"
                )
                conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_scores")
                with contextlib.suppress(Exception):
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_ticker_ts ON {table_name} (ticker, timestamp)"
                    )
            return len(df)
        except Exception as e:
            logger.error("export_scores_to_duckdb_failed", error=str(e))
            return 0

    def query_scores_duckdb(
        self,
        db_path: str | Path = DEFAULT_DUCKDB_PATH,
        table_name: str = "bist_canonical_scores",
        ticker: str | None = None,
        limit: int = 100,
    ) -> pl.DataFrame:
        """DuckDB üzerinden geçmiş skor kayıtlarını Polars DataFrame olarak sorgular.

        Args:
            db_path: DuckDB dosya yolu.
            table_name: Tablo adı.
            ticker: İsteğe bağlı hisse filtresi.
            limit: Maksimum satır sayısı.

        Returns:
            Polars DataFrame.
        """
        empty_df = self.export_scores_to_polars([])
        path_obj = Path(db_path)
        if not path_obj.exists() or path_obj.stat().st_size == 0:
            return empty_df

        try:
            with duckdb.connect(str(path_obj), read_only=True) as conn:
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name = ?",
                    [table_name],
                ).fetchall()
                if not tables:
                    return empty_df

                if ticker:
                    clean_tick = str(ticker).strip().upper()
                    query = f"SELECT * FROM {table_name} WHERE ticker = ? ORDER BY timestamp DESC LIMIT ?"
                    arrow_res = conn.execute(query, [clean_tick, limit]).arrow()
                else:
                    query = f"SELECT * FROM {table_name} ORDER BY timestamp DESC LIMIT ?"
                    arrow_res = conn.execute(query, [limit]).arrow()

                return pl.from_arrow(arrow_res)
        except Exception as e:
            logger.error("query_scores_duckdb_failed", error=str(e))
            return empty_df

    # =====================================================
    # BOYUT HESAPLAMA METOTLARI (FAIL-SAFE KORUMALI)
    # =====================================================

    def _score_technical(self, f: dict[str, Any]) -> float:
        """Teknik indikatör boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        rsi = self._s(f.get("rsi_14"), default=50.0)
        if rsi > 70.0:
            score -= 10.0
        elif rsi < 30.0:
            score += 10.0
        elif 40.0 < rsi < 60.0:
            score += 5.0

        macd = self._s(f.get("macd_hist"), default=0.0)
        if macd > 0.0:
            score += 5.0
        elif macd < 0.0:
            score -= 5.0

        bb = self._s(f.get("bb_position"), default=0.5)
        if bb > 0.9:
            score -= 5.0
        elif bb < 0.1:
            score += 10.0

        adx = self._s(f.get("adx"), default=0.0)
        if adx > 25.0:
            score += 5.0

        trend_slope = self._s(f.get("trend_slope_20d"), default=0.0)
        trend_r2 = self._s(f.get("trend_r2_20d"), default=0.0)
        if trend_r2 > 0.5 and trend_slope > 0.0:
            score += min(trend_slope * 0.05 * trend_r2, 15.0)
        elif trend_r2 > 0.5 and trend_slope < 0.0:
            score += max(trend_slope * 0.05 * trend_r2 * 0.5, -15.0)

        return max(0.0, min(100.0, score))

    def _score_momentum(self, f: dict[str, Any]) -> float:
        """Momentum ve ivme boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        roc_5d = self._s(f.get("roc_5d"), default=0.0)
        roc_20d = self._s(f.get("roc_20d"), default=0.0)

        if roc_5d > 3.0:
            score += min(roc_5d * 3.0, 20.0)
        elif roc_5d < -3.0:
            score += max(roc_5d * 3.0, -20.0)

        if roc_20d > 5.0:
            score += min(roc_20d, 15.0)
        elif roc_20d < -5.0:
            score += max(roc_20d, -15.0)

        accel = self._s(f.get("momentum_acceleration"), default=0.0)
        if accel > 0.0:
            score += 5.0
        elif accel < 0.0:
            score -= 5.0

        trend_r2 = self._s(f.get("trend_r2_20d"), default=0.0)
        if trend_r2 > 0.7:
            score += 5.0

        return max(0.0, min(100.0, score))

    def _score_relative_strength(self, f: dict[str, Any]) -> float:
        """Göreceli güç (RS) boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        rs_5d = self._s(f.get("rs_vs_bist_5d"), default=0.0)
        score += min(max(rs_5d * 0.10, -20.0), 20.0)

        rs_sector = self._s(f.get("rs_vs_sector_5d"), default=0.0)
        score += min(max(rs_sector * 0.05, -10.0), 10.0)

        rs_trend = self._s(f.get("rs_trend"), default=0.0)
        score += min(max(rs_trend * 5.0, -10.0), 10.0)

        return max(0.0, min(100.0, score))

    def _score_volume(self, f: dict[str, Any]) -> float:
        """Hacim ve mikroyapı boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        vol_z = self._s(f.get("volume_zscore"), default=0.0)
        clamped_z = min(max(vol_z, -3.0), 3.0)
        score += clamped_z * 8.0

        vol_trend = self._s(f.get("volume_trend"), default=0.0)
        score += min(max(vol_trend * 0.3, -10.0), 10.0)

        tick = self._s(f.get("tick_rule"), default=0.0)
        score += min(max(tick * 5.0, -10.0), 10.0)

        return max(0.0, min(100.0, score))

    def _score_fundamental(self, f: dict[str, Any]) -> float:
        """Temel analiz boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        fcf = self._s(f.get("fcf_yield_pct"), default=0.0)
        if abs(fcf) > 1e-6:
            score += min(max(fcf * 0.04, -15.0), 15.0)

        bsq = self._s(f.get("balance_sheet_quality"), default=50.0)
        score += min(max((bsq - 50.0) * 0.08, -10.0), 10.0)

        value = self._s(f.get("value_score"), default=0.0)
        score += min(max(value * 0.1, -10.0), 10.0)

        quality = self._s(f.get("quality_score"), default=0.0)
        score += min(max(quality * 0.05, -10.0), 10.0)

        roe = self._s(f.get("roe"), default=0.0)
        if abs(roe) > 1e-6:
            score += min(max(roe * 0.1, -5.0), 5.0)

        return max(0.0, min(100.0, score))

    def _score_news_sentiment(self, f: dict[str, Any]) -> float:
        """KAP ve haber duygu boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        kap_sent = self._s(f.get("kap_sentiment_weighted", f.get("kap_sentiment_avg")), default=0.0)
        news_sent = self._s(f.get("news_sentiment_weighted"), default=0.0)

        if abs(kap_sent) > 1e-6 or abs(news_sent) > 1e-6:
            combined = 0.6 * kap_sent + 0.4 * news_sent
            score += min(max(combined * 20.0, -25.0), 25.0)

        sent_mom = self._s(f.get("sentiment_momentum"), default=0.0)
        score += min(max(sent_mom * 10.0, -15.0), 15.0)

        return max(0.0, min(100.0, score))

    def _score_catalyst(self, f: dict[str, Any]) -> float:
        """Katalizör boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        cat_count = self._s(f.get("catalyst_count"), default=0.0)
        cat_importance = self._s(f.get("catalyst_importance"), default=0.0)
        cat_days = self._s(f.get("catalyst_days_nearest"), default=999.0)
        cat_decay = self._s(f.get("catalyst_time_decay_score"), default=0.0)

        if cat_count > 0.0:
            score += min(cat_decay * 20.0, 20.0)
            if cat_days <= 7.0:
                score += min(cat_importance * 15.0, 20.0)

        return max(0.0, min(100.0, score))

    def _score_mean_reversion(self, f: dict[str, Any]) -> float:
        """Ortalamaya dönüş boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        rsi = self._s(f.get("rsi_14"), default=50.0)
        bb_zscore = self._s(f.get("bb_zscore_20d"), default=0.0)

        if rsi < 30.0:
            score += (30.0 - rsi) * 0.8
        elif rsi > 70.0:
            score -= (rsi - 70.0) * 0.5

        if bb_zscore < -2.0:
            score += min(abs(bb_zscore) * 5.0, 20.0)
        elif bb_zscore > 2.0:
            score -= min(bb_zscore * 3.0, 15.0)

        mr_signal = self._s(f.get("mean_reversion_signal"), default=0.0)
        score += min(max(mr_signal * 10.0, -15.0), 15.0)

        return max(0.0, min(100.0, score))

    def _score_seasonality(self, f: dict[str, Any]) -> float:
        """Mevsimsellik ve takvim boyutunu hesaplar (0-100)."""
        score = DEFAULT_NEUTRAL_SCORE

        month_avg = self._s(f.get("seasonality_current_month_avg"), default=0.0)
        month_wr = self._s(f.get("seasonality_current_month_win_rate"), default=0.0)

        if month_wr > 0.0:
            score += min(max((month_wr - 0.5) * 40.0, -20.0), 20.0)

        if abs(month_avg) > 1e-6:
            score += min(max(month_avg * 5.0, -15.0), 15.0)

        quarter_avg = self._s(f.get("seasonality_current_quarter_avg"), default=0.0)
        if abs(quarter_avg) > 1e-6:
            score += min(max(quarter_avg * 2.0, -10.0), 10.0)

        return max(0.0, min(100.0, score))

    def _score_regime_fit(self, f: dict[str, Any], regime: str) -> float:
        """Piyasa rejimi ile hisse davranışı uyumunu hesaplar (0-100)."""
        mom = self._s(f.get("momentum_20d"), default=0.0)

        regime_fit_table = {
            "BULL": {"LONG": 85.0, "SHORT": 15.0},
            "BEAR": {"LONG": 15.0, "SHORT": 85.0},
            "SIDEWAYS": {"LONG": 50.0, "SHORT": 50.0},
            "HIGH_VOL": {"LONG": 35.0, "SHORT": 65.0},
            "UNKNOWN": {"LONG": 50.0, "SHORT": 50.0},
        }

        direction = "LONG" if mom > 0.0 else "SHORT"
        fit_dict = regime_fit_table.get(regime, regime_fit_table["UNKNOWN"])
        return fit_dict.get(direction, DEFAULT_NEUTRAL_SCORE)

    def _score_risk(self, f: dict[str, Any]) -> float:
        """Risk ve oynaklık boyutunu hesaplar (0-100, yüksek = güvenli)."""
        score = DEFAULT_RISK_BASELINE_SCORE

        atr = self._s(f.get("atr_pct"), default=0.0)
        if atr > 5.0:
            score -= 25.0
        elif atr > 3.0:
            score -= 10.0
        elif 0.0 < atr < 1.5:
            score += 10.0

        vol_20d = self._s(f.get("volatility_20d"), default=20.0)
        if vol_20d > 40.0:
            score -= 20.0
        elif vol_20d > 25.0:
            score -= 5.0
        elif vol_20d < 15.0:
            score += 10.0

        dd = self._s(f.get("drawdown_20d"), default=0.0)
        if dd > 15.0:
            score -= 15.0
        elif dd > 10.0:
            score -= 8.0

        falling_temp = self._s(f.get("falling_is_temporary"), default=0.5)
        if falling_temp > 0.7:
            score += 5.0

        catch_knife = self._s(f.get("catch_falling_knife_risk"), default=0.0)
        if catch_knife > 50.0:
            score -= 10.0

        return max(0.0, min(100.0, score))

    def _score_data_quality(self, f: dict[str, Any]) -> float:
        """Veri kalitesi ve feature tazelik derecesini hesaplar (0-100)."""
        if not f:
            return 0.0

        score = 100.0

        critical_features = [
            "rsi_14",
            "momentum_20d",
            "volume_zscore",
            "atr_pct",
            "rs_vs_bist_5d",
            "kap_sentiment_avg",
        ]
        missing_critical = sum(
            1 for feat in critical_features if f.get(feat) is None or str(f.get(feat)) in ("STALE", "MISSING", "UNKNOWN")
        )
        score -= missing_critical * 10.0

        stale_count = sum(
            1 for v in f.values() if isinstance(v, str) and v in ("STALE", "MISSING", "UNKNOWN")
        )
        total_features = len(f)
        if total_features > 0:
            stale_pct = stale_count / total_features
            score -= stale_pct * 30.0

        if f.get("fcf_yield_pct") is None and f.get("balance_sheet_quality") is None:
            score -= 10.0

        if f.get("kap_sentiment_avg") is None and f.get("news_sentiment_weighted") is None:
            score -= 5.0

        return max(0.0, min(100.0, score))

    def _determine_direction(self, vector: ScoreVector, opportunity_score: float, regime: str) -> str:
        """Fırsat ve momentum boyutlarına göre yön önerisini belirler."""
        mom = vector.momentum
        technical = vector.technical

        if opportunity_score < DEFAULT_SHORT_THRESHOLD:
            return "SHORT"
        if opportunity_score > DEFAULT_LONG_THRESHOLD or (mom > 55.0 and technical > 55.0):
            return "LONG"
        if mom < 45.0 and technical < 45.0:
            return "SHORT"

        return "NEUTRAL"

    @staticmethod
    def _s(val: Any, default: float = 0.0) -> float:
        """Sayısal dönüşüm ve NaN/Inf koruyucu yardımcı metot.

        Args:
            val: Dönüştürülecek nesne.
            default: Geçersizlik durumunda döndürülecek varsayılan değer.

        Returns:
            Geçerli sonlu float değer.
        """
        if val is None:
            return default
        if isinstance(val, (np.ndarray, list)):
            if len(val) == 0:
                return default
            val = val[0]
        try:
            res = float(val)
            return res if np.isfinite(res) else default
        except (TypeError, ValueError):
            return default

    def __repr__(self) -> str:
        return f"<CanonicalScoringPipeline regimes={list(self.REGIME_WEIGHTS.keys())} history_size={len(self._history)}>"


# =====================================================
# CANONICAL FEATURE REGISTRY (TEK DOĞRULUK KAYNAĞI)
# =====================================================
CANONICAL_FEATURE_REGISTRY: list[str] = [
    # Motor 1: Relatif Güç
    "rs_vs_bist_1d",
    "rs_vs_bist_5d",
    "rs_vs_bist_20d",
    "rs_vs_bist_60d",
    "rs_vs_sector_5d",
    "rs_vs_peers_5d",
    "rs_trend",
    "rs_peer_rank",
    # Motor 2: Momentum + Trend
    "roc_5d",
    "roc_20d",
    "roc_60d",
    "momentum_20d",
    "trend_slope_20d",
    "trend_r2_20d",
    "momentum_acceleration",
    "momentum_accel_trend",
    "price_vs_sma20",
    "price_vs_sma50",
    "price_vs_sma200",
    "near_20d_high",
    "near_60d_high",
    "near_120d_high",
    "breakout_failure",
    "drawdown_20d",
    "recovery_strength",
    # Motor 3: Hacim + Mikroyapı
    "volume_percentile",
    "volume_zscore",
    "volume_trend",
    "volume_up_down_ratio",
    "tick_rule",
    "vwap_deviation",
    "avg_volume_5d",
    "obv",
    # Motor 4: Fundamental
    "sector_norm_pe_ratio",
    "sector_norm_pb_ratio",
    "fcf_yield_pct",
    "fcf_margin",
    "balance_sheet_quality",
    "profit_margin_pct",
    "roe",
    "roa",
    # Motor 5: KAP + Haber
    "kap_sentiment_avg",
    "kap_sentiment_latest",
    "news_sentiment_weighted",
    "sentiment_momentum",
    "kap_avg_importance",
    # Motor 6: Katalizör
    "catalyst_count",
    "catalyst_importance",
    "catalyst_days_nearest",
    # Motor 7: Neden Düşüyor?
    "falling_is_temporary",
    "fall_market_selloff",
    "fall_sector_selloff",
    # Teknik (canonical scoring)
    "rsi_14",
    "macd_hist",
    "bb_position",
    "adx",
    "bb_zscore_20d",
    "mean_reversion_signal",
    # Mevsimsellik
    "seasonality_current_month_avg",
    "seasonality_current_month_win_rate",
    "seasonality_current_quarter_avg",
    # Katalizör detay
    "catalyst_time_decay_score",
    # Risk
    "atr_pct",
    "volatility_20d",
    "realized_vol_20d",
    "catch_falling_knife_risk",
    # Cross-Sectional (canonical scoring)
    "rank_return_5d",
    "rank_return_20d",
    "rank_volume_zscore",
    "rank_rsi_14",
    "sector_rel_return_5d",
    "sector_zscore_momentum_20d",
    "cs_zscore_roc_5d",
    "cs_zscore_roc_20d",
    # Market Breadth
    "market_breadth",
    "market_ad_ratio",
]

# Benzersiz ve sıralı tutulur
CANONICAL_FEATURE_REGISTRY = list(dict.fromkeys(CANONICAL_FEATURE_REGISTRY))


def get_canonical_features() -> list[str]:
    """Canonical feature listesini döndürür (tek doğruluk kaynağı)."""
    return list(CANONICAL_FEATURE_REGISTRY)


def validate_model_feature_contract(
    model: Any,
    registry: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Modelin feature sözleşmesini registry ile doğrular.

    Args:
        model: Doğrulanacak model (feature_names niteliği aranır).
        registry: Karşılaştırılacak özellik listesi.

    Returns:
        (is_consistent, warnings) ikilisi.
    """
    if registry is None:
        registry = CANONICAL_FEATURE_REGISTRY

    warnings: list[str] = []
    model_features = getattr(model, "feature_names", [])
    model_cs = getattr(model, "cs_features", [])

    registry_set = set(registry)
    for fname in model_features:
        base = fname.replace("_cs_zscore", "").replace("_cs_rank", "")
        if base not in registry_set and not fname.endswith(("_cs_zscore", "_cs_rank")):
            warnings.append(f"Model feature '{fname}' not in canonical registry")

    for fname in model_cs:
        base = fname.replace("_cs_zscore", "").replace("_cs_rank", "")
        if base not in registry_set:
            warnings.append(f"CS base feature '{base}' not in canonical registry")

    return len(warnings) == 0, warnings


# =====================================================
# MODÜL SEVİYESİ KOLAYLIK FONKSİYONLARI VE SINGLETON
# =====================================================
canonical_scoring = CanonicalScoringPipeline()


def compute_canonical_score(
    ticker: str,
    features: dict[str, Any],
    regime: str = "UNKNOWN",
    ml_model: Any = None,
) -> CanonicalScore:
    """Modül seviyesinde kanonik skor hesaplama kolaylık fonksiyonu."""
    return canonical_scoring.compute_canonical_score(ticker, features, regime=regime, ml_model=ml_model)


def compute_score_vector(
    ticker: str,
    features: dict[str, Any],
    regime: str = "UNKNOWN",
) -> ScoreVector:
    """Modül seviyesinde skor vektörü hesaplama kolaylık fonksiyonu."""
    return canonical_scoring.compute_score_vector(ticker, features, regime=regime)


def score_batch(
    batch_features: dict[str, dict[str, Any]],
    regime: str = "UNKNOWN",
    ml_model: Any = None,
) -> list[CanonicalScore]:
    """Modül seviyesinde toplu hisse skorlama fonksiyonu."""
    return canonical_scoring.score_batch(batch_features, regime=regime, ml_model=ml_model)


def score_batch_polars(
    df: pl.DataFrame,
    ticker_col: str = "ticker",
    regime: str = "UNKNOWN",
    ml_model: Any = None,
) -> pl.DataFrame:
    """Modül seviyesinde Polars DataFrame skorlama fonksiyonu."""
    return canonical_scoring.score_batch_polars(df, ticker_col=ticker_col, regime=regime, ml_model=ml_model)


def export_scores_to_polars(scores: list[CanonicalScore] | None = None) -> pl.DataFrame:
    """Modül seviyesinde skorları Polars formatına dönüştürme fonksiyonu."""
    return canonical_scoring.export_scores_to_polars(scores)


def export_scores_to_duckdb(
    scores: list[CanonicalScore] | None = None,
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_canonical_scores",
) -> int:
    """Modül seviyesinde skorları DuckDB'ye aktarma fonksiyonu."""
    return canonical_scoring.export_scores_to_duckdb(scores, db_path=db_path, table_name=table_name)


def query_scores_duckdb(
    db_path: str | Path = DEFAULT_DUCKDB_PATH,
    table_name: str = "bist_canonical_scores",
    ticker: str | None = None,
    limit: int = 100,
) -> pl.DataFrame:
    """Modül seviyesinde DuckDB'den skor sorgulama fonksiyonu."""
    return canonical_scoring.query_scores_duckdb(db_path=db_path, table_name=table_name, ticker=ticker, limit=limit)


def get_scoring_history() -> list[CanonicalScore]:
    """Kayıtlı kanonik skor geçmişini döndürür."""
    return canonical_scoring.get_history()


def clear_scoring_history() -> None:
    """Kayıtlı kanonik skor geçmişini temizler."""
    canonical_scoring.clear_history()


__all__ = [
    "DEFAULT_ML_WEIGHT",
    "DEFAULT_RULE_WEIGHT",
    "DEFAULT_NEUTRAL_SCORE",
    "DEFAULT_RISK_BASELINE_SCORE",
    "DEFAULT_LONG_THRESHOLD",
    "DEFAULT_SHORT_THRESHOLD",
    "DEFAULT_MAX_HISTORY",
    "DEFAULT_DUCKDB_PATH",
    "REGIME_WEIGHTS_MAP",
    "ScoreVector",
    "CanonicalScore",
    "CanonicalScoringPipeline",
    "CANONICAL_FEATURE_REGISTRY",
    "get_canonical_features",
    "validate_model_feature_contract",
    "canonical_scoring",
    "compute_canonical_score",
    "compute_score_vector",
    "score_batch",
    "score_batch_polars",
    "export_scores_to_polars",
    "export_scores_to_duckdb",
    "query_scores_duckdb",
    "get_scoring_history",
    "clear_scoring_history",
]
