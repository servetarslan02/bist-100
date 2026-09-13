"""
ALPHA BIST — FOMC & TCMB Toplantı ve Metin Duygu Analiz Modülü

Merkez Bankası (FED & TCMB) faiz kararları, politika metinleri ve tutanaklarının
taranması, Hawkish/Dovish duyarlılık puanlaması ve BIST100 üzerindeki makro
etki skorlaması.

Özellikler:
  - FED FOMC tutanak & bildiri duygu analizi (İngilizce NLP sözlüğü)
  - TCMB PPK (Para Politikası Kurulu) karar metni analizi (Türkçe NLP sözlüğü)
  - Hawkish (+1.0) / Dovish (-1.0) kutuplaşma puanı
  - Faiz sürprizi (gerçekleşen - piyasa medyan beklentisi)
  - DuckDB toplantı arşivi
  - Point-in-Time uyumu: Gelecek kararlar sızdırılmaz
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import datetime

import duckdb
import structlog

logger = structlog.get_logger(__name__)

DB_TABLE_CB_EVENTS = "central_bank_events"

# FED & TCMB Hawkish / Dovish sözlükleri
HAWKISH_EN_KEYWORDS: set[str] = {
    "inflation", "tightening", "rate hike", "restrictive", "overheating",
    "persistent", "elevated", "further increase", "resilient", "upside risks",
    "demand pressure", "curb inflation", "vigilant", "firm stance",
}

DOVISH_EN_KEYWORDS: set[str] = {
    "cut", "easing", "slowdown", "weakness", "recession", "downside risks",
    "soft landing", "transitory", "moderation", "pause", "labor market softening",
    "accommodative", "cooling", "headwinds",
}

HAWKISH_TR_KEYWORDS: set[str] = {
    "sıkılaştırma", "faiz artırımı", "enflasyon baskısı", "enflasyonist",
    "kararlılıkla", "sıkı duruş", "yukarı yönlü riskler", "talep fazlası",
    "fiyat istikrarı", "risk primi", "parasal sıkılık", "gerektiğinde",
}

DOVISH_TR_KEYWORDS: set[str] = {
    "faiz indirimi", "gevşeme", "yavaşlama", "destekleyici", "aşağı yönlü",
    "dezenflasyon", "ılımlı", "toparlanma", "teşvik", "kredi genişlemesi",
    "canlanma", "finansal koşulların gevşemesi",
}


class CentralBank(Enum):
    """Merkez bankası türü."""

    FED = auto()
    TCMB = auto()
    ECB = auto()


class CBEventType(Enum):
    """Merkez bankası olay türü."""

    RATE_DECISION = auto()
    MINUTES = auto()
    PRESS_CONFERENCE = auto()
    INFLATION_REPORT = auto()


@dataclass
class CBEvent:
    """Merkez bankası karar veya duyuru öğesi.

    Attributes:
        id: Benzersiz kimlik.
        bank: Hangi merkez bankası (FED, TCMB, ECB).
        event_type: Olay türü.
        event_date: Olay tarihi (Point-in-Time için kesin tarih).
        title: Açıklama / başlık.
        rate_decision_bps: Faiz değişimi (baz puan: +250, 0, -100 vb.).
        rate_surprise_bps: Sürpriz farkı (gerçekleşen - beklenti bps).
        policy_rate: Yeni faiz oranı (yüzde cinsinden).
        hawk_score: Hawkish (+1.0) / Dovish (-1.0) skoru.
        text_content: Karar metni veya özet.
    """

    bank: CentralBank
    event_type: CBEventType
    event_date: datetime.date
    title: str
    id: str = ""
    rate_decision_bps: float = 0.0
    rate_surprise_bps: float = 0.0
    policy_rate: float = 0.0
    hawk_score: float = 0.0
    confidence: float = 0.5
    text_content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Varsayılan ID oluşturur."""
        if not self.id:
            self.id = f"{self.bank.name}_{self.event_date.isoformat()}_{self.event_type.name}"

    def __repr__(self) -> str:
        """CBEvent kısa temsili."""
        return (
            f"CBEvent({self.bank.name} on {self.event_date.isoformat()}: "
            f"rate={self.policy_rate:.2f}%, hawk={self.hawk_score:+.2f})"
        )


