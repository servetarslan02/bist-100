"""
ALPHA BIST — Paper Risk Gate v1.0

Portfolio Risk Yonetimi:
- Max position weight
- Max sector weight
- Max portfolio exposure
- Max drawdown alarmi + kill-switch
- Gunluk kayip limiti
- Data quality bozulursa NO_TRADE
- Herhangi bir kritik hatada NO_TRADE (fail-safe)

KURAL: Risk Gate 'NO_TRADE' diyebilmeli. Sistem hicbir kosulda
islem yapmak zorunda olmamali.
"""

from typing import Dict, List, Optional, Any
from collections import defaultdict
import structlog

logger = structlog.get_logger()


class PaperRiskGate:
    """Paper trading risk gate — fail-safe, fail-closed."""

    def __init__(
        self,
        max_position_pct: float = 10.0,
        max_sector_pct: float = 30.0,
        max_portfolio_exposure_pct: float = 100.0,
        max_drawdown_pct: float = 20.0,
        kill_switch_drawdown_pct: float = 25.0,
        daily_loss_limit_pct: float = 5.0,
        liquidity_min_volume: int = 100_000,
        data_quality_min_stocks: int = 50,
    ):
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.kill_switch_drawdown_pct = kill_switch_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.liquidity_min_volume = liquidity_min_volume
        self.data_quality_min_stocks = data_quality_min_stocks

        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._consecutive_errors = 0
        self._max_consecutive_errors = 3

    def is_kill_switch_active(self) -> bool:
        """Kill switch aktif mi?"""
        return self._kill_switch_active

    def get_kill_switch_reason(self) -> str:
        return self._kill_switch_reason

    def reset_kill_switch(self):
        """Kill switch'i manuel resetle."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        logger.warning("Kill switch RESET manually")

    def check_all(
        self,
        portfolio,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        sector: str = "",
        data_quality_ok: bool = True,
        model_version_valid: bool = True,
    ) -> List[Dict[str, Any]]:
        """Tum risk check'lerini calistir."""
        checks = []

        # === 0. KILL SWITCH ===
        checks.append(self._check_kill_switch())

        # === 1. DATA QUALITY ===
        checks.append(self._check_data_quality(data_quality_ok))

        # === 2. MODEL VALIDITY ===
        checks.append(self._check_model_validity(model_version_valid))

        # === 3. POSITION SIZE ===
        checks.append(self._check_position_size(portfolio, ticker, side, quantity, price))

        # === 4. SECTOR CONCENTRATION ===
        checks.append(self._check_sector_concentration(portfolio, ticker, side, quantity, price, sector))

        # === 5. PORTFOLIO EXPOSURE ===
        checks.append(self._check_portfolio_exposure(portfolio, ticker, side, quantity, price))

        # === 6. DRAWDOWN ===
        checks.append(self._check_drawdown(portfolio))

        # === 7. DAILY LOSS ===
        checks.append(self._check_daily_loss(portfolio))

        blocked = [c for c in checks if c["result"] in ("BLOCK", "NO_TRADE")]
        if blocked:
            logger.warning("Risk gate BLOCKED",
                          ticker=ticker, side=side,
                          reasons=[c["check_name"] for c in blocked])
        else:
            logger.info("Risk gate PASSED", ticker=ticker, side=side)

        return checks

    def is_trade_allowed(self, checks: List[Dict[str, Any]]) -> bool:
        """Tum check'lerden gecildi mi?"""
        for check in checks:
            if check["result"] in ("BLOCK", "NO_TRADE"):
                return False
        return True

    def get_block_reason(self, checks: List[Dict[str, Any]]) -> str:
        """Block sebebini birlestir."""
        blocks = [c for c in checks if c["result"] in ("BLOCK", "NO_TRADE")]
        return "; ".join(f"{c['check_name']}: {c['details']}" for c in blocks)

    # ===================== INDIVIDUAL CHECKS =====================

    def _check_kill_switch(self) -> Dict[str, Any]:
        if self._kill_switch_active:
            return {
                "check_name": "kill_switch",
                "result": "BLOCK",
                "details": f"KILL SWITCH ACTIVE: {self._kill_switch_reason}",
                "severity": "BLOCK",
            }
        return {"check_name": "kill_switch", "result": "PASS", "details": "OK", "severity": "INFO"}

    def _check_data_quality(self, ok: bool) -> Dict[str, Any]:
        if not ok:
            return {
                "check_name": "data_quality",
                "result": "NO_TRADE",
                "details": "Data quality check FAILED — NO_TRADE",
                "severity": "BLOCK",
            }
        return {"check_name": "data_quality", "result": "PASS", "details": "OK", "severity": "INFO"}

    def _check_model_validity(self, valid: bool) -> Dict[str, Any]:
        if not valid:
            return {
                "check_name": "model_validity",
                "result": "NO_TRADE",
                "details": "Champion model invalid or not loaded — NO_TRADE",
                "severity": "BLOCK",
            }
        return {"check_name": "model_validity", "result": "PASS", "details": "OK", "severity": "INFO"}

    def _check_position_size(self, portfolio, ticker: str, side: str, quantity: int, price: float) -> Dict[str, Any]:
        if side == "SELL":
            return {"check_name": "position_size", "result": "PASS", "details": "SELL side — no position size limit", "severity": "INFO"}

        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return {"check_name": "position_size", "result": "BLOCK", "details": "Portfolio value is zero", "severity": "BLOCK"}

        new_position_value = quantity * price
        current_position_value = 0.0
        pos = portfolio.get_position(ticker)
        if pos:
            current_position_value = pos["market_value"]

        total_position_value = current_position_value + new_position_value
        position_pct = (total_position_value / total_value) * 100

        if position_pct > self.max_position_pct:
            return {
                "check_name": "position_size",
                "result": "BLOCK",
                "details": f"Position {position_pct:.1f}% > limit {self.max_position_pct}%",
                "severity": "BLOCK",
            }
        return {"check_name": "position_size", "result": "PASS", "details": f"{position_pct:.1f}% <= {self.max_position_pct}%", "severity": "INFO"}

    def _check_sector_concentration(self, portfolio, ticker: str, side: str, quantity: int, price: float, sector: str) -> Dict[str, Any]:
        if not sector or side == "SELL":
            return {"check_name": "sector_concentration", "result": "PASS", "details": "No sector or SELL side", "severity": "INFO"}

        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return {"check_name": "sector_concentration", "result": "PASS", "details": "Portfolio value is zero", "severity": "INFO"}

        sector_values = defaultdict(float)
        for pos in portfolio.get_all_positions():
            s = pos.get("sector", "UNKNOWN")
            sector_values[s] += pos["market_value"]

        new_value = quantity * price
        sector_values[sector] += new_value

        max_sector_pct = max((v / total_value) * 100 for v in sector_values.values())

        if max_sector_pct > self.max_sector_pct:
            return {
                "check_name": "sector_concentration",
                "result": "BLOCK",
                "details": f"Sector {sector}: {max_sector_pct:.1f}% > limit {self.max_sector_pct}%",
                "severity": "BLOCK",
            }
        return {"check_name": "sector_concentration", "result": "PASS", "details": f"Max sector {max_sector_pct:.1f}% <= {self.max_sector_pct}%", "severity": "INFO"}

    def _check_portfolio_exposure(self, portfolio, ticker: str, side: str, quantity: int, price: float) -> Dict[str, Any]:
        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return {"check_name": "portfolio_exposure", "result": "PASS", "details": "Portfolio value is zero", "severity": "INFO"}

        current_exposure = portfolio.get_invested_value()
        if side == "BUY":
            new_exposure = current_exposure + (quantity * price)
        else:
            pos = portfolio.get_position(ticker)
            sell_value = min(quantity * price, pos["market_value"]) if pos else 0
            new_exposure = max(0, current_exposure - sell_value)

        exposure_pct = (new_exposure / total_value) * 100

        if exposure_pct > self.max_portfolio_exposure_pct:
            return {
                "check_name": "portfolio_exposure",
                "result": "BLOCK",
                "details": f"Exposure {exposure_pct:.1f}% > limit {self.max_portfolio_exposure_pct}%",
                "severity": "BLOCK",
            }
        return {"check_name": "portfolio_exposure", "result": "PASS", "details": f"{exposure_pct:.1f}% <= {self.max_portfolio_exposure_pct}%", "severity": "INFO"}

    def _check_drawdown(self, portfolio) -> Dict[str, Any]:
        current_dd = portfolio.get_current_drawdown()

        if current_dd >= self.kill_switch_drawdown_pct:
            self._kill_switch_active = True
            self._kill_switch_reason = f"Max drawdown {current_dd:.1f}% >= kill-switch {self.kill_switch_drawdown_pct}%"
            return {
                "check_name": "drawdown",
                "result": "BLOCK",
                "details": self._kill_switch_reason,
                "severity": "BLOCK",
            }

        if current_dd >= self.max_drawdown_pct:
            return {
                "check_name": "drawdown",
                "result": "WARN",
                "details": f"Drawdown {current_dd:.1f}% >= alarm {self.max_drawdown_pct}%",
                "severity": "WARN",
            }

        return {"check_name": "drawdown", "result": "PASS", "details": f"{current_dd:.1f}% < {self.max_drawdown_pct}%", "severity": "INFO"}

    def _check_daily_loss(self, portfolio) -> Dict[str, Any]:
        if len(portfolio._equity_curve) < 2:
            return {"check_name": "daily_loss", "result": "PASS", "details": "Not enough history", "severity": "INFO"}

        recent = portfolio._equity_curve[-2:]
        if len(recent) >= 2:
            daily_return = (recent[-1]["equity"] / recent[-2]["equity"] - 1) * 100
            if daily_return <= -self.daily_loss_limit_pct:
                return {
                    "check_name": "daily_loss",
                    "result": "BLOCK",
                    "details": f"Daily loss {daily_return:.1f}% >= limit {self.daily_loss_limit_pct}%",
                    "severity": "BLOCK",
                }
        return {"check_name": "daily_loss", "result": "PASS", "details": "OK", "severity": "INFO"}

    def record_error(self):
        """Ard arda hata sayacini artir."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._max_consecutive_errors:
            self._kill_switch_active = True
            self._kill_switch_reason = f"{self._consecutive_errors} consecutive errors — kill switch activated"
            logger.critical(self._kill_switch_reason)

    def clear_errors(self):
        """Hata sayacini sifirla."""
        self._consecutive_errors = 0


# Singleton
paper_risk_gate = PaperRiskGate()
