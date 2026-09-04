"""
ALPHA BIST — Gelişmiş Event Replay Motoru

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

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import orjson

try:
    import polars as pl
except ImportError:
    pl = None

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SystemState:
    """Sistem durumu snapshot'ı.

    Belirli bir andaki tüm sistem durumunu tutar.
    Audit trail ve state recovery için kullanılır.
    """

    timestamp: datetime
    cash: float
    positions: dict[str, dict[str, Any]]
    pending_orders: list[dict[str, Any]]
    regime: str
    feature_cache: dict[str, Any]
    model_version: str
    config_hash: str

    def __repr__(self) -> str:
        """SystemState okunabilir temsili."""
        return (
            f"SystemState("
            f"cash={self.cash:,.0f}, "
            f"positions={len(self.positions)}, "
            f"regime={self.regime!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Sistem durumunu sözlük formatına dönüştürür.

        Returns:
            Durum bilgilerini içeren sözlük
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "cash": self.cash,
            "positions": self.positions,
            "pending_orders": self.pending_orders,
            "regime": self.regime,
            "feature_cache": self.feature_cache,
            "model_version": self.model_version,
            "config_hash": self.config_hash,
        }


@dataclass
class ReplayDecision:
    """Replay sırasında verilen karar.

    Her bir ticaret kararını ve gerekçesini tutar.
    """

    timestamp: datetime
    ticker: str
    action: str  # BUY | SELL | HOLD | NO_ACTION
    score: float
    confidence: float
    features: dict[str, float]
    reasoning: str

    def __repr__(self) -> str:
        """ReplayDecision okunabilir temsili."""
        return (
            f"ReplayDecision("
            f"ticker={self.ticker!r}, "
            f"action={self.action!r}, "
            f"score={self.score:.2f}, "
            f"confidence={self.confidence:.4f})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Kararı sözlük formatına dönüştürür.

        Returns:
            Karar bilgilerini içeren sözlük
        """
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
    """Denetim kaydı.

    Audit trail zincirindeki her bir olayı tutar.
    Hash zinciri ile bütünlük doğrulaması sağlar.
    """

    event_id: str
    timestamp: datetime
    event_type: str  # market_data | signal | trade | decision | state_change
    data: dict[str, Any]
    state_before: SystemState | None = None
    state_after: SystemState | None = None
    hash_chain: str = ""  # Önceki hash'e zincirleme

    def __repr__(self) -> str:
        """AuditRecord okunabilir temsili."""
        return (
            f"AuditRecord("
            f"id={self.event_id!r}, "
            f"type={self.event_type!r}, "
            f"hash={self.hash_chain!r})"
        )

    def compute_hash(self, prev_hash: str = "") -> str:
        """Hash hesapla (audit trail zinciri).

        Args:
            prev_hash: Önceki kayıt hash'i

        Returns:
            SHA-256 tabanlı 16 karakterlik hash
        """
        content = (
            f"{self.event_id}:{self.timestamp.isoformat()}:"
            f"{self.event_type}:"
            f"{orjson.dumps(self.data, option=orjson.OPT_SORT_KEYS).decode()}"
        )
        return hashlib.sha256(f"{prev_hash}:{content}".encode()).hexdigest()[:16]

    def seal(self, prev_hash: str = "") -> str:
        """Hash hesapla ve kaydet (immutable seal).

        Args:
            prev_hash: Önceki kayıt hash'i

        Returns:
            Hesaplanan hash
        """
        self.hash_chain = self.compute_hash(prev_hash)
        return self.hash_chain


@dataclass
class ReplaySnapshot:
    """Replay anlık durumu.

    Replay sırasında belirli bir andaki tüm durumu tutar.
    """

    timestamp: datetime
    equity: float
    cash: float
    positions: dict[str, dict]
    decisions: list[ReplayDecision]
    trades: list[dict[str, Any]]
    market_state: dict[str, Any]

    def __repr__(self) -> str:
        """ReplaySnapshot okunabilir temsili."""
        return (
            f"ReplaySnapshot("
            f"equity={self.equity:,.0f}, "
            f"cash={self.cash:,.0f}, "
            f"positions={len(self.positions)}, "
            f"decisions={len(self.decisions)})"
        )