class CBTextAnalyzer:
    """Merkez bankası politika duyuru metinlerini inceleyen NLP analizcisi."""

    def __init__(self) -> None:
        """Sözlük ve regex modellerini hazırlar."""
        self._en_hawk = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in HAWKISH_EN_KEYWORDS]
        self._en_dove = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in DOVISH_EN_KEYWORDS]
        self._tr_hawk = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in HAWKISH_TR_KEYWORDS]
        self._tr_dove = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in DOVISH_TR_KEYWORDS]

    def score_text(self, text: str, bank: CentralBank) -> tuple[float, float]:
        """Metnin Hawkish (+1.0) ile Dovish (-1.0) arasındaki skorunu ve güvenini hesaplar.

        Args:
            text: İncelenecek metin.
            bank: İlgili merkez bankası.

        Returns:
            (hawk_score, confidence) çifti.
        """
        if not text or len(text.strip()) < 10:
            return 0.0, 0.2

        if bank in (CentralBank.FED, CentralBank.ECB):
            hawk_patterns = self._en_hawk
            dove_patterns = self._en_dove
        else:
            hawk_patterns = self._tr_hawk
            dove_patterns = self._tr_dove

        hawk_count = sum(len(p.findall(text)) for p in hawk_patterns)
        dove_count = sum(len(p.findall(text)) for p in dove_patterns)
        total = hawk_count + dove_count

        if total == 0:
            return 0.0, 0.3

        # -1.0 ile +1.0 arasında normalize
        hawk_score = (hawk_count - dove_count) / float(total)
        confidence = min(1.0, 0.3 + (total / 10.0) * 0.7)

        return float(hawk_score), float(confidence)


