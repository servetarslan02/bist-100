"""
ALPHA BIST — Report Generator

Otomatik rapor oluşturma agent'ı.
BIST-30/50/100 multi-index destekli.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import structlog

logger = structlog.get_logger()
_TZ_ISTANBUL = timezone(timedelta(hours=3))


class ReportGenerator:
    """Otomatik rapor üretici — multi-index destekli."""

    def generate_daily_report(
        self,
        date: Optional[str] = None,
        market_summary: Optional[Dict[str, Any]] = None,
        signals: Optional[List[Dict[str, Any]]] = None,
        per_index: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Günlük rapor üret.

        Args:
            date: Rapor tarihi
            market_summary: Piyasa özeti
            signals: Üretilen sinyaller
            per_index: Endeks bazlı sinyal sayıları
        """
        target_date = date or datetime.now(_TZ_ISTANBUL).strftime("%Y-%m-%d")

        result = {
            "date": target_date,
            "timestamp": datetime.now(_TZ_ISTANBUL).isoformat(),
            "type": "daily",
        }

        md_lines = []
        md_lines.append(f"# 📊 ALPHA BIST Günlük Rapor — {target_date}")
        md_lines.append("")

        if market_summary:
            md_lines.append("## 📈 Piyasa Özeti")
            md_lines.append(f"- **BIST-100 Değişim:** %{market_summary.get('bist100_change_pct', 0):.2f}")
            md_lines.append(f"- **Piyasa Rejimi:** {market_summary.get('regime_tr', 'Bilinmiyor')}")
            md_lines.append(f"- **Tavsiye:** {market_summary.get('advice', '-')}")
            md_lines.append("")

        if per_index:
            md_lines.append("## 📊 Endeks Bazlı Sinyal Sayıları")
            for idx, count in per_index.items():
                md_lines.append(f"- **{idx.upper()}:** {count} sinyal")
            md_lines.append("")

        if signals:
            md_lines.append("## 🎯 En İyi Sinyaller")
            md_lines.append("| # | Hisse | Endeks | Skor |")
            md_lines.append("|---|-------|--------|------|")
            for i, sig in enumerate(signals[:10], 1):
                md_lines.append(f"| {i} | {sig.get('ticker', '?')} | {sig.get('source_index', '?')} | {sig.get('score', 0):.4f} |")
            md_lines.append("")

        md_lines.append("---")
        md_lines.append("*ALPHA BIST Quantitative Intelligence*")

        result["markdown"] = "\n".join(md_lines)
        return result

    def generate_model_report(self, model_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Model performans raporu."""
        result = {"timestamp": datetime.now(_TZ_ISTANBUL).isoformat(), "type": "model_performance"}
        md_lines = ["# 🧠 Model Performans Raporu", ""]

        if model_metrics:
            for model_name, metrics in model_metrics.get("individual_results", {}).items():
                md_lines.append(f"### {model_name.upper()}")
                md_lines.append(f"- R²: {metrics.get('r2', 0):.4f}")
                md_lines.append(f"- IC: {metrics.get('ic', 0):.4f}")
                md_lines.append("")

        result["markdown"] = "\n".join(md_lines)
        return result


report_generator = ReportGenerator()
