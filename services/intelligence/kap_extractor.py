"""
ALPHA BIST — KAP Extractor v1.0

KAP bildirimlerinden yapılandırılmış veri çıkarma:
- Olay türü sınıflandırması
- Finansal etki yönü + büyüklüğü
- Beklenmediklik skoru
- Belirsizlik skoru
- Sektör zincirleme etkisi

LLM varsa kullanır, yoksa kural tabanlı çalışır.
"""

import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class KAPExtractedEvent:
    """Yapılandırılmış KAP olayı."""
    ticker: str
    kap_id: str
    event_type: str           # DIVIDEND, BONUS, INVESTMENT, CONTRACT, etc.
    event_subtype: str        # Alt tür
    financial_impact: float   # -1 ile +1 arası
    impact_magnitude: float   # 0-1 (ne kadar büyük etki)
    surprise_score: float     # 0-1 (beklenmediklik)
    uncertainty: float        # 0-1 (bilgi eksikliği)
    time_horizon: str         # IMMEDIATE, SHORT, MEDIUM, LONG
    affected_sectors: List[str]
    description: str
    raw_title: str
    raw_summary: str


# Olay türü → finansal etki haritası
EVENT_IMPACT_MAP = {
    "DIVIDEND": {"impact": 0.3, "magnitude": 0.4, "horizon": "SHORT"},
    "BONUS_SHARE": {"impact": 0.2, "magnitude": 0.3, "horizon": "SHORT"},
    "RIGHTS_ISSUE": {"impact": -0.1, "magnitude": 0.3, "horizon": "MEDIUM"},
    "INVESTMENT": {"impact": 0.2, "magnitude": 0.5, "horizon": "LONG"},
    "CONTRACT": {"impact": 0.3, "magnitude": 0.4, "horizon": "MEDIUM"},
    "BUYBACK": {"impact": 0.2, "magnitude": 0.3, "horizon": "SHORT"},
    "MERGER": {"impact": 0.1, "magnitude": 0.7, "horizon": "LONG"},
    "ACQUISITION": {"impact": 0.1, "magnitude": 0.6, "horizon": "LONG"},
    "FINANCIAL_RESULT": {"impact": 0.0, "magnitude": 0.5, "horizon": "IMMEDIATE"},
    "MANAGEMENT_CHANGE": {"impact": 0.0, "magnitude": 0.3, "horizon": "MEDIUM"},
    "LEGAL": {"impact": -0.2, "magnitude": 0.4, "horizon": "LONG"},
    "REGULATORY": {"impact": -0.1, "magnitude": 0.5, "horizon": "MEDIUM"},
    "CAPITAL_INCREASE": {"impact": -0.1, "magnitude": 0.4, "horizon": "MEDIUM"},
    "GUIDANCE": {"impact": 0.0, "magnitude": 0.3, "horizon": "MEDIUM"},
    "CONTRACT_WIN": {"impact": 0.4, "magnitude": 0.5, "horizon": "MEDIUM"},
    "CONTRACT_LOSS": {"impact": -0.4, "magnitude": 0.5, "horizon": "MEDIUM"},
    "PLANT_SHUTDOWN": {"impact": -0.5, "magnitude": 0.6, "horizon": "MEDIUM"},
    "EXPANSION": {"impact": 0.3, "magnitude": 0.5, "horizon": "LONG"},
}

# Anahtar kelime → olay türü eşleme
KEYWORD_MAP = {
    "temettü": "DIVIDEND",
    "kar payı": "DIVIDEND",
    "dividend": "DIVIDEND",
    "bedelsiz": "BONUS_SHARE",
    "bonus share": "BONUS_SHARE",
    "bedelli": "RIGHTS_ISSUE",
    "rights issue": "RIGHTS_ISSUE",
    "yatırım": "INVESTMENT",
    "investment": "INVESTMENT",
    "sözleşme": "CONTRACT",
    "contract": "CONTRACT",
    "ihale": "CONTRACT_WIN",
    "geri alım": "BUYBACK",
    "buyback": "BUYBACK",
    "birleşme": "MERGER",
    "merger": "MERGER",
    "devralma": "ACQUISITION",
    "acquisition": "ACQUISITION",
    "finansal sonuç": "FINANCIAL_RESULT",
    "financial result": "FINANCIAL_RESULT",
    "bilanço": "FINANCIAL_RESULT",
    "yönetim değişikliği": "MANAGEMENT_CHANGE",
    "ceo": "MANAGEMENT_CHANGE",
    "dava": "LEGAL",
    "lawsuit": "LEGAL",
    "regülasyon": "REGULATORY",
    "sermaye artırımı": "CAPITAL_INCREASE",
    "kapasite artışı": "EXPANSION",
    "fabrika": "EXPANSION",
    "üretim": "EXPANSION",
    "durdurma": "PLANT_SHUTDOWN",
    "kapanma": "PLANT_SHUTDOWN",
}


