# c:\Users\serve\Downloads\Compressed\bist-100\services\ml\fingpt.py
"""ALPHA BIST — FinGPT ve Kural Tabanlı Finansal Duygu Analizi Motoru (Financial Sentiment Engine).

BIST-100 hisse senetleri ve piyasa geneli için çok kaynaklı (KAP bildirimleri,
finansal haberler, aracı kurum raporları, sosyal medya) duygu (sentiment) analizi yapar.
Gerektiğinde FinBERT veya Türkçe BERT transformer modellerini kullanır; modeller
veya GPU mevcut değilse genişletilmiş BIST finansal sözlüğü ile yüksek hızlı ve güvenli
kural tabanlı (rule-based) yedek mekanizmaya (fallback) geçer.

Kullanım Prensipleri:
- Sıfır Veri Sızıntısı (Point-In-Time): Haber ve KAP duyuruları yalnızca zaman damgası
  itibarıyla geçmiş pencerede değerlendirilir.
- Eşzamanlılık Güvenliği: `threading.RLock()` ile çoklu iş parçacığı koruması.
- DuckDB Entegrasyonu: SSD korumalı WAL ayarları ile denetim izi kaydı.
- Polars Desteği: Doğrudan Polars DataFrame metin sütunları üzerinde toplu duygu analizi.
- Fail-Closed Mimarisi: Boş metin, eksik model veya geçersiz girdilerde güvenli nötr yanıt.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

logger = structlog.get_logger(__name__)

# ==============================================================================
# 1. STANDART YAPILANDIRMA SABİTLERİ (DEFAULT_*)
# ==============================================================================
DEFAULT_MODEL_NAME: Final[str] = "FinBERT"
DEFAULT_WINDOW_HOURS: Final[int] = 24
DEFAULT_MAX_HISTORY_PER_TICKER: Final[int] = 500

DEFAULT_SOURCE_WEIGHTS: Final[dict[str, float]] = {
    "kap": 1.0,  # Kamuyu Aydınlatma Platformu — Resmi ve en yüksek güvenilirlik
    "news": 0.7,  # Finans haber ajansları
    "social": 0.3,  # Sosyal medya ve topluluk kanalları
}

DEFAULT_POS_THRESHOLD: Final[float] = 0.10
DEFAULT_NEG_THRESHOLD: Final[float] = -0.10

DEFAULT_DUCKDB_PATH: Final[str] = "data/ml_audit.duckdb"
DEFAULT_WAL_AUTO_CHECKPOINT: Final[str] = "10MB"

# BIST ve KAP bildirimlerine özel genişletilmiş finansal sözlük
BIST_POSITIVE_KEYWORDS: Final[tuple[str, ...]] = (
    "yükseliş",
    "artış",
    "kâr",
    "net kâr",
    "büyüme",
    "rekor",
    "güçlü",
    "olumlu",
    "pozitif",
    "buy",
    "al",
    "güzel",
    "iyi",
    "temettü",
    "bedelsiz",
    "ihale kazandı",
    "yeni iş ilişkisi",
    "sipariş",
    "yatırım",
    "anlaşma",
    "ihracat artışı",
    "kapasite artışı",
    "hedef fiyat yükseltildi",
    "al tavsiyesi",
)

BIST_NEGATIVE_KEYWORDS: Final[tuple[str, ...]] = (
    "düşüş",
    "kayıp",
    "zarar",
    "net zarar",
    "azalma",
    "zayıf",
    "olumsuz",
    "negatif",
    "sell",
    "sat",
    "kötü",
    "risk",
    "konkordato",
    "tedbir",
    "ceza",
    "dava",
    "iptal",
    "küçülme",
    "iflas",
    "tahsisli borçlanma",
    "kredi notu düşürüldü",
    "hedef fiyat indirildi",
    "sat tavsiyesi",
)


def configure_duckdb_wal(
    con: duckdb.DuckDBPyConnection,
    checkpoint_size: str = DEFAULT_WAL_AUTO_CHECKPOINT,
) -> None:
    """DuckDB bağlantısını SSD korumalı WAL sınırları ile optimize eder.

    Args:
        con: Yapılandırılacak DuckDB bağlantısı.
        checkpoint_size: WAL otomatik kontrol noktası boyutu (örn: '10MB').
    """
    try:
        con.execute(f"PRAGMA wal_autocheckpoint='{checkpoint_size}';")
    except Exception as e:
        logger.warning("duckdb_wal_config_failed", error=str(e))


# ==============================================================================
# 2. ENUM VE VERİ MODELLERİ
# ==============================================================================
class SentimentType(StrEnum):
    """Duygu analizi yön sınıfı."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class SentimentSource(StrEnum):
    """Duygu verisi kaynağı."""

    KAP = "kap"
    NEWS = "news"
    SOCIAL = "social"


