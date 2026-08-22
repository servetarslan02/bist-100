"""
ALPHA BIST — Research Memory & Context v1.0

- Research Context Engine
- Research Memory
- Long-Term Memory
- Research Lineage
- Data Lineage
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque
import json
import structlog

logger = structlog.get_logger()


@dataclass
class ResearchRecord:
    """Araştırma kaydı."""
    record_id: str
    ticker: str
    date: str
    thesis: str
    evidence: List[str]
    risks: List[str]
    prediction: Dict[str, Any]
    outcome: Optional[Dict[str, Any]] = None
    model_version: str = ""
    prompt_version: str = ""
    confidence: float = 0.0


@dataclass
class LineageNode:
    """Lineage düğümü."""
    node_type: str  # raw_data, feature, model, prediction, decision, order, fill
    node_id: str
    timestamp: str
    parent_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResearchMemory:
    """Araştırma hafızası."""

    def __init__(self):
        self._records: deque = deque(maxlen=10000)
        self._ticker_index: Dict[str, List[ResearchRecord]] = {}

    def add_record(self, record: ResearchRecord):
        """Araştırma kaydı ekle."""
        if len(self._records) == self._records.maxlen:
            old_record = self._records.popleft()
            if old_record.ticker in self._ticker_index:
                try:
                    self._ticker_index[old_record.ticker].remove(old_record)
                except ValueError:
                    pass

        self._records.append(record)
        if record.ticker not in self._ticker_index:
            self._ticker_index[record.ticker] = []
        self._ticker_index[record.ticker].append(record)

    def get_ticker_history(self, ticker: str, limit: int = 10) -> List[Dict]:
        """Ticker araştırma geçmişi."""
        records = self._ticker_index.get(ticker, [])[-limit:]
        return [
            {
                "date": r.date,
                "thesis": r.thesis,
                "prediction": r.prediction,
                "outcome": r.outcome,
                "confidence": r.confidence,
            }
            for r in records
        ]

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """Son araştırmalar."""
        records = list(self._records)[-limit:]
        return [
            {
                "ticker": r.ticker,
                "date": r.date,
                "thesis": r.thesis[:100],
                "confidence": r.confidence,
            }
            for r in records
        ]

    def store_llm_analysis(
        self,
        ticker: str,
        thesis: str,
        direction: str,
        confidence: float,
        key_risks: Optional[List[str]] = None,
        model_version: str = "llm_agent_v1",
    ) -> ResearchRecord:
        """
        LLM Agent analizini otomatik kaydet.

        LLM Agent her analiz sonunda bu metodu çağırır.
        Kaydedilen analizler gelecek RAG sorgulamaları için kullanılır.

        Args:
            ticker:        BIST hisse kodu
            thesis:        Analiz tezi (max 200 karakter)
            direction:     LONG, SHORT veya NEUTRAL
            confidence:    LLM güven skoru (0.0-1.0)
            key_risks:     Risk faktörleri listesi
            model_version: LLM modeli/versiyon etiketi

        Returns:
            Oluşturulan ResearchRecord nesnesi
        """
        import uuid

        record = ResearchRecord(
            record_id=str(uuid.uuid4())[:8],
            ticker=ticker,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            thesis=thesis[:200],
            evidence=[],
            risks=key_risks or [],
            prediction={"direction": direction, "confidence": confidence},
            outcome=None,
            model_version=model_version,
            confidence=confidence,
        )
        self.add_record(record)
        logger.info(
            "LLM analysis stored in research memory",
            ticker=ticker,
            direction=direction,
            confidence=confidence,
        )
        return record

class ResearchContextEngine:
    """AI'ya ilgili context oluşturma."""

    def build_context(self, ticker: str, features: Dict, market_state: Dict, news: List, kap: List, signals: List, predictions: List) -> Dict[str, Any]:
        """Her analiz için ilgili veriyi topla."""
        return {
            "ticker": ticker,
            "features": features,
            "market_state": market_state,
            "recent_news": news[:5],
            "recent_kap": kap[:5],
            "recent_signals": signals[:5],
            "prediction_history": predictions[:10],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class DataLineage:
    """Veri lineage takibi."""

    def __init__(self):
        self._nodes_by_key: Dict[str, LineageNode] = {}
        self._children_index: Dict[str, List[str]] = {}
        self._keys: deque = deque(maxlen=10000)

    def add_node(self, node: LineageNode):
        """Lineage düğümü ekle."""
        key = f"{node.node_type}:{node.node_id}"
        
        # Eğer maxlen ulaşıldıysa eskisini sil
        if len(self._keys) == self._keys.maxlen:
            oldest_key = self._keys.popleft()
            if oldest_key in self._nodes_by_key:
                old_node = self._nodes_by_key.pop(oldest_key)
                for parent_id in old_node.parent_ids:
                    if parent_id in self._children_index and oldest_key in self._children_index[parent_id]:
                        self._children_index[parent_id].remove(oldest_key)

        self._keys.append(key)
        self._nodes_by_key[key] = node

        # Child indeksini güncelle
        for parent_id in node.parent_ids:
            if parent_id not in self._children_index:
                self._children_index[parent_id] = []
            if key not in self._children_index[parent_id]:
                self._children_index[parent_id].append(key)

    def trace_forward(self, node_type: str, node_id: str) -> List[Dict]:
        """İleriye doğru izle (raw → feature → model → prediction)."""
        key = f"{node_type}:{node_id}"
        node = self._nodes_by_key.get(key)
        if not node:
            return []

        result = [{
            "type": node.node_type,
            "id": node.node_id,
            "timestamp": node.timestamp,
            "metadata": node.metadata,
        }]

        # Children (O(1) lookup ile iterasyon)
        child_keys = self._children_index.get(key, [])
        for child_key in child_keys:
            child = self._nodes_by_key.get(child_key)
            if child:
                result.extend(self.trace_forward(child.node_type, child.node_id))
        return result

    def trace_backward(self, node_type: str, node_id: str) -> List[Dict]:
        """Geriye doğru izle (prediction → model → feature → raw)."""
        key = f"{node_type}:{node_id}"
        node = self._nodes_by_key.get(key)
        if not node:
            return []

        result = [{
            "type": node.node_type,
            "id": node.node_id,
            "timestamp": node.timestamp,
            "metadata": node.metadata,
        }]

        for parent_id in node.parent_ids:
            parent_type, parent_node_id = parent_id.split(":", 1) if ":" in parent_id else ("unknown", parent_id)
            result.extend(self.trace_backward(parent_type, parent_node_id))
        return result


# Singletons
research_memory = ResearchMemory()
research_context_engine = ResearchContextEngine()
data_lineage = DataLineage()