class EnhancedReplayEngine:
    """
    Gelişmiş event replay motoru.

    "Belirli bir tarihte ne biliyorsam sadece onu kullanarak karar ver."
    """

    def __init__(self) -> None:
        """Event replay motorunu başlatır."""
        self._handlers: dict[str, Callable] = {}
        self._audit_trail: list[AuditRecord] = []
        self._state_snapshots: list[SystemState] = []
        self._current_hash: str = "genesis"

    def __repr__(self) -> str:
        """EnhancedReplayEngine okunabilir temsili."""
        return (
            f"EnhancedReplayEngine("
            f"handlers={len(self._handlers)}, "
            f"audit_events={len(self._audit_trail)}, "
            f"snapshots={len(self._state_snapshots)})"
        )

    def register_handler(self, event_type: str, handler: Callable) -> None:
        """Event handler kaydet.

        Args:
            event_type: Olay tipi
            handler: İşleyici fonksiyon
        """
        self._handlers[event_type] = handler

    def create_snapshot(
        self,
        timestamp: datetime,
        cash: float,
        positions: dict[str, dict],
        regime: str = "UNKNOWN",
        model_version: str = "v1",
        config_hash: str = "",
    ) -> SystemState:
        """Sistem durumu snapshot'ı oluştur.

        Args:
            timestamp: Zaman damgası
            cash: Nakit miktarı
            positions: Pozisyon sözlüğü
            regime: Piyasa rejimi
            model_version: Model versiyonu
            config_hash: Konfigürasyon hash'i

        Returns:
            SystemState nesnesi
        """
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
        if len(self._state_snapshots) > 1000:
            self._state_snapshots = self._state_snapshots[-1000:]
        return state

    def restore_snapshot(self, snapshot: SystemState) -> dict[str, Any]:
        """Snapshot'tan durum geri yükle.

        Args:
            snapshot: Geri yüklenecek snapshot

        Returns:
            Durum sözlüğü
        """
        return {
            "cash": snapshot.cash,
            "positions": snapshot.positions.copy(),
            "regime": snapshot.regime,
            "model_version": snapshot.model_version,
        }

    def replay_day(
        self,
        target_date: datetime,
        market_data: pl.DataFrame,
        initial_state: SystemState,
        feature_engine: Callable | None = None,
        signal_engine: Callable | None = None,
    ) -> tuple[list[ReplayDecision], list[dict[str, Any]], list[AuditRecord]]:
        """
        Belirli bir günü yeniden oynat.

        Args:
            target_date: Oynatılacak tarih
            market_data: O güne ait piyasa verisi
            initial_state: Gün başı sistem durumu
            feature_engine: Feature hesaplama fonksiyonu
            signal_engine: Sinyal üretme fonksiyonu

        Returns:
            (decisions, trades, audit_trail) üçlüsü
        """
        logger.info(
            "gun_replay_baslatiliyor: tarih=%s, nakit=%s, pozisyon=%s",
            target_date.isoformat(),
            initial_state.cash,
            len(initial_state.positions),
        )

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
        day_data = market_data.filter(pl.col("date") == target_date)

        if day_data.is_empty():
            logger.warning(
                "tarih_icin_piyasa_verisi_yok: tarih=%s",
                target_date.isoformat(),
            )
            return decisions, trades, self._audit_trail

        # Record market data
        for row in day_data.iter_rows(named=True):
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
            for ticker in day_data["ticker"].unique().to_list():
                # Sadece bu ana kadar olan veriyi kullan
                available_data = market_data.filter(
                    (pl.col("date") <= target_date) & (pl.col("ticker") == ticker)
                )
                try:
                    features = feature_engine(available_data, ticker, target_date)
                    features_by_ticker[ticker] = features
                except Exception as e:
                    logger.warning(
                        "feature_engine_hatasi: ticker=%s, hata=%s",
                        ticker,
                        str(e),
                    )

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
                        ticker_rows = day_data.filter(pl.col("ticker") == ticker)
                        if not ticker_rows.is_empty():
                            price = ticker_rows["close"].item(0)
                            quantity = self._calculate_position_size(cash, price, decision.confidence)
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
                        ticker_rows = day_data.filter(pl.col("ticker") == ticker)
                        if not ticker_rows.is_empty():
                            price = ticker_rows["close"].item(0)
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
                    logger.warning(
                        "signal_engine_hatasi: ticker=%s, hata=%s",
                        ticker,
                        str(e),
                    )

        # Record end-of-day state
        equity = cash
        for ticker, pos in positions.items():
            ticker_rows = day_data.filter(pl.col("ticker") == ticker)
            if not ticker_rows.is_empty():
                equity += pos["quantity"] * ticker_rows["close"].item(0)

        self._record_event(
            timestamp=target_date,
            event_type="state_change",
            data={
                "type": "day_end",
                "cash": cash,
                "positions": len(positions),
                "equity": equity,
            },
        )

        logger.info(
            "gun_replay_tamamlandi: tarih=%s, karar=%s, islem=%s, audit=%s",
            target_date.isoformat(),
            len(decisions),
            len(trades),
            len(self._audit_trail),
        )

        return decisions, trades, self._audit_trail

    def compare_decisions(
        self,
        expected: list[ReplayDecision],
        actual: list[ReplayDecision],
        tolerance: float = 0.01,
    ) -> dict[str, Any]:
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
                    mismatches.append(
                        {
                            "ticker": exp.ticker,
                            "action": exp.action,
                            "expected_score": round(exp.score, 2),
                            "actual_score": round(act.score, 2),
                            "difference": round(abs(exp.score - act.score), 4),
                        }
                    )
            else:
                mismatches.append(
                    {
                        "ticker": exp.ticker,
                        "action": exp.action,
                        "status": "missing_in_actual",
                    }
                )

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
        """Pozisyon büyüklüğü hesapla.

        Args:
            cash: Mevcut nakit
            price: Hisse fiyatı
            confidence: Model güven skoru
            max_position_pct: Maksimum pozisyon yüzdesi

        Returns:
            Alınacak hisse adedi
        """
        max_value = cash * max_position_pct * confidence
        quantity = int(max_value / price)
        return max(0, quantity)

    def _record_event(
        self,
        timestamp: datetime,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Audit event kaydet.

        Args:
            timestamp: Zaman damgası
            event_type: Olay tipi
            data: Olay verisi
        """
        record = AuditRecord(
            event_id=f"evt_{len(self._audit_trail):06d}",
            timestamp=timestamp,
            event_type=event_type,
            data=data,
        )
        self._current_hash = record.seal(self._current_hash)
        self._audit_trail.append(record)
        if len(self._audit_trail) > 1000:
            self._audit_trail = self._audit_trail[-1000:]

    def get_audit_trail(self) -> list[dict[str, Any]]:
        """Audit trail'i döndür.

        Returns:
            Audit kayıtlarının sözlük listesi
        """
        return [r.to_dict() for r in self._audit_trail]

    def verify_audit_integrity(self) -> bool:
        """Audit trail bütünlüğünü doğrula.

        Returns:
            True ise zincir bozulmamış
        """
        prev_hash = "genesis"
        for record in self._audit_trail:
            expected_hash = record.compute_hash(prev_hash)
            if record.hash_chain != expected_hash:
                logger.error(
                    "audit_bütünlük_ihlali: event_id=%s",
                    record.event_id,
                )
                return False
            prev_hash = record.hash_chain
        return True


# Singleton
enhanced_replay = EnhancedReplayEngine()
