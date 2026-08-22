"""
ALPHA BIST — News → World → Stock Pipeline v2.0 (LLM Agent Tabanlı)

Haber → LLM Agent (RAG + World State + Knowledge Graph) →
Entity → Event → Importance → World State → Impact → Affected Stocks

Bu zincir eksiksiz olmalı.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog
from services.intelligence.llm_agent import llm_agent

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
    event_type: str = ""
    sentiment: float = 0.0
    importance: float = 0.0
    novelty: float = 0.0
    credibility: float = 0.5

    # Etki
    affected_tickers: List[str] = field(default_factory=list)
    affected_sectors: List[str] = field(default_factory=list)
    world_state_delta: Dict[str, float] = field(default_factory=dict)
    propagation_chain: List[Dict] = field(default_factory=list)

    # LLM Ajan çıktıları
    key_insight: str = ""
    surprise_score: float = 0.5
    uncertainty_score: float = 0.3
    regime_override: Optional[str] = None
    tool_calls_made: List[str] = field(default_factory=list)
    is_llm_analyzed: bool = False


class NewsPipeline:
    """Haber işleme pipeline'ı (LLM Agent tabanlı — RAG + WorldState + KnowledgeGraph)."""

    def process(self, raw_news: Dict) -> ProcessedNews:
        """
        Ham haberi LLM Agent ile işleyerek yapılandırılmış veriye dönüştür.

        LLM Agent şunlara erişir:
        - WorldState (anlık makro tablo)
        - KnowledgeGraph (sektör-şirket etki ağı)
        - ResearchMemory (geçmiş analizler — RAG)
        - Piyasa rejimi
        """
        title = raw_news.get("title", "")
        body = raw_news.get("body", "")
        text = f"{title} {body}".strip()

        if not text:
            return self._build_empty(raw_news)

        # Haberde hisse kodu ve sektör ipuçları var mı?
        ticker_hint = raw_news.get("ticker")
        sector_hint = raw_news.get("sector")

        # LLM Agent analizi — RAG + WorldState + KnowledgeGraph bağlamlı
        analysis = llm_agent.analyze_news(
            text=text,
            ticker=ticker_hint,
            sector=sector_hint,
        )

        # World state delta hesapla
        world_delta = self._compute_world_delta(
            analysis.event_type,
            analysis.sentiment,
            analysis.importance,
        )

        return ProcessedNews(
            news_id=raw_news.get("id", ""),
            timestamp=datetime.now(timezone.utc),
            source=raw_news.get("source", "unknown"),
            title=title,
            body=body,
            entities=analysis.entities,
            event_type=analysis.event_type,
            sentiment=analysis.sentiment,
            importance=analysis.importance,
            novelty=0.7,  # Gelecekte duplicate detection ile güncellenecek
            credibility=raw_news.get("credibility", 0.5),
            affected_tickers=analysis.affected_tickers,
            affected_sectors=analysis.affected_sectors,
            world_state_delta=world_delta,
            key_insight=analysis.key_insight,
            surprise_score=analysis.surprise_score,
            uncertainty_score=analysis.uncertainty_score,
            regime_override=analysis.regime_override,
            tool_calls_made=analysis.tool_calls_made,
            is_llm_analyzed=True,
        )

    def _build_empty(self, raw_news: Dict) -> ProcessedNews:
        return ProcessedNews(
            news_id=raw_news.get("id", ""),
            timestamp=datetime.now(timezone.utc),
            source=raw_news.get("source", "unknown"),
            title="",
        )

    def _compute_world_delta(
        self, event_type: str, sentiment: float, importance: float
    ) -> Dict[str, float]:
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

        return delta

# Singleton
news_pipeline = NewsPipeline()
