"""
ALPHA BIST — Enhanced Event Replay Engine

Belirli bir günü/anı yeniden oynatma motoru.
- Bug reproducing
- Model debugging
- Karar audit
- State recovery

Özellikler:
1. Point-in-time data ile replay
2. Event-by-event oynatma
3. Karar karşılaştırma (expected vs actual)
4. State snapshot & restore
5. Audit trail

Referanslar:
- BACKTEST-NIHAI-SPEC.md - Event Replay
- 02-SISTEM-MIMARISI.md - 2.4 Idempotency ve tekrar-oynatılabilirlik
"""

import json
import hashlib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import structlog

logger = structlog.get_logger()


@dataclass
class SystemState:
    """Sistem durumu snapshot'ı."""
    timestamp: datetime
    cash: float
    positions: Dict[str, Dict[str, Any]]
    pending_orders: List[Dict[str, Any]]
    regime: str
    feature_cache: Dict[str, Any]
    model_version: str
    config_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cash": self.cash,
            "positions": self.positions,
            "pending_orders": self.pending_orders,
            "regime": self.regime,
            "model_version": self.model_version,
            "config_hash": self.config_hash,
        }


@dataclass
class ReplayDecision:
    """Replay sırasında verilen karar."""
    timestamp: datetime
    ticker: str
    action: str  # BUY | SELL | HOLD | NO_ACTION
    score: float
    confidence: float
    features: Dict[str, float]
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "ticker": self.ticker,
            "action": self.action,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 4),
            "features": {k: round(v, 4) for k, v in self.features.items()},
            "reasoning": self.reasoning,
        }


@dataclass
class AuditRecord:
    """Denetim kaydı."""
    event_id: str
    timestamp: datetime
    event_type: str  # market_data | signal | trade | decision | state_change
    data: Dict[str, Any]
    state_before: Optional[SystemState] = None
    state_after: Optional[SystemState] = None
    hash_chain: str = ""  # Önceki hash'e zincirleme

    def compute_hash(self, prev_hash: str = "") -> str:
        """Hash hesapla (audit trail zinciri)."""
        content = f"{self.event_id}:{self.timestamp.isoformat()}:{self.event_type}:{json.dumps(self.data, sort_keys=True)}"
        return hashlib.sha256(f"{prev_hash}:{content}".encode()).hexdigest()[:16]

    def seal(self, prev_hash: str = "") -> str:
        """Hash hesapla ve kaydet (immutable seal)."""
        self.hash_chain = self.compute_hash(prev_hash)
        return self.hash_chain


@dataclass
class ReplaySnapshot:
    """Replay anlık durumu."""
    timestamp: datetime
    equity: float
    cash: float
    positions: Dict[str, Dict]
    decisions: List[ReplayDecision]
    trades: List[Dict[str, Any]]
    market_state: Dict[str, Any]


