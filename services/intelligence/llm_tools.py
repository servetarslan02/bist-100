"""
ALPHA BIST — LLM Tool Registry v1.0

LLM Agent'ın kullanabileceği tüm araçların (tools) tanımı ve
uygulaması. Her araç gerçek sistem singleton'larına bağlıdır.

Araçlar Gemini Function Calling schema formatında tanımlanır,
böylece hem gerçek API hem de mock modunda kullanılabilir.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()

# ─── ARAÇ ŞEMALARI (Gemini Function Calling formatı) ────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "get_world_state",
        "description": (
            "Anlık küresel piyasa durumunu getirir: VIX seviyesi, "
            "USD/TRY baskısı, TCMB faiz baskısı, jeopolitik risk, "
            "küresel risk iştahı ve emtia baskısı (0-1 arası normalize)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_knowledge_graph",
        "description": (
            "Bir makro olayın veya sektörün hangi şirketleri, sektörleri "
            "etkilediğini ve etki yönünü (pozitif/negatif) döndürür. "
            "Örnek: 'OIL' → THYAO: negatif, TUPRS: pozitif."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Sorgulanacak entity: 'macro_OIL', 'sector_BANK', 'THYAO' gibi.",
                },
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_research_memory",
        "description": (
            "Belirli bir hisse için geçmişteki LLM analizlerini ve "
            "araştırma notlarını getirir (RAG). Son 5 analizi özetler: "
            "tarih, tez, tahmin ve gerçekleşen sonuç."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu, örn: 'THYAO', 'AKBNK'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Kaç kayıt getirilsin (varsayılan: 5)",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_ticker_features",
        "description": (
            "Bir hissenin anlık teknik ve temel özelliklerini getirir: "
            "RSI, momentum, ATR, Bollinger Band pozisyonu, hacim z-skoru, "
            "P/E, P/B, ROE, piyasa değeri."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_regime",
        "description": (
            "Piyasanın şu anki rejimini döndürür: BULL, BEAR, CRISIS, "
            "HIGH_VOLATILITY, RECOVERY, SIDEWAYS vb. Güven skoru ve "
            "rejimdeki gün sayısını da içerir."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_ensemble_forecast",
        "description": (
            "ML modellerinin (XGBoost, LightGBM, Heuristic) bir hisse "
            "için beklenen getiri tahminlerini ve modeller arası "
            "uyum/anlaşmazlık skorunu döndürür."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_signal_conflicts",
        "description": (
            "Bir hisse için teknik, fundamental, momentum, sentiment, "
            "makro ve AI sinyalleri arasındaki çatışmaları raporlar. "
            "Hangi sinyaller birbiriyle çelişiyor? Güven düşüyor mu?"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_spec_score",
        "description": (
            "Bir hisse için SPEC (Anormal Davranış + Kanıt + Rejim Uyumu) "
            "skorunu ve bunu oluşturan kanıt listesini döndürür. "
            "Yüksek skor yüksek conviction demektir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "override_regime",
        "description": (
            "KRİTİK ARAÇ: Piyasa rejimini acil olarak günceller. "
            "Yalnızca haberin importance >= 0.85 ve gerçek bir "
            "jeopolitik/makroekonomik şok varsa kullanılmalıdır. "
            "Örnek: büyük savaş haberi, merkez bankası sürpriz kararı."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "new_regime": {
                    "type": "string",
                    "description": "Yeni rejim: 'CRISIS', 'RISK_OFF', 'RECOVERY', 'HIGH_VOLATILITY'",
                },
                "reason": {
                    "type": "string",
                    "description": "Gerekçe metni (zorunlu, loglanır)",
                },
                "confidence": {
                    "type": "number",
                    "description": "LLM'in bu karar için güven skoru (0.0-1.0)",
                },
            },
            "required": ["new_regime", "reason", "confidence"],
        },
    },
    {
        "name": "store_analysis",
        "description": (
            "LLM analizini research_memory'e kaydeder. "
            "Gelecekteki RAG sorgulamaları için hafızaya yazar. "
            "Her analiz sonunda çağrılmalıdır."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "BIST hisse kodu",
                },
                "thesis": {
                    "type": "string",
                    "description": "Analiz tezi (Türkçe, 200 karakter max)",
                },
                "direction": {
                    "type": "string",
                    "description": "LONG, SHORT veya NEUTRAL",
                },
                "confidence": {
                    "type": "number",
                    "description": "Güven skoru (0.0-1.0)",
                },
                "key_risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ana risk faktörleri listesi",
                },
            },
            "required": ["ticker", "thesis", "direction", "confidence"],
        },
    },
]


# ─── ARAÇ UYGULAMALARI ───────────────────────────────────────────────────────

class LLMToolExecutor:
    """
    LLM'in araç çağrılarını gerçek sistem singleton'larına yönlendirir.
    Herhangi bir bağımlılık yüklü değilse graceful fallback döner.
    """

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Araç çağrısını çalıştır ve sonucu döndür."""
        logger.info("LLM tool call", tool=tool_name, args=list(arguments.keys()))

        handlers = {
            "get_world_state":        self._get_world_state,
            "get_knowledge_graph":    self._get_knowledge_graph,
            "get_research_memory":    self._get_research_memory,
            "get_ticker_features":    self._get_ticker_features,
            "get_regime":             self._get_regime,
            "get_ensemble_forecast":  self._get_ensemble_forecast,
            "get_signal_conflicts":   self._get_signal_conflicts,
            "get_spec_score":         self._get_spec_score,
            "override_regime":        self._override_regime,
            "store_analysis":         self._store_analysis,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Bilinmeyen araç: {tool_name}"}

        try:
            return handler(**arguments)
        except Exception as exc:
            logger.error("Tool execution failed", tool=tool_name, error=str(exc))
            return {"error": str(exc), "tool": tool_name}

    # ── Araç 1: World State ──────────────────────────────────────────────────
    def _get_world_state(self) -> Dict[str, Any]:
        try:
            from services.intelligence.world_state import world_state_manager
            state = world_state_manager.get_state_dict()
            return {"status": "ok", "world_state": state}
        except Exception as exc:
            logger.warning("world_state_manager erişilemedi", error=str(exc))
            return {
                "status": "unavailable",
                "world_state": {},
                "error": str(exc),
            }

    # ── Araç 2: Knowledge Graph ──────────────────────────────────────────────
    def _get_knowledge_graph(self, entity_id: str) -> Dict[str, Any]:
        try:
            from services.intelligence.knowledge_graph import knowledge_graph
            relations = knowledge_graph.get_related_entities(entity_id)
            result = []
            for entity, relation in relations:
                result.append({
                    "entity": entity.name,
                    "entity_type": entity.entity_type,
                    "relation": relation.relation_type,
                    "strength": relation.strength,
                })
            return {"status": "ok", "entity_id": entity_id, "relations": result}
        except Exception as exc:
            logger.warning("knowledge_graph erişilemedi", error=str(exc))
            return {
                "status": "unavailable",
                "entity_id": entity_id,
                "relations": [],
                "error": str(exc),
            }

    # ── Araç 3: Research Memory (RAG) ────────────────────────────────────────
    def _get_research_memory(self, ticker: str, limit: int = 5) -> Dict[str, Any]:
        try:
            from services.intelligence.research_memory import research_memory
            history = research_memory.get_ticker_history(ticker, limit=limit)
            return {"status": "ok", "ticker": ticker, "history": history}
        except Exception as exc:
            logger.warning("research_memory erişilemedi", error=str(exc))
            return {
                "status": "unavailable",
                "ticker": ticker,
                "history": [],
                "error": str(exc),
            }

    # ── Araç 4: Ticker Features ──────────────────────────────────────────────
    def _get_ticker_features(self, ticker: str) -> Dict[str, Any]:
        return {
            "status": "available_in_context",
            "ticker": ticker,
            "note": "Feature verisi analiz bağlamında (context) mevcut.",
        }

    # ── Araç 5: Regime ───────────────────────────────────────────────────────
    def _get_regime(self) -> Dict[str, Any]:
        try:
            from services.intelligence.regime import regime_engine
            regime = regime_engine.get_regime()
            return {
                "status": "ok",
                "regime": regime.regime if hasattr(regime, "regime") else str(regime),
                "confidence": getattr(regime, "confidence", 0.7),
                "duration_days": getattr(regime, "duration_hours", 0) / 24.0 if hasattr(regime, "duration_hours") else 0,
            }
        except Exception as exc:
            logger.warning("regime_engine erişilemedi", error=str(exc))
            return {
                "status": "unavailable",
                "regime": None,
                "confidence": 0.0,
                "error": str(exc),
            }

    # ── Araç 6: Ensemble Forecast ────────────────────────────────────────────
    def _get_ensemble_forecast(self, ticker: str) -> Dict[str, Any]:
        try:
            from services.intelligence.ensemble_forecast import ensemble_forecaster
            result = ensemble_forecaster.get_latest(ticker)
            if result:
                return {
                    "status": "ok",
                    "ticker": ticker,
                    "expected_return_5d": getattr(result, "expected_return_5d", 0.0),
                    "expected_return_20d": getattr(result, "expected_return_20d", 0.0),
                    "model_agreement": getattr(result, "model_agreement", 0.5),
                    "ensemble_confidence": getattr(result, "ensemble_confidence", 0.5),
                }
        except Exception as exc:
            logger.warning("ensemble_forecaster erişilemedi", error=str(exc))
        return {
            "status": "unavailable",
            "ticker": ticker,
            "expected_return_5d": None,
            "expected_return_20d": None,
            "model_agreement": None,
            "ensemble_confidence": None,
        }

    # ── Araç 7: Signal Conflicts ─────────────────────────────────────────────
    def _get_signal_conflicts(self, ticker: str) -> Dict[str, Any]:
        return {
            "status": "available_in_context",
            "ticker": ticker,
            "note": "Sinyal çatışma raporu analiz bağlamında (context) mevcut.",
        }

    # ── Araç 8: SPEC Score ───────────────────────────────────────────────────
    def _get_spec_score(self, ticker: str) -> Dict[str, Any]:
        try:
            from services.intelligence.spec_engine import spec_engine
            result = spec_engine.get_latest(ticker)
            if result:
                return {
                    "status": "ok",
                    "ticker": ticker,
                    "spec_score": getattr(result, "spec_score", 50),
                    "category": getattr(result, "category", "WATCH"),
                    "evidence_count": len(getattr(result, "evidence_list", [])),
                }
        except Exception as exc:
            logger.warning("spec_engine erişilemedi", error=str(exc))
        return {
            "status": "unavailable",
            "ticker": ticker,
            "spec_score": None,
            "category": None,
            "evidence_count": 0,
        }

    # ── Araç 9: Override Regime ──────────────────────────────────────────────
    def _override_regime(
        self,
        new_regime: str,
        reason: str,
        confidence: float,
    ) -> Dict[str, Any]:
        """
        Kara Kuğu koruması: LLM piyasa rejimini acil günceller.
        Güvenlik: confidence < 0.80 ise redder.
        """
        if confidence < 0.80:
            logger.warning(
                "Regime override rejected — low confidence",
                confidence=confidence,
                attempted_regime=new_regime,
            )
            return {
                "status": "rejected",
                "reason": f"Güven skoru çok düşük: {confidence:.2f} < 0.80",
            }

        ALLOWED_REGIMES = {
            "CRISIS", "RISK_OFF", "HIGH_VOLATILITY",
            "RECOVERY", "BULL", "BEAR", "SIDEWAYS",
        }
        if new_regime not in ALLOWED_REGIMES:
            return {
                "status": "rejected",
                "reason": f"Geçersiz rejim: {new_regime}. İzin verilenler: {ALLOWED_REGIMES}",
            }

        try:
            from services.intelligence.regime import regime_engine
            regime_engine.override_regime(new_regime, reason=reason, confidence=confidence)
            logger.critical(
                "REGIME OVERRIDDEN BY LLM",
                new_regime=new_regime,
                reason=reason,
                confidence=confidence,
            )
            return {
                "status": "ok",
                "message": f"Rejim '{new_regime}' olarak güncellendi.",
                "reason": reason,
                "confidence": confidence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except (ImportError, AttributeError):
            logger.error("Regime override failed: regime_engine not available")
            return {
                "status": "error",
                "message": "Rejim motoru mevcut değil — override yapılamadı.",
                "reason": reason,
            }

    # ── Araç 10: Store Analysis ──────────────────────────────────────────────
    def _store_analysis(
        self,
        ticker: str,
        thesis: str,
        direction: str,
        confidence: float,
        key_risks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        try:
            from services.intelligence.research_memory import research_memory, ResearchRecord
            import uuid
            record = ResearchRecord(
                record_id=str(uuid.uuid4())[:8],
                ticker=ticker,
                date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                thesis=thesis[:200],
                evidence=[],
                risks=key_risks or [],
                prediction={"direction": direction, "confidence": confidence},
                confidence=confidence,
                model_version="llm_agent_v1",
            )
            research_memory.add_record(record)
            logger.info("LLM analysis stored", ticker=ticker, direction=direction)
            return {"status": "ok", "ticker": ticker, "stored": True}
        except Exception as exc:
            logger.warning("store_analysis başarısız", error=str(exc))
            return {"status": "error", "ticker": ticker, "stored": False, "error": str(exc)}


# Singleton
llm_tool_executor = LLMToolExecutor()
