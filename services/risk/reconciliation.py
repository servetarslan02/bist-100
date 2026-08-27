"""
ALPHA BIST — Portfolio Reconciliation v1.0

Periyodik kontrol:
- Ledger vs Positions vs Cash vs Equity
- Uyuşmazlık tespiti
- Raporlama

FAZ 11: Portfolio Reconciliation
"""

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class ReconciliationResult:
    """Uzlaştırma sonucu."""

    is_consistent: bool
    cash_diff: float
    position_diff: float
    equity_diff: float
    errors: list[str]
    warnings: list[str]


class ReconciliationEngine:
    """Portfolio uzlaştırma motoru."""

    def reconcile(
        self,
        portfolio_id: int,
        ledger_cash: float,
        ledger_positions_value: float,
        ledger_equity: float,
        db_cash: float,
        db_positions_value: float,
        db_equity: float,
        tolerance: float = 0.01,
    ) -> ReconciliationResult:
        """Ledger vs DB karşılaştır.

        Cash + Position Market Values = Equity (tutarlı mı?)
        """
        errors = []
        warnings = []

        # Cash kontrolü
        cash_diff = abs(ledger_cash - db_cash)
        if cash_diff > tolerance:
            errors.append(f"Cash mismatch: ledger={ledger_cash:.2f}, db={db_cash:.2f}, diff={cash_diff:.2f}")

        # Position value kontrolü
        position_diff = abs(ledger_positions_value - db_positions_value)
        if position_diff > tolerance:
            errors.append(
                f"Position mismatch: ledger={ledger_positions_value:.2f}, db={db_positions_value:.2f}, diff={position_diff:.2f}"
            )

        # Equity kontrolü
        equity_diff = abs(ledger_equity - db_equity)
        if equity_diff > tolerance:
            errors.append(f"Equity mismatch: ledger={ledger_equity:.2f}, db={db_equity:.2f}, diff={equity_diff:.2f}")

        # Cash + Positions = Equity kontrolü
        calculated_equity = ledger_cash + ledger_positions_value
        calc_diff = abs(calculated_equity - ledger_equity)
        if calc_diff > tolerance:
            errors.append(
                f"Equation mismatch: cash({ledger_cash:.2f}) + positions({ledger_positions_value:.2f}) ≠ equity({ledger_equity:.2f})"
            )

        is_consistent = len(errors) == 0

        if not is_consistent:
            logger.warning("Portfolio reconciliation FAILED", portfolio_id=portfolio_id, errors=errors)

        return ReconciliationResult(
            is_consistent=is_consistent,
            cash_diff=round(cash_diff, 2),
            position_diff=round(position_diff, 2),
            equity_diff=round(equity_diff, 2),
            errors=errors,
            warnings=warnings,
        )


# Singleton
reconciliation_engine = ReconciliationEngine()
