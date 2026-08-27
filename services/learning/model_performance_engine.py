"""ALPHA BIST — Model Performance Engine v2.0

Kapsamlı model performans takip ve metrik hesaplama motoru:
- Directional Accuracy & Hit Rate
- Net PnL (BIST Takas + MKK + Aracı Kurum + BSMV komisyonları düşülmüş)
- Risk-Adjusted: Yıllıklandırılmış Sharpe Oranı & Max Drawdown
- Kalibrasyon: Brier Skoru & Log-Loss
- Sıralama Korelasyonu: Information Coefficient (IC) & Rank IC (Spearman)
- Rejim Bazlı Performans Ayrıştırması (BULL, BEAR, RANGE, VOLATILE)
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Yasal BIST işlem maliyet oranları
BIST_FEE_RATE = 0.000056  # %0.0056 BIST Pay Piyasası Takas Payı
MKK_FEE_RATE = 0.0000109  # %0.00109 MKK Saklama
BROKER_COMMISSION = 0.0003  # %0.03 Aracı Kurum Komisyonu
BSMV_TAX_RATE = 0.05  # %5 BSMV (Komisyon üzerinden)
ROUNDTRIP_COST_PCT = 2 * (BIST_FEE_RATE + MKK_FEE_RATE + BROKER_COMMISSION * (1 + BSMV_TAX_RATE)) * 100
# Yaklaşık %0.074 roundtrip işlem maliyeti


@dataclass
class PerformanceMetrics:
    """Tek model veya versiyon için hesaplanan detaylı metrikler."""

    model_id: str
    model_version: str
    total_samples: int
    evaluated_samples: int
    direction_accuracy: float
    hit_rate_pct: float
    precision: float
    recall: float
    f1_score: float
    mean_return_pct: float
    cumulative_return_pct: float
    gross_pnl: float
    transaction_costs: float
    net_pnl: float
    annualized_sharpe: float
    max_drawdown_pct: float
    brier_score: float
    information_coefficient: float
    rank_ic: float
    win_loss_ratio: float
    regime_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    horizon_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ModelPerformanceEngine:
    """Tahmin ve gerçekleşen sonuçları eşleştirerek performans metriklerini hesaplar."""

    @staticmethod
    def calculate_metrics(
        model_id: str,
        model_version: str,
        predictions_with_outcomes: list[dict[str, Any]],
        risk_free_rate_annual: float = 0.40,  # TCMB referans faiz oranı
    ) -> PerformanceMetrics:
        """Gerçekleşmiş sonuçlar üzerinden tüm performans metriklerini hesaplar."""
        total_samples = len(predictions_with_outcomes)
        if total_samples == 0:
            return PerformanceMetrics(
                model_id=model_id,
                model_version=model_version,
                total_samples=0,
                evaluated_samples=0,
                direction_accuracy=0.5,
                hit_rate_pct=50.0,
                precision=0.5,
                recall=0.5,
                f1_score=0.5,
                mean_return_pct=0.0,
                cumulative_return_pct=0.0,
                gross_pnl=0.0,
                transaction_costs=0.0,
                net_pnl=0.0,
                annualized_sharpe=0.0,
                max_drawdown_pct=0.0,
                brier_score=0.25,
                information_coefficient=0.0,
                rank_ic=0.0,
                win_loss_ratio=1.0,
            )

        correct_dirs = 0
        returns = []
        net_returns = []
        gross_pnls = []
        costs = []
        brier_errors = []
        pred_scores = []
        actual_returns = []

        tp = fp = tn = fn = 0
        regime_data: dict[str, list[dict]] = {}
        horizon_data: dict[str, list[dict]] = {}

        for p in predictions_with_outcomes:
            pred_dir = (p.get("predicted_direction") or "UP").upper()
            act_dir = (p.get("actual_direction") or ("UP" if (p.get("actual_return", 0) > 0) else "DOWN")).upper()
            confidence = float(p.get("confidence", 0.5))
            act_ret = float(p.get("actual_return", 0.0))
            pos_size = float(p.get("position_value", 10000.0))
            regime = p.get("market_regime", "UNKNOWN")
            horizon = p.get("prediction_horizon", "1-5D")

            # 1. Yön Doğruluğu & Confusion Matrix
            is_correct = pred_dir == act_dir
            if is_correct:
                correct_dirs += 1

            if pred_dir == "UP" and act_dir == "UP":
                tp += 1
            elif pred_dir == "UP" and act_dir == "DOWN":
                fp += 1
            elif pred_dir == "DOWN" and act_dir == "DOWN":
                tn += 1
            elif pred_dir == "DOWN" and act_dir == "UP":
                fn += 1

            # 2. Getiri ve Maliyet Hesapları
            # Eğer AL dediyse hisse getirisi, SAT/SHORT dediyse ters getiri
            trade_ret = act_ret if pred_dir in ["UP", "LONG", "BUY"] else -act_ret
            trade_cost_pct = ROUNDTRIP_COST_PCT
            net_trade_ret = trade_ret - trade_cost_pct

            returns.append(trade_ret)
            net_returns.append(net_trade_ret)

            gross_pnl = pos_size * (trade_ret / 100.0)
            cost = pos_size * (trade_cost_pct / 100.0)
            gross_pnls.append(gross_pnl)
            costs.append(cost)

            # 3. Kalibrasyon / Brier Skoru
            # Brier = (confidence - actual_binary)^2
            act_binary = 1.0 if act_dir == "UP" else 0.0
            prob_up = confidence if pred_dir == "UP" else (1.0 - confidence)
            brier_errors.append((prob_up - act_binary) ** 2)

            pred_scores.append(prob_up)
            actual_returns.append(act_ret)

            # Rejim ve Vade Gruplama
            regime_data.setdefault(regime, []).append({"correct": is_correct, "ret": net_trade_ret})
            horizon_data.setdefault(horizon, []).append({"correct": is_correct, "ret": net_trade_ret})

        n = len(predictions_with_outcomes)
        accuracy = correct_dirs / n
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.5
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.5
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.5

        mean_ret = float(np.mean(returns))
        cum_ret = float(np.sum(net_returns))
        total_gross_pnl = float(np.sum(gross_pnls))
        total_costs = float(np.sum(costs))
        total_net_pnl = total_gross_pnl - total_costs

        # Sharpe Oranı (Yıllıklandırılmış, 252 işlem günü)
        std_ret = float(np.std(net_returns)) if len(net_returns) > 1 else 1.0
        rf_daily = (risk_free_rate_annual / 252.0) * 100.0
        annualized_sharpe = float(np.sqrt(252) * (np.mean(net_returns) - rf_daily) / std_ret) if std_ret > 1e-6 else 0.0

        # Max Drawdown
        equity_curve = np.cumsum(net_returns)
        peak = np.maximum.accumulate(equity_curve)
        drawdowns = peak - equity_curve
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

        brier = float(np.mean(brier_errors))

        # Information Coefficient (IC) & Rank IC
        if len(pred_scores) > 2 and np.std(pred_scores) > 1e-6 and np.std(actual_returns) > 1e-6:
            ic = float(np.corrcoef(pred_scores, actual_returns)[0, 1])
            if math.isnan(ic):
                ic = 0.0

            # Spearman Rank Correlation
            rank_preds = np.argsort(np.argsort(pred_scores))
            rank_actuals = np.argsort(np.argsort(actual_returns))
            rank_ic = float(np.corrcoef(rank_preds, rank_actuals)[0, 1])
            if math.isnan(rank_ic):
                rank_ic = 0.0
        else:
            ic = 0.0
            rank_ic = 0.0

        # Win / Loss Ratio
        wins = [r for r in net_returns if r > 0]
        losses = [r for r in net_returns if r < 0]
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = abs(float(np.mean(losses))) if losses else 1.0
        win_loss_ratio = float(avg_win / avg_loss) if avg_loss > 0 else 1.0

        # Rejim Kırılımı
        regime_breakdown = {}
        for r_name, r_items in regime_data.items():
            r_acc = sum(1 for x in r_items if x["correct"]) / len(r_items)
            r_ret = float(np.mean([x["ret"] for x in r_items]))
            regime_breakdown[r_name] = {
                "samples": len(r_items),
                "accuracy": round(r_acc, 3),
                "mean_net_return_pct": round(r_ret, 3),
            }

        # Vade Kırılımı
        horizon_breakdown = {}
        for h_name, h_items in horizon_data.items():
            h_acc = sum(1 for x in h_items if x["correct"]) / len(h_items)
            h_ret = float(np.mean([x["ret"] for x in h_items]))
            horizon_breakdown[h_name] = {
                "samples": len(h_items),
                "accuracy": round(h_acc, 3),
                "mean_net_return_pct": round(h_ret, 3),
            }

        return PerformanceMetrics(
            model_id=model_id,
            model_version=model_version,
            total_samples=total_samples,
            evaluated_samples=n,
            direction_accuracy=round(accuracy, 4),
            hit_rate_pct=round(accuracy * 100.0, 2),
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1, 4),
            mean_return_pct=round(mean_ret, 4),
            cumulative_return_pct=round(cum_ret, 2),
            gross_pnl=round(total_gross_pnl, 2),
            transaction_costs=round(total_costs, 2),
            net_pnl=round(total_net_pnl, 2),
            annualized_sharpe=round(annualized_sharpe, 3),
            max_drawdown_pct=round(max_dd, 2),
            brier_score=round(brier, 4),
            information_coefficient=round(ic, 4),
            rank_ic=round(rank_ic, 4),
            win_loss_ratio=round(win_loss_ratio, 2),
            regime_breakdown=regime_breakdown,
            horizon_breakdown=horizon_breakdown,
        )
