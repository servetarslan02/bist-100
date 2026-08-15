"""
ALPHA BIST — API Server v1.0

REST API + Dashboard serving:
- GET /                    → Dashboard
- GET /api/universe        → BIST evreni
- GET /api/opportunities   → Fırsatlar
- GET /api/portfolio       → Portföy
- GET /api/risk            → Risk durumu
- GET /api/system/health   → Sağlık kontrolü
- GET /api/audit           → Audit log
- GET /api/config          → Konfigürasyon

Kullanım:
  python3 run_api.py
  python3 run_api.py --port 8000
"""

import asyncio
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

sys.path.insert(0, str(Path(__file__).parent))

import structlog
from services.core.logging import setup_logging

logger = structlog.get_logger()


class AlphaAPIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler — API + static files."""

    # Shared state (set by main)
    system = None

    def do_GET(self):
        """GET request handler."""
        path = self.path.split("?")[0]

        # API endpoints (frontend uyumlu)
        if path in ("/api/universe", "/api/market/instruments", "/api/market/state"):
            self._json_response(self._get_market_state())
        elif path in ("/api/opportunities", "/api/signals"):
            self._json_response(self._get_signals())
        elif path == "/api/portfolio":
            self._json_response(self._get_portfolio())
        elif path in ("/api/risk", "/api/world/state"):
            self._json_response(self._get_world_state())
        elif path in ("/api/system/health", "/api/status"):
            self._json_response(self._get_status())
        elif path == "/api/system/metrics":
            self._json_response(self._get_metrics())
        elif path == "/api/audit":
            self._json_response(self._get_audit())
        elif path == "/api/config":
            self._json_response(self._get_config())
        elif path == "/api/knowledge-graph":
            self._json_response(self._get_knowledge_graph())
        elif path == "/api/ranking":
            self._json_response(self._get_ranking())
        elif path == "/api/motors":
            self._json_response(self._get_motors())
        elif path == "/api/backtest":
            self._json_response(self._get_backtest())
        elif path == "/api/risk-enhanced":
            self._json_response(self._get_risk_enhanced())
        elif path == "/api/alerts":
            self._json_response(self._get_alerts())
        elif path == "/api/models":
            self._json_response(self._get_models())
        elif path == "/api/learning":
            self._json_response(self._get_learning())
        elif path == "/api/regime":
            self._json_response(self._get_regime())
        elif path == "/":
            self._serve_dashboard()
        else:
            self._serve_static(path)

    def _json_response(self, data: dict):
        """JSON response gönder."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _serve_dashboard(self):
        """Dashboard HTML serve et."""
        dashboard_path = Path(__file__).parent / "apps" / "web" / "dashboard.html"
        if dashboard_path.exists():
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(dashboard_path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Dashboard not found")

    def _serve_static(self, path):
        """Static dosya serve et."""
        static_path = Path(__file__).parent / "apps" / "web" / path.lstrip("/")
        if static_path.exists() and static_path.is_file():
            content_type = "text/html" if path.endswith(".html") else "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(static_path.read_bytes())
        else:
            self.send_response(404)
            self.end_headers()

    def _get_market_state(self) -> dict:
        """Market state + instruments."""
        try:
            from services.ingestion.bist_universe import bist_universe
            tickers = bist_universe.get_tickers()
            # Snapshot'tan son tarama bilgilerini al
            snapshot = {}
            if self.system and hasattr(self.system, '_snapshot_system'):
                latest = self.system._snapshot_system.get_latest()
                if latest:
                    snapshot = latest.get("state", {})
            return {
                "regime": snapshot.get("regime", "UNKNOWN"),
                "breadth_pct": snapshot.get("breadth", 50),
                "advancing": snapshot.get("advancing", 0),
                "declining": snapshot.get("declining", 0),
                "avg_rsi": 50,
                "avg_momentum": 0,
                "avg_volatility": 20,
                "anomaly_count": snapshot.get("anomalies", 0),
                "risk_appetite": 0.5,
                "instruments": [{"symbol": t, "name": t, "sector": "OTHER"} for t in tickers[:500]],
                "total": len(tickers),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"regime": "UNKNOWN", "instruments": [], "error": str(e)}

    def _get_signals(self) -> dict:
        """Sinyaller / fırsatlar."""
        try:
            if self.system and hasattr(self.system, '_last_opportunities'):
                opps = self.system._last_opportunities or []
                signals = [{
                    "ticker": o.get("ticker", ""),
                    "name": o.get("ticker", ""),
                    "score": o.get("score", 0),
                    "direction": o.get("direction", "NEUTRAL"),
                    "risk_level": "MEDIUM",
                    "horizon": "1-5D",
                    "expected_return_pct": o.get("score", 50) / 10,
                    "spec_category": o.get("signal", "NORMAL"),
                } for o in opps]
                return signals
            return []
        except Exception as e:
            return []

    def _get_world_state(self) -> dict:
        """World state + risk."""
        try:
            if self.system and hasattr(self.system, '_world_state'):
                state = self.system._world_state.get_state_dict()
                return {
                    "global_risk_appetite": state.get("global_risk_appetite", 0.5),
                    "usd_strength": state.get("usd_strength", 0.5),
                    "us_rate_pressure": state.get("us_rate_pressure", 0.5),
                    "commodity_pressure": state.get("commodity_pressure", 0.5),
                    "oil_pressure": state.get("oil_pressure", 0.5),
                    "turkey_macro_risk": state.get("turkey_macro_risk", 0.5),
                    "geopolitical_risk": state.get("geopolitical_risk", 0.5),
                    "em_risk_appetite": state.get("emerging_market_risk", 0.5),
                    "vix_level": state.get("vix_level", 15),
                    "inflation_pressure": 0.5,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            return {"global_risk_appetite": 0.5, "vix_level": 15}
        except Exception as e:
            return {"error": str(e)}

    def _get_status(self) -> dict:
        """Sistem durumu (frontend uyumlu)."""
        try:
            if self.system:
                health = self.system._health_checker.check_all()
                services = {}
                for name, comp in health.get("components", {}).items():
                    services[name] = comp.get("status", "unknown").lower()
                return {
                    "status": "ok" if health["overall"] == "HEALTHY" else "degraded",
                    "services": services,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            return {"status": "unknown", "services": {}}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _get_portfolio(self) -> dict:
        """Portföy durumu."""
        try:
            if self.system and hasattr(self.system, '_db'):
                import asyncio
                loop = asyncio.new_event_loop()
                portfolio = loop.run_until_complete(
                    self.system._db.pg_fetchrow("SELECT * FROM portfolios LIMIT 1")
                )
                loop.close()
                if portfolio:
                    return dict(portfolio)
            return {"error": "Portfolio not found"}
        except Exception as e:
            return {"error": str(e)}

    def _get_risk(self) -> dict:
        """Risk durumu."""
        try:
            if self.system:
                health = self.system._health_checker.check_all()
                return {
                    "risk_level": "LOW",
                    "health": health,
                    "config": {
                        "max_position_pct": self.system._config.get("risk.max_position_pct"),
                        "max_sector_pct": self.system._config.get("risk.max_sector_pct"),
                        "max_drawdown_pct": self.system._config.get("risk.max_drawdown_pct"),
                    },
                }
            return {"risk_level": "UNKNOWN"}
        except Exception as e:
            return {"error": str(e)}

    def _get_health(self) -> dict:
        """Sistem sağlık durumu."""
        try:
            if self.system:
                health = self.system._health_checker.check_all()
                state = self.system._system_state.get_health()
                return {
                    "overall": health["overall"],
                    "components": health["components"],
                    "state": state,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            return {"overall": "UNKNOWN"}
        except Exception as e:
            return {"error": str(e)}

    def _get_metrics(self) -> dict:
        """Metrikler."""
        try:
            if self.system:
                return self.system._prometheus.get_metrics()
            return {}
        except Exception as e:
            return {"error": str(e)}

    def _get_audit(self) -> dict:
        """Audit log."""
        try:
            if self.system:
                stats = self.system._audit_log.get_stats()
                recent = self.system._audit_log.get_recent(limit=50)
                return {"stats": stats, "recent": recent}
            return {"entries": []}
        except Exception as e:
            return {"error": str(e)}

    def _get_config(self) -> dict:
        """Konfigürasyon."""
        try:
            if self.system:
                return self.system._config.get_all()
            return {}
        except Exception as e:
            return {"error": str(e)}

    def _get_knowledge_graph(self) -> dict:
        """Knowledge graph."""
        try:
            if self.system:
                stats = self.system._knowledge_graph.get_stats()
                return stats
            return {}
        except Exception as e:
            return {"error": str(e)}

    def _get_alerts(self) -> dict:
        """Uyarılar."""
        try:
            if self.system and hasattr(self.system, '_notification_system'):
                notifications = self.system._notification_system.get_unread(limit=50)
                return [{
                    "id": n.get("id", ""),
                    "alert_type": n.get("category", ""),
                    "severity": n.get("severity", "INFO"),
                    "title": n.get("title", ""),
                    "message": n.get("message", ""),
                    "created_at": n.get("timestamp", ""),
                } for n in notifications]
            return []
        except Exception as e:
            return []

    def _get_models(self) -> dict:
        """Model registry."""
        try:
            # Statik model listesi (MLflow entegrasyonu sonrası dinamik olacak)
            return [{
                "id": 1,
                "name": "LightGBM Momentum",
                "description": "5 günlük momentum tahmini",
                "model_type": "lightgbm",
                "status": "active",
                "latest_version": "v1",
                "latest_status": "candidate",
                "metrics": {"accuracy": 0.52, "sharpe": 1.1},
            }, {
                "id": 2,
                "name": "Heuristic Rule-Based",
                "description": "Kural tabanlı fallback model",
                "model_type": "rule_based",
                "status": "active",
                "latest_version": "v1",
                "latest_status": "active",
                "metrics": {"accuracy": 0.50},
            }]
        except Exception as e:
            return []

    def _get_ranking(self) -> dict:
        """Ranking model durumu."""
        try:
            from services.ml.ranking_model import ranking_model
            return {
                "status": ranking_model.get_model_status(),
                "feature_importance": ranking_model.get_feature_importance(),
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_motors(self) -> dict:
        """7 motor durumu."""
        return {
            "motors": [
                {"name": "Relative Strength", "status": "active", "features": 11},
                {"name": "Momentum + Trend", "status": "active", "features": 6},
                {"name": "Volume + Microstructure", "status": "active", "features": 8},
                {"name": "Fundamental", "status": "active", "features": 4},
                {"name": "KAP + News", "status": "active", "features": 5},
                {"name": "Catalyst", "status": "active", "features": 5},
                {"name": "Why Falling", "status": "active", "features": 8},
            ],
            "total_features": 47,
        }

    def _get_backtest(self) -> dict:
        """Backtest durumu."""
        try:
            from services.backtest.enhanced_walk_forward import walk_forward_engine
            return {
                "engine": "walk_forward",
                "train_days": walk_forward_engine.train_days,
                "test_days": walk_forward_engine.test_days,
                "purge_days": walk_forward_engine.purge_days,
                "embargo_days": walk_forward_engine.embargo_days,
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_risk_enhanced(self) -> dict:
        """Gelişmiş risk durumu."""
        try:
            from services.risk.enhanced_risk import concentration_risk
            return {
                "ledoit_wolf": True,
                "volatility_targeting": True,
                "kelly_criterion": True,
                "rebalance_engine": True,
                "concentration_risk": True,
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_learning(self) -> dict:
        """Öğrenme durumu."""
        try:
            if self.system and hasattr(self.system, '_learning'):
                insights = self.system._learning.get_insights()
                pending = self.system._learning.get_pending_outcomes()
                return {
                    "insights": insights,
                    "pending_outcomes": len(pending),
                    "recent_predictions": self.system._learning.get_prediction_history(10),
                }
            return {"error": "Learning system not available"}
        except Exception as e:
            return {"error": str(e)}

    def _get_regime(self) -> dict:
        """Regime durumu."""
        try:
            if self.system and hasattr(self.system, '_regime_engine'):
                regime = self.system._regime_engine.current_regime
                if regime:
                    return {
                        "regime": regime.regime.value,
                        "confidence": regime.confidence,
                        "duration_hours": regime.duration_hours,
                    }
            return {"regime": "UNKNOWN"}
        except Exception as e:
            return {"error": str(e)}

    def log_message(self, format, *args):
        """HTTP loglarını suppress et."""
        pass


def run_api_server(port: int = 8000, system=None):
    """API sunucusunu başlat."""
    AlphaAPIHandler.system = system

    server = HTTPServer(("0.0.0.0", port), AlphaAPIHandler)
    logger.info("API server started", port=port)
    print(f"\n🌐 API: http://localhost:{port}")
    print(f"📊 Dashboard: http://localhost:{port}/")
    print(f"📈 Opportunities: http://localhost:{port}/api/opportunities")
    print(f"💼 Portfolio: http://localhost:{port}/api/portfolio")
    print(f"🔧 Health: http://localhost:{port}/api/system/health")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
