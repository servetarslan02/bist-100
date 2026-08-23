"""
ALPHA BIST — Paper Trading Orchestrator v2.0 (Institutional BIST Engine)

Kurumsal BIST Seans, Risk, Eşleşme ve T+2 Takas Entegrasyonu:
- Model Signals (Top N Alpha)
- Pre-Trade Risk & Uygunluk Kapısı (BIST Fiyat Adımları, Tavan/Taban Marjı, Brüt Takas)
- Seans Durum Makinesi (Açılış/Kapanış Açık Artırması, Sürekli Müzayede, Kapanış Fiyatından İşlemler)
- T+2 Takas ve Valörlü Bakiye Takibi
- Tam Audit Trail ve Performans Metrikleri
"""

import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import structlog

from .virtual_portfolio import VirtualPortfolio
from .paper_execution import PaperExecutionEngine, paper_execution
from .state_store import PaperStateStore, paper_state_store
from .performance_tracker import PerformanceTracker, performance_tracker
from .paper_risk_gate import PaperRiskGate
from services.core.market_session_fsm import BISTMarketPhase, bist_session_fsm
from services.core.bist_tick_size import round_to_bist_tick

logger = structlog.get_logger()


class PaperTradingOrchestrator:
    """Institutional BIST Paper Trading Orchestrator."""

    def __init__(
        self,
        champion_version: str = "LambdaRank_v3_LOCKED",
        initial_capital: float = 1_000_000.0,
        db_path: str = "data/paper_trading_state.db",
        store: Optional[PaperStateStore] = None,
        execution: Optional[PaperExecutionEngine] = None,
    ):
        self._champion_version = champion_version
        self.initial_capital = initial_capital
        self.store = store or PaperStateStore(db_path=db_path)
        self.portfolio = VirtualPortfolio(initial_capital=initial_capital, state_store=self.store)
        self.execution = execution or paper_execution
        self.performance = PerformanceTracker()
        self.risk_gate = PaperRiskGate()

        # State store'dan yükle
        self.portfolio.load_from_store()

        logger.info("PaperTradingOrchestrator initialized",
                    champion=self._champion_version,
                    initial_capital=initial_capital)

    def process_daily_cycle(
        self,
        date: str,
        signals: List[Dict[str, Any]],
        prices: Dict[str, float],
        volumes: Optional[Dict[str, int]] = None,
        reference_prices: Optional[Dict[str, float]] = None,
        sector_map: Optional[Dict[str, str]] = None,
        benchmark_return_pct: float = 0.0,
        circuit_breaker_active: bool = False,
    ) -> Dict[str, Any]:
        """Günlük simülasyon döngüsünü kurumsal BIST kurallarıyla çalıştırır."""
        logger.info("Starting daily paper trading cycle", date=date, num_signals=len(signals))

        orders_today: List[Dict[str, Any]] = []
        trades_today: List[Dict[str, Any]] = []
        errors: List[str] = []

        volumes = volumes or {}
        reference_prices = reference_prices or {}
        sector_map = sector_map or {}
        previous_equity = self.portfolio.get_total_value()

        # 1. Devre Kesici Kontrolü
        if circuit_breaker_active or self.risk_gate.is_kill_switch_active():
            msg = "Kill switch active or Circuit Breaker engaged — NO_TRADE"
            logger.warning(msg)
            self._audit_no_trade(date, msg)
            return {"status": "HALTED", "reason": msg, "date": date}

        # 2. Champion Model Sinyal Filtreleme
        valid_signals = [s for s in signals if s.get("model_version") == self._champion_version]
        if not valid_signals:
            msg = "No valid champion signals — NO_TRADE"
            logger.warning(msg)
            self._audit_no_trade(date, msg)
            return {"status": "NO_TRADE", "reason": msg, "date": date}

        # 3. Sinyal -> Risk -> Seans -> Eşleşme
        for sig in valid_signals:
            try:
                res = self._process_signal(date, sig, prices, volumes, reference_prices, sector_map)
                if res.get("order"):
                    orders_today.append(res["order"])
                if res.get("trade"):
                    trades_today.append(res["trade"])
            except Exception as e:
                err = f"Signal processing error for {sig.get('ticker')}: {e}"
                logger.error(err)
                errors.append(err)
                self._audit_error(date, "SIGNAL_PROCESSING", str(e), sig.get("ticker"))

        # 4. Fiyatları Mark-to-Market Güncelle
        self.portfolio.update_prices(prices, date)

        # 5. Seans Sonu T+2 Takas Valörlerini Kaydır (T+2 -> T+1 -> Settled)
        self.portfolio.roll_settlement_day()

        # 6. Performans ve Raporlama
        perf = self.performance.compute_daily_performance(
            date=date,
            portfolio_value=self.portfolio.get_total_value(),
            cash=self.portfolio.cash,
            initial_capital=self.portfolio.initial_capital,
            trades_today=trades_today,
            orders_today=orders_today,
            num_positions=len(self.portfolio.get_all_positions()),
            benchmark_return_pct=benchmark_return_pct,
            prev_portfolio_value=previous_equity,
        )
        self._audit_performance(date, perf)

        # 7. Kalıcı Durumu Kaydet
        self.portfolio.save_to_store(date)

        return {
            "status": "COMPLETED",
            "date": date,
            "portfolio_summary": self.portfolio.get_summary(),
            "num_signals": len(valid_signals),
            "num_orders": len(orders_today),
            "num_trades": len(trades_today),
            "num_errors": len(errors),
            "daily_performance": perf,
            "errors": errors,
        }

    def _process_signal(
        self,
        date: str,
        signal: Dict[str, Any],
        prices: Dict[str, float],
        volumes: Dict[str, int],
        reference_prices: Dict[str, float],
        sector_map: Dict[str, str],
    ) -> Dict[str, Any]:
        ticker = signal.get("ticker", "")
        direction = signal.get("direction", "")
        price = prices.get(ticker, 0.0)
        volume = volumes.get(ticker, 1_000_000)
        reference_price = reference_prices.get(ticker, price)
        sector = sector_map.get(ticker, signal.get("sector", ""))

        if price <= 0:
            self._audit_no_trade(date, f"No price for {ticker}", ticker)
            return {}

        self._audit_signal(date, signal)

        # Alış veya Satış Yönü
        if direction == "LONG":
            side = "BUY"
            if ticker in self.portfolio._positions:
                self._audit_no_trade(date, f"Already holding {ticker}", ticker)
                return {}
            total_value = self.portfolio.get_total_value()
            target_weight = min(self.risk_gate.max_position_pct / 100.0, 0.1)
            quantity = int((total_value * target_weight) / price)
        elif direction == "SHORT":
            if ticker not in self.portfolio._positions:
                self._audit_no_trade(date, f"No position to exit for {ticker}", ticker)
                return {}
            side = "SELL"
            quantity = self.portfolio._positions[ticker]["quantity"]
        else:
            self._audit_no_trade(date, f"Unknown direction: {direction}", ticker)
            return {}

        if quantity <= 0:
            self._audit_no_trade(date, f"Quantity too small for {ticker}", ticker)
            return {}

        # Risk Kapısı
        risk_checks = self.risk_gate.check_all(
            portfolio=self.portfolio,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            sector=sector,
            data_quality_ok=True,
            model_version_valid=(signal.get("model_version") == self._champion_version),
        )
        if not self.risk_gate.is_trade_allowed(risk_checks):
            reason = self.risk_gate.get_block_reason(risk_checks)
            self._audit_no_trade(date, f"Risk gate blocked: {reason}", ticker)
            return {}

        # Ertesi Seans Açılışı (T+1 Open) / Stokastik Gecelik Gap
        next_open = signal.get("next_open_price")
        if next_open is not None and next_open > 0:
            market_price = float(next_open)
        else:
            _vol = 0.25
            gap_pct = float(np.clip(np.random.normal(0.0, _vol / 20.0), -0.03, 0.03))
            market_price = price * (1.0 + gap_pct)

        market_price = round_to_bist_tick(market_price, side=side)

        order = self.execution.execute_signal(
            date=date,
            ticker=ticker,
            side=side,
            quantity=quantity,
            signal_price=price,
            market_price=market_price,
            avg_volume=volume,
            volatility=0.25,
            spread_pct=0.1,
            sector=sector,
            reference_price=reference_price,
            is_halted=bool(signal.get("is_halted", False)),
        )

        self._audit_order(date, order)
        self.store.save_order(order)

        if order["status"] not in ["FILLED", "PARTIAL_FILL"]:
            return {"order": order}

        executed_qty = order["quantity"]
        if side == "BUY":
            res = self.portfolio.open_position(
                ticker=ticker,
                quantity=executed_qty,
                price=order["execution_price"],
                sector=sector,
                date=date,
                commission=order["commission"],
                is_gross_settlement=bool(signal.get("is_gross_settlement", False)),
            )
        else:
            res = self.portfolio.close_position(
                ticker=ticker,
                price=order["execution_price"],
                quantity=executed_qty,
                date=date,
                commission=order["commission"],
                reason="EXIT_SIGNAL",
            )
            if res.get("success") and res.get("trade"):
                return {"order": order, "trade": res["trade"]}

        return {"order": order}

    # ===================== AUDIT HELPERS =====================

    def _audit_signal(self, date: str, signal: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "entry_type": "SIGNAL",
            "ticker": signal.get("ticker"),
            "signal": signal.get("direction"),
            "rank": signal.get("rank"),
            "model_version": signal.get("model_version"),
            "predicted_probability": signal.get("confidence"),
            "reason": f"score={signal.get('score')}",
        }
        self.store.append_audit(entry)

    def _audit_order(self, date: str, order: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "entry_type": "ORDER",
            "ticker": order["ticker"],
            "execution_price": order.get("execution_price"),
            "slippage": order.get("slippage_pct"),
            "reason": f"status={order['status']}, qty={order['quantity']}",
        }
        self.store.append_audit(entry)

    def _audit_performance(self, date: str, perf: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "entry_type": "PERFORMANCE",
            "reason": f"portfolio_value={perf['portfolio_value']:.2f}, return={perf['cumulative_return_pct']:.2f}%",
        }
        self.store.append_audit(entry)

    def _audit_no_trade(self, date: str, reason: str, ticker: Optional[str] = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "entry_type": "NO_TRADE",
            "ticker": ticker,
            "reason": reason,
        }
        self.store.append_audit(entry)

    def _audit_error(self, date: str, error_type: str, message: str, ticker: Optional[str] = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "entry_type": "ERROR",
            "ticker": ticker,
            "reason": f"{error_type}: {message}",
        }
        self.store.append_audit(entry)


paper_orchestrator = PaperTradingOrchestrator()