@dataclass(slots=True)
class SentimentResult:
    """Tek bir metin için hesaplanmış duygu analizi sonucu."""

    text: str
    sentiment: str
    score: float
    confidence: float
    source: str
    ticker: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Sonucu standart sözlük formatına çevirir."""
        return {
            "text": self.text,
            "sentiment": str(self.sentiment),
            "score": float(self.score),
            "confidence": float(self.confidence),
            "source": str(self.source),
            "ticker": str(self.ticker),
            "timestamp": str(self.timestamp),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SentimentResult:
        """Sözlükten SentimentResult nesnesi oluşturur."""
        return cls(
            text=str(data.get("text", "")),
            sentiment=str(data.get("sentiment", SentimentType.NEUTRAL.value)),
            score=float(data.get("score", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            source=str(data.get("source", SentimentSource.NEWS.value)),
            ticker=str(data.get("ticker", "")),
            timestamp=str(data.get("timestamp", datetime.now(UTC).isoformat())),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"SentimentResult(ticker='{self.ticker}', sent='{self.sentiment}', "
            f"score={self.score:+.3f}, conf={self.confidence:.2f}, src='{self.source}')"
        )


@dataclass(slots=True)
class AggregatedSentiment:
    """Tek bir hisse senedi için belirli bir zaman penceresindeki toplulaştırılmış duygu skoru."""

    ticker: str
    avg_score: float
    weighted_score: float
    sentiment: str
    n_sources: int
    confidence: float
    latest_score: float
    momentum: float
    calculated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Toplu duygu modelini sözlük formatına çevirir."""
        return {
            "ticker": self.ticker,
            "avg_score": float(self.avg_score),
            "weighted_score": float(self.weighted_score),
            "sentiment": str(self.sentiment),
            "n_sources": int(self.n_sources),
            "confidence": float(self.confidence),
            "latest_score": float(self.latest_score),
            "momentum": float(self.momentum),
            "calculated_at": str(self.calculated_at),
        }

    def to_orjson_bytes(self) -> bytes:
        """Yüksek hızlı serileştirilmiş orjson byte dizisine dönüştürür."""
        return orjson.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AggregatedSentiment:
        """Sözlükten AggregatedSentiment nesnesi oluşturur."""
        return cls(
            ticker=str(data.get("ticker", "")),
            avg_score=float(data.get("avg_score", 0.0)),
            weighted_score=float(data.get("weighted_score", 0.0)),
            sentiment=str(data.get("sentiment", SentimentType.NEUTRAL.value)),
            n_sources=int(data.get("n_sources", 0)),
            confidence=float(data.get("confidence", 0.0)),
            latest_score=float(data.get("latest_score", 0.0)),
            momentum=float(data.get("momentum", 0.0)),
            calculated_at=str(data.get("calculated_at", datetime.now(UTC).isoformat())),
        )

    def __repr__(self) -> str:
        """Kullanıcı dostu metin temsili."""
        return (
            f"AggregatedSentiment(ticker='{self.ticker}', sent='{self.sentiment}', "
            f"weighted={self.weighted_score:+.3f}, mom={self.momentum:+.3f}, n={self.n_sources})"
        )


