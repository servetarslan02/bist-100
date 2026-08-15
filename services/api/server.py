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

        # API endpoints
        if path == "/api/universe":
            self._json_response(self._get_universe())
        elif path == "/api/opportunities":
            self._json_response(self._get_opportunities())
        elif path == "/api/portfolio":
            self._json_response(self._get_portfolio())
        elif path == "/api/risk":
            self._json_response(self._get_risk())
        elif path == "/api/system/health":
            self._json_response(self._get_health())
        elif path == "/api/system/metrics":
            self._json_response(self._get_metrics())
        elif path == "/api/audit":
            self._json_response(self._get_audit())
        elif path == "/api/config":
            self._json_response(self._get_config())
        elif path == "/api/knowledge-graph":
            self._json_response(self._get_knowledge_graph())
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

    def _get_universe(self) -> dict:
        """BIST evreni."""
        try:
            from services.ingestion.bist_universe import bist_universe
            tickers = bist_universe.get_tickers()
            return {
                "tickers": tickers[:100],
                "total": len(tickers),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_opportunities(self) -> dict:
        """Fırsatlar."""
        try:
            if self.system and hasattr(self.system, '_last_opportunities'):
                return {
                    "opportunities": self.system._last_opportunities[:20],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            return {"opportunities": [], "message": "No scan yet"}
        except Exception as e:
            return {"error": str(e)}

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
