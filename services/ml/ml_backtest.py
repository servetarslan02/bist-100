"""ALPHA BIST — ML Backtest Integration (Nihai — FAZ 6).

Model predictions → backtest engine entegrasyonu.
Ensemble vs single model karşılaştırması, regime-based performans analizi,
transaction cost dahil backtest.
"""
import numpy as np
from typing import Dict, Any, Optional, List, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger()


@dataclass
class BacktestTrade:
    """Backtest işlem kaydı."""
    timestamp: str
    ticker: str
    side: str  # BUY / SELL
    price: float
    quantity: int
    signal_score: float
    model_name: str
    commission: float = 0.0
    slippage: float = 0.0
    pnl: float = 0.0


@dataclass
class BacktestResult:
    """Backtest sonucu."""
    model_name: str
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_pnl: float
    avg_holding_days: float
    calmar_ratio: float
    equity_curve: List[Tuple[str, float]]
    trades: List[BacktestTrade]
    regime_performance: Dict[str, Dict[str, float]]


@dataclass
class ComparisonResult:
    """Model karşılaştırma sonucu."""
    models: List[BacktestResult]
    best_model: str
    ranking_metric: str
    ranking: List[Tuple[str, float]]


class MLBacktestEngine:
    """ML model tahminlerini backtest eden motor.

    Özellikler:
    - Model predictions → backtest pipeline
    - Ensemble vs single model karşılaştırması
    - Regime-based performans analizi
    - Transaction cost (commission + slippage) dahil
    - Walk-forward backtest desteği
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        commission_rate: float = 0.001,   # %0.1
        slippage_rate: float = 0.0005,    # %0.05
        max_position_pct: float = 0.10,   # %10
        risk_free_rate: float = 0.0,      # Risksiz faiz
        annualization_factor: int = 252,  # İş günü
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.max_position_pct = max_position_pct
        self.risk_free_rate = risk_free_rate
        self.annualization_factor = annualization_factor

    def run_backtest(
        self,
        model_name: str,
        predict_fn: Callable,
        price_data: Dict[str, np.ndarray],     # {ticker: prices}
        feature_data: Dict[str, np.ndarray],    # {ticker: features}
        dates: List[str],                       # Tarih listesi
        regimes: Optional[List[str]] = None,    # Rejim etiketleri
        tickers: Optional[List[str]] = None,
    ) -> BacktestResult:
        """Tek model için backtest çalıştır.

        Args:
            model_name: Model adı
            predict_fn: Tahmin fonksiyonu (X) → scores
            price_data: {ticker: price_array}
            feature_data: {ticker: feature_array}
            dates: Tarih listesi
            regimes: Her gün için rejim etiketi (opsiyonel)
            tickers: Hisse listesi (opsiyonel, price_data'dan alınır)

        Returns:
            BacktestResult
        """
        if tickers is None:
            tickers = list(price_data.keys())

        capital = self.initial_capital
        positions: Dict[str, Dict[str, Any]] = {}  # {ticker: {qty, entry_price, entry_date}}
        trades: List[BacktestTrade] = []
        equity_curve: List[Tuple[str, float]] = []
        regime_perf: Dict[str, List[float]] = {}

        n_days = len(dates)

        for day_idx in range(n_days):
            date = dates[day_idx]
            regime = regimes[day_idx] if regimes else "UNKNOWN"

            if regime not in regime_perf:
                regime_perf[regime] = []

            # Her hisse için tahmin al
            scores: Dict[str, float] = {}
            for ticker in tickers:
                if ticker not in feature_data or ticker not in price_data:
                    continue
                feats = feature_data[ticker]
                if len(feats.shape) == 1:
                    feats = feats.reshape(1, -1)
                if day_idx >= feats.shape[0]:
                    continue

                try:
                    X = feats[day_idx:day_idx + 1]
                    pred = predict_fn(X)
                    scores[ticker] = float(pred[0]) if hasattr(pred, '__len__') else float(pred)
                except Exception as e:
                    logger.debug("Handled exception, continuing", error=str(e))
                    continue

            if not scores:
                # Equity kaydet
                portfolio_value = capital
                for t, pos in positions.items():
                    if t in price_data and day_idx < len(price_data[t]):
                        portfolio_value += pos["qty"] * price_data[t][day_idx]
                equity_curve.append((date, portfolio_value))
                continue

            # SELL sinyalleri (skor < 0.3)
            for ticker in list(positions.keys()):
                if ticker in scores and scores[ticker] < 0.3:
                    if ticker in price_data and day_idx < len(price_data[ticker]):
                        sell_price = price_data[ticker][day_idx] * (1 - self.slippage_rate)
                        pos = positions[ticker]
                        commission = sell_price * pos["qty"] * self.commission_rate
                        pnl = (sell_price - pos["entry_price"]) * pos["qty"] - commission
                        capital += sell_price * pos["qty"] - commission

                        trades.append(BacktestTrade(
                            timestamp=date,
                            ticker=ticker,
                            side="SELL",
                            price=sell_price,
                            quantity=pos["qty"],
                            signal_score=scores[ticker],
                            model_name=model_name,
                            commission=commission,
                            slippage=sell_price * self.slippage_rate * pos["qty"],
                            pnl=pnl,
                        ))

                        regime_perf[regime].append(pnl)
                        del positions[ticker]

            # BUY sinyalleri (skor > 0.7)
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            for ticker, score in sorted_scores:
                if ticker in positions:
                    continue
                if score < 0.7:
                    continue

                # Pozisyon büyüklüğü
                portfolio_value = capital
                for t, pos in positions.items():
                    if t in price_data and day_idx < len(price_data[t]):
                        portfolio_value += pos["qty"] * price_data[t][day_idx]

                max_invest = portfolio_value * self.max_position_pct
                if capital < max_invest * 0.1:
                    break  # Yetersiz sermaye

                if ticker in price_data and day_idx < len(price_data[ticker]):
                    buy_price = price_data[ticker][day_idx] * (1 + self.slippage_rate)
                    qty = int(max_invest / buy_price)
                    if qty <= 0:
                        continue

                    commission = buy_price * qty * self.commission_rate
                    total_cost = buy_price * qty + commission

                    if total_cost > capital:
                        qty = int((capital * 0.95) / buy_price)
                        if qty <= 0:
                            continue
                        total_cost = buy_price * qty + commission

                    capital -= total_cost
                    positions[ticker] = {
                        "qty": qty,
                        "entry_price": buy_price,
                        "entry_date": date,
                    }

                    trades.append(BacktestTrade(
                        timestamp=date,
                        ticker=ticker,
                        side="BUY",
                        price=buy_price,
                        quantity=qty,
                        signal_score=score,
                        model_name=model_name,
                        commission=commission,
                        slippage=buy_price * self.slippage_rate * qty,
                    ))

            # Portfolio değeri
            portfolio_value = capital
            for t, pos in positions.items():
                if t in price_data and day_idx < len(price_data[t]):
                    portfolio_value += pos["qty"] * price_data[t][day_idx]
            equity_curve.append((date, portfolio_value))

        # Metrikleri hesapla
        metrics = self._calculate_metrics(equity_curve, trades, capital, positions, price_data, dates)

        # Regime performansı
        regime_summary = {}
        for regime, pnls in regime_perf.items():
            if pnls:
                regime_summary[regime] = {
                    "total_pnl": round(float(np.sum(pnls)), 2),
                    "avg_pnl": round(float(np.mean(pnls)), 2),
                    "win_rate": round(float(np.mean([p > 0 for p in pnls])), 4),
                    "n_trades": len(pnls),
                }

        return BacktestResult(
            model_name=model_name,
            total_return=metrics["total_return"],
            annualized_return=metrics["annualized_return"],
            sharpe_ratio=metrics["sharpe_ratio"],
            max_drawdown=metrics["max_drawdown"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            total_trades=len(trades),
            avg_trade_pnl=metrics["avg_trade_pnl"],
            avg_holding_days=metrics["avg_holding_days"],
            calmar_ratio=metrics["calmar_ratio"],
            equity_curve=equity_curve,
            trades=trades,
            regime_performance=regime_summary,
        )

    def compare_models(
        self,
        models: Dict[str, Callable],
        price_data: Dict[str, np.ndarray],
        feature_data: Dict[str, np.ndarray],
        dates: List[str],
        regimes: Optional[List[str]] = None,
        ranking_metric: str = "sharpe_ratio",
    ) -> ComparisonResult:
        """Birden fazla modeli karşılaştır.

        Args:
            models: {model_name: predict_fn}
            price_data, feature_data, dates, regimes: Backtest verileri
            ranking_metric: Sıralama metriği

        Returns:
            ComparisonResult
        """
        results = []

        for name, predict_fn in models.items():
            logger.info("backtesting_model", model=name)
            try:
                result = self.run_backtest(
                    model_name=name,
                    predict_fn=predict_fn,
                    price_data=price_data,
                    feature_data=feature_data,
                    dates=dates,
                    regimes=regimes,
                )
                results.append(result)
            except Exception as e:
                logger.error("backtest_failed", model=name, error=str(e))

        # Sırala
        def get_metric(r: BacktestResult) -> float:
            return getattr(r, ranking_metric, 0.0)

        results.sort(key=get_metric, reverse=True)

        ranking = [(r.model_name, get_metric(r)) for r in results]
        best_model = ranking[0][0] if ranking else "none"

        return ComparisonResult(
            models=results,
            best_model=best_model,
            ranking_metric=ranking_metric,
            ranking=ranking,
        )

    def _calculate_metrics(
        self,
        equity_curve: List[Tuple[str, float]],
        trades: List[BacktestTrade],
        final_capital: float,
        positions: Dict[str, Any],
        price_data: Dict[str, np.ndarray],
        dates: List[str],
    ) -> Dict[str, float]:
        """Performans metriklerini hesapla."""
        if not equity_curve:
            return self._empty_metrics()

        values = np.array([v for _, v in equity_curve])
        n_days = len(values)

        # Toplam getiri
        total_return = (values[-1] / self.initial_capital) - 1.0

        # Yıllıklaştırılmış getiri
        years = n_days / self.annualization_factor
        annualized_return = (1 + total_return) ** (1 / max(years, 0.01)) - 1.0

        # Günlük getiriler
        daily_returns = np.diff(values) / values[:-1] if len(values) > 1 else np.array([0.0])

        # Sharpe ratio
        mean_daily = float(np.mean(daily_returns))
        std_daily = float(np.std(daily_returns))
        sharpe = ((mean_daily - self.risk_free_rate / self.annualization_factor) / max(std_daily, 1e-8)) * np.sqrt(self.annualization_factor)

        # Max drawdown
        running_max = np.maximum.accumulate(values)
        drawdown = (values - running_max) / running_max
        max_drawdown = float(np.abs(np.min(drawdown)))

        # Win rate
        sell_trades = [t for t in trades if t.side == "SELL"]
        if sell_trades:
            wins = sum(1 for t in sell_trades if t.pnl > 0)
            win_rate = wins / len(sell_trades)
        else:
            win_rate = 0.0

        # Profit factor
        gross_profit = sum(t.pnl for t in sell_trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in sell_trades if t.pnl < 0))
        profit_factor = gross_profit / max(gross_loss, 1.0)

        # Ortalama trade PnL
        avg_trade_pnl = float(np.mean([t.pnl for t in sell_trades])) if sell_trades else 0.0

        # Ortalama holding süresi
        holding_days = []
        buy_dates: Dict[str, str] = {}
        for t in trades:
            if t.side == "BUY":
                buy_dates[t.ticker] = t.timestamp
            elif t.side == "SELL" and t.ticker in buy_dates:
                try:
                    buy_dt = datetime.fromisoformat(buy_dates[t.ticker])
                    sell_dt = datetime.fromisoformat(t.timestamp)
                    holding_days.append((sell_dt - buy_dt).days)
                except Exception as e:
                    logger.debug("Handled exception", error=str(e), context="ml_backtest.py:386")
                    pass
                del buy_dates[t.ticker]
        avg_holding = float(np.mean(holding_days)) if holding_days else 0.0

        # Calmar ratio
        calmar = annualized_return / max(max_drawdown, 1e-8)

        return {
            "total_return": round(total_return, 4),
            "annualized_return": round(annualized_return, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_trade_pnl": round(avg_trade_pnl, 2),
            "avg_holding_days": round(avg_holding, 1),
            "calmar_ratio": round(calmar, 4),
        }

    def _empty_metrics(self) -> Dict[str, float]:
        """Boş metrik seti."""
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl": 0.0,
            "avg_holding_days": 0.0,
            "calmar_ratio": 0.0,
        }


# Singleton
ml_backtest_engine = MLBacktestEngine()