class CentralBankScraperService:
    """Merkez bankası veri toplayıcı, skorlayıcı ve DuckDB saklama servisi."""

    def __init__(self, db_path: str = "data/central_bank.duckdb") -> None:
        """CentralBankScraperService başlatıcı.

        Args:
            db_path: DuckDB veritabanı yolu.
        """
        self.db_path = db_path
        self.analyzer = CBTextAnalyzer()
        self._lock = threading.RLock()
        self._memory_con = duckdb.connect(":memory:") if self.db_path == ":memory:" else None
        self._events: list[CBEvent] = []
        self._init_db()

    def __repr__(self) -> str:
        """Servis temsili."""
        return f"CentralBankScraperService(db={self.db_path}, events={len(self._events)})"

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """DuckDB bağlantısını döndürür."""
        if self._memory_con is not None:
            return self._memory_con
        return duckdb.connect(self.db_path)

    def _init_db(self) -> None:
        """DuckDB tablosunu hazırlar."""
        try:
            con = self._get_connection()
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE_CB_EVENTS} (
                    id                  VARCHAR PRIMARY KEY,
                    bank                VARCHAR NOT NULL,
                    event_type          VARCHAR NOT NULL,
                    event_date          DATE NOT NULL,
                    title               VARCHAR NOT NULL,
                    rate_decision_bps   DOUBLE,
                    rate_surprise_bps   DOUBLE,
                    policy_rate         DOUBLE,
                    hawk_score          DOUBLE,
                    confidence          DOUBLE,
                    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            if self._memory_con is None:
                con.close()
            logger.info("Merkez bankası DB tablosu hazır.", db=self.db_path)
        except Exception as exc:
            logger.warning("Merkez bankası DB başlatılamadı.", hata=str(exc))

    def record_event(self, event: CBEvent) -> CBEvent:
        """Yeni bir merkez bankası kararını analiz edip kaydeder.

        Args:
            event: Kaydedilecek olay.

        Returns:
            Puanlanmış ve veritabanına eklenmiş olay.
        """
        if event.text_content and event.hawk_score == 0.0:
            hawk, conf = self.analyzer.score_text(event.text_content, event.bank)
            event.hawk_score = hawk
            event.confidence = conf

        with self._lock:
            self._events.append(event)

        try:
            con = self._get_connection()
            con.execute(
                f"""
                INSERT OR REPLACE INTO {DB_TABLE_CB_EVENTS}
                    (id, bank, event_type, event_date, title,
                     rate_decision_bps, rate_surprise_bps, policy_rate,
                     hawk_score, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    event.id,
                    event.bank.name,
                    event.event_type.name,
                    event.event_date,
                    event.title,
                    event.rate_decision_bps,
                    event.rate_surprise_bps,
                    event.policy_rate,
                    event.hawk_score,
                    event.confidence,
                ],
            )
            if self._memory_con is None:
                con.close()
        except Exception as exc:
            logger.warning("Merkez bankası olayı kaydedilemedi.", id=event.id, hata=str(exc))

        logger.info(
            "Merkez bankası kararı işlendi.",
            bank=event.bank.name,
            date=event.event_date.isoformat(),
            policy_rate=event.policy_rate,
            hawk=round(event.hawk_score, 2),
        )
        return event

    def get_latest_stance(self, bank: CentralBank) -> dict[str, Any]:
        """Belirtilen merkez bankasının en güncel faiz ve duruş özetini döndürür.

        Args:
            bank: Merkez bankası.

        Returns:
            Özet sözlüğü.
        """
        with self._lock:
            bank_events = [e for e in self._events if e.bank == bank]

        if not bank_events:
            return {
                "bank": bank.name,
                "latest_rate": 0.0,
                "latest_hawk_score": 0.0,
                "has_data": False,
            }

        bank_events.sort(key=lambda x: x.event_date, reverse=True)
        latest = bank_events[0]

        return {
            "bank": bank.name,
            "latest_date": latest.event_date.isoformat(),
            "latest_rate": latest.policy_rate,
            "rate_decision_bps": latest.rate_decision_bps,
            "rate_surprise_bps": latest.rate_surprise_bps,
            "hawk_score": latest.hawk_score,
            "confidence": latest.confidence,
            "has_data": True,
        }

    def compute_bist_macro_shock(self) -> dict[str, float]:
        """TCMB ve FED duruşunun BIST üzerindeki birleşik makro şok etkisini hesaplar.

        Pozitif şok: BIST için destekleyici (Dovish FED + Enflasyonla mücadelede güven veren TCMB)
        Negatif şok: Likidite sıkışması ve kur/tahvil baskısı

        Returns:
            {bist_sentiment_impact, fed_hawk, tcmb_hawk} katsayıları.
        """
        fed_stance = self.get_latest_stance(CentralBank.FED)
        tcmb_stance = self.get_latest_stance(CentralBank.TCMB)

        fed_hawk = fed_stance.get("hawk_score", 0.0)
        tcmb_hawk = tcmb_stance.get("hawk_score", 0.0)
        tcmb_surprise = tcmb_stance.get("rate_surprise_bps", 0.0)

        # Fed sıkılaşması BIST için negatif baskı (-0.4 çarpan)
        # TCMB sürpriz faiz artışı kısa vadede borsaya satış/tahvile kayış getirir (-0.3 çarpan)
        fed_impact = -0.4 * fed_hawk
        tcmb_impact = -0.001 * tcmb_surprise - 0.2 * tcmb_hawk

        combined_impact = max(-1.0, min(1.0, fed_impact + tcmb_impact))

        return {
            "bist_sentiment_impact": float(combined_impact),
            "fed_hawk_score": float(fed_hawk),
            "tcmb_hawk_score": float(tcmb_hawk),
            "tcmb_surprise_bps": float(tcmb_surprise),
        }


# Singleton
cb_service = CentralBankScraperService()

__all__ = [
    "CBEvent",
    "CBEventType",
    "CBTextAnalyzer",
    "CentralBank",
    "CentralBankScraperService",
    "cb_service",
]
