"""ALPHA BIST — Daily Report Generator."""
from typing import Dict, Any, List
from datetime import datetime
import structlog
logger = structlog.get_logger()

def generate_daily_report(portfolio: Dict, trades: List[Dict], risk_metrics: Dict) -> Dict[str, Any]:
    """Günlük rapor oluştur."""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "portfolio_value": portfolio.get("equity", 0),
        "cash": portfolio.get("cash", 0),
        "positions": len(portfolio.get("positions", {})),
        "trades_today": len(trades),
        "daily_pnl": portfolio.get("daily_pnl", 0),
        "total_pnl": portfolio.get("total_pnl", 0),
        "drawdown": risk_metrics.get("drawdown", 0),
        "risk_level": risk_metrics.get("risk_level", "UNKNOWN"),
    }