# ==============================================================================
# 3. FİNGPT VE KURAL TABANLI SENTİMENT MOTORU
# ==============================================================================
class FinGPTSentiment:
    """BIST-100 finansal metin duygu analizi ve haber akışı puanlama motoru."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        """FinGPTSentiment motorunu başlatır.

        Args:
            model_name: Kullanılacak model kimliği (örn: FinBERT, TurkishBERT).
        """
        self._lock: Final[threading.RLock] = threading.RLock()
        self.model_name: str = model_name
        self._model: Any = None
        self._tokenizer: Any = None
        self._sentiment_history: dict[str, list[SentimentResult]] = {}
        self._source_weights: dict[str, float] = dict(DEFAULT_SOURCE_WEIGHTS)
        self._is_loaded: bool = False

        logger.info("fingpt_sentiment_initialized", model_name=self.model_name)

    @property
    def is_loaded(self) -> bool:
        """Modelin belleğe yüklenip yüklenmediğini bildirir."""
        with self._lock:
            return self._is_loaded

    def load_model(self) -> bool:
        """HuggingFace Transformers tabanlı duygu modelini ve tokenizer'ını yükler.

        Returns:
            Yükleme başarılıysa True, aksi takdirde False (kural tabanlı fallback aktif kalır).
        """
        with self._lock:
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                if self.model_name == "FinBERT":
                    model_path = "ProsusAI/finbert"
                elif self.model_name == "TurkishBERT":
                    model_path = "dbmdz/bert-base-turkish-cased"
                else:
                    model_path = self.model_name

                self._tokenizer = AutoTokenizer.from_pretrained(model_path)
                self._model = AutoModelForSequenceClassification.from_pretrained(model_path)
                self._model.eval()
                self._is_loaded = True
                logger.info("sentiment_transformer_loaded", model=self.model_name)
                return True
            except ImportError:
                logger.info("transformers_not_installed_rule_based_fallback_active")
                self._is_loaded = False
                return False
            except Exception as e:
                logger.warning("sentiment_model_load_failed", error=str(e))
                self._is_loaded = False
                return False

    def analyze(
        self,
        text: str,
        source: str = SentimentSource.NEWS.value,
        ticker: str = "",
    ) -> SentimentResult:
        """Tek bir finansal metin için duygu analizi yapar.

        Args:
            text: Analiz edilecek metin içeriği.
            source: Bilgi kaynağı ('kap', 'news', 'social').
            ticker: İlgili BIST hisse sembolü (opsiyonel).

        Returns:
            Hesaplanan SentimentResult nesnesi.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return SentimentResult(
                text="",
                sentiment=SentimentType.NEUTRAL.value,
                score=0.0,
                confidence=0.0,
                source=source,
                ticker=ticker,
            )

        with self._lock:
            if self._is_loaded and self._model is not None:
                return self._transformer_analyze(clean_text, source, ticker)
            return self._rule_based_analyze(clean_text, source, ticker)

    def analyze_batch(
        self,
        texts: list[str],
        source: str = SentimentSource.NEWS.value,
        ticker: str = "",
    ) -> list[SentimentResult]:
        """Birden çok metni toplu olarak analiz eder.

        Args:
            texts: Metin listesi.
            source: Bilgi kaynağı.
            ticker: İlgili hisse kodu.

        Returns:
            SentimentResult nesneleri listesi.
        """
        return [self.analyze(t, source=source, ticker=ticker) for t in texts]

    def get_ticker_sentiment(
        self,
        ticker: str,
        window_hours: int = DEFAULT_WINDOW_HOURS,
    ) -> AggregatedSentiment | None:
        """Belirtilen hisse için son zaman penceresindeki tüm duygu kayıtlarını ağırlıklı toplulaştırır.

        Args:
            ticker: BIST hisse sembolü (örn: THYAO).
            window_hours: Geriye dönük incelenecek saat penceresi.

        Returns:
            AggregatedSentiment nesnesi veya kayıt yoksa None.
        """
        with self._lock:
            history = self._sentiment_history.get(ticker, [])
            if not history:
                return None

            now = datetime.now(UTC)

            def _parse_ts(ts_str: str) -> datetime:
                try:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
                except Exception:
                    return now

            recent = [
                r
                for r in history
                if (now - _parse_ts(r.timestamp)).total_seconds() <= (window_hours * 3600)
            ]

            if not recent:
                return None

            scores = [r.score for r in recent]
            confidences = [r.confidence for r in recent]

            weighted_scores: list[float] = []
            weights_sum: float = 0.0

            for r in recent:
                w = self._source_weights.get(r.source.lower(), 0.5)
                eff_w = w * max(r.confidence, 0.1)
                weighted_scores.append(r.score * eff_w)
                weights_sum += eff_w

            avg_score = float(np.mean(scores))
            weighted_score = float(np.sum(weighted_scores) / max(weights_sum, 1e-6))

            if weighted_score > DEFAULT_POS_THRESHOLD:
                sentiment = SentimentType.POSITIVE.value
            elif weighted_score < DEFAULT_NEG_THRESHOLD:
                sentiment = SentimentType.NEGATIVE.value
            else:
                sentiment = SentimentType.NEUTRAL.value

            # Duygu İvmesi (Momentum)
            if len(scores) >= 2:
                recent_avg = float(np.mean(scores[-3:])) if len(scores) >= 3 else float(scores[-1])
                older_avg = float(np.mean(scores[:-3])) if len(scores) > 3 else float(scores[0])
                momentum = float(recent_avg - older_avg)
            else:
                momentum = 0.0

            res = AggregatedSentiment(
                ticker=ticker,
                avg_score=round(avg_score, 4),
                weighted_score=round(weighted_score, 4),
                sentiment=sentiment,
                n_sources=len(recent),
                confidence=round(float(np.mean(confidences)), 4),
                latest_score=round(float(scores[-1]), 4),
                momentum=round(momentum, 4),
            )

            # DuckDB denetim tablosuna kaydet
            try:
                save_aggregated_sentiment_to_duckdb(res)
            except Exception as e:
                logger.debug("save_aggregated_sentiment_to_duckdb_failed", error=str(e))

            return res

    def _transformer_analyze(self, text: str, source: str, ticker: str) -> SentimentResult:
        """Transformer modeli ile çıkarım yapar."""
        try:
            import torch

            inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model(**inputs)

            probs = torch.softmax(outputs.logits, dim=1).numpy()[0]

            if len(probs) == 3:
                # [positive, negative, neutral]
                score = float(probs[0] - probs[1])
                confidence = float(np.max(probs))
                if probs[0] > probs[1] and probs[0] > probs[2]:
                    sentiment = SentimentType.POSITIVE.value
                elif probs[1] > probs[0] and probs[1] > probs[2]:
                    sentiment = SentimentType.NEGATIVE.value
                else:
                    sentiment = SentimentType.NEUTRAL.value
            else:
                score = float(probs[0])
                confidence = float(np.max(probs))
                sentiment = SentimentType.POSITIVE.value if score > 0.5 else SentimentType.NEGATIVE.value

            res = SentimentResult(
                text=text[:120],
                sentiment=sentiment,
                score=round(score, 4),
                confidence=round(confidence, 4),
                source=source,
                ticker=ticker,
                timestamp=datetime.now(UTC).isoformat(),
            )

            if ticker:
                if ticker not in self._sentiment_history:
                    self._sentiment_history[ticker] = []
                self._sentiment_history[ticker].append(res)
                if len(self._sentiment_history[ticker]) > DEFAULT_MAX_HISTORY_PER_TICKER:
                    self._sentiment_history[ticker] = self._sentiment_history[ticker][-DEFAULT_MAX_HISTORY_PER_TICKER:]

            return res

        except Exception as e:
            logger.warning("transformer_sentiment_failed_falling_back_to_rules", error=str(e))
            return self._rule_based_analyze(text, source, ticker)

    def _rule_based_analyze(self, text: str, source: str, ticker: str) -> SentimentResult:
        """Genişletilmiş BIST finansal sözlüğü ile kural tabanlı duygu analizi yürütür."""
        text_lower = text.lower()

        pos_count = sum(1 for w in BIST_POSITIVE_KEYWORDS if w in text_lower)
        neg_count = sum(1 for w in BIST_NEGATIVE_KEYWORDS if w in text_lower)

        if pos_count > neg_count:
            diff = pos_count - neg_count
            score = float(min(diff * 0.25, 1.0))
            sentiment = SentimentType.POSITIVE.value
        elif neg_count > pos_count:
            diff = neg_count - pos_count
            score = float(max(-diff * 0.25, -1.0))
            sentiment = SentimentType.NEGATIVE.value
        else:
            score = 0.0
            sentiment = SentimentType.NEUTRAL.value

        confidence = float(min((pos_count + neg_count) * 0.20, 0.95))
        if confidence == 0.0:
            confidence = 0.50  # Nötr ifadeler için makul taban güven

        res = SentimentResult(
            text=text[:120],
            sentiment=sentiment,
            score=round(score, 4),
            confidence=round(confidence, 4),
            source=source,
            ticker=ticker,
            timestamp=datetime.now(UTC).isoformat(),
        )

        if ticker:
            if ticker not in self._sentiment_history:
                self._sentiment_history[ticker] = []
            self._sentiment_history[ticker].append(res)
            if len(self._sentiment_history[ticker]) > DEFAULT_MAX_HISTORY_PER_TICKER:
                self._sentiment_history[ticker] = self._sentiment_history[ticker][-DEFAULT_MAX_HISTORY_PER_TICKER:]

        return res

    def get_history(self, ticker: str, limit: int = 50) -> list[dict[str, Any]]:
        """Hisseye ait son duygu analiz geçmişini liste olarak döndürür."""
        with self._lock:
            history = self._sentiment_history.get(ticker, [])
            return [r.to_dict() for r in history[-limit:]]

    def __repr__(self) -> str:
        """FinGPTSentiment motorunun metin temsili."""
        return f"FinGPTSentiment(model='{self.model_name}', loaded={self._is_loaded}, tickers={len(self._sentiment_history)})"