from services.intelligence.llm_agent import llm_agent

class KAPExtractor:
    """KAP bildirimlerinden yapılandırılmış veri çıkarma (LLM Agent & RAG Tabanlı)."""

    def extract(
        self,
        ticker: str,
        kap_id: str,
        title: str,
        summary: str = "",
        kap_history: Optional[List[Dict]] = None,
    ) -> KAPExtractedEvent:
        """KAP bildiriminden LLM Agent ile yapılandırılmış veri çıkar."""
        text = f"{title} {summary}".strip()
        if not text:
            return self._build_empty(ticker, kap_id)

        # 1. LLM Agent Çağrısı (RAG + KAP geçmişi bağlamlı)
        analysis = llm_agent.analyze_kap(
            ticker=ticker,
            title=title,
            summary=summary,
            kap_history=kap_history,
        )

        # 2. Olay türü sınıflandırması
        event_type = self._classify_event(text)
        if event_type == "UNKNOWN" and analysis.event_type != "OTHER":
            event_type = analysis.event_type

        impact_info = EVENT_IMPACT_MAP.get(event_type, {"impact": 0, "magnitude": 0.3, "horizon": "MEDIUM"})
        base_impact = impact_info["impact"]
        impact_magnitude = impact_info["magnitude"]
        time_horizon = impact_info["horizon"]

        # 3. LLM'den gelen sentiment ve etkiyi harmanla
        financial_impact = base_impact + (analysis.sentiment * 0.5)
        financial_impact = max(-1.0, min(1.0, financial_impact))

        affected_sectors = analysis.affected_sectors or ["ALL"]

        return KAPExtractedEvent(
            ticker=ticker,
            kap_id=kap_id,
            event_type=event_type,
            event_subtype=analysis.event_type,
            financial_impact=round(financial_impact, 4),
            impact_magnitude=round(impact_magnitude, 4),
            surprise_score=round(analysis.surprise_score, 4),
            uncertainty=round(analysis.uncertainty_score, 4),
            time_horizon=time_horizon,
            affected_sectors=affected_sectors,
            description=analysis.key_insight or title[:200],
            raw_title=title,
            raw_summary=summary[:500] if summary else "",
        )

    def _build_empty(self, ticker: str, kap_id: str) -> KAPExtractedEvent:
        return KAPExtractedEvent(
            ticker=ticker, kap_id=kap_id, event_type="UNKNOWN", event_subtype="",
            financial_impact=0.0, impact_magnitude=0.0, surprise_score=0.0, uncertainty=0.0,
            time_horizon="MEDIUM", affected_sectors=["ALL"], description="", raw_title="", raw_summary=""
        )

    def _classify_event(self, text: str) -> str:
        """Fallback specific classification for EVENT_IMPACT_MAP keys."""
        text = text.lower()
        for keyword, event_type in KEYWORD_MAP.items():
            if keyword in text:
                return event_type
        return "UNKNOWN"


class SectorChainImpact:
    """Sektör zincirleme etki hesaplama."""

    # Sektörler arası etki zincirleri
    CHAINS = {
        "ENERGY": {
            "AVIATION": {"impact": -0.6, "reason": "Yakıt maliyeti"},
            "RETAIL": {"impact": -0.3, "reason": "Lojistik maliyeti"},
            "CONSTR": {"impact": -0.2, "reason": "Enerji maliyeti"},
            "METAL": {"impact": -0.3, "reason": "Üretim maliyeti"},
        },
        "BANK": {
            "CONSTR": {"impact": -0.5, "reason": "Kredi maliyeti"},
            "RETAIL": {"impact": -0.3, "reason": "Tüketici kredisi"},
            "REAL": {"impact": -0.4, "reason": "Mortgage maliyeti"},
        },
        "TECH": {
            "TELECOM": {"impact": 0.3, "reason": "Talep artışı"},
        },
        "METAL": {
            "CONSTR": {"impact": -0.3, "reason": "Hammadde maliyeti"},
            "AUTO": {"impact": -0.2, "reason": "Hammadde maliyeti"},
        },
    }

    def compute_chain_impact(self, source_sector: str, impact_direction: float) -> List[Dict[str, Any]]:
        """Sektör zincirleme etkisi hesapla.

        Args:
            source_sector: Etki kaynağı sektör
            impact_direction: Etki yönü (pozitif/negatif)

        Returns:
            [{"sector": "AVIATION", "impact": -0.6, "reason": "Yakıt maliyeti"}, ...]
        """
        chains = self.CHAINS.get(source_sector, {})
        results = []

        for target_sector, chain_info in chains.items():
            chain_impact = chain_info["impact"] * (1 if impact_direction > 0 else -1)
            results.append({
                "source_sector": source_sector,
                "target_sector": target_sector,
                "impact": round(chain_impact, 4),
                "reason": chain_info["reason"],
            })

        return results


# Singletons
kap_extractor = KAPExtractor()
sector_chain = SectorChainImpact()
