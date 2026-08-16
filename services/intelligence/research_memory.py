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
        self._records: List[ResearchRecord] = []
        self._ticker_index: Dict[str, List[int]] = {}

    def add_record(self, record: ResearchRecord):
        """Araştırma kaydı ekle."""
        idx = len(self._records)
        self._records.append(record)
        if record.ticker not in self._ticker_index:
            self._ticker_index[record.ticker] = []
        self._ticker_index[record.ticker].append(idx)

    def get_ticker_history(self, ticker: str, limit: int = 10) -> List[Dict]:
        """Ticker araştırma geçmişi."""
        indices = self._ticker_index.get(ticker, [])
        records = [self._records[i] for i in indices[-limit:]]
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
        return [
            {
                "ticker": r.ticker,
                "date": r.date,
                "thesis": r.thesis[:100],
                "confidence": r.confidence,
            }
            for r in self._records[-limit:]
        ]


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
        self._nodes: List[LineageNode] = []
        self._index: Dict[str, List[int]] = {}

    def add_node(self, node: LineageNode):
        """Lineage düğümü ekle."""
        idx = len(self._nodes)
        self._nodes.append(node)
        key = f"{node.node_type}:{node.node_id}"
        if key not in self._index:
            self._index[key] = []
        self._index[key].append(idx)

    def trace_forward(self, node_type: str, node_id: str) -> List[Dict]:
        """İleriye doğru izle (raw → feature → model → prediction)."""
        key = f"{node_type}:{node_id}"
        indices = self._index.get(key, [])
        result = []
        for idx in indices:
            node = self._nodes[idx]
            result.append({
                "type": node.node_type,
                "id": node.node_id,
                "timestamp": node.timestamp,
                "metadata": node.metadata,
            })
            # Children
            for child in self._nodes:
                if key in child.parent_ids:
                    result.extend(self.trace_forward(child.node_type, child.node_id))
        return result

    def trace_backward(self, node_type: str, node_id: str) -> List[Dict]:
        """Geriye doğru izle (prediction → model → feature → raw)."""
        key = f"{node_type}:{node_id}"
        indices = self._index.get(key, [])
        result = []
        for idx in indices:
            node = self._nodes[idx]
            result.append({
                "type": node.node_type,
                "id": node.node_id,
                "timestamp": node.timestamp,
                "metadata": node.metadata,
            })
            for parent_id in node.parent_ids:
                parent_type, parent_node_id = parent_id.split(":", 1) if ":" in parent_id else ("unknown", parent_id)
                result.extend(self.trace_backward(parent_type, parent_node_id))
        return result


# Singletons
research_memory = ResearchMemory()
research_context_engine = ResearchContextEngine()
data_lineage = DataLineage()