class EnhancedReplayEngine:
    """
    Gelişmiş event replay motoru.

    "Belirli bir tarihte ne biliyorsam sadece onu kullanarak karar ver."
    """

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._audit_trail: List[AuditRecord] = []
        self._state_snapshots: List[SystemState] = []
        self._current_hash: str = "genesis"

    def register_handler(self, event_type: str, handler: Callable):
        """Event handler kaydet."""
        self._handlers[event_type] = handler
        return self

    def create_snapshot(
        self,
        timestamp: datetime,
        cash: float,
        positions: Dict[str, Dict],
        regime: str = "UNKNOWN",
        model_version: str = "v1",
        config_hash: str = "",
    ) -> SystemState:
        """Sistem durumu snapshot'ı oluştur."""
        state = SystemState(
            timestamp=timestamp,
            cash=cash,
            positions=positions.copy(),
            pending_orders=[],
            regime=regime,
            feature_cache={},
            model_version=model_version,
            config_hash=config_hash,
        )
        self._state_snapshots.append(state)
        return state

    def restore_snapshot(self, snapshot: SystemState) -> Dict[str, Any]:
        """Snapshot'tan durum geri yükle."""
        return {
            "cash": snapshot.cash,
            "positions": snapshot.positions.copy(),
            "regime": snapshot.regime,
            "model_version": snapshot.model_version,
        }

    def replay_day(
        self,
        target_date: datetime,
        market_data: pd.DataFrame,
        initial_state: SystemState,
        feature_engine: Optional[Callable] = None,
        signal_engine: Optional[Callable] = None,
    ) -> Tuple[List[ReplayDecision], List[Dict[str, Any]], List[AuditRecord]]:
        """
        Belirli bir günü yeniden oynat.

        Args:
            target_date: Oynatılacak tarih
            market_data: O güne ait piyasa verisi
            initial_state: Gün başı sistem durumu
            feature_engine: Feature hesaplama fonksiyonu
            signal_engine: Sinyal üretme fonksiyonu

        Returns:
            (decisions, trades, audit_trail)
        """
        logger.info("Starting day replay",
                    date=target_date.isoformat(),
                    initial_cash=initial_state.cash,
                    initial_positions=len(initial_state.positions))

        decisions = []
        trades = []
        self._audit_trail = []
        self._current_hash = "genesis"

        # Snapshot initial state
        self._record_event(
            timestamp=target_date,
            event_type="state_change",
            data={"type": "day_start", "state": initial_state.to_dict()},
        )

        # Current state
        state = self.restore_snapshot(initial_state)
        cash = state["cash"]
        positions = state["positions"]

        # Get day's market data
        day_data = market_data[market_data["date"] == target_date]

        if day_data.empty:
            logger.warning("No market data for date", date=target_date.isoformat())
            return decisions, trades, self._audit_trail

        # Record market data
        for _, row in day_data.iterrows():
            self._record_event(
                timestamp=target_date,
                event_type="market_data",
                data={
                    "ticker": row.get("ticker"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                },
            )

        # Compute features (point-in-time)
        features_by_ticker = {}
        if feature_engine:
            for ticker in day_data["ticker"].unique():
                # Sadece bu ana kadar olan veriyi kullan
                available_data = market_data[
                    (market_data["date"] <= target_date) &
                    (market_data["ticker"] == ticker)
                ]
                try:
                    features = feature_engine(available_data, ticker, target_date)
                    features_by_ticker[ticker] = features
                except Exception as e:
                    logger.warning("Feature engine error",
                                  ticker=ticker, error=str(e))

        # Generate signals
        if signal_engine:
            for ticker, features in features_by_ticker.items():
                try:
                    signal = signal_engine(features, ticker, target_date)
                    decision = ReplayDecision(
                        timestamp=target_date,
                        ticker=ticker,
                        action=signal.get("action", "NO_ACTION"),
                        score=signal.get("score", 0),
                        confidence=signal.get("confidence", 0),
                        features=features,
                        reasoning=signal.get("reasoning", ""),
                    )
                    decisions.append(decision)

                    self._record_event(
                        timestamp=target_date,
                        event_type="decision",
                        data=decision.to_dict(),
                    )

                    # Execute trades based on decisions
                    if decision.action == "BUY" and decision.score >= 70:
                        price = day_data[day_data["ticker"] == ticker]["close"].iloc[0]
                        quantity = self._calculate_position_size(
                            cash, price, decision.confidence
                        )
                        if quantity > 0:
                            trade = {
                                "date": str(target_date),
                                "ticker": ticker,
                                "side": "BUY",
                                "quantity": quantity,
                                "price": price,
                                "score": decision.score,
                            }
                            trades.append(trade)
                            cash -= quantity * price
                            positions[ticker] = {
                                "quantity": quantity,
                                "entry_price": price,
                                "entry_date": str(target_date),
                            }

                            self._record_event(
                                timestamp=target_date,
                                event_type="trade",
                                data=trade,
                            )

                    elif decision.action == "SELL" and ticker in positions:
                        price = day_data[day_data["ticker"] == ticker]["close"].iloc[0]
                        pos = positions[ticker]
                        trade = {
                            "date": str(target_date),
                            "ticker": ticker,
                            "side": "SELL",
                            "quantity": pos["quantity"],
                            "price": price,
                            "pnl": (price - pos["entry_price"]) * pos["quantity"],
                        }
                        trades.append(trade)
                        cash += pos["quantity"] * price
                        del positions[ticker]

                        self._record_event(
                            timestamp=target_date,
                            event_type="trade",
                            data=trade,
                        )

                except Exception as e:
                    logger.warning("Signal engine error",
                                  ticker=ticker, error=str(e))

        # Record end-of-day state
        self._record_event(
            timestamp=target_date,
            event_type="state_change",
            data={
                "type": "day_end",
                "cash": cash,
                "positions": len(positions),
                "equity": cash + sum(
                    p["quantity"] * day_data[day_data["ticker"] == t]["close"].iloc[0]
                    for t, p in positions.items()
                    if not day_data[day_data["ticker"] == t].empty
                ),
            },
        )

        logger.info("Day replay complete",
                    date=target_date.isoformat(),
                    decisions=len(decisions),
                    trades=len(trades),
                    audit_events=len(self._audit_trail))

        return decisions, trades, self._audit_trail

    def compare_decisions(
        self,
        expected: List[ReplayDecision],
        actual: List[ReplayDecision],
        tolerance: float = 0.01,
    ) -> Dict[str, Any]:
        """
        Beklenen ve gerçekleşen kararları karşılaştır.

        Args:
            expected: Beklenen kararlar
            actual: Gerçekleşen kararlar
            tolerance: Skor toleransı

        Returns:
            Karşılaştırma raporu
        """
        mismatches = []

        expected_map = {(d.ticker, d.action): d for d in expected}
        actual_map = {(d.ticker, d.action): d for d in actual}

        for key, exp in expected_map.items():
            if key in actual_map:
                act = actual_map[key]
                if abs(exp.score - act.score) > tolerance:
                    mismatches.append({
                        "ticker": exp.ticker,
                        "action": exp.action,
                        "expected_score": round(exp.score, 2),
                        "actual_score": round(act.score, 2),
                        "difference": round(abs(exp.score - act.score), 4),
                    })
            else:
                mismatches.append({
                    "ticker": exp.ticker,
                    "action": exp.action,
                    "status": "missing_in_actual",
                })

        return {
            "total_expected": len(expected),
            "total_actual": len(actual),
            "mismatches": len(mismatches),
            "is_deterministic": len(mismatches) == 0,
            "details": mismatches,
        }

    def _calculate_position_size(
        self,
        cash: float,
        price: float,
        confidence: float,
        max_position_pct: float = 0.10,
    ) -> int:
        """Pozisyon büyüklüğü hesapla."""
        max_value = cash * max_position_pct * confidence
        quantity = int(max_value / price)
        return max(0, quantity)

    def _record_event(
        self,
        timestamp: datetime,
        event_type: str,
        data: Dict[str, Any],
    ):
        """Audit event kaydet."""
        record = AuditRecord(
            event_id=f"evt_{len(self._audit_trail):06d}",
            timestamp=timestamp,
            event_type=event_type,
            data=data,
        )
        self._current_hash = record.seal(self._current_hash)
        self._audit_trail.append(record)

    def get_audit_trail(self) -> List[Dict[str, Any]]:
        """Audit trail'i döndür."""
        return [r.to_dict() for r in self._audit_trail]

    def verify_audit_integrity(self) -> bool:
        """Audit trail bütünlüğünü doğrula."""
        prev_hash = "genesis"
        for record in self._audit_trail:
            expected_hash = record.compute_hash(prev_hash)
            if record.hash_chain != expected_hash:
                logger.error("Audit trail integrity violation",
                           event_id=record.event_id)
                return False
            prev_hash = record.hash_chain
        return True


# Singleton
enhanced_replay = EnhancedReplayEngine()
