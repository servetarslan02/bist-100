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
from ..core.event_bus import (
    ensure_topics, AlphaEvent, EventType,
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

    async def _on_anomaly(self, event: AlphaEvent):
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
                ai_event = AlphaEvent(
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

    async def _on_signal(self, event: AlphaEvent):
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

    async def _on_kap_event(self, event: AlphaEvent):
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
        """Build context for LLM analysis."""
        context = {
            "ticker": ticker,
            "event_data": event_data,
            "timestamp": datetime.utcnow().isoformat(),
        }

        try:
            # Get features from Redis
            features = await redis_hgetall(f"features:{ticker}")
            if features:
                context["features"] = features

            # Get market state
            market_state = await redis_get("market_state")
            if market_state:
                context["market_state"] = market_state

            # Get recent signals
            signals = await pg_fetch("""
                SELECT * FROM signals
                WHERE instrument_id = (SELECT id FROM instruments WHERE symbol = $1)
                AND status = 'ACTIVE'
                ORDER BY created_at DESC LIMIT 5
            """, ticker)
            if signals:
                context["recent_signals"] = [dict(s) for s in signals]

        except Exception as e:
            logger.warning("Context building partial failure", error=str(e))

        return context

    async def _analyze_with_llm(self, prompt: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send analysis request to LLM (Ollama)."""
        try:
            # Build the full prompt
            system_prompt = """You are ALPHA, an advanced financial market intelligence AI.
Analyze the provided market data and provide:
1. Assessment (what's happening)
2. Reasoning (why it matters)
3. Confidence (0-100)
4. Risk factors
5. Actionable insight

Be concise, data-driven, and objective. Do not give financial advice."""

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
                return {
                    "analysis": result.get("response", ""),
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
