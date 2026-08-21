"""ALPHA BIST — Model Performance Reporter v2.0

Otomatik performans ve öğrenme raporu üreticisi:
- Karşılaştırmalı model tablosu
- En başarılı ve en başarısız modeller
- Rejim bazlı liderlik matrisi
- Sinyal ağırlık dağılımı
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import structlog

from .model_performance_engine import PerformanceMetrics
from .model_trust_engine import ModelTrustScore

logger = structlog.get_logger()


class ModelPerformanceReporter:
    """Modeller için detaylı performans ve güvenilirlik raporları üretir."""

    @staticmethod
    def generate_markdown_report(
        metrics_list: List[PerformanceMetrics],
        trust_scores: List[ModelTrustScore],
        current_regime: str = "BULL_MOMENTUM",
    ) -> str:
        """Kapsamlı markdown formatında performans raporu üretir."""
        lines = [
            "# 📊 ALPHA BIST — Otonom Model Öğrenme ve Performans Raporu",
            f"*Rapor Tarihi: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC | Aktif Piyasa Rejimi: **{current_regime}***\n",
            "## 1. Model Karşılaştırma ve Güvenilirlik Matrisi",
            "",
            "| Model | Versiyon | Örneklem | Yön Doğruluğu | Net Getiri | Net PnL | Sharpe | Max DD | Brier | Güven Skoru | Sinyal Ağırlığı |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]

        trust_map = {ts.model_id: ts for ts in trust_scores}

        sorted_metrics = sorted(
            metrics_list,
            key=lambda m: trust_map.get(m.model_id, None).reliability_score if m.model_id in trust_map else m.direction_accuracy,
            reverse=True
        )

        for m in sorted_metrics:
            ts = trust_map.get(m.model_id)
            rel_score = f"{ts.reliability_score:.3f}" if ts else "N/A"
            weight = f"%{ts.recommended_fusion_weight * 100:.1f}" if ts else "N/A"
            pnl_str = f"₺{m.net_pnl:+,.2f}"
            ret_str = f"%{m.mean_return_pct:+.2f}"

            lines.append(
                f"| **{m.model_id}** | `{m.model_version}` | {m.evaluated_samples} | "
                f"%{m.hit_rate_pct:.1f} | {ret_str} | {pnl_str} | "
                f"{m.annualized_sharpe:.2f} | %{m.max_drawdown_pct:.1f} | "
                f"{m.brier_score:.3f} | **{rel_score}** | **{weight}** |"
            )

        lines.append("")

        # 2. Lider ve Zayıf Modeller
        if sorted_metrics:
            best_model = sorted_metrics[0]
            worst_model = sorted_metrics[-1]
            lines.extend([
                "## 2. Model Liderlik ve Teşhis Özeti",
                f"- 🏆 **En Güvenilir Model:** `{best_model.model_id}` (Doğruluk: %{best_model.hit_rate_pct:.1f}, Sharpe: {best_model.annualized_sharpe:.2f}, Net PnL: ₺{best_model.net_pnl:,.2f})",
                f"- ⚠️ **Geliştirilmesi Gereken Model:** `{worst_model.model_id}` (Doğruluk: %{worst_model.hit_rate_pct:.1f}, Brier: {worst_model.brier_score:.3f})",
                "",
            ])

        # 3. Rejim Bazlı Başarı Dağılımı
        lines.extend([
            "## 3. Piyasa Rejimine Göre Model Uzmanlıkları",
            "",
            "| Rejim | En Başarılı Model | Rejim Doğruluğu | Ortalama Net Getiri |",
            "|---|---|---|---|",
        ])

        regimes = ["BULL_MOMENTUM", "BEAR_CORRECTION", "RANGE_BOUND", "HIGH_VOLATILITY"]
        for reg in regimes:
            best_reg_model = None
            best_reg_acc = -1.0
            best_reg_ret = 0.0

            for m in metrics_list:
                r_stat = m.regime_breakdown.get(reg, {})
                if r_stat and r_stat.get("accuracy", 0) > best_reg_acc:
                    best_reg_acc = r_stat.get("accuracy", 0)
                    best_reg_ret = r_stat.get("mean_net_return_pct", 0)
                    best_reg_model = m.model_id

            if best_reg_model:
                lines.append(f"| **{reg}** | `{best_reg_model}` | %{best_reg_acc * 100:.1f} | %{best_reg_ret:+.2f} |")
            else:
                lines.append(f"| **{reg}** | `Ensemble_Default` | %50.0 | %0.00 |")

        lines.extend([
            "",
            "---",
            "*Bu rapor ALPHA BIST Autonomous MLOps Engine tarafından otomatik üretilmiştir. Veriler BIST işlem maliyetleri düşülerek hesaplanmıştır.*"
        ])

        return "\n".join(lines)
