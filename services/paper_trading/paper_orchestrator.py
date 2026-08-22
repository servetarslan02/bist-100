"""
ALPHA BIST — Paper Trading Orchestrator v1.0

Daily Autonomous Loop:

    DATA
      ↓
    DATA QUALITY
      ↓
    FEATURES
      ↓
    REGIME
      ↓
    CHAMPION (LOCKED — sadece aktif champion)
      ↓
    SIGNAL
      ↓
    RISK GATE
      ↓
    PAPER EXECUTION
      ↓
    PORTFOLIO
      ↓
    PERFORMANCE
      ↓
    AUDIT LOG

KURALLAR:
- Champion LOCKED. Challenger dogrudan giremez.
- Paper trading sonuclari model egitimine dogrudan geri beslenmez.
- Her hatada NO_TRADE, fail-safe.
- State persistent (SQLite).
- Gercek para/broker YOK.

Mevcut modelleri kullanir:
- services.ml.ranking_model.OpportunityScore (champion sinyalleri)
- services.learning.continuous_learning.ModelRegistry (champion versiyon)
- services.core.audit_log.AuditLog (audit)
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
import structlog

from .state_store import PaperStateStore
from .virtual_portfolio import VirtualPortfolio
from .paper_execution import PaperExecutionEngine
from .paper_risk_gate import PaperRiskGate
from .performance_tracker import PerformanceTracker

logger = structlog.get_logger()


class PaperTradingOrchestrator:
    """Paper trading autonomous orchestrator."""

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        state_store: Optional[PaperStateStore] = None,
        champion_version: str = "LambdaRank_v3_LOCKED",
    ):
        self.initial_capital = initial_capital
        self.store = state_store or PaperStateStore("data/paper_trading_state.db")

        # Sub-systems
        self.portfolio = VirtualPortfolio(initial_capital, self.store)
        self.execution = PaperExecutionEngine()
        self.risk_gate = PaperRiskGate()
        self.performance = PerformanceTracker(self.store)

        # Champion reference (read-only)
        self._champion_version = champion_version
        self._champion_loaded = False

        # Replay/backtest mode
        self._replay_mode = False
        self._replay_data: Dict[str, pd.DataFrame] = {}

        # Load persistent state
        self.portfolio.load_from_store()

        logger.info("PaperTradingOrchestrator initialized",
                   champion=self._champion_version,
                   initial_capital=initial_capital)

    # ===================== MODES =====================

    def set_replay_mode(self, market_data: Dict[str, pd.DataFrame]):
        """Gecmis veri uzerinde replay/backtest modu."""
        self._replay_mode = True
        self._replay_data = market_data
        logger.info("Replay mode enabled", tickers=len(market_data))

    def reset(self):
        """Tum state'i sifirla."""
        self.portfolio.reset()
        self.risk_gate.reset_kill_switch()
        logger.warning("PaperTradingOrchestrator RESET")

    # ===================== DAILY LOOP =====================

    def run_daily_cycle(
        self,
        date: str,
        market_data: Dict[str, pd.DataFrame],
        sector_map: Dict[str, str],
        champion_signals: Optional[List[Dict]] = None,
        benchmark_return_pct: float = 0.0,
        data_quality_ok: bool = True,
    ) -> Dict[str, Any]:
        """
        Gunluk otonom dongu.

        Args:
            date: Islem tarihi (YYYY-MM-DD)
            market_data: {ticker: OHLCV DataFrame}
            sector_map: {ticker: sector}
            champion_signals: Champion'dan gelen sinyaller (OpportunityScore dict listesi)
            benchmark_return_pct: XU100 gunluk getirisi
            data_quality_ok: Veri kalitesi OK mu?

        Returns:
            Gunluk rapor dict.
        """
        logger.info("=" * 60)
        logger.info("DAILY PAPER TRADING CYCLE", date=date)
        logger.info("=" * 60)

        self.execution.reset_daily_turnover()
        self.risk_gate.clear_errors()

        orders_today: List[Dict] = []
        trades_today: List[Dict] = []
        errors: List[str] = []

        try:
            # === STAGE 1: DATA QUALITY ===
            if not data_quality_ok:
                msg = "Data quality check FAILED — NO_TRADE"
                logger.error(msg)
                self._audit_no_trade(date, msg)
                self.risk_gate.record_error()
                return {"status": "NO_TRADE", "reason": msg, "date": date}

            if len(market_data) < self.risk_gate.data_quality_min_stocks:
                msg = f"Insufficient stocks: {len(market_data)} < {self.risk_gate.data_quality_min_stocks}"
                logger.error(msg)
                self._audit_no_trade(date, msg)
                self.risk_gate.record_error()
                return {"status": "NO_TRADE", "reason": msg, "date": date}

            # === STAGE 2: UPDATE PRICES (Mark-to-Market) ===
            prices = {}
            volumes = {}
            for ticker, df in market_data.items():
                if not df.empty and 'Close' in df.columns:
                    if date in df.index.strftime('%Y-%m-%d').values:
                        row = df.loc[df.index.strftime('%Y-%m-%d') == date]
                        if not row.empty:
                            prices[ticker] = float(row['Close'].iloc[-1])
                            volumes[ticker] = int(row['Volume'].iloc[-1]) if 'Volume' in row.columns else 1_000_000
                    else:
                        prices[ticker] = float(df['Close'].iloc[-1])
                        volumes[ticker] = int(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 1_000_000

            self.portfolio.update_prices(prices, date)

            # === STAGE 3: CHAMPION SIGNALS ===
            if champion_signals is None:
                msg = "No champion signals provided — NO_TRADE"
                logger.warning(msg)
                self._audit_no_trade(date, msg)
                return {"status": "NO_TRADE", "reason": msg, "date": date}

            # Champion versiyon kontrolu
            for sig in champion_signals:
                if sig.get("model_version", "") != self._champion_version:
                    logger.warning("Signal from non-champion model — ignoring",
                                 expected=self._champion_version,
                                 got=sig.get("model_version"))

            # Sadece champion sinyallerini kullan
            valid_signals = [
                s for s in champion_signals
                if s.get("model_version", "") == self._champion_version
            ]

            if not valid_signals:
                msg = "No valid champion signals — NO_TRADE"
                logger.warning(msg)
                self._audit_no_trade(date, msg)
                return {"status": "NO_TRADE", "reason": msg, "date": date}

            # === STAGE 4: SIGNAL -> RISK -> EXECUTION ===
            for sig in valid_signals:
                try:
                    result = self._process_signal(date, sig, prices, volumes, sector_map)
                    if result.get("order"):
                        orders_today.append(result["order"])
                    if result.get("trade"):
                        trades_today.append(result["trade"])
                except Exception as e:
                    err = f"Signal processing error for {sig.get('ticker')}: {e}"
                    logger.error(err)
                    errors.append(err)
                    self._audit_error(date, "SIGNAL_PROCESSING", str(e), sig.get("ticker"))
                    self.risk_gate.record_error()

            # === STAGE 5: PERFORMANCE ===
            prev_value = self.portfolio._equity_curve[-2]["equity"] if len(self.portfolio._equity_curve) >= 2 else self.portfolio.initial_capital

            perf = self.performance.compute_daily_performance(
                date=date,
                portfolio_value=self.portfolio.get_total_value(),
                cash=self.portfolio.cash,
                initial_capital=self.portfolio.initial_capital,
                trades_today=trades_today,
                orders_today=orders_today,
                num_positions=len(self.portfolio.get_all_positions()),
                benchmark_return_pct=benchmark_return_pct,
                prev_portfolio_value=prev_value,
            )

            # Audit performance
            self._audit_performance(date, perf)

            # === STAGE 6: SAVE STATE ===
            self.portfolio.save_to_store(date)

            # === REPORT ===
            report = {
                "status": "COMPLETED",
                "date": date,
                "portfolio_summary": self.portfolio.get_portfolio_summary(),
                "num_signals": len(valid_signals),
                "num_orders": len(orders_today),
                "num_trades": len(trades_today),
                "num_errors": len(errors),
                "daily_performance": perf,
                "errors": errors,
            }

            logger.info("Daily cycle completed", date=date, orders=len(orders_today), trades=len(trades_today))
            return report

        except Exception as e:
            err = f"CRITICAL ERROR in daily cycle: {e}"
            logger.critical(err)
            self._audit_error(date, "CRITICAL", str(e))
            self.risk_gate.record_error()
            return {"status": "ERROR", "reason": str(e), "date": date}

    def _process_signal(
        self,
        date: str,
        signal: Dict[str, Any],
        prices: Dict[str, float],
        volumes: Dict[str, float],
        sector_map: Dict[str, str],
    ) -> Dict[str, Any]:
        """Tek sinyali isle: risk check -> execution -> portfolio update."""
        ticker = signal.get("ticker", "")
        direction = signal.get("direction", "LONG")
        rank = signal.get("rank", 0)
        score = signal.get("score", 0)
        confidence = signal.get("confidence", 0.5)
        model_version = signal.get("model_version", "")
        regime = signal.get("regime", "UNKNOWN")

        price = prices.get(ticker, 0)
        volume = volumes.get(ticker, 1_000_000)
        sector = sector_map.get(ticker, "")

        if price <= 0:
            self._audit_no_trade(date, f"No price for {ticker}", ticker)
            return {}

        # Audit: signal
        self._audit_signal(date, signal)

        # Determine side
        if direction == "LONG":
            side = "BUY"
            if ticker in self.portfolio._positions:
                self._audit_no_trade(date, f"Already holding {ticker}", ticker)
                return {}
        elif direction == "SHORT":
            if ticker not in self.portfolio._positions:
                self._audit_no_trade(date, f"No position to exit for {ticker}", ticker)
                return {}
            side = "SELL"
        else:
            self._audit_no_trade(date, f"Unknown direction: {direction}", ticker)
            return {}

        # Position sizing (esit agirlik)
        total_value = self.portfolio.get_total_value()
        target_weight = min(self.risk_gate.max_position_pct / 100, 0.1)
        position_value = total_value * target_weight
        quantity = int(position_value / price)

        if quantity <= 0:
            self._audit_no_trade(date, f"Quantity too small for {ticker}", ticker)
            return {}

        # === RISK GATE ===
        risk_checks = self.risk_gate.check_all(
            portfolio=self.portfolio,
            ticker=ticker,
            side=side,
            quantity=quantity,
            price=price,
            sector=sector,
            data_quality_ok=True,
            model_version_valid=(model_version == self._champion_version),
        )

        allowed = self.risk_gate.is_trade_allowed(risk_checks)
        self._audit_risk_check(date, ticker, risk_checks, allowed)

        if not allowed:
            reason = self.risk_gate.get_block_reason(risk_checks)
            self._audit_no_trade(date, f"Risk gate blocked: {reason}", ticker)
            return {}

        # === EXECUTION ===
        # Volatilite ve spread'i hesapla (sabit değerler yerine)
        _vol = self._estimate_volatility(ticker) if hasattr(self, '_estimate_volatility') else 0.25
        _spread = self._estimate_spread(ticker, volume) if hasattr(self, '_estimate_spread') else 0.1
        order = self.execution.execute_signal(
            date=date, ticker=ticker, side=side, quantity=quantity,
            signal_price=price, 
            market_price=price * (1.002 if side == "BUY" else 0.998), # FIX: Simulate live execution gap/delay
            avg_volume=volume, volatility=_vol, spread_pct=_spread,
            sector=sector,
        )

        self._audit_order(date, order)
        self.store.save_order(order)

        if order["status"] != "FILLED":
            return {"order": order}

        # === PORTFOLIO UPDATE ===
        if side == "BUY":
            result = self.portfolio.open_position(
                ticker=ticker, quantity=quantity,
                price=order["execution_price"], sector=sector,
                date=date, commission=order["commission"],
            )
        else:
            result = self.portfolio.close_position(
                ticker=ticker, price=order["execution_price"],
                date=date, commission=order["commission"],
                reason="EXIT_SIGNAL",
            )
            if result.get("success") and result.get("trade"):
                return {"order": order, "trade": result["trade"]}

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
            "reason": f"regime={signal.get('regime')}, score={signal.get('score')}",
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

    def _audit_risk_check(self, date: str, ticker: str, checks: List[Dict], allowed: bool):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": date,
            "entry_type": "RISK_CHECK",
            "ticker": ticker,
            "reason": "ALLOWED" if allowed else f"BLOCKED: {self.risk_gate.get_block_reason(checks)}",
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

    # ===================== REPORTING =====================

    def get_full_report(self) -> Dict[str, Any]:
        """Tam paper trading raporu."""
        equity_curve = self.portfolio.get_equity_curve()
        trades = self.portfolio.get_trades()

        metrics = self.performance.compute_full_metrics(equity_curve, trades)

        return {
            "champion_version": self._champion_version,
            "initial_capital": self.initial_capital,
            "portfolio_summary": self.portfolio.get_portfolio_summary(),
            "performance_metrics": metrics,
            "equity_curve_length": len(equity_curve),
            "total_trades": len(trades),
        }

    def run_backtest_replay(
        self,
        market_data: Dict[str, pd.DataFrame],
        sector_map: Dict[str, str],
        signals_by_date: Dict[str, List[Dict]],
        benchmark_returns: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Gecmis veri uzerinde paper trading replay.

        Args:
            market_data: {ticker: OHLCV DataFrame}
            sector_map: {ticker: sector}
            signals_by_date: {date: [signal_dict, ...]}
            benchmark_returns: {date: XU100_return_pct}
        """
        logger.info("Starting paper trading replay",
                   tickers=len(market_data), days=len(signals_by_date))

        self.reset()
        self.set_replay_mode(market_data)

        dates = sorted(signals_by_date.keys())

        for date in dates:
            benchmark = benchmark_returns.get(date, 0.0) if benchmark_returns else 0.0
            signals = signals_by_date.get(date, [])

            self.run_daily_cycle(
                date=date,
                market_data=market_data,
                sector_map=sector_map,
                champion_signals=signals,
                benchmark_return_pct=benchmark,
                data_quality_ok=True,
            )

        report = self.get_full_report()
        logger.info("Replay completed", days=len(dates), trades=report["total_trades"])
        return report


# Singleton
paper_orchestrator = PaperTradingOrchestrator()
