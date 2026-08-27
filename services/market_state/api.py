"""ALPHA BIST — Market State API Endpoints v2.0

REST API endpoint'leri:
- GET /api/market/state      — Tam market state
- GET /api/market/breadth    — Breadth detayları
- GET /api/market/regime     — Ensemble regime + probabilities
- GET /api/market/transition — Transition history + stats
- GET /api/market/multi-tf   — Multi-timeframe states
- GET /api/market/alerts     — Aktif alert'ler
- GET /api/market/health     — Sağlık durumu
"""

from datetime import UTC, datetime

import structlog

logger = structlog.get_logger()


def register_market_state_routes(app, market_state_service):
    """FastAPI app'e market state route'larını ekle.

    Args:
        app: FastAPI instance
        market_state_service: MarketStateService instance
    """

    @app.get("/api/market/state")
    async def get_market_state():
        """Tam market state — tüm bileşenler birleşik."""
        try:
            state = market_state_service.get_current_state()
            if state is None:
                return {"error": "Market state not available", "status": "initializing"}
            return state.to_dict() if hasattr(state, "to_dict") else state
        except Exception as e:
            logger.error("api_market_state_failed", error=str(e))
            return {"error": str(e)}

    @app.get("/api/market/breadth")
    async def get_breadth():
        """Market breadth detayları — 7 gösterge."""
        try:
            breadth = market_state_service.get_breadth()
            if breadth is None:
                return {"error": "Breadth not available"}
            return breadth.to_dict() if hasattr(breadth, "to_dict") else breadth
        except Exception as e:
            logger.error("api_breadth_failed", error=str(e))
            return {"error": str(e)}

    @app.get("/api/market/regime")
    async def get_regime():
        """Ensemble regime — 3 yöntem, probabilities, consensus."""
        try:
            regime = market_state_service.get_ensemble_regime()
            if regime is None:
                return {"error": "Regime not available"}
            return regime.to_dict() if hasattr(regime, "to_dict") else regime
        except Exception as e:
            logger.error("api_regime_failed", error=str(e))
            return {"error": str(e)}

    @app.get("/api/market/transition")
    async def get_transition():
        """Transition history + stats — geçiş matrisi, kararlılık."""
        try:
            tracker = market_state_service.get_transition_tracker()
            if tracker is None:
                return {"error": "Transition tracker not available"}

            stats = tracker.get_stats()
            recent = tracker.get_recent_transitions(limit=20)
            alerts = tracker.check_alerts()

            return {
                "stats": stats.to_dict() if hasattr(stats, "to_dict") else stats,
                "recent_transitions": recent,
                "alerts": alerts,
            }
        except Exception as e:
            logger.error("api_transition_failed", error=str(e))
            return {"error": str(e)}

    @app.get("/api/market/multi-tf")
    async def get_multi_timeframe():
        """Multi-timeframe states — intraday, daily, weekly, monthly."""
        try:
            multi_tf = market_state_service.get_multi_timeframe()
            if multi_tf is None:
                return {"error": "Multi-timeframe not available"}
            return multi_tf.to_dict() if hasattr(multi_tf, "to_dict") else multi_tf
        except Exception as e:
            logger.error("api_multi_tf_failed", error=str(e))
            return {"error": str(e)}

    @app.get("/api/market/alerts")
    async def get_alerts():
        """Aktif alert'ler — rejim değişimi, kararlılık, breadth aşırı."""
        try:
            alerts = []

            # Transition alerts
            tracker = market_state_service.get_transition_tracker()
            if tracker:
                alerts.extend(tracker.check_alerts())

            # Breadth alerts
            breadth = market_state_service.get_breadth()
            if breadth and hasattr(breadth, "alert_level") and breadth.alert_level != "NORMAL":
                alerts.append(
                    {
                        "type": "BREADTH_ALERT",
                        "severity": breadth.alert_level,
                        "message": f"Breadth seviyesi: {breadth.breadth_state} (pct: {breadth.pct_advancing:.1f}%)",
                        "breadth_state": breadth.breadth_state,
                        "pct_advancing": breadth.pct_advancing,
                    }
                )

            return {
                "alerts": alerts,
                "count": len(alerts),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.error("api_alerts_failed", error=str(e))
            return {"error": str(e)}

    @app.get("/api/market/health")
    async def get_health():
        """Market state sağlık durumu."""
        try:
            state = market_state_service.get_current_state()
            tracker = market_state_service.get_transition_tracker()
            breadth = market_state_service.get_breadth()

            health = {
                "status": "ok",
                "components": {
                    "market_state": "ok" if state else "unavailable",
                    "breadth": "ok" if breadth else "unavailable",
                    "transition_tracker": "ok" if tracker else "unavailable",
                },
                "last_update": None,
                "regime": None,
                "stability": None,
            }

            if state:
                if hasattr(state, "regime"):
                    health["regime"] = state.regime
                elif isinstance(state, dict):
                    health["regime"] = state.get("regime")

            if tracker:
                stats = tracker.get_stats()
                health["stability"] = stats.stability_score if hasattr(stats, "stability_score") else None
                health["total_transitions"] = stats.total_transitions if hasattr(stats, "total_transitions") else 0

            return health
        except Exception as e:
            logger.error("api_health_failed", error=str(e))
            return {"status": "error", "error": str(e)}

    logger.info("market_state_api_routes_registered")
