"""
ALPHA BIST — Report Generator

Otomatik rapor oluşturma agent'ı.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class ReportGenerator:
    """Otomatik rapor üretici."""

    def generate_daily_report(self, date: str | None = None,
                              market_summary: dict[str, Any] | None = None,
                              signals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Günlük rapor üret."""
        target_date = date or datetime.now(_TZ_ISTANBUL).strftime("%Y-%m-%d")
        result = {"date": target_date, "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(), "type": "daily"}

        md_lines = [f"# 📊 ALPHA BIST Günlük Rapor — {target_date}", ""]

        if market_summary:
            md_lines.append("## 📈 Piyasa Özeti")
            md_lines.append(f"- **BIST-100 Değişim:** %{market_summary.get('bist100_change_pct', 0):.2f}")
            md_lines.append(f"- **Piyasa Rejimi:** {market_summary.get('regime_tr', 'Bilinmiyor')}")
            md_lines.append(f"- **Tavsiye:** {market_summary.get('advice', '-')}")
            md_lines.append("")

        if signals:
            md_lines.append("## 🎯 En İyi Sinyaller")
            md_lines.append("| # | Hisse | Skor |")
            md_lines.append("|---|-------|------|")
            for i, sig in enumerate(signals[:10], 1):
                md_lines.append(f"| {i} | {sig.get('ticker', '?')} | {sig.get('score', 0):.4f} |")
            md_lines.append("")

        md_lines.append("---")
        md_lines.append("*ALPHA BIST Quantitative Intelligence*")

        result["markdown"] = "\n".join(md_lines)
        return result


report_generator = ReportGenerator()
