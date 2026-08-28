"""
ALPHA BIST — Unified Risk Orchestrator v2.0

BIST-100 Ekosisteminin Tüm Risk Katmanlarını Birleştiren Merkezi Orkestratör:
1. Pre-Trade Risk Gate & BIST Kural Doğrulaması (Kuruş adımı, tavan/taban, açığa satış, brüt takas)
2. Portföy Düzeyi Risk Analizi (VaR/CVaR, Ledoit-Wolf PSD Kovaryans, Stres Testi, Tail Hedge)
3. Likidite Riski ve Piyasa Etkisi (L-VaR, ADV katılımı, Kyle's Lambda slippage)
4. Dinamik Rejim ve Drawdown Yönetimi (Otomatik de-risking, Kill-switch)
5. Gerçek Zamanlı Streaming Fiyat & Limit Yakınlık İzleme
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from services.core.market_session_fsm import BISTMarketPhase
from services.core.risk_gate import RiskDecision, RiskGate, risk_gate
from services.paper_trading.pre_trade_risk import PreTradeRiskEngine, pre_trade_risk_engine
from services.risk.covariance import CovarianceEstimator, covariance_estimator, ensure_positive_semi_definite
from services.risk.drawdown_response import DrawdownResponseSystem, drawdown_system
from services.risk.dynamic_limits import DynamicRiskLimits, dynamic_limits
from services.risk.enhanced_risk import ConcentrationRisk, concentration_risk
from services.risk.liquidity_risk import LiquidityRiskEngine, liquidity_risk_engine
from services.risk.monitoring import Alert, AlertSeverity, AlertType, RiskMonitor, risk_monitor
from services.risk.risk_parity import RiskParityOptimizer, risk_parity_optimizer
from services.risk.stress_test import StressTestEngine, stress_test_engine
from services.risk.tail_hedge import TailRiskHedger, tail_hedger
from services.risk.var_cvar import VaRCalculator, var_calculator

logger = structlog.get_logger()


@dataclass
class PreTradeOrderRequest:
    """Tekil emir öncesi risk değerlendirme talebi."""

    ticker: str
    side: str  # "BUY" | "SELL" | "SHORT"
    quantity: int
    price: float
    order_type: str = "LIMIT"
    reference_price: float | None = None
    last_trade_price: float | None = None
    market_phase: BISTMarketPhase = BISTMarketPhase.CONTINUOUS_AUCTION
    model_confidence: float = 0.50
    adv_tl: float | None = None
    spread_bps: float | None = None
    is_gross_settlement: bool = False


class RiskOrchestrator:
    """Tüm risk servislerini birleştiren merkezi risk kontrol orkestratörü."""

    def __init__(
        self,
        gate: RiskGate = risk_gate,
        pre_trade: PreTradeRiskEngine = pre_trade_risk_engine,
        liquidity: LiquidityRiskEngine = liquidity_risk_engine,
        drawdown: DrawdownResponseSystem = drawdown_system,
        dyn_limits: DynamicRiskLimits = dynamic_limits,
        monitor: RiskMonitor = risk_monitor,
        var_calc: VaRCalculator = var_calculator,
        stress: StressTestEngine = stress_test_engine,
        hedger: TailRiskHedger = tail_hedger,
        parity: RiskParityOptimizer = risk_parity_optimizer,
        cov_est: CovarianceEstimator = covariance_estimator,
    ):
        self.gate = gate
        self.pre_trade = pre_trade
        self.liquidity = liquidity
        self.drawdown = drawdown
        self.dynamic_limits = dyn_limits
        self.monitor = monitor
        self.var_calculator = var_calc
        self.stress_engine = stress
        self.tail_hedger = hedger
        self.risk_parity = parity
        self.covariance_estimator = cov_est
        self.concentration = concentration_risk
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""

        logger.info("RiskOrchestrator successfully initialized with all connected subsystems")

    # =====================================================
    # 1. UNIFIED PRE-TRADE RISK CHECK
    # =====================================================
    def evaluate_pre_trade(
        self,
        order: PreTradeOrderRequest,
        portfolio_state: dict[str, Any],
        regime: str = "SIDEWAYS",
    ) -> RiskDecision:
        """Tüm BIST kuralları, limitler, drawdown durumu ve likidite kısıtlarını tek adımda denetler."""
        is_risk_reducing_sell = (order.side == "SELL")

        if (self._kill_switch_active or self.drawdown.is_system_halted()) and not is_risk_reducing_sell:
            reason = f"KILL SWITCH AKTİF / SİSTEM DURDURULDU: {self._kill_switch_reason or 'Drawdown Acil Durumu'}"
            return RiskDecision(
                allowed=False,
                reason=reason,
                checks_passed=0,
                checks_failed=1,
                details={"kill_switch": True, "reason": reason},
            )

        if (not self.drawdown.is_trading_allowed()) and not is_risk_reducing_sell:
            dd_state = self.drawdown.get_state()
            return RiskDecision(
                allowed=False,
                reason=f"Drawdown müdahalesi devrede: {dd_state.description} (DD: %{dd_state.current_drawdown_pct:.1f})",
                checks_passed=0,
                checks_failed=1,
                details={"drawdown_action": dd_state.action.value},
            )


        portfolio_value = float(portfolio_state.get("total_value", portfolio_state.get("current_capital", 100000.0)))
        portfolio_cash = float(portfolio_state.get("cash", portfolio_value))
        current_positions = portfolio_state.get("positions", {})

        checks_passed = 0
        checks_failed = 0
        details = {}
        reasons = []

        # 1. BIST Mikroyapı ve Seans Doğrulaması (PreTradeRiskEngine)
        ref_price = order.reference_price if order.reference_price else order.price
        bist_val = self.pre_trade.validate_order(
            ticker=order.ticker,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            price=order.price,
            reference_price=ref_price,
            market_phase=order.market_phase,
            portfolio_cash=portfolio_cash,
            last_trade_price=order.last_trade_price,
        )

        if not bist_val.is_valid:
            checks_failed += 1
            reasons.append(f"BIST Kural İhlali [{bist_val.rejection_code}]: {bist_val.rejection_reason}")
            details["bist_rejection"] = bist_val.rejection_code
        else:
            checks_passed += 1

        # 2. Likidite Riski & ADV Katılımı (LiquidityRiskEngine)
        order_val = float(order.quantity * order.price)
        liq_metrics = self.liquidity.evaluate_order_liquidity(
            ticker=order.ticker,
            order_value=order_val,
            price=order.price,
            adv_tl=order.adv_tl,
            spread_bps=order.spread_bps,
            is_gross_settlement=order.is_gross_settlement,
        )

        if not liq_metrics.is_tradable:
            checks_failed += 1
            reasons.append(f"Aşırı Likidite Riski: ADV katılımı %{liq_metrics.participation_rate_pct:.1f} > limit")
        else:
            checks_passed += 1

        details["liquidity_score"] = liq_metrics.liquidity_score
        details["expected_slippage_pct"] = liq_metrics.expected_market_impact_pct
        details["sizing_multiplier"] = liq_metrics.liquidity_sizing_multiplier

        # 3. Dinamik Rejim Limitleri & Kelly (DynamicRiskLimits)
        dyn = self.dynamic_limits.get_limits(regime=regime)
        position_pct = (order_val / portfolio_value * 100.0) if portfolio_value > 0 else 100.0
        if position_pct > dyn.max_position_pct:
            checks_failed += 1
            reasons.append(f"Dinamik Pozisyon Limiti: %{position_pct:.1f} > rejim limiti %{dyn.max_position_pct:.1f}")
        else:
            checks_passed += 1

        # 4. RiskGate Portföy & Model Güveni Kontrolü
        gate_res = self.gate.check_order(
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            portfolio_value=portfolio_value,
            current_positions=current_positions if isinstance(current_positions, dict) else {},
            model_confidence=order.model_confidence,
            market_open=(order.market_phase != BISTMarketPhase.CLOSED),
        )

        if not gate_res.allowed:
            checks_failed += gate_res.checks_failed
            reasons.append(gate_res.reason)
        else:
            checks_passed += gate_res.checks_passed

        details.update(gate_res.details)
        allowed = checks_failed == 0
        final_reason = "; ".join(reasons) if reasons else "Tüm kurumsal risk denetimlerinden başarıyla geçti."

        return RiskDecision(
            allowed=allowed,
            reason=final_reason,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            details=details,
        )

    # =====================================================
    # 2. UNIFIED PORTFOLIO RISK ASSESSMENT
    # =====================================================
    def assess_portfolio_risk(
        self,
        portfolio: dict[str, Any],
        market_data: dict[str, Any] | None = None,
        returns_history: np.ndarray | None = None,
        regime: str = "SIDEWAYS",
    ) -> dict[str, Any]:
        """Tüm portföy için çok boyutlu risk değerlendirmesi ve L-VaR raporu üretir."""
        portfolio_value = float(portfolio.get("total_value", portfolio.get("current_capital", 100000.0)))
        weights = portfolio.get("weights", {})
        positions = portfolio.get("positions", [])

        report: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "portfolio_value": portfolio_value,
            "regime": regime,
            "trading_allowed": self.is_trading_allowed(),
        }

        # 1. VaR / CVaR
        base_var_95 = 0.0
        if returns_history is not None and len(returns_history) > 10:
            try:
                returns_clean = np.nan_to_num(np.asarray(returns_history, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
                var_rep = self.var_calculator.calculate_full_var_report(
                    returns=returns_clean,
                    portfolio_value=portfolio_value,
                )
                base_var_95 = float(var_rep["consensus"]["var_95"])
                report["var_cvar"] = var_rep
            except Exception as e:
                report["var_cvar"] = {"error": str(e)}


        # 2. Likidite Riski & L-VaR
        try:
            pos_list = []
            if isinstance(positions, list):
                pos_list = positions
            elif isinstance(positions, dict):
                for tick, pdata in positions.items():
                    val = (
                        pdata.get("qty", 0) * pdata.get("avg_cost", 0)
                        if isinstance(pdata, dict)
                        else float(weights.get(tick, 0) * portfolio_value)
                    )
                    pos_list.append({"ticker": tick, "value": val})

            liq_report = self.liquidity.calculate_portfolio_liquidity(
                positions=pos_list,
                total_portfolio_value=portfolio_value,
                base_var_95=base_var_95,
            )
            report["liquidity"] = {
                "score": liq_report.portfolio_liquidity_score,
                "weighted_spread_bps": liq_report.weighted_spread_bps,
                "liquidation_cost_tl": liq_report.total_liquidation_cost_tl,
                "liquidity_adjusted_var_95": liq_report.liquidity_adjusted_var_95,
                "lvar_increment_pct": liq_report.lvar_increment_pct,
                "max_liquidation_days": liq_report.max_liquidation_days,
                "recommendations": liq_report.recommendations,
            }
        except Exception as e:
            report["liquidity"] = {"error": str(e)}

        # 3. Konsantrasyon (HHI & Max Weight)
        if weights:
            try:
                hhi = self.concentration.compute_hhi(weights)
                max_t, max_w = self.concentration.compute_max_concentration(weights)
                report["concentration"] = {
                    "hhi": round(hhi, 4),
                    "max_position": max_t,
                    "max_weight_pct": round(max_w * 100.0, 2),
                }
            except Exception as e:
                report["concentration"] = {"error": str(e)}

        # 4. Drawdown Response Durumu
        try:
            dd_state = self.drawdown.get_state()
            report["drawdown"] = {
                "current_pct": dd_state.current_drawdown_pct,
                "max_pct": dd_state.max_drawdown_pct,
                "action": dd_state.action.value,
                "severity": dd_state.severity.value,
                "position_scale": dd_state.position_scale,
            }
        except Exception as e:
            report["drawdown"] = {"error": str(e)}

        # 5. Stres Testi
        try:
            stress_rep = self.stress_engine.run_all_scenarios(portfolio)
            report["stress_test"] = {
                "risk_score": float(stress_rep.risk_score),
                "worst_scenario": stress_rep.worst_scenario.scenario_name if stress_rep.worst_scenario else "N/A",
                "worst_impact_pct": float(stress_rep.worst_scenario.total_impact_pct)
                if stress_rep.worst_scenario
                else 0.0,
                "recommendations": stress_rep.recommendations,
            }
        except Exception as e:
            report["stress_test"] = {"error": str(e)}

        # 6. Tail Hedge Önerisi
        try:
            hedge = self.tail_hedger.analyze(portfolio_value, regime=regime)
            report["tail_hedge"] = {
                "strategy": hedge.strategy,
                "hedge_ratio": hedge.hedge_ratio,
                "cost_pct": hedge.estimated_cost_pct,
                "protection_level": hedge.protection_level,
            }
        except Exception as e:
            report["tail_hedge"] = {"error": str(e)}

        # 7. Dinamik Adaptif Kompozit Risk Skoru (0-100)
        report["composite_risk_score"] = self._compute_adaptive_risk_score(report, regime)

        return report

    def _compute_adaptive_risk_score(self, report: dict[str, Any], regime: str) -> float:
        """Piyasa rejimi ve çoklu metriklerle adaptif kompozit risk skoru (0-100)."""
        regime_weights = {
            "BULL": 0.80,
            "SIDEWAYS": 1.00,
            "BEAR": 1.30,
            "CRISIS": 1.60,
        }
        reg_mult = regime_weights.get(regime.upper(), 1.00)

        score = 30.0  # Temel zemin skoru

        # VaR etkisi
        if "var_cvar" in report and "consensus" in report["var_cvar"]:
            var_val = report["var_cvar"]["consensus"].get("var_95", 0.0)
            pval = report.get("portfolio_value", 100000.0)
            var_pct = (var_val / pval * 100.0) if pval > 0 else 0.0
            score += min(25.0, var_pct * 5.0)

        # Drawdown etkisi
        if "drawdown" in report:
            dd_pct = report["drawdown"].get("current_pct", 0.0)
            score += min(20.0, dd_pct * 1.5)

        # Konsantrasyon etkisi
        if "concentration" in report:
            hhi = report["concentration"].get("hhi", 0.10)
            score += min(15.0, hhi * 30.0)

        # Likidite riski etkisi
        if "liquidity" in report:
            liq_score = report["liquidity"].get("score", 80.0)
            score += max(0.0, (80.0 - liq_score) * 0.25)

        total_score = min(100.0, max(0.0, score * reg_mult))
        return round(float(total_score), 1)

    # =====================================================
    # 3. REAL-TIME STREAMING & EMERGENCY CONTROLS
    # =====================================================
    def on_price_tick(
        self,
        ticker: str,
        price: float,
        volume: float = 0.0,
        best_bid: float | None = None,
        best_ask: float | None = None,
        reference_price: float | None = None,
    ) -> list[Alert]:
        """Canlı fiyat tick'ini risk monitoring motoruna besler."""
        return self.monitor.ingest_price_tick(
            ticker=ticker,
            price=price,
            volume=volume,
            best_bid=best_bid,
            best_ask=best_ask,
            reference_price=reference_price,
        )

    def trigger_emergency_kill_switch(self, reason: str) -> dict[str, Any]:
        """Tüm alım-satım operasyonlarını anında kilitler."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self.drawdown.update_equity(0.0)  # Trigger emergency state
        logger.critical("EMERGENCY KILL SWITCH TRIGGERED IN RISK ORCHESTRATOR", reason=reason)
        return {
            "kill_switch_active": True,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
            "status": "ALL_TRADING_HALTED",
        }

    def reset_kill_switch(self) -> dict[str, Any]:
        """Yetkili onayı ile kill switch'i sıfırlar."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self.drawdown.reset(force=True, reason="RiskOrchestrator reset_kill_switch")
        logger.warning("Kill switch reset by authorized call")
        return {"kill_switch_active": False, "status": "TRADING_RESTORED"}

    def is_trading_allowed(self) -> bool:
        """Sistemin işlem yapmaya uygun olup olmadığını kontrol eder."""
        return (
            not self._kill_switch_active
            and self.drawdown.is_trading_allowed()
            and not self.drawdown.is_system_halted()
        )

    def get_summary(self) -> dict[str, Any]:
        """Risk orkestratörü sistem durum özeti."""
        dd_state = self.drawdown.get_state()
        return {
            "trading_allowed": self.is_trading_allowed(),
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "drawdown_action": dd_state.action.value,
            "drawdown_severity": dd_state.severity.value,
            "current_drawdown_pct": dd_state.current_drawdown_pct,
            "alerts": self.monitor.get_alert_summary(),
        }


# Singleton
risk_orchestrator = RiskOrchestrator()
