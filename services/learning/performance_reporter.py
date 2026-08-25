"""ALPHA BIST — Model Performance Reporter v2.5

Genişletilmiş çoklu pencere ve 5-rejimli MLOps analiz raporlayıcısı:
- Son 250, Son 500 ve Son 1000+ tahmin karşılaştırması
- 5 Piyasa Rejiminde Liderlik Matrisi (Boğa, Ayı, Yatay, Yüksek Volatilite, Düşük Volatilite)
- İstatistiki Güvenilirlik ve Sharpe yakınsaması
- Dinamik Adaptif Sinyal Ağırlıkları
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone
import structlog

from .model_performance_engine import PerformanceMetrics
from .model_trust_engine import ModelTrustScore

logger = structlog.get_logger()


class ModelPerformanceReporter:
    """Modeller için detaylı performans, çoklu pencere ve rejim raporları üretir."""

    @staticmethod
    def generate_markdown_report(
        metrics_list: List[PerformanceMetrics],
        trust_scores: List[ModelTrustScore],
        current_regime: str = "BULL_TREND",
        window_comparison: Optional[Dict[str, List[PerformanceMetrics]]] = None,
    ) -> str:
        """Kapsamlı markdown formatında performans raporu üretir."""
        lines = [
            "# 📊 ALPHA BIST — Kurumsal Model Öğrenme ve İstatistiki Performans Raporu",
            f"*Rapor Tarihi: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC | Aktif Piyasa Rejimi: **{current_regime}***\n",
            "## 1. Genel Model Karşılaştırma ve Güvenilirlik Matrisi (Tüm Örneklem)",
            "",
            "| Model | Versiyon | Örneklem ($N$) | Yön Doğruluğu | Ort. Net Getiri | Net PnL (TL) | Sharpe | Max DD | Brier Skoru | Güven Skoru ($S_{rel}$) | Sinyal Ağırlığı |",
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

        # 2. Çoklu Pencere Karşılaştırması (Son 250 vs 500 vs 1000+)
        if window_comparison:
            lines.extend([
                "## 2. Zaman Penceresi Karşılaştırması (Son 250 vs 500 vs 1000+ Tahmin)",
                "",
                "| Model | Son 250 Doğruluk / Sharpe | Son 500 Doğruluk / Sharpe | 1000+ Doğruluk / Sharpe | İstikrar & Trend |",
                "|---|---|---|---|---|",
            ])

            w250 = {m.model_id: m for m in window_comparison.get("250", [])}
            w500 = {m.model_id: m for m in window_comparison.get("500", [])}
            wall = {m.model_id: m for m in window_comparison.get("all", sorted_metrics)}

            for m_id in [m.model_id for m in sorted_metrics]:
                m250 = w250.get(m_id)
                m500 = w500.get(m_id)
                mall = wall.get(m_id)

                str_250 = f"%{m250.hit_rate_pct:.1f} / {m250.annualized_sharpe:.2f}" if m250 else "N/A"
                str_500 = f"%{m500.hit_rate_pct:.1f} / {m500.annualized_sharpe:.2f}" if m500 else "N/A"
                str_all = f"%{mall.hit_rate_pct:.1f} / {mall.annualized_sharpe:.2f}" if mall else "N/A"

                trend = "🟢 Gelişiyor" if (m250 and mall and m250.hit_rate_pct >= mall.hit_rate_pct) else "🟡 Stabil"

                lines.append(f"| **{m_id}** | {str_250} | {str_500} | {str_all} | {trend} |")

            lines.append("")

        # 3. 5 Piyasa Rejimine Göre Model Liderlikleri
        lines.extend([
            "## 3. 5 Piyasa Rejimine Göre Model Uzmanlıkları",
            "",
            "| Piyasa Rejimi | En Başarılı Model | Rejim Doğruluğu | Ort. Net Getiri | İkinci Model |",
            "|---|---|---|---|---|",
        ])

        regimes_info = [
            ("BULL_TREND", "Boğa Piyasası (Güçlü Yükseliş Trendi)"),
            ("BEAR_MARKET", "Ayı Piyasası (Düşüş & Sert Düzeltme)"),
            ("SIDEWAYS_RANGE", "Yatay Piyasa (Testere & Range-Bound)"),
            ("HIGH_VOLATILITY", "Yüksek Volatilite (Panik / Haber Şoku)"),
            ("LOW_VOLATILITY", "Düşük Volatilite (Sıkışma & Konsolidasyon)"),
        ]

        for reg_code, reg_desc in regimes_info:
            scored_models = []
            for m in metrics_list:
                r_stat = m.regime_breakdown.get(reg_code, {})
                if r_stat and r_stat.get("samples", 0) >= 5:
                    scored_models.append({
                        "model": m.model_id,
                        "accuracy": r_stat.get("accuracy", 0.0),
                        "ret": r_stat.get("mean_net_return_pct", 0.0),
                    })

            scored_models.sort(key=lambda x: x["accuracy"], reverse=True)

            if len(scored_models) >= 2:
                best = scored_models[0]
                second = scored_models[1]
                lines.append(
                    f"| **{reg_desc}** | 🏆 `{best['model']}` | %{best['accuracy'] * 100:.1f} | %{best['ret']:+.2f} | `{second['model']}` (%{second['accuracy']*100:.1f}) |"
                )
            elif len(scored_models) == 1:
                best = scored_models[0]
                lines.append(
                    f"| **{reg_desc}** | 🏆 `{best['model']}` | %{best['accuracy'] * 100:.1f} | %{best['ret']:+.2f} | - |"
                )
            else:
                lines.append(
                    f"| **{reg_desc}** | `Ensemble_Default` | %50.0 | %+0.00 | - |"
                )

        lines.extend([
            "",
            "## 4. İstatistiki Teşhis ve Güvenilirlik Çıkarımları",
            f"- 📌 **Gözlem Sayısı ($N$):** Modeller {sum(m.evaluated_samples for m in metrics_list)} toplam tahmin üzerinden değerlendirildi.",
            "- 🛡️ **BIST Komisyon Koruması:** Tüm net getiriler BIST Pay Piyasası Takas Payı (%0.0056), MKK (%0.00109), Aracı Kurum (%0.03) ve BSMV (%5) kesilerek hesaplandı.",
            "- ⚖️ **Ağırlık Dağılımı:** Hiçbir model tek başına baskın olamaz (%35 tavan, %5 taban koruması devrede).",
            "",
            "---",
            "*Bu rapor ALPHA BIST Autonomous MLOps Engine tarafından otomatik üretilmiştir.*"
        ])

        return "\n".join(lines)
