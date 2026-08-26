"""
ALPHA BIST — LLM Context Builder v1.0 (RAG Motoru)

Her LLM analizi öncesinde zenginleştirilmiş bir bağlam (context)
paketi hazırlar:

  World State       → Anlık makro ekonomik tablo
  Knowledge Graph   → Sektör-şirket etki ağı
  Research Memory   → Geçmiş LLM analizleri (RAG)
  Ticker Features   → Teknik + temel özellikler
  Regime            → Piyasa rejimi
  Signal Conflicts  → Sinyal çatışma raporu
  SPEC Score        → SPEC kanıt ve skor detayı

Bu bağlam paketi llm_agent.py tarafından prompt'a eklenir.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import orjson
import structlog

logger = structlog.get_logger()


class LLMContextBuilder:
    """
    RAG merkezi: Tüm sistem verilerini tek bir bağlam nesnesine toplar.
    Her veri kaynağı için graceful fallback uygulanır.
    """

    def build_news_context(
        self,
        ticker: Optional[str] = None,
        sector: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Haber analizi için bağlam paketi.
        Eğer ticker biliniyorsa: geçmiş hafıza + features da eklenir.
        """
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context_type": "news",
        }

        # 1. World State — her zaman eklenir
        context["world_state"] = self._fetch_world_state()

        # 2. Piyasa rejimi
        context["market_regime"] = self._fetch_regime()

        # 3. Ticker varsa: geçmiş hafıza + sektör etkileri
        if ticker:
            context["research_history"] = self._fetch_research_memory(ticker)
            context["ticker_features_summary"] = self._fetch_features_summary(ticker)

        # 4. Sektör varsa: knowledge graph etkileri
        if sector:
            context["sector_relations"] = self._fetch_sector_relations(sector)

        return context

    def build_kap_context(
        self,
        ticker: str,
        kap_history: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        KAP bildirimi analizi için bağlam paketi.
        Şirketin geçmiş KAP bildirimleri ve LLM analizleri dahil edilir.
        """
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context_type": "kap",
            "ticker": ticker,
        }

        # 1. Geçmiş LLM analizleri (RAG)
        context["research_history"] = self._fetch_research_memory(ticker, limit=5)

        # 2. Geçmiş KAP bildirimleri (varsa)
        if kap_history:
            context["previous_kap_announcements"] = kap_history[:3]

        # 3. World State
        context["world_state"] = self._fetch_world_state()

        # 4. Rejim
        context["market_regime"] = self._fetch_regime()

        # 5. Sektör etkileri (ticker'dan sektör çıkarılamıyorsa atla)
        context["spec_score"] = self._fetch_spec_score(ticker)

        return context

    def build_signal_fusion_context(
        self,
        ticker: str,
        signals: Dict[str, Any],
        conflict_details: List[str],
        features: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Signal Fusion aşaması için LLM meta-skor bağlamı.
        LLM tüm çelişen sinyalleri + piyasa bağlamını görerek
        kendi 'hakem skoru'nu üretir.
        """
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context_type": "signal_fusion",
            "ticker": ticker,
        }

        # 1. Sinyal bileşenleri
        context["signals"] = {
            component: {
                "direction": data.get("direction", "NEUTRAL"),
                "score": round(data.get("score", 50), 1),
            }
            for component, data in signals.items()
        }

        # 2. Çatışmalar — en kritik bilgi
        context["signal_conflicts"] = conflict_details

        # 3. Ana teknik özellikler (özet)
        context["technical_summary"] = {
            "rsi_14": features.get("rsi_14", 50),
            "momentum_20d": features.get("momentum_20d", 0),
            "atr_pct": features.get("atr_pct", 0),
            "volume_zscore": features.get("volume_zscore", 0),
            "bb_position": features.get("bb_position", 0.5),
        }

        # 4. World State (kısa özet)
        ws = self._fetch_world_state()
        context["world_state_summary"] = {
            "global_risk_appetite": ws.get("global_risk_appetite", 0.5),
            "turkey_macro_risk": ws.get("turkey_macro_risk", 0.5),
            "vix_level": ws.get("vix_level", 20),
            "geopolitical_risk": ws.get("geopolitical_risk", 0.4),
        }

        # 5. Piyasa rejimi
        context["market_regime"] = self._fetch_regime()

        # 6. Geçmiş hafıza özeti (son 3)
        context["research_history"] = self._fetch_research_memory(ticker, limit=3)

        return context

    def build_decision_narrative_context(
        self,
        ticker: str,
        decision: Dict[str, Any],
        features: Dict[str, Any],
        price: float,
    ) -> Dict[str, Any]:
        """
        Nihai karar için Türkçe açıklama bağlamı.
        Tüm kararı + gerekçeyi Türkçe metne çevirmek için kullanılır.
        """
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context_type": "decision_narrative",
            "ticker": ticker,
            "price": price,
            "decision": decision,
            "technical_summary": {
                "rsi_14": features.get("rsi_14", 50),
                "momentum_20d": features.get("momentum_20d", 0),
                "pe_ratio": features.get("pe_ratio", 0),
            },
            "world_state": self._fetch_world_state(),
            "market_regime": self._fetch_regime(),
        }

    # ── İç Yardımcı Metodlar ─────────────────────────────────────────────────

    def _fetch_world_state(self) -> Dict[str, Any]:
        try:
            from services.intelligence.world_state import world_state_manager
            return world_state_manager.get_state_dict()
        except ImportError:
            return {
                "global_risk_appetite": 0.55,
                "vix_level": 18.5,
                "turkey_macro_risk": 0.65,
                "geopolitical_risk": 0.40,
                "oil_pressure": 0.50,
                "usd_strength": 0.60,
                "inflation_pressure": 0.70,
                "note": "mock_data",
            }

    def _fetch_regime(self) -> Dict[str, Any]:
        try:
            from services.intelligence.regime import regime_engine
            r = regime_engine.get_regime()
            return {
                "regime": r.regime if hasattr(r, "regime") else str(r),
                "confidence": getattr(r, "confidence", 0.7),
                "duration_days": getattr(r, "duration", 0),
            }
        except (ImportError, AttributeError):
            return {"regime": "BULL", "confidence": 0.70, "duration_days": 12}

    def _fetch_research_memory(self, ticker: str, limit: int = 5) -> List[Dict]:
        try:
            from services.intelligence.research_memory import research_memory
            return research_memory.get_ticker_history(ticker, limit=limit)
        except ImportError:
            return []

    def _fetch_features_summary(self, ticker: str) -> Dict[str, Any]:
        # Feature store'a direkt erişim yok; orchestrator bağlamda sağlar.
        return {"note": "Feature verisi orchestrator tarafından bağlama eklenir."}

    def _fetch_sector_relations(self, sector: str) -> List[Dict]:
        try:
            from services.intelligence.knowledge_graph import knowledge_graph
            entity_id = f"sector_{sector}"
            relations = knowledge_graph.get_related_entities(entity_id)
            return [
                {
                    "entity": e.name,
                    "relation": r.relation_type,
                    "strength": r.strength,
                }
                for e, r in relations[:10]
            ]
        except ImportError:
            return []

    def _fetch_spec_score(self, ticker: str) -> Dict[str, Any]:
        try:
            from services.intelligence.spec_engine import spec_engine
            result = spec_engine.get_latest(ticker)
            if result:
                return {
                    "spec_score": getattr(result, "spec_score", 50),
                    "category": getattr(result, "category", "WATCH"),
                }
        except (ImportError, AttributeError):
            logger.warning("Error in _fetch_spec_score: (ImportError, AttributeError)", exc_info=True)
        return {"spec_score": None, "category": None}

    def to_prompt_text(self, context: Dict[str, Any]) -> str:
        """
        Bağlam nesnesini LLM prompt'una eklenebilecek metin bloğuna dönüştürür.
        JSON olarak eklenir — LLM'in yapılandırılmış veriyi daha iyi okuması için.
        """
        try:
            return orjson.dumps(context, option=orjson.OPT_INDENT_2, default=str).decode()
        except Exception:
            return str(context)


# Singleton
llm_context_builder = LLMContextBuilder()
