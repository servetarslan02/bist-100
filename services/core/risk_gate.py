"""ALPHA BIST — Risk Gate v1.0

Merkezi risk kontrolü — order gönderilmeden önce.
Fail-safe, fail-closed.
"""

import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    checks_passed: int = 0
    checks_failed: int = 0
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class RiskGate:
    """Merkezi risk gate — order üretiminden önce."""

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

    def check_order(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        portfolio_value: float,
        current_positions: Dict[str, Any],
        model_confidence: float = 0.5,
        market_open: bool = True,
        data_valid: bool = True,
        circuit_open: bool = False,
    ) -> RiskDecision:
        """Order risk kontrolü."""
        checks_passed = 0
        checks_failed = 0
        details = {}
        reasons = []

        # 1. Circuit breaker
        if circuit_open:
            return RiskDecision(False, "Circuit breaker OPEN", 0, 1, {"circuit": "open"})

        # 2. Market session
        if not market_open:
            return RiskDecision(False, "Market closed", 0, 1, {"market": "closed"})

        # 3. Data validity
        if not data_valid:
            return RiskDecision(False, "Invalid/stale data", 0, 1, {"data": "invalid"})

        checks_passed += 3

        # 4. Portfolio exposure
        current_exposure = sum(
            p.get("qty", 0) * p.get("avg_cost", 0)
            for p in current_positions.values()
        )
        exposure_pct = (current_exposure / portfolio_value * 100) if portfolio_value > 0 else 100
        if exposure_pct > self.max_portfolio_exposure_pct:
            checks_failed += 1
            reasons.append(f"Portfolio exposure {exposure_pct:.1f}% > {self.max_portfolio_exposure_pct}%")
        else:
            checks_passed += 1
        details["exposure_pct"] = round(exposure_pct, 2)

        # 5. Single order size
        order_value = quantity * price
        order_pct = (order_value / portfolio_value * 100) if portfolio_value > 0 else 100
        if order_pct > self.max_single_order_pct:
            checks_failed += 1
            reasons.append(f"Order size {order_pct:.1f}% > {self.max_single_order_pct}%")
        else:
            checks_passed += 1
        details["order_pct"] = round(order_pct, 2)

        # 6. Position concentration
        pos = current_positions.get(ticker, {})
        existing_qty = pos.get("qty", 0)
        new_qty = existing_qty + quantity if side == "BUY" else existing_qty - quantity
        position_value = new_qty * price
        position_pct = (position_value / portfolio_value * 100) if portfolio_value > 0 else 100
        if position_pct > self.max_position_pct:
            checks_failed += 1
            reasons.append(f"Position {position_pct:.1f}% > {self.max_position_pct}%")
        else:
            checks_passed += 1
        details["position_pct"] = round(position_pct, 2)

        # 7. Model confidence
        if model_confidence < self.min_confidence:
            checks_failed += 1
            reasons.append(f"Confidence {model_confidence:.2f} < {self.min_confidence}")
        else:
            checks_passed += 1
        details["confidence"] = round(model_confidence, 4)

        # 8. Daily loss limit
        daily_loss_pct = abs(self._daily_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
        if self._daily_pnl < 0 and daily_loss_pct > self.daily_loss_limit_pct:
            checks_failed += 1
            reasons.append(f"Daily loss {daily_loss_pct:.1f}% > {self.daily_loss_limit_pct}%")
        else:
            checks_passed += 1

        # 9. BIST Kuralları entegrasyonu
        _checks_failed_before_bist = checks_failed
        try:
            from services.core.short_selling import short_selling_monitor
            from services.core.halt_monitor import halt_monitor
            from services.core.price_limits import price_limit_monitor
            from services.core.compliance import compliance_checker

            # Açığa satış kontrolü
            if side == "SELL" and ticker not in current_positions:
                ss = short_selling_monitor.can_short_sell(ticker, price)
                if not ss.allowed:
                    checks_failed += 1
                    reasons.append(f"Short selling: {ss.reason}")

            # Halt kontrolü
            halt = halt_monitor.check_halt(ticker)
            if halt.halted:
                checks_failed += 1
                reasons.append(f"Halted: {halt.reason}")

            # SPK uyumluluk
            current_pos_pct = 0
            if ticker in current_positions:
                pos_val = current_positions[ticker].get("qty", 0) * current_positions[ticker].get("avg_cost", 0)
                current_pos_pct = pos_val / portfolio_value if portfolio_value > 0 else 0
            comp = compliance_checker.check_spk_compliance(side, ticker, order_value, portfolio_value, current_pos_pct)
            if comp.action == "BLOCK":
                checks_failed += 1
                reasons.append(f"SPK: {comp.reason}")
            elif comp.notification_required:
                details["spk_notification"] = comp.reason
        except Exception:
            pass  # BIST kuralları modülleri yoksa skip
        else:
            # Yalnızca bu blok içinde hiçbir alt-kontrol başarısız olmadıysa
            # "geçti" say (önceki hali, içeride bir kural reddetse bile
            # istisna fırlatılmadığı için her zaman checks_passed'i artırıyordu)
            if checks_failed == _checks_failed_before_bist:
                checks_passed += 1

        # 10. Macro stress test kontrolü
        if self._macro_stress_result:
            worst_impact = self._macro_stress_result.get("worst_scenario", {}).get("impact_pct", 0)
            if worst_impact < self.macro_stress_threshold_pct:
                checks_failed += 1
                reasons.append(f"Macro stress test: %{abs(worst_impact):.1f} kayıp riski (eşik: %{abs(self.macro_stress_threshold_pct):.0f})")
            else:
                checks_passed += 1
            details["macro_stress_worst"] = worst_impact

        allowed = checks_failed == 0
        reason = "; ".join(reasons) if reasons else "All checks passed"

        return RiskDecision(allowed, reason, checks_passed, checks_failed, details)

    def set_macro_stress_result(self, stress_result: Dict[str, Any]):
        """Macro stres testi sonucunu risk gate'e besle."""
        self._macro_stress_result = stress_result

    def check_macro_stress(
        self,
        portfolio: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Macro stres testi çalıştır ve sonucu kaydet."""
        try:
            from services.macro.stress_test import macro_stress_test
            report = macro_stress_test.get_report(portfolio)
            self._macro_stress_result = report
            return report
        except Exception as e:
            return {"error": str(e)}

    def update_daily_pnl(self, pnl: float):
        self._daily_pnl = pnl

    def reset_daily(self):
        self._daily_pnl = 0.0


# Singleton
risk_gate = RiskGate()