# ==============================================================================
# 4. POLARS İLE VEKTÖRİZE DUYGU ANALİZİ
# ==============================================================================
def analyze_polars(
    df: pl.DataFrame,
    text_col: str = "text",
    ticker_col: str | None = "ticker",
    source: str = SentimentSource.NEWS.value,
) -> pl.DataFrame:
    """Polars DataFrame içindeki metin sütunlarını toplu analiz edip skor sütunları ekler.

    Args:
        df: Metinleri içeren Polars DataFrame.
        text_col: Metin sütununun adı.
        ticker_col: Hisse kodu sütununun adı (opsiyonel).
        source: Veri kaynağı.

    Returns:
        'sentiment', 'sentiment_score', 'sentiment_conf' sütunları eklenmiş Polars DataFrame.
    """
    if df is None or len(df) == 0 or text_col not in df.columns:
        return pl.DataFrame()

    analyzer = FinGPTSentiment()
    texts = df[text_col].cast(pl.Utf8).fill_null("").to_list()
    tickers = (
        df[ticker_col].cast(pl.Utf8).fill_null("").to_list()
        if ticker_col and ticker_col in df.columns
        else [""] * len(texts)
    )

    sentiments: list[str] = []
    scores: list[float] = []
    confs: list[float] = []

    for t, sym in zip(texts, tickers, strict=False):
        res = analyzer.analyze(t, source=source, ticker=sym)
        sentiments.append(res.sentiment)
        scores.append(res.score)
        confs.append(res.confidence)

    return df.with_columns([
        pl.Series("sentiment", sentiments, dtype=pl.Utf8),
        pl.Series("sentiment_score", scores, dtype=pl.Float64),
        pl.Series("sentiment_conf", confs, dtype=pl.Float64),
    ])


