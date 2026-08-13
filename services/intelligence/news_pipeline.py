"""
ALPHA BIST — News → World → Stock Pipeline v1.0

Haber → NLP → Entity → Event → Importance → World State → Impact → Affected Stocks

Bu zincir eksiksiz olmalı.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class ProcessedNews:
    """İşlenmiş haber."""
    news_id: str
    timestamp: datetime
    source: str
    title: str
    body: str = ""

    # NLP çıktıları
    language: str = "tr"
    entities: List[Dict] = field(default_factory=list)
    event_type: str = ""  # MACRO | COMPANY | SECTOR | GEOPOLITICAL
    sentiment: float = 0.0  # -1 ile +1
    importance: float = 0.0  # 0-1
    novelty: float = 0.0  # 0-1
    credibility: float = 0.5

    # Etki
    affected_tickers: List[str] = field(default_factory=list)
    world_state_delta: Dict[str, float] = field(default_factory=dict)
    propagation_chain: List[Dict] = field(default_factory=list)


class NewsPipeline:
    """Haber işleme pipeline'ı."""

    # Entity patterns (basit regex tabanlı)
    COMPANY_PATTERNS = {
        "THYAO": ["thyao", "türk hava yolları", "thy"],
        "ASELS": ["asels", "aselsan"],
        "AKBNK": ["akbnk", "akbank"],
        "GARAN": ["garan", "garanti"],
        "TUPRS": ["tuprs", "tüpraş"],
        "EREGL": ["ergl", "ereğli"],
        "BIMAS": ["bimas", "bim"],
        "SAHOL": ["sahol", "sabancı"],
        "KCHOL": ["kchol", "koç"],
    }

    MACRO_PATTERNS = {
        "FED": ["fed", "federal reserve", "fomc", "powell"],
        "TCMB": ["tcmb", "merkez bankası", "faiz kararı"],
        "CPI": ["enflasyon", "tüfe", "cpi", "tüfe"],
        "GDP": ["büyüme", "gdp", "gsyh"],
        "OIL": ["petrol", "brent", "ham petrol", "opec"],
        "USD": ["dolar", "usd", "döviz", "kur"],
        "VIX": ["vix", "korku endeksi", "volatilite"],
    }

    # Event classification patterns
    EVENT_PATTERNS = {
        "EARNINGS": ["bilanço", "finansal sonuç", "kar açıklaması", "faaliyet raporu"],
        "INVESTMENT": ["yatırım", "sözleşme", "ihale", "proje"],
        "DIVIDEND": ["temettü", "kar payı", "nakit temettü"],
        "CAPITAL": ["bedelli", "bedelsiz", "sermaye artırımı"],
        "MERGER": ["birleşme", "satın alma", "devralma"],
        "REGULATION": ["düzenleme", "mevzuat", "spk", "bdk"],
        "GEOPOLITICAL": ["savaş", "ambargo", "yaptırım", "seçim", "darbe"],
    }

    def process(self, raw_news: Dict) -> ProcessedNews:
        """
        Ham haberi işlenmiş haber haline getir.

        Pipeline:
        raw_news → language detection → entity extraction →
        event classification → sentiment → importance →
        novelty → affected tickers → world state delta
        """
        title = raw_news.get("title", "")
        body = raw_news.get("body", "")
        text = f"{title} {body}".lower()

        # 1. Entity extraction
        entities = self._extract_entities(text)

        # 2. Event classification
        event_type = self._classify_event(text)

        # 3. Sentiment
        sentiment = self._analyze_sentiment(text)

        # 4. Importance
        importance = self._assess_importance(text, entities, event_type)

        # 5. Novelty (basit — aynı başlık daha önce görülmemişse novel)
        novelty = 0.7  # Varsayılan

        # 6. Affected tickers
        affected = self._find_affected_tickers(entities, event_type)

        # 7. World state delta
        world_delta = self._compute_world_delta(event_type, sentiment, importance)

        return ProcessedNews(
            news_id=raw_news.get("id", ""),
            timestamp=datetime.utcnow(),
            source=raw_news.get("source", "unknown"),
            title=title,
            body=body,
            entities=entities,
            event_type=event_type,
            sentiment=sentiment,
            importance=importance,
            novelty=novelty,
            credibility=raw_news.get("credibility", 0.5),
            affected_tickers=affected,
            world_state_delta=world_delta,
        )

    def _extract_entities(self, text: str) -> List[Dict]:
        """Entity extraction — şirket, kurum, ülke."""
        entities = []

        # Şirketler
        for ticker, patterns in self.COMPANY_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    entities.append({"type": "COMPANY", "name": ticker, "confidence": 0.8})
                    break

        # Makro
        for name, patterns in self.MACRO_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    entities.append({"type": "MACRO", "name": name, "confidence": 0.7})
                    break

        return entities

    def _classify_event(self, text: str) -> str:
        """Olay sınıflandırma."""
        for event_type, patterns in self.EVENT_PATTERNS.items():
            for pattern in patterns:
                if pattern in text:
                    if event_type in ["GEOPOLITICAL", "REGULATION"]:
                        return "GEOPOLITICAL"
                    elif event_type in ["EARNINGS", "INVESTMENT", "DIVIDEND", "CAPITAL", "MERGER"]:
                        return "COMPANY"
                    else:
                        return "MACRO"

        # Varsayılan
        if any(w in text for words in self.COMPANY_PATTERNS.values() for w in words):
            return "COMPANY"
        return "OTHER"

    def _analyze_sentiment(self, text: str) -> float:
        """Sentiment analizi (-1 ile +1)."""
        positive = [
            "yükseliş", "artış", "kazanç", "rekor", "büyüme", "kar",
            "olumlu", "başarı", "gelişme", "anlaşma", "sözleşme",
            "pozitif", "güçlü", "iyimser",
        ]
        negative = [
            "düşüş", "kayıp", "zarar", "azalış", "olumsuz", "gerileme",
            "risk", "uyarı", "iptal", "erteleme", "dava", "ceza",
            "negatif", "zayıf", "kötümser", "kriz", "çöküş",
        ]

        pos = sum(1 for w in positive if w in text)
        neg = sum(1 for w in negative if w in text)
        total = pos + neg

        if total == 0:
            return 0.0
        return (pos - neg) / total

    def _assess_importance(self, text: str, entities: List[Dict], event_type: str) -> float:
        """Önem değerlendirmesi (0-1)."""
        importance = 0.3  # Baz

        # Şirket haberi
        if event_type == "COMPANY":
            importance += 0.2

        # Makro haberi
        if event_type == "MACRO":
            importance += 0.3

        # Jeopolitik
        if event_type == "GEOPOLITICAL":
            importance += 0.4

        # Çoklu entity
        if len(entities) > 3:
            importance += 0.1

        # Kritik kelimeler
        critical = ["sürpriz", "beklenmedik", "acil", "olağanüstü", "rekor", "tarihi"]
        if any(w in text for w in critical):
            importance += 0.2

        return min(importance, 1.0)

    def _find_affected_tickers(self, entities: List[Dict], event_type: str) -> List[str]:
        """Etkilenecek hisseleri bul."""
        tickers = set()

        for entity in entities:
            if entity["type"] == "COMPANY":
                tickers.add(entity["name"])
            elif entity["type"] == "MACRO":
                # Makro olayları tüm piyasayı etkiler ama bazı sektörleri daha fazla
                if entity["name"] == "FED":
                    tickers.update(["AKBNK", "GARAN", "YKBNK"])  # Bankacılık
                elif entity["name"] == "OIL":
                    tickers.update(["TUPRS", "PETKM", "THYAO"])
                elif entity["name"] == "TCMB":
                    tickers.update(["AKBNK", "GARAN", "YKBNK"])

        return list(tickers)

    def _compute_world_delta(self, event_type: str, sentiment: float, importance: float) -> Dict[str, float]:
        """World state değişimini hesapla."""
        delta = {}

        if event_type == "MACRO":
            if sentiment < -0.3:
                delta["global_risk_appetite"] = -0.1 * importance
                delta["geopolitical_risk"] = 0.1 * importance
            elif sentiment > 0.3:
                delta["global_risk_appetite"] = 0.1 * importance

        elif event_type == "GEOPOLITICAL":
            delta["geopolitical_risk"] = 0.2 * importance
            delta["global_risk_appetite"] = -0.15 * importance

        elif event_type == "COMPANY":
            # Şirket haberleri world state'i çok etkilemez
            pass

        return delta


# Singleton
news_pipeline = NewsPipeline()
