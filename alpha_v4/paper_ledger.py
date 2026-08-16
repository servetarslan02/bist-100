"""Persistent event-sourced paper portfolio ledger for ALPHA v4.

This module is simulation-only. It has no broker connectivity and cannot place real
orders. Every mutation is append-only and portfolio state is reconstructed from the
ledger, making restart/replay tests possible.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class PaperLedgerError(RuntimeError):
    pass


class InsufficientCashError(PaperLedgerError):
    pass


class InsufficientPositionError(PaperLedgerError):
    pass


class MissingMarkError(PaperLedgerError):
    pass


@dataclass(frozen=True)
class PositionState:
    ticker: str
    quantity: float
    average_cost: float


@dataclass(frozen=True)
class PaperAccountState:
    account_id: str
    cash: float
    positions: Mapping[str, PositionState]
    realized_pnl: float
    fees_paid: float
    event_count: int


@dataclass(frozen=True)
class MarkedPaperState:
    account: PaperAccountState
    market_value: float
    equity: float
    unrealized_pnl: float


class PaperLedger:
    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_ledger_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    account_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    decision_id TEXT,
                    risk_decision_id TEXT,
                    model_id TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_paper_account_seq
                    ON paper_ledger_events(account_id, sequence);
                """
            )

    def _append(
        self,
        *,
        account_id: str,
        event_type: str,
        event_time: datetime,
        payload: Mapping[str, object],
        decision_id: str | None = None,
        risk_decision_id: str | None = None,
        model_id: str | None = None,
        event_id: str | None = None,
    ) -> str:
        if not account_id.strip():
            raise ValueError("account_id is required")
        event_id = event_id or uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_ledger_events (
                    event_id, account_id, event_type, event_time,
                    decision_id, risk_decision_id, model_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    account_id,
                    event_type,
                    event_time.isoformat(),
                    decision_id,
                    risk_decision_id,
                    model_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
        return event_id

    def deposit(
        self,
        account_id: str,
        amount: float,
        *,
        event_time: datetime,
        event_id: str | None = None,
    ) -> str:
        if amount <= 0:
            raise ValueError("deposit amount must be positive")
        return self._append(
            account_id=account_id,
            event_type="DEPOSIT",
            event_time=event_time,
            payload={"amount": float(amount)},
            event_id=event_id,
        )

    def record_fill(
        self,
        account_id: str,
        *,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
        commission: float,
        event_time: datetime,
        decision_id: str,
        risk_decision_id: str,
        model_id: str,
        event_id: str | None = None,
    ) -> str:
        """Record a simulated fill only after portfolio constraints are checked."""
        if not ticker.strip():
            raise ValueError("ticker is required")
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        if commission < 0:
            raise ValueError("commission cannot be negative")
        for value, name in (
            (decision_id, "decision_id"),
            (risk_decision_id, "risk_decision_id"),
            (model_id, "model_id"),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required for paper fills")

        state = self.reconstruct(account_id)
        gross = quantity * price
        if side == "BUY":
            required_cash = gross + commission
            if state.cash + 1e-9 < required_cash:
                raise InsufficientCashError(
                    f"required={required_cash:.8f}, available={state.cash:.8f}"
                )
        else:
            position = state.positions.get(ticker)
            available = 0.0 if position is None else position.quantity
            if available + 1e-12 < quantity:
                raise InsufficientPositionError(
                    f"required={quantity:.8f}, available={available:.8f}"
                )

        return self._append(
            account_id=account_id,
            event_type=f"{side}_FILL",
            event_time=event_time,
            decision_id=decision_id,
            risk_decision_id=risk_decision_id,
            model_id=model_id,
            payload={
                "ticker": ticker,
                "quantity": float(quantity),
                "price": float(price),
                "commission": float(commission),
                "simulation_only": True,
            },
            event_id=event_id,
        )

    def reconstruct(self, account_id: str) -> PaperAccountState:
        cash = 0.0
        realized_pnl = 0.0
        fees_paid = 0.0
        positions: dict[str, PositionState] = {}

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM paper_ledger_events
                WHERE account_id = ?
                ORDER BY sequence ASC
                """,
                (account_id,),
            ).fetchall()

        for row in rows:
            payload = json.loads(row["payload_json"])
            event_type = row["event_type"]
            if event_type == "DEPOSIT":
                cash += float(payload["amount"])
                continue

            ticker = str(payload["ticker"])
            quantity = float(payload["quantity"])
            price = float(payload["price"])
            commission = float(payload["commission"])
            fees_paid += commission

            if event_type == "BUY_FILL":
                cash -= quantity * price + commission
                previous = positions.get(ticker)
                previous_qty = 0.0 if previous is None else previous.quantity
                previous_cost = (
                    0.0
                    if previous is None
                    else previous.average_cost * previous.quantity
                )
                # Buy commission is part of economic acquisition cost.
                new_qty = previous_qty + quantity
                new_total_cost = previous_cost + quantity * price + commission
                positions[ticker] = PositionState(
                    ticker=ticker,
                    quantity=new_qty,
                    average_cost=new_total_cost / new_qty,
                )
            elif event_type == "SELL_FILL":
                previous = positions.get(ticker)
                if previous is None or previous.quantity + 1e-12 < quantity:
                    raise PaperLedgerError("corrupt ledger: sell exceeds position")
                net_proceeds = quantity * price - commission
                cash += net_proceeds
                realized_pnl += net_proceeds - quantity * previous.average_cost
                remaining = previous.quantity - quantity
                if remaining <= 1e-12:
                    positions.pop(ticker, None)
                else:
                    positions[ticker] = PositionState(
                        ticker=ticker,
                        quantity=remaining,
                        average_cost=previous.average_cost,
                    )
            else:
                raise PaperLedgerError(f"unknown ledger event: {event_type}")

        return PaperAccountState(
            account_id=account_id,
            cash=cash,
            positions=dict(positions),
            realized_pnl=realized_pnl,
            fees_paid=fees_paid,
            event_count=len(rows),
        )

    def mark_to_market(
        self, account_id: str, marks: Mapping[str, float]
    ) -> MarkedPaperState:
        state = self.reconstruct(account_id)
        market_value = 0.0
        unrealized = 0.0
        for ticker, position in state.positions.items():
            if ticker not in marks:
                raise MissingMarkError(f"missing market mark for {ticker}")
            mark = float(marks[ticker])
            if mark <= 0:
                raise MissingMarkError(f"invalid market mark for {ticker}")
            market_value += position.quantity * mark
            unrealized += position.quantity * (mark - position.average_cost)

        return MarkedPaperState(
            account=state,
            market_value=market_value,
            equity=state.cash + market_value,
            unrealized_pnl=unrealized,
        )