# ==============================================================================
# 5. DUCKDB VERİTABANI DENETİM İZİ YÖNETİMİ
# ==============================================================================
def save_aggregated_sentiment_to_duckdb(
    agg: AggregatedSentiment,
    db_path: str = DEFAULT_DUCKDB_PATH,
) -> None:
    """Toplu hisse duygu analiz sonucunu DuckDB denetim tablosuna SSD korumalı WAL sınırlarıyla kaydeder.

    Args:
        agg: Kaydedilecek AggregatedSentiment nesnesi.
        db_path: Hedef DuckDB dosya yolu.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = duckdb.connect(db_path)
    try:
        configure_duckdb_wal(con)

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ml_fingpt_sentiment_audit (
                audit_id VARCHAR PRIMARY KEY,
                ticker VARCHAR,
                calculated_at TIMESTAMP,
                avg_score DOUBLE,
                weighted_score DOUBLE,
                sentiment VARCHAR,
                n_sources BIGINT,
                confidence DOUBLE,
                momentum DOUBLE
            );
            """
        )

        audit_id = f"sent_{uuid.uuid4().hex[:8]}"

        con.execute(
            """
            INSERT OR REPLACE INTO ml_fingpt_sentiment_audit
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            [
                audit_id,
                agg.ticker,
                agg.calculated_at,
                agg.avg_score,
                agg.weighted_score,
                agg.sentiment,
                agg.n_sources,
                agg.confidence,
                agg.momentum,
            ],
        )
        logger.info("aggregated_sentiment_saved_to_duckdb", ticker=agg.ticker, score=agg.weighted_score)
    finally:
        con.close()


def read_sentiment_history_polars(
    db_path: str = DEFAULT_DUCKDB_PATH,
    ticker: str | None = None,
    limit: int = 50,
) -> pl.DataFrame:
    """DuckDB'de kayıtlı geçmiş duygu analizi kayıtlarını Polars DataFrame olarak döndürür.

    Args:
        db_path: DuckDB dosya yolu.
        ticker: Filtrelenecek hisse kodu (opsiyonel).
        limit: Alınacak azami kayıt sayısı.

    Returns:
        Polars DataFrame.
    """
    if not os.path.exists(db_path):
        return pl.DataFrame()

    con = duckdb.connect(db_path, read_only=True)
    try:
        configure_duckdb_wal(con)
        where_clause = f"WHERE ticker = '{ticker}'" if ticker else ""
        query = f"""
            SELECT audit_id, ticker, calculated_at, avg_score, weighted_score,
                   sentiment, n_sources, confidence, momentum
            FROM ml_fingpt_sentiment_audit
            {where_clause}
            ORDER BY calculated_at DESC
            LIMIT {limit};
        """
        arrow_table = con.execute(query).arrow()
        return pl.from_arrow(arrow_table)
    except Exception as e:
        logger.warning("read_sentiment_history_polars_failed", error=str(e))
        return pl.DataFrame()
    finally:
        con.close()


# ==============================================================================
# 6. DIŞA AKTARILAN MODÜL SEMBOLLERİ (__all__)
# ==============================================================================
__all__: Final[list[str]] = [
    "BIST_NEGATIVE_KEYWORDS",
    "BIST_POSITIVE_KEYWORDS",
    "DEFAULT_DUCKDB_PATH",
    "DEFAULT_MAX_HISTORY_PER_TICKER",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_NEG_THRESHOLD",
    "DEFAULT_POS_THRESHOLD",
    "DEFAULT_SOURCE_WEIGHTS",
    "DEFAULT_WAL_AUTO_CHECKPOINT",
    "DEFAULT_WINDOW_HOURS",
    "SentimentType",
    "SentimentSource",
    "SentimentResult",
    "AggregatedSentiment",
    "FinGPTSentiment",
    "analyze_polars",
    "configure_duckdb_wal",
    "save_aggregated_sentiment_to_duckdb",
    "read_sentiment_history_polars",
]
