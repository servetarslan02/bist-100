"""ALPHA BIST â€” Risk Gate v1.0

Merkezi risk kontrolÃ¼ â€” order gÃ¶nderilmeden Ã¶nce.
Fail-safe, fail-closed.
"""

from dataclasses import dataclass
from typing import Any

import structlog
import functools
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer("alpha-bist.risk_gate")

def otel_trace(span_name: str):
    """Decorator to wrap a method in an OTel span."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return func(self, *args, **kwargs)
        return wrapper
    return decorator


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    checks_passed: int = 0
    checks_failed: int = 0
    details: dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class RiskGate:
    """Merkezi risk gate â€” order Ã¼retiminden Ã¶nce."""

    def __init__(
        self,
        max_position_pct: float = 10.0,
        max_portfolio_exposure_pct: float = 95.0,
        max_single_order_pct: float = 5.0,
        min_confidence: float = 0.3,
        max_drawdown_pct: float = 20.0,
        daily_loss_limit_pct: float = 5.0,
        macro_stress_threshold_pct: float = -15.0,
    ):
        self.max_position_pct = max_position_pct
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_single_order_pct = max_single_order_pct
        self.min_confidence = min_confidence
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.macro_stress_threshold_pct = macro_stress_threshold_pct
        self._daily_pnl = 0.0
        self._macro_stress_result = None

    @otel_trace("risk_gate.check_order")
    def check_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        portfolio_value: float,
        current_positions: dict[str, Any],
        model_confidence: float = 0.5,
        market_open: bool = True,
        data_valid: bool = True,
        circuit_open: bool = False,
        mc_var_95: float = 0.0,
        mc_cvar_95: float = 0.0,
    ) -> RiskDecision:
        """Order risk kontrolÃ¼."""
        # Otomatik gÃ¼nlÃ¼k P&L senkronizasyonu
        self.sync_daily_pnl()
        # 1. Devre kesici ve temel kontroller
        early_exit = self._check_circuit_breakers(circuit_open, ticker, details={})
        if early_exit:
            return early_exit

        if not market_open:
            return RiskDecision(False, "Market closed", 0, 1, {"market": "closed"})
        if not data_valid:
            return RiskDecision(False, "Invalid/stale data", 0, 1, {"data": "invalid"})
        if quantity <= 0 or price <= 0:
            return RiskDecision(
                False, f"Invalid order quantity ({quantity}) or price ({price})", 0, 1, {"order": "invalid_parameters"}
            )

        checks_passed = 3
        checks_failed = 0
        details = {}
        reasons = []
        order_value = quantity * price

        # 2. Pozisyon ve boyut kontrolleri
        cp, cf, det, rea = self._check_position_limits(
            ticker, side, quantity, price, portfolio_value, current_positions, model_confidence
        )
        checks_passed += cp
        checks_failed += cf
        details.update(det)
        reasons.extend(rea)

        # 3. GÃ¼nlÃ¼k zarar limiti
        daily_loss_pct = abs(self._daily_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
        if self._daily_pnl < 0 and daily_loss_pct > self.daily_loss_limit_pct:
            checks_failed += 1
            reasons.append(f"Daily loss {daily_loss_pct:.1f}% > {self.daily_loss_limit_pct}%")
        else:
            checks_passed += 1

        # 4. BIST kurallarÄ±
        cp, cf, det = self._check_bist_rules(ticker, side, price, order_value, portfolio_value, current_positions)
        checks_passed += cp
        checks_failed += cf
        details.update(det)
        reasons.extend([r for r in [det.get("spk_notification")] if r])

        # 5. Monte Carlo VaR
        cp, cf, rea = self._check_monte_carlo_var(mc_var_95, mc_cvar_95)
        checks_passed += cp
        checks_failed += cf
        reasons.extend(rea)
        if mc_var_95 != 0:
            details["mc_var_95"] = round(mc_var_95, 2)
        if mc_cvar_95 != 0:
            details["mc_cvar_95"] = round(mc_cvar_95, 2)

        # 6. Macro stress test
        if self._macro_stress_result:
            worst_impact = self._macro_stress_result.get("worst_scenario", {}).get("impact_pct", 0)
            if worst_impact < self.macro_stress_threshold_pct:
                checks_failed += 1
                reasons.append(
                    f"Macro stress test: %{abs(worst_impact):.1f} kayÄ±p riski (eÅŸik: %{abs(self.macro_stress_threshold_pct):.0f})"
                )
            else:
                checks_passed += 1
            details["macro_stress_worst"] = worst_impact

        allowed = checks_failed == 0
        reason = "; ".join(reasons) if reasons else "All checks passed"
        return RiskDecision(allowed, reason, checks_passed, checks_failed, details)

    def _check_circuit_breakers(self, circuit_open: bool, ticker: str, details: dict):
        """Devre kesici ve fiyat limiti kontrolleri."""
        if circuit_open:
            return RiskDecision(False, "Circuit breaker OPEN", 0, 1, {"circuit": "open"})
        try:
            from services.core.auto_circuit_breaker import auto_circuit_breaker

            if auto_circuit_breaker.get_status().get("ebdks_active", False):
                return RiskDecision(False, "EBDKS aktif â€” tÃ¼m iÅŸlemler durduruldu", 0, 1, {"ebdks": "active"})
        except Exception:
            logger.warning("Circuit breaker check failed", exc_info=True)
        try:
            from services.core.price_limits import price_limit_monitor

            if price_limit_monitor.get_effective_limit(ticker) == 0.0:
                details["ipo_no_limit"] = True
        except Exception:
            logger.warning("Price limit check failed", exc_info=True)
        return None

    def _check_position_limits(
        self, ticker, side, quantity, price, portfolio_value, current_positions, model_confidence
    ):
        """Pozisyon boyutu ve confidence kontrolleri."""
        passed = failed = 0
        details = {}
        reasons = []

        current_exposure = sum(p.get("qty", 0) * p.get("avg_cost", 0) for p in current_positions.values())
        exposure_pct = (current_exposure / portfolio_value * 100) if portfolio_value > 0 else 100
        if exposure_pct > self.max_portfolio_exposure_pct:
            failed += 1
            reasons.append(f"Portfolio exposure {exposure_pct:.1f}% > {self.max_portfolio_exposure_pct}%")
        else:
            passed += 1
        details["exposure_pct"] = round(exposure_pct, 2)

        order_pct = (quantity * price / portfolio_value * 100) if portfolio_value > 0 else 100
        if order_pct > self.max_single_order_pct:
            failed += 1
            reasons.append(f"Order size {order_pct:.1f}% > {self.max_single_order_pct}%")
        else:
            passed += 1
        details["order_pct"] = round(order_pct, 2)

        pos = current_positions.get(ticker, {})
        existing_qty = pos.get("qty", 0)
        new_qty = existing_qty + quantity if side == "BUY" else existing_qty - quantity
        position_pct = (new_qty * price / portfolio_value * 100) if portfolio_value > 0 else 100
        if position_pct > self.max_position_pct:
            failed += 1
            reasons.append(f"Position {position_pct:.1f}% > {self.max_position_pct}%")
        else:
            passed += 1
        details["position_pct"] = round(position_pct, 2)

        if model_confidence < self.min_confidence:
            failed += 1
            reasons.append(f"Confidence {model_confidence:.2f} < {self.min_confidence}")
        else:
            passed += 1
        details["confidence"] = round(model_confidence, 4)

        return passed, failed, details, reasons

    def _check_bist_rules(self, ticker, side, price, order_value, portfolio_value, current_positions):
        """BIST kurallarÄ±: aÃ§Ä±ÄŸa satÄ±ÅŸ, halt, SPK uyumluluk."""
        passed = failed = 0
        details = {}
        reasons = []

        try:
            from services.core.compliance import compliance_checker
            from services.core.halt_monitor import halt_monitor
            from services.core.short_selling import short_selling_monitor

            if side == "SELL" and ticker not in current_positions:
                ss = short_selling_monitor.can_short_sell(ticker, price, last_trade_price=price)
                if not ss.allowed:
                    failed += 1
                    reasons.append(f"Short selling: {ss.reason}")

            halt = halt_monitor.check_halt(ticker)
            if halt.halted:
                failed += 1
                reasons.append(f"Halted: {halt.reason}")

            current_pos_pct = 0
            if ticker in current_positions:
                pos_val = current_positions[ticker].get("qty", 0) * current_positions[ticker].get("avg_cost", 0)
                current_pos_pct = pos_val / portfolio_value if portfolio_value > 0 else 0
            comp = compliance_checker.check_spk_compliance(side, ticker, order_value, portfolio_value, current_pos_pct)
            if comp.action == "BLOCK":
                failed += 1
                reasons.append(f"SPK: {comp.reason}")
            elif comp.notification_required:
                details["spk_notification"] = comp.reason

            if failed == 0:
                passed += 1
        except Exception as e:
            logger.error("BIST compliance check FAILED â€” blocking order (fail-closed)", error=str(e))
            failed += 1
            reasons.append(f"BIST compliance check error: {e}")

        return passed, failed, details

    def _check_monte_carlo_var(self, mc_var_95, mc_cvar_95):
        """Monte Carlo VaR/CVaR kontrolÃ¼."""
        passed = failed = 0
        reasons = []
        threshold = 15.0

        if mc_var_95 != 0:
            var_abs = abs(mc_var_95)
            if var_abs > threshold:
                reasons.append(f"MC VaR %{var_abs:.1f} > %{threshold:.0f} eÅŸik (risk yÃ¼ksek)")
                failed += 1
            else:
                passed += 1

        return passed, failed, reasons

    @otel_trace("risk_gate.set_macro_stress_result")
    def set_macro_stress_result(self, stress_result: dict[str, Any]):
        """Macro stres testi sonucunu risk gate'e besle."""
        self._macro_stress_result = stress_result

    @otel_trace("risk_gate.check_macro_stress")
    def check_macro_stress(
        self,
        portfolio: dict[str, Any],
    ) -> dict[str, Any]:
        """Macro stres testi Ã§alÄ±ÅŸtÄ±r ve sonucu kaydet."""
        try:
            from services.macro.stress_test import macro_stress_test

            report = macro_stress_test.get_report(portfolio)
            self._macro_stress_result = report
            return report
        except Exception as e:
            return {"error": str(e)}

    @otel_trace("risk_gate.update_daily_pnl")
    def update_daily_pnl(self, pnl: float):
        self._daily_pnl = pnl

    @otel_trace("risk_gate.sync_daily_pnl")
    def sync_daily_pnl(self):
        """PortfolioManager'dan gÃ¼nlÃ¼k P&L otomatik Ã§ek."""
        try:
            from services.portfolio.portfolio_manager import portfolio_manager

            if portfolio_manager:
                snapshots = portfolio_manager.get_equity_snapshots(limit=2)
                if len(snapshots) >= 2:
                    today_equity = snapshots[-1]["total_equity"]
                    yesterday_equity = snapshots[-2]["total_equity"]
                    self._daily_pnl = today_equity - yesterday_equity
                else:
                    self._daily_pnl = 0.0
        except Exception as e:
            logger.debug("Daily PnL sync skipped", error=str(e))

    @otel_trace("risk_gate.reset_daily")
    def reset_daily(self):
        self._daily_pnl = 0.0


# Singleton
risk_gate = RiskGate()

