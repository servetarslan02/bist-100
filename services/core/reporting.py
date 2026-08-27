"""ALPHA BIST — Daily Report Generator."""

from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


def generate_daily_report(portfolio: dict, trades: list[dict], risk_metrics: dict) -> dict[str, Any]:
    """Günlük rapor oluştur."""
    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "portfolio_value": portfolio.get("equity", 0),
        "cash": portfolio.get("cash", 0),
        "positions": len(portfolio.get("positions", {})),
        "trades_today": len(trades),
        "daily_pnl": portfolio.get("daily_pnl", 0),
        "total_pnl": portfolio.get("total_pnl", 0),
        "drawdown": risk_metrics.get("drawdown", 0),
        "risk_level": risk_metrics.get("risk_level", "UNKNOWN"),
    }


def generate_report(report_type: str = "daily", **kwargs) -> dict[str, Any]:
    """Backward-compatible wrapper — queue.py bu metodu çağırır."""
    logger.info("Generating report", report_type=report_type)
    return generate_daily_report(
        portfolio=kwargs.get("portfolio", {}),
        trades=kwargs.get("trades", []),
        risk_metrics=kwargs.get("risk_metrics", {}),
    )
