"""ALPHA BIST - Intelligence Service (AI/LLM Integration)"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import httpx
import structlog

from ..core.config import settings
from ..core.database import (
    init_databases, close_databases, pg_fetch, pg_fetchrow,
    redis_get, redis_set, redis_hgetall,
)
from ..core.event_schema import CanonicalEvent
from ..core.event_bus import (
    ensure_topics, EventType,
    EventConsumer, publish_event,
)
from ..core.logging import setup_logging
from .spec_engine import spec_engine, SPECConfig
from .impact_engine import impact_engine
from .world_state import world_state_manager

logger = structlog.get_logger()


class IntelligenceService:
    """AI/LLM integration for deep analysis and reasoning."""

    def __init__(self):
        self._running = False
        self._consumer: EventConsumer = None
        self._http_client: httpx.AsyncClient = None

    async def start(self):
        """Start the intelligence service."""
        setup_logging()
        logger.info("Starting Intelligence Service")

        await init_databases()
        ensure_topics()

        self._http_client = httpx.AsyncClient(timeout=120.0)
        self._running = True

        # Set up event consumer
        self._consumer = EventConsumer(
            group_id="intelligence",
            topics=["anomaly.detected", "signal.generated", "kap.event"],
            auto_offset_reset="latest",
        )
        self._consumer.on(EventType.ANOMALY_DETECTED, self._on_anomaly)
        self._consumer.on(EventType.SIGNAL_GENERATED, self._on_signal)
        self._consumer.on(EventType.KAP_EVENT, self._on_kap_event)

        logger.info("Intelligence Service started")
        await self._consumer.consume_loop()

    async def stop(self):
        """Stop the intelligence service."""
        self._running = False
        if self._consumer:
            self._consumer.stop()
        if self._http_client:
            await self._http_client.aclose()
        await close_databases()
        logger.info("Intelligence Service stopped")

    async def _on_anomaly(self, event: CanonicalEvent):
        """Handle anomaly events with AI analysis."""
        try:
            ticker = event.data.get("ticker")
            anomaly_type = event.data.get("anomaly_type")
            score = event.data.get("score", 0)

            if score < 0.7:
                return

            logger.info("Analyzing anomaly", ticker=ticker, type=anomaly_type, score=score)

            # Build context for LLM
            context = await self._build_context(ticker, event.data)

            # Ask LLM to analyze
            analysis = await self._analyze_with_llm(
                prompt=f"Analyze this market anomaly for {ticker}:",
                context=context,
            )

            if analysis:
                # Store analysis
                await redis_set(f"ai_analysis:{ticker}", json.dumps(analysis), ex=3600)

                # Publish AI analysis event
                ai_event = CanonicalEvent(
                    event_type=EventType.SIGNAL_GENERATED,
                    source="intelligence",
                    data={
                        "ticker": ticker,
                        "analysis": analysis,
                        "anomaly_type": anomaly_type,
                        "anomaly_score": score,
                    },
                )
                publish_event(ai_event, key=ticker)

        except Exception as e:
            logger.error("Anomaly analysis error", error=str(e))

    async def _on_signal(self, event: CanonicalEvent):
        """Handle signal events with AI reasoning."""
        try:
            ticker = event.data.get("ticker")
            signal_type = event.data.get("signal_type")
            score = event.data.get("score", 0)

            if score < 70:
                return

            logger.info("Analyzing signal", ticker=ticker, type=signal_type, score=score)

            # Build context
            context = await self._build_context(ticker, event.data)

            # Ask LLM for reasoning
            reasoning = await self._analyze_with_llm(
                prompt=f"Provide detailed reasoning for this trading signal on {ticker}:",
                context=context,
            )

            if reasoning:
                await redis_set(f"ai_reasoning:{ticker}", json.dumps(reasoning), ex=3600)

        except Exception as e:
            logger.error("Signal analysis error", error=str(e))

    async def _on_kap_event(self, event: CanonicalEvent):
        """Handle KAP events with AI interpretation."""
        try:
            ticker = event.data.get("ticker")
            title = event.data.get("title", "")
            summary = event.data.get("summary", "")

            if not ticker:
                return

            logger.info("Analyzing KAP event", ticker=ticker, title=title[:50])

            # Build context
            context = {
                "ticker": ticker,
                "kap_title": title,
                "kap_summary": summary,
                "sentiment": event.data.get("sentiment", 0),
                "importance": event.data.get("importance", 0),
                "is_price_sensitive": event.data.get("is_price_sensitive", False),
            }

            # Ask LLM to interpret
            interpretation = await self._analyze_with_llm(
                prompt=f"Interpret this KAP (Public Disclosure Platform) announcement for {ticker} and assess its market impact:",
                context=context,
            )

            if interpretation:
                await redis_set(f"ai_kap_analysis:{ticker}", json.dumps(interpretation), ex=3600)

        except Exception as e:
            logger.error("KAP analysis error", error=str(e))

    async def _build_context(self, ticker: str, event_data: Dict) -> Dict[str, Any]:
        """Build enriched context for LLM analysis.
        
        v1.1: Knowledge graph, historical analogues, prediction history,
        model uncertainty, scenario results, counterfactuals,
        news cluster, event propagation, portfolio exposure eklenendi.
        """
        context = {
            "ticker": ticker,
            "event_data": event_data,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            # 1. Features from Redis
            features = await redis_hgetall(f"features:{ticker}")
            if features:
                context["features"] = features

            # 2. Market state
            market_state = await redis_get("market_state")
            if market_state:
                context["market_state"] = market_state

            # 3. World state
            world_state = await redis_get("world_state")
            if world_state:
                context["world_state"] = world_state

            # 4. Recent signals
            signals = await pg_fetch("""
                SELECT signal_type, direction, score, confidence, risk_level,
                       horizon, expected_return_pct, created_at
                FROM signals
                WHERE instrument_id = (SELECT id FROM instruments WHERE symbol = $1)
                AND status = 'ACTIVE'
                ORDER BY created_at DESC LIMIT 5
            """, ticker)
            if signals:
                context["recent_signals"] = [dict(s) for s in signals]

            # 5. Prediction history
            predictions = await pg_fetch("""
                SELECT mp.predicted_direction, mp.predicted_return_pct,
                       mp.probability_positive, mo.actual_return_pct, mo.is_correct
                FROM model_predictions mp
                LEFT JOIN model_outcomes mo ON mo.prediction_id = mp.id
                WHERE mp.instrument_id = (SELECT id FROM instruments WHERE symbol = $1)
                ORDER BY mp.created_at DESC LIMIT 10
            """, ticker)
            if predictions:
                context["prediction_history"] = [dict(p) for p in predictions]

            # 6. Historical analogues (benzer durumlar)
            analogues = await redis_get(f"analogues:{ticker}")
            if analogues:
                context["historical_analogues"] = analogues

            # 7. Model uncertainty
            model_info = await redis_get(f"model_confidence:{ticker}")
            if model_info:
                context["model_uncertainty"] = model_info

            # 8. Portfolio exposure
            portfolio = await pg_fetch("""
                SELECT p.quantity, p.avg_cost, p.current_price, p.weight_pct
                FROM positions p
                JOIN instruments i ON p.instrument_id = i.id
                WHERE i.symbol = $1 AND p.status = 'OPEN'
            """, ticker)
            if portfolio:
                context["portfolio_exposure"] = [dict(p) for p in portfolio]

            # 9. Knowledge graph relations
            kg_relations = await pg_fetch("""
                SELECT kr.relation_type, kr.strength, ke.name as related_entity
                FROM knowledge_relations kr
                JOIN knowledge_entities ke ON ke.id = kr.target_entity_id
                WHERE kr.source_entity_id = (
                    SELECT id FROM knowledge_entities WHERE name = $1 LIMIT 1
                )
                ORDER BY kr.strength DESC LIMIT 10
            """, ticker)
            if kg_relations:
                context["knowledge_graph"] = [dict(r) for r in kg_relations]

            # 10. Event propagation impact
            impact = await redis_get(f"impact:{ticker}")
            if impact:
                context["event_propagation"] = impact

        except Exception as e:
            logger.warning("Context building partial failure", error=str(e))

        return context

    async def _analyze_with_llm(self, prompt: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send analysis request to LLM (Ollama)."""
        try:
            # Build the full prompt
            system_prompt = """You are ALPHA, an advanced financial market intelligence AI.
Analyze the provided market data and return a JSON object with these fields:
- assessment: what is happening (string)
- reasoning: why it matters (string)
- direction: LONG | SHORT | NEUTRAL
- confidence: 0-100 (integer)
- risk_factors: list of risk factor strings
- invalidation: what would invalidate this thesis (string)
- horizon: SHORT (1-5d) | MEDIUM (1-4w) | LONG (1-6m)
- evidence_strength: WEAK | MODERATE | STRONG

Return ONLY valid JSON, no other text. Do not give financial advice."""

            user_prompt = f"{prompt}\n\nContext:\n{json.dumps(context, indent=2, default=str)}"

            # Call Ollama API
            response = await self._http_client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 1024,
                    },
                },
            )

            if response.status_code == 200:
                result = response.json()
                raw_response = result.get("response", "")
                
                # Try to parse structured JSON from LLM
                parsed = None
                try:
                    # Find JSON in response
                    import re
                    json_match = re.search(r'\{[^{}]*\}', raw_response, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group())
                except (json.JSONDecodeError, Exception):
                    pass
                
                return {
                    "analysis": raw_response,
                    "structured": parsed,
                    "model": settings.ollama_model,
                    "timestamp": datetime.utcnow().isoformat(),
                    "eval_count": result.get("eval_count", 0),
                    "eval_duration_ms": result.get("eval_duration", 0) / 1000000,
                }
            else:
                logger.warning("LLM request failed", status=response.status_code)
                return None

        except Exception as e:
            logger.error("LLM analysis error", error=str(e))
            return None


# =====================================================
# Entry Point
# =====================================================

async def main():
    """Main entry point for the intelligence service."""
    service = IntelligenceService()
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()
    except Exception as e:
        logger.error("Intelligence Service crashed", error=str(e))
        await service.stop()
        raise


if __name__ == "__main__":
    asyncio.run(main())
