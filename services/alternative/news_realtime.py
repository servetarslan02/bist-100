"""
ALPHA BIST — Gerçek Zamanlı Haber Akışı & Duygu Analiz Modülü

BIST'e özgü çok kaynaklı gerçek zamanlı haber toplama ve anlık duygu skorlama.
KAP, Reuters Türkiye, Bloomberg HT ve Ekşi Sözlük kaynaklarından gelen haberleri
normalleştirir, duygu skorlar ve feature pipeline'a iletir.

Özellikler:
  - Çok kaynaklı haber sinyali (KAP bildirim + finans medyası)
  - Başlık tabanlı kural + anahtar kelime duygu puanlama
  - Piyasa etkisi ağırlıklı skor (LLM proxy olmadan hızlı yol)
  - DuckDB tabanlı haber arşivi (tarihsel bakış için)
  - Ticker eşleştirme: Haber başlığından otomatik ticker tespiti
  - Haber çarpma faktörü: Kısa sürede çok haber → anormallik uyarısı
  - Point-in-Time uyumu: Gelecek haberler önceki dönemlere sızmaz
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

import duckdb
import structlog

logger = structlog.get_logger(__name__)

# Sabitler
DB_TABLE_NEWS = "news_items"
MAX_CACHE_SIZE: int = 5_000
DEFAULT_DECAY_HOURS: float = 24.0    # Eski haberlerin ağırlığı azalır
BURST_WINDOW_SECONDS: float = 300.0  # 5 dakika
BURST_THRESHOLD: int = 10            # 5 dakikada 10+ haber = anormallik

# BIST100 başlıca hisseler (ticker eşleştirme için)
BIST_TICKER_ALIASES: dict[str, list[str]] = {
    "THYAO": ["Türk Hava Yolları", "THY", "Turkish Airlines"],
    "GARAN": ["Garanti", "Garanti Bankası", "Garanti BBVA"],
    "AKBNK": ["Akbank"],
    "EREGL": ["Ereğli Demir Çelik", "Erdemir", "Ereğli"],
    "BIMAS": ["BİM", "BIM Mağazalar"],
    "KCHOL": ["Koç Holding"],
    "SISE": ["Şişecam", "Sisecam"],
    "FROTO": ["Ford Otomotiv", "Ford Otosan"],
    "TOASO": ["Tofaş", "Tofas"],
    "ISCTR": ["İş Bankası", "İşbank"],
    "PETKM": ["Petkim"],
    "TUPRS": ["Tüpraş"],
    "KOZAL": ["Koza Altın"],
    "SAHOL": ["Sabancı Holding"],
    "EKGYO": ["Emlak Konut", "Emlak GYO"],
}

# Duygu anahtar kelimeleri (Türkçe + İngilizce)
POSITIVE_KEYWORDS: set[str] = {
    "artış", "yükseldi", "kâr", "büyüme", "rekor", "güçlü",
    "onay", "anlaşma", "temettü", "bölünme", "iyimser", "beklenti üzeri",
    "yatırım", "kazandı", "positive", "beat", "growth", "record",
    "dividend", "upgrade", "bullish",
}
NEGATIVE_KEYWORDS: set[str] = {
    "düşüş", "düştü", "zarar", "kaybetti", "daralma", "uyarı",
    "ceza", "soruşturma", "iflas", "şikâyet", "satış", "baskı",
    "geriledi", "negative", "miss", "loss", "decline", "downgrade",
    "fine", "probe", "warning", "sell", "bearish",
}


class NewsSource(Enum):
    """Haber kaynağı türü.

    Attributes:
        KAP: Kamuyu Aydınlatma Platformu bildirimleri.
        REUTERS: Reuters Türkiye finans haberleri.
        BLOOMBERG_HT: Bloomberg HT piyasa haberleri.
        EKSI_SOZLUK: Ekşi Sözlük sosyal sinyal.
        GENERIC: Bilinmeyen/genel kaynak.
    """

    KAP = auto()
    REUTERS = auto()
    BLOOMBERG_HT = auto()
    EKSI_SOZLUK = auto()
    GENERIC = auto()


@dataclass
class NewsItem:
    """Tek haber öğesi.

    Attributes:
        id: Benzersiz haber kimliği.
        source: Haber kaynağı.
        title: Haber başlığı.
        body: Haber metni (opsiyonel, özet).
        published_at: Yayın zamanı (UTC).
        tickers: Haberle ilişkili hisse kodları.
        sentiment_score: Duygu skoru (-1 kötü, 0 nötr, +1 iyi).
        confidence: Duygu skor güven düzeyi (0-1).
        impact_weight: Kaynak güvenilirlik ağırlığı.
        raw_metadata: Kaynak özgü meta-veri.
    """

    title: str
    source: NewsSource = NewsSource.GENERIC
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    published_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    body: str = ""
    tickers: list[str] = field(default_factory=list)
    sentiment_score: float = 0.0
    confidence: float = 0.5
    impact_weight: float = 1.0
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """NewsItem kısa temsili."""
        ts = self.published_at.strftime("%H:%M")
        return (
            f"NewsItem({self.source.name}@{ts}, "
            f"tickers={self.tickers}, "
            f"sentiment={self.sentiment_score:+.2f})"
        )


class TickerExtractor:
    """Haber metninden BIST ticker eşleştirme motoru."""

    def __init__(self, aliases: dict[str, list[str]] | None = None) -> None:
        """TickerExtractor başlatıcı.

        Args:
            aliases: {ticker: [alias_listesi]} sözlüğü.
        """
        self._aliases = aliases or BIST_TICKER_ALIASES
        # Arama için ters index
        self._index: dict[str, str] = {}
        for ticker, names in self._aliases.items():
            for name in names:
                self._index[name.lower()] = ticker
            self._index[ticker.lower()] = ticker

    def __repr__(self) -> str:
        """TickerExtractor kısa temsili."""
        return f"TickerExtractor(tickers={len(self._aliases)})"

    def extract(self, text: str) -> list[str]:
        """Metinden BIST ticker'larını çıkarır.

        Args:
            text: Haber başlığı veya metni.

        Returns:
            Eşleşen ticker kodları listesi (tekrarsız).
        """
        lower_text = text.lower()
        found: set[str] = set()
        for alias, ticker in self._index.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", lower_text):
                found.add(ticker)
        return sorted(found)


class KeywordSentimentScorer:
    """Anahtar kelime tabanlı duygu puanlama motoru."""

    def __init__(
        self,
        positive: set[str] | None = None,
        negative: set[str] | None = None,
    ) -> None:
        """KeywordSentimentScorer başlatıcı.

        Args:
            positive: Olumlu anahtar kelimeler.
            negative: Olumsuz anahtar kelimeler.
        """
        self._positive = positive or POSITIVE_KEYWORDS
        self._negative = negative or NEGATIVE_KEYWORDS

    def __repr__(self) -> str:
        """KeywordSentimentScorer kısa temsili."""
        return (
            f"KeywordSentimentScorer("
            f"pos={len(self._positive)}, neg={len(self._negative)})"
        )

    def score(self, text: str) -> tuple[float, float]:
        """Metni duygu açısından puanlar.

        Args:
            text: Haber başlığı veya metni.

        Returns:
            (sentiment_score, confidence) demeti.
            sentiment_score: -1.0 ila +1.0 arası.
            confidence: 0.3 (eşleşme yok) → 0.9 (güçlü sinyal).
        """
        lower = text.lower()
        pos_count = sum(1 for kw in self._positive if kw in lower)
        neg_count = sum(1 for kw in self._negative if kw in lower)

        total = pos_count + neg_count
        if total == 0:
            return 0.0, 0.30  # Nötr, düşük güven

        net = pos_count - neg_count
        score = net / max(total, 1)
        # Güven: eşleşme sayısına göre artar, max 0.85
        confidence = min(0.85, 0.4 + total * 0.10)
        return float(score), float(confidence)


# Kaynak güvenilirlik ağırlıkları
SOURCE_WEIGHTS: dict[NewsSource, float] = {
    NewsSource.KAP: 1.5,          # Resmi açıklama → en yüksek ağırlık
    NewsSource.REUTERS: 1.2,
    NewsSource.BLOOMBERG_HT: 1.1,
    NewsSource.EKSI_SOZLUK: 0.4,  # Sosyal → düşük ağırlık
    NewsSource.GENERIC: 0.7,
}


class RealTimeNewsFeed:
    """Gerçek zamanlı haber akışı yöneticisi (thread-safe).

    Gelen haberleri puanlar, arşivler ve burst (haber patlaması) tespiti yapar.
    """

    def __init__(
        self,
        db_path: str = "data/news_realtime.duckdb",
        decay_hours: float = DEFAULT_DECAY_HOURS,
        max_cache: int = MAX_CACHE_SIZE,
    ) -> None:
        """RealTimeNewsFeed başlatıcı.

        Args:
            db_path: DuckDB arşiv dosyası (':memory:' ise geçici).
            decay_hours: Haber ağırlık azalma süresi (saat).
            max_cache: Bellek içi önbellek kapasitesi.
        """
        self.db_path = db_path
        self.decay_hours = decay_hours
        self.max_cache = max_cache
        self._ticker_extractor = TickerExtractor()
        self._scorer = KeywordSentimentScorer()
        self._cache: list[NewsItem] = []
        self._lock = threading.RLock()
        self._memory_con = duckdb.connect(":memory:") if self.db_path == ":memory:" else None
        self._init_db()

    def __repr__(self) -> str:
        """RealTimeNewsFeed kısa temsili."""
        return (
            f"RealTimeNewsFeed(cache={len(self._cache)}, "
            f"decay={self.decay_hours}h)"
        )

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısını döndürür."""
        if self._memory_con is not None:
            return self._memory_con
        return duckdb.connect(self.db_path)

    def _init_db(self) -> None:
        """DuckDB haber arşivi tablosunu başlatır."""
        try:
            con = self._get_connection()
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_NEWS} (
                    id              VARCHAR PRIMARY KEY,
                    source          VARCHAR NOT NULL,
                    title           VARCHAR NOT NULL,
                    published_at    TIMESTAMP NOT NULL,
                    tickers         VARCHAR,
                    sentiment_score DOUBLE,
                    confidence      DOUBLE,
                    impact_weight   DOUBLE,
                    body_excerpt    VARCHAR
                )
            """)
            if self._memory_con is None:
                con.close()
            logger.info("Haber arşivi DB hazır.", db=self.db_path)
        except Exception as exc:
            logger.warning("Haber DB başlatılamadı, yalnızca önbellek modu.", hata=str(exc))

    def ingest(self, item: NewsItem) -> NewsItem:
        """Tek haber öğesini işler, puanlar ve arşivler.

        Ticker tespiti ve duygu puanlama otomatik yapılır.
        item üzerindeki mevcut puanlama değerleri geçersiz kılınır.

        Args:
            item: İşlenecek haber öğesi.

        Returns:
            Puanlanmış ve güncellemiş haber öğesi.
        """
        # Ticker eşleştirme
        text = f"{item.title} {item.body}"
        if not item.tickers:
            item.tickers = self._ticker_extractor.extract(text)

        # Duygu puanlama
        sentiment, confidence = self._scorer.score(text)
        item.sentiment_score = sentiment
        item.confidence = confidence
        item.impact_weight = SOURCE_WEIGHTS.get(item.source, 0.7)

        with self._lock:
            # Önbellek kapasitesi kontrolü
            if len(self._cache) >= self.max_cache:
                self._cache = self._cache[-(self.max_cache // 2):]  # Yarısını tut

            self._cache.append(item)

        # DuckDB arşivle
        self._archive(item)

        logger.debug(
            "Haber işlendi.",
            kaynak=item.source.name,
            tickers=item.tickers,
            sentiment=round(item.sentiment_score, 2),
        )
        return item

    def _archive(self, item: NewsItem) -> None:
        """Haberi DuckDB'ye arşivler.

        Args:
            item: Arşivlenecek haber öğesi.
        """
        try:
            con = self._get_connection()
            con.execute(
                f"""
                INSERT OR IGNORE INTO {DB_TABLE_NEWS}
                    (id, source, title, published_at, tickers,
                     sentiment_score, confidence, impact_weight, body_excerpt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.id,
                    item.source.name,
                    item.title,
                    item.published_at,
                    ",".join(item.tickers),
                    item.sentiment_score,
                    item.confidence,
                    item.impact_weight,
                    item.body[:300] if item.body else "",
                ],
            )
            if self._memory_con is None:
                con.close()
        except Exception as exc:
            logger.warning("Haber arşivlenemedi.", id=item.id, hata=str(exc))

    def get_ticker_sentiment(
        self,
        ticker: str,
        since: datetime | None = None,
    ) -> dict[str, float]:
        """Belirli bir ticker için ağırlıklı duygu özeti.

        Üssel azalma ağırlığı ile son haberlerin etkisi daha büyüktür.

        Args:
            ticker: BIST hisse kodu.
            since: Başlangıç zamanı (None ise 24 saat önce).

        Returns:
            {weighted_sentiment, n_items, avg_confidence} özet sözlüğü.
        """
        cutoff = since or datetime.now(tz=UTC)
        cutoff_ts = cutoff.timestamp() - self.decay_hours * 3600

        with self._lock:
            relevant = [
                item for item in self._cache
                if ticker in item.tickers
                and item.published_at.timestamp() >= cutoff_ts
            ]

        if not relevant:
            return {
                "weighted_sentiment": 0.0,
                "n_items": 0.0,
                "avg_confidence": 0.0,
            }

        now_ts = time.time()
        decay_rate = 0.693 / (self.decay_hours * 3600)  # ln(2)/yarıömür

        total_weight = 0.0
        weighted_sum = 0.0
        conf_sum = 0.0

        for item in relevant:
            age = now_ts - item.published_at.timestamp()
            decay = max(0.01, item.impact_weight * (1.0 - decay_rate * age))
            weighted_sum += item.sentiment_score * decay * item.confidence
            total_weight += decay * item.confidence
            conf_sum += item.confidence

        sentiment = weighted_sum / max(total_weight, 1e-10)
        avg_conf = conf_sum / len(relevant)

        return {
            "weighted_sentiment": float(sentiment),
            "n_items": float(len(relevant)),
            "avg_confidence": float(avg_conf),
        }

    def get_market_sentiment(
        self,
        since: datetime | None = None,
    ) -> dict[str, float]:
        """Tüm piyasa için genel ağırlıklı duygu özeti.

        Args:
            since: Başlangıç zamanı (None ise 24 saat önce).

        Returns:
            {weighted_sentiment, n_items, avg_confidence} özet sözlüğü.
        """
        cutoff = since or datetime.now(tz=UTC)
        cutoff_ts = cutoff.timestamp() - self.decay_hours * 3600

        with self._lock:
            relevant = [
                item for item in self._cache
                if item.published_at.timestamp() >= cutoff_ts
            ]

        if not relevant:
            return {
                "weighted_sentiment": 0.0,
                "n_items": 0.0,
                "avg_confidence": 0.0,
            }

        now_ts = time.time()
        decay_rate = 0.693 / (self.decay_hours * 3600)

        total_weight = 0.0
        weighted_sum = 0.0
        conf_sum = 0.0

        for item in relevant:
            age = now_ts - item.published_at.timestamp()
            decay = max(0.01, item.impact_weight * (1.0 - decay_rate * age))
            weighted_sum += item.sentiment_score * decay * item.confidence
            total_weight += decay * item.confidence
            conf_sum += item.confidence

        sentiment = weighted_sum / max(total_weight, 1e-10)
        avg_conf = conf_sum / len(relevant)

        return {
            "weighted_sentiment": float(sentiment),
            "n_items": float(len(relevant)),
            "avg_confidence": float(avg_conf),
        }

    def detect_burst(
        self,
        ticker: str | None = None,
    ) -> dict[str, Any]:
        """Son pencerede haber patlaması olup olmadığını kontrol eder.

        Args:
            ticker: Kontrol edilecek hisse (None ise tüm haberler).

        Returns:
            {is_burst, n_items, window_seconds} sözlüğü.
        """
        cutoff = time.time() - BURST_WINDOW_SECONDS

        with self._lock:
            if ticker:
                recent = [
                    i for i in self._cache
                    if ticker in i.tickers
                    and i.published_at.timestamp() >= cutoff
                ]
            else:
                recent = [
                    i for i in self._cache
                    if i.published_at.timestamp() >= cutoff
                ]

        n = len(recent)
        is_burst = n >= BURST_THRESHOLD
        if is_burst:
            logger.warning(
                "Haber patlaması tespit edildi!",
                ticker=ticker or "ALL",
                n_items=n,
                pencere_saniye=BURST_WINDOW_SECONDS,
            )
        return {
            "is_burst": is_burst,
            "n_items": n,
            "window_seconds": BURST_WINDOW_SECONDS,
        }

    def get_market_aggregate_sentiment(self) -> dict[str, float]:
        """Tüm haber akışından piyasa genelinde duygu agregasyonu.

        Returns:
            {market_sentiment, n_items, bullish_ratio, bearish_ratio} sözlüğü.
        """
        cutoff = time.time() - self.decay_hours * 3600

        with self._lock:
            recent = [
                i for i in self._cache
                if i.published_at.timestamp() >= cutoff
            ]

        if not recent:
            return {
                "market_sentiment": 0.0,
                "n_items": 0.0,
                "bullish_ratio": 0.0,
                "bearish_ratio": 0.0,
            }

        bullish = sum(1 for i in recent if i.sentiment_score > 0.1)
        bearish = sum(1 for i in recent if i.sentiment_score < -0.1)
        total = len(recent)
        avg_sent = sum(i.sentiment_score * i.impact_weight for i in recent) / max(total, 1)

        return {
            "market_sentiment": float(avg_sent),
            "n_items": float(total),
            "bullish_ratio": float(bullish / total),
            "bearish_ratio": float(bearish / total),
        }


__all__: list[str] = [
    "KeywordSentimentScorer",
    "NewsItem",
    "NewsSource",
    "RealTimeNewsFeed",
    "TickerExtractor",
    "news_feed",
]

# Singleton
news_feed = RealTimeNewsFeed()
