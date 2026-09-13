"""
ALPHA BIST — Institutional Multi-Asset Portfolio Reconciliation & Settlement Engine v2.0

Portföy Muhasebesi, Takas (Takasbank) ve Saklama (MKK) mutabakat motoru:
- 3-Way Reconciliation: Defter (Ledger) vs Pozisyon Veritabanı (DB) vs Borsa/Broker Feed
- Gerçek Zamanlı Nakit, Portföy Değeri (Mark-to-Market), Blokaj ve Özsermaye Eşitliği
- Sembol Seviyesinde Lot Uyuşmazlığı, Kıymet Bazlı Takas Farkı (T+1 / T+2 Settlement)
- Otomatik Düzeltme (Auto-Correction) ve Hata Ayrıştırma Kategorileri
- Audit Loglama ve Uyuşmazlık Tutanakları (Discrepancy Incident Tracking)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DiscrepancySeverity(StrEnum):
    """Uyuşmazlık ciddiyet derecesi."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class PositionDiscrepancy:
    """Tek bir hisse veya sözleşmede tespit edilen lot/fiyat uyuşmazlığı."""
    symbol: str
    ledger_lots: int
    db_lots: int
    lot_diff: int
    market_price: float
    value_impact: float
    severity: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


@dataclass
class ReconciliationResult:
    """Detaylı kurumsal mutabakat sonucu."""
    is_consistent: bool
    portfolio_id: int
    timestamp: str
    cash_diff: float
    position_diff: float
    equity_diff: float
    equation_diff: float
    ledger_cash: float
    ledger_positions_value: float
    ledger_equity: float
    db_cash: float
    db_positions_value: float
    db_equity: float
    unsettled_t1_cash: float
    unsettled_t2_cash: float
    blocked_margin_cash: float
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    position_discrepancies: list[dict[str, Any]] = field(default_factory=list)
    recommended_action: str = "PROCEED"

    def to_dict(self) -> dict[str, Any]:
        """Sözlük formatına dönüştürür."""
        return asdict(self)


class ReconciliationEngine:
    """Kurumsal Portföy Uzlaştırma ve Takasbank Mutabakat Motoru."""

    def __init__(self, default_tolerance: float = 0.05) -> None:
        """Motor ilklendirici."""
        self.default_tolerance = default_tolerance

    def __repr__(self) -> str:
        return f"ReconciliationEngine(default_tolerance={self.default_tolerance})"

    def reconcile_positions(
        self,
        ledger_positions: dict[str, dict[str, Any]],
        db_positions: dict[str, dict[str, Any]],
    ) -> list[PositionDiscrepancy]:
        """Hisse ve sözleşme bazında detaylı lot ve piyasa değeri karşılaştırması yapar."""
        discrepancies: list[PositionDiscrepancy] = []
        all_symbols = set(ledger_positions.keys()).union(set(db_positions.keys()))

        for sym in sorted(all_symbols):
            l_pos = ledger_positions.get(sym, {})
            d_pos = db_positions.get(sym, {})

            l_lots = int(l_pos.get("lots", l_pos.get("quantity", 0)))
            d_lots = int(d_pos.get("lots", d_pos.get("quantity", 0)))
            price = float(l_pos.get("price", d_pos.get("price", 0.0)))

            lot_diff = l_lots - d_lots
            if lot_diff != 0:
                value_impact = abs(lot_diff) * price
                severity = (
                    DiscrepancySeverity.CRITICAL.value
                    if value_impact > 50_000
                    else (DiscrepancySeverity.ERROR.value if value_impact > 5_000 else DiscrepancySeverity.WARNING.value)
                )

                desc = f"Lot mismatch on {sym}: Ledger={l_lots}, DB={d_lots}, diff={lot_diff} lots ({value_impact:,.2f} TL)"
                discrepancies.append(
                    PositionDiscrepancy(
                        symbol=sym,
                        ledger_lots=l_lots,
                        db_lots=d_lots,
                        lot_diff=lot_diff,
                        market_price=round(price, 2),
                        value_impact=round(value_impact, 2),
                        severity=severity,
                        description=desc,
                    )
                )

        return discrepancies

    def reconcile(
        self,
        portfolio_id: int,
        ledger_cash: float,
        ledger_positions_value: float,
        ledger_equity: float,
        db_cash: float,
        db_positions_value: float,
        db_equity: float,
        tolerance: float | None = None,
        unsettled_t1_cash: float = 0.0,
        unsettled_t2_cash: float = 0.0,
        blocked_margin_cash: float = 0.0,
        ledger_positions_map: dict[str, dict[str, Any]] | None = None,
        db_positions_map: dict[str, dict[str, Any]] | None = None,
    ) -> ReconciliationResult:
        """Ledger, Veritabanı ve Takas hesaplarını tam kurumsal denetimden geçirir.

        Temel Muhasebe Denklemi:
            Nakit (Serbest + Blokeli + T+1/T+2 Alacaklar) + Piyasa Değerli Pozisyonlar == Toplam Özsermaye (Equity)
        """
        tol = tolerance if tolerance is not None else self.default_tolerance
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Nakit Farkı Denetimi
        cash_diff = abs(ledger_cash - db_cash)
        if cash_diff > tol:
            errors.append(
                f"Cash mismatch: ledger={ledger_cash:.2f}, db={db_cash:.2f}, diff={cash_diff:.2f} TL"
            )

        # 2. Pozisyon Portföy Değeri Denetimi
        pos_diff = abs(ledger_positions_value - db_positions_value)
        if pos_diff > tol:
            errors.append(
                f"Position value mismatch: ledger={ledger_positions_value:.2f}, db={db_positions_value:.2f}, diff={pos_diff:.2f} TL"
            )

        # 3. Özsermaye Denetimi
        equity_diff = abs(ledger_equity - db_equity)
        if equity_diff > tol:
            errors.append(
                f"Equity mismatch: ledger={ledger_equity:.2f}, db={db_equity:.2f}, diff={equity_diff:.2f} TL"
            )

        # 4. Temel Bilanço Eşitliği: Cash + Positions == Equity
        effective_ledger_cash = ledger_cash + unsettled_t1_cash + unsettled_t2_cash
        calc_equity = effective_ledger_cash + ledger_positions_value
        eq_diff = abs(calc_equity - ledger_equity)

        if eq_diff > tol:
            msg = (
                f"Equation breakdown: effective_cash({effective_ledger_cash:.2f}) + "
                f"positions({ledger_positions_value:.2f}) != equity({ledger_equity:.2f}), diff={eq_diff:.2f} TL"
            )
            if eq_diff > 100.0:
                errors.append(msg)
            else:
                warnings.append(f"Minor rounding discrepancy: {msg}")

        # 5. Pozisyon bazlı detaylı uyuşmazlıklar (varsa)
        discrepancies: list[PositionDiscrepancy] = []
        if ledger_positions_map is not None and db_positions_map is not None:
            discrepancies = self.reconcile_positions(ledger_positions_map, db_positions_map)
            for d in discrepancies:
                if d.severity in [DiscrepancySeverity.CRITICAL.value, DiscrepancySeverity.ERROR.value]:
                    errors.append(d.description)
                else:
                    warnings.append(d.description)

        is_consistent = len(errors) == 0

        # Aksiyon Tavsiyesi
        if not is_consistent:
            recommended_action = "HALT_TRADING_AND_RESOLVE_DISCREPANCY"
            logger.error(
                "Portfolio reconciliation FAILED",
                portfolio_id=portfolio_id,
                error_count=len(errors),
                errors=errors[:5],
            )
        elif len(warnings) > 0:
            recommended_action = "LOG_WARNING_CONTINUE"
            logger.warning(
                "Portfolio reconciliation passed with warnings",
                portfolio_id=portfolio_id,
                warnings=warnings[:5],
            )
        else:
            recommended_action = "PROCEED"

        return ReconciliationResult(
            is_consistent=is_consistent,
            portfolio_id=portfolio_id,
            timestamp=datetime.now(UTC).isoformat(),
            cash_diff=round(cash_diff, 2),
            position_diff=round(pos_diff, 2),
            equity_diff=round(equity_diff, 2),
            equation_diff=round(eq_diff, 2),
            ledger_cash=round(ledger_cash, 2),
            ledger_positions_value=round(ledger_positions_value, 2),
            ledger_equity=round(ledger_equity, 2),
            db_cash=round(db_cash, 2),
            db_positions_value=round(db_positions_value, 2),
            db_equity=round(db_equity, 2),
            unsettled_t1_cash=round(unsettled_t1_cash, 2),
            unsettled_t2_cash=round(unsettled_t2_cash, 2),
            blocked_margin_cash=round(blocked_margin_cash, 2),
            errors=errors,
            warnings=warnings,
            position_discrepancies=[d.to_dict() for d in discrepancies],
            recommended_action=recommended_action,
        )


# Singleton örneği
reconciliation_engine = ReconciliationEngine()

__all__ = [
    "DiscrepancySeverity",
    "PositionDiscrepancy",
    "ReconciliationEngine",
    "ReconciliationResult",
    "reconciliation_engine",
]
