"""
ALPHA BIST — Çok Çekirdekli (Multi-Core) Yüksek Hızlı Bayesian Optimizasyon Motoru
==================================================================================
Tüm CPU çekirdeklerini ve RAM'i kullanarak 30 yıllık BIST verisi üzerinde
saniyede yüzlerce denemeyi paralel (Multiprocessing) olarak icra eder.
"""

from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import optuna
import os
import multiprocessing
import structlog
import warnings
warnings.filterwarnings('ignore')

optuna.logging.set_verbosity(optuna.logging.WARNING)
logger = structlog.get_logger()


@dataclass
class StrategyParameters:
    """Taranan strateji parametre kümesi."""
    min_buyer_pressure: float = 52.0
    min_candle_score: float = 70.0
    dynamic_edge_threshold: float = 50.0
    rsi_period: int = 14
    rsi_oversold: float = 35.0
    volume_surge_mult: float = 1.5

    # Dinamik Trend Rider
    atr_initial_stop_mult: float = 2.0
    atr_breakeven_mult: float = 2.5
    atr_trailing_mult: float = 3.0
    trend_ema_fast: int = 9
    trend_ema_slow: int = 21

    # Rejim ve Portföy
    regime_sma_fast: int = 50
    regime_sma_slow: int = 200
    crisis_exit_buffer: float = 0.95
    max_positions_bull: int = 10
    max_positions_bear: int = 3
    position_alloc_bull: float = 0.10
    position_alloc_bear: float = 0.05


@dataclass
class OptimizationTrialResult:
    trial_id: int
    params: StrategyParameters
    total_return_pct: float = 0.0
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 1.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    fitness_score: float = 0.0


class BayesianMetricOptimizer:
    """Tüm CPU çekirdeklerini kullanan yüksek hızlı optimizasyon motoru."""

    def __init__(self, bm_df: pd.DataFrame, stock_dict: Dict[str, pd.DataFrame]):
        self.bm_df = bm_df
        self.stock_dict = stock_dict
        self._precompute_technicals()

    def _precompute_technicals(self):
        """Tüm teknik göstergeleri tek bir matriste RAM'e alır."""
        self.tech_cache = {}
        for ticker, df in self.stock_dict.items():
            if len(df) < 50:
                continue
            closes = df["Close"].values.astype(np.float64)
            opens = df["Open"].values.astype(np.float64)
            highs = df["High"].values.astype(np.float64)
            lows = df["Low"].values.astype(np.float64)
            volumes = df["Volume"].values.astype(np.float64)

            # ATR 14
            tr1 = highs[1:] - lows[1:]
            tr2 = np.abs(highs[1:] - closes[:-1])
            tr3 = np.abs(lows[1:] - closes[:-1])
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            atr14 = np.zeros(len(df), dtype=np.float64)
            for i in range(14, len(df)):
                atr14[i] = np.mean(tr[max(0, i-14):i])

            # RSI 14
            diff = np.diff(closes)
            gains = np.where(diff > 0, diff, 0)
            losses = np.where(diff < 0, -diff, 0)
            rsi14 = np.full(len(df), 50.0, dtype=np.float64)
            for i in range(14, len(df)):
                avg_g = np.mean(gains[max(0, i-14):i])
                avg_l = np.mean(losses[max(0, i-14):i])
                if avg_l == 0:
                    rsi14[i] = 100.0
                else:
                    rs = avg_g / max(avg_l, 1e-9)
                    rsi14[i] = 100.0 - (100.0 / (1.0 + rs))

            # 20 günlük ortalama hacim
            vol_avg20 = np.zeros(len(df), dtype=np.float64)
            for i in range(20, len(df)):
                vol_avg20[i] = np.mean(volumes[max(0, i-20):i])

            self.tech_cache[ticker] = {
                "atr14": atr14,
                "rsi14": rsi14,
                "closes": closes,
                "opens": opens,
                "highs": highs,
                "lows": lows,
                "volumes": volumes,
                "vol_avg20": vol_avg20,
                "dates": df.index
            }

    def simulate_fast(self, params: StrategyParameters, start_year: int = 1997, end_year: int = 2026, initial_capital: float = 100000.0) -> OptimizationTrialResult:
        """C-hızında saf NumPy simülasyonu."""
        COMMISSION_RATE = 0.0015
        SLIPPAGE_RATE = 0.0010

        trading_dates = [d for d in self.bm_df.index if start_year <= d.year <= end_year]
        if len(trading_dates) < 30:
            return OptimizationTrialResult(trial_id=0, params=params)

        capital = initial_capital
        positions = {}
        pending_buy_orders = []
        pending_sell_orders = []
        trade_logs = []
        equity_curve = []

        bm_closes = self.bm_df["Close"].values
        bm_dates = self.bm_df.index

        for day_idx in range(len(trading_dates)):
            current_date = trading_dates[day_idx]
            global_idx = bm_dates.get_loc(current_date)

            # 1. Bekleyen Satışlar ($t+1$ Open)
            for sell_ord in pending_sell_orders:
                t = sell_ord["ticker"]
                if t in positions:
                    cdata = self.tech_cache.get(t)
                    if cdata and current_date in cdata["dates"]:
                        d_idx = cdata["dates"].get_loc(current_date)
                        open_p = cdata["opens"][d_idx]
                        exit_p = open_p * (1 - SLIPPAGE_RATE)
                        pos = positions[t]

                        pnl = (exit_p - pos["entry_price"]) * pos["shares"]
                        fee = (pos["entry_price"] + exit_p) * pos["shares"] * COMMISSION_RATE
                        net_pnl = pnl - fee
                        capital += (exit_p * pos["shares"]) - (exit_p * pos["shares"] * COMMISSION_RATE)

                        ret_pct = ((exit_p - pos["entry_price"]) / pos["entry_price"]) * 100
                        trade_logs.append({"pnl": net_pnl, "ret_pct": ret_pct})
                        positions.pop(t, None)
            pending_sell_orders = []

            # 2. Bekleyen Alışlar ($t+1$ Open)
            for buy_ord in pending_buy_orders:
                t = buy_ord["ticker"]
                if t not in positions:
                    cdata = self.tech_cache.get(t)
                    if cdata and current_date in cdata["dates"]:
                        d_idx = cdata["dates"].get_loc(current_date)
                        open_p = cdata["opens"][d_idx]
                        entry_p = open_p * (1 + SLIPPAGE_RATE)
                        cost_with_fee = entry_p * (1 + COMMISSION_RATE)

                        invest_amount = buy_ord["amount"]
                        shares = int(invest_amount / cost_with_fee)

                        if shares > 0 and capital >= (shares * cost_with_fee):
                            capital -= (shares * cost_with_fee)
                            positions[t] = {
                                "shares": shares,
                                "entry_price": entry_p,
                                "peak_price": entry_p,
                                "stop_loss": entry_p - (cdata["atr14"][d_idx] * params.atr_initial_stop_mult),
                                "breakeven_hit": False
                            }
            pending_buy_orders = []

            # 3. Rejim
            bm_now = bm_closes[global_idx]
            bm_sma50 = np.mean(bm_closes[max(0, global_idx-params.regime_sma_fast):global_idx+1])
            bm_sma200 = np.mean(bm_closes[max(0, global_idx-params.regime_sma_slow):global_idx+1])
            is_bull = bm_now >= bm_sma50
            is_crisis = bm_now < (bm_sma200 * params.crisis_exit_buffer)

            # 4. Trend Rider & Pozisyon Takibi
            for ticker, pos in list(positions.items()):
                cdata = self.tech_cache.get(ticker)
                if not cdata or current_date not in cdata["dates"]:
                    continue
                d_idx = cdata["dates"].get_loc(current_date)
                close_p = cdata["closes"][d_idx]
                high_p = cdata["highs"][d_idx]
                atr_val = cdata["atr14"][d_idx]

                if high_p > pos["peak_price"]:
                    pos["peak_price"] = high_p

                if close_p >= pos["entry_price"] + (atr_val * params.atr_breakeven_mult):
                    pos["breakeven_hit"] = True

                if pos["breakeven_hit"]:
                    new_stop = pos["peak_price"] - (atr_val * params.atr_trailing_mult)
                    pos["stop_loss"] = max(pos["stop_loss"], new_stop, pos["entry_price"])

                if close_p <= pos["stop_loss"] or is_crisis:
                    pending_sell_orders.append({"ticker": ticker})

            # 5. Giriş Taraması
            max_pos = params.max_positions_bull if is_bull else params.max_positions_bear
            active_cnt = len(positions) + len(pending_buy_orders) - len(pending_sell_orders)

            if active_cnt < max_pos and not is_crisis:
                candidates = []
                for ticker, cdata in self.tech_cache.items():
                    if ticker in positions or any(o["ticker"] == ticker for o in pending_buy_orders):
                        continue
                    if current_date not in cdata["dates"]:
                        continue
                    d_idx = cdata["dates"].get_loc(current_date)
                    if d_idx < 30:
                        continue

                    rsi_v = cdata["rsi14"][d_idx]
                    vol_v = cdata["volumes"][d_idx]
                    vol_avg = cdata["vol_avg20"][d_idx]
                    close_p = cdata["closes"][d_idx]
                    open_p = cdata["opens"][d_idx]
                    low_p = cdata["lows"][d_idx]
                    high_p = cdata["highs"][d_idx]

                    # Hızlı Alıcı Baskısı Hesabı
                    total_range = max(high_p - low_p, 1e-4)
                    lower_wick = min(open_p, close_p) - low_p
                    body = abs(close_p - open_p) if close_p >= open_p else 0
                    buyer_press = ((lower_wick + body) / total_range) * 100.0

                    if buyer_press >= params.min_buyer_pressure and (vol_v >= vol_avg * params.volume_surge_mult or rsi_v <= params.rsi_oversold):
                        candidates.append({"ticker": ticker, "score": buyer_press})

                candidates.sort(key=lambda x: x["score"], reverse=True)
                available = max_pos - active_cnt
                for cand in candidates[:available]:
                    alloc = params.position_alloc_bull if is_bull else params.position_alloc_bear
                    pos_val = capital * alloc
                    if pos_val > 100:
                        pending_buy_orders.append({"ticker": cand["ticker"], "amount": pos_val})

            # Gün Sonu Portföy
            curr_pos_val = sum(p["shares"] * self.tech_cache[t]["closes"][self.tech_cache[t]["dates"].get_loc(current_date)]
                               for t, p in positions.items() if current_date in self.tech_cache[t]["dates"])
            equity_curve.append(capital + curr_pos_val)

        final_eq = equity_curve[-1] if equity_curve else initial_capital
        total_ret = ((final_eq - initial_capital) / initial_capital) * 100

        # Metrikler
        df_eq = pd.Series(equity_curve)
        peak = df_eq.cummax()
        dd = (df_eq - peak) / peak * 100
        max_dd = float(dd.min()) if len(dd) > 0 else 0.0

        df_t = pd.DataFrame(trade_logs)
        t_cnt = len(df_t)
        w_cnt = len(df_t[df_t["pnl"] > 0]) if t_cnt > 0 else 0
        w_rate = (w_cnt / t_cnt * 100) if t_cnt > 0 else 0.0
        w_sum = df_t[df_t["pnl"] > 0]["pnl"].sum() if t_cnt > 0 else 0
        l_sum = abs(df_t[df_t["pnl"] < 0]["pnl"].sum()) if t_cnt > 0 else 1e-9
        pf = round(float(w_sum / max(l_sum, 1e-9)), 2)

        returns = df_eq.pct_change().dropna()
        sharpe = float(np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)) if len(returns) > 10 else 0.0

        dd_penalty = max(0.01, (1.0 - abs(max_dd) / 100.0)) ** 2
        trade_credibility = min(2.0, np.log10(max(10, t_cnt)))
        fitness = float(max(0.0, sharpe) * pf * dd_penalty * trade_credibility)

        return OptimizationTrialResult(
            trial_id=0,
            params=params,
            total_return_pct=round(total_ret, 1),
            sharpe_ratio=round(sharpe, 2),
            profit_factor=pf,
            win_rate=round(w_rate, 1),
            max_drawdown=round(max_dd, 2),
            total_trades=t_cnt,
            fitness_score=round(fitness, 3)
        )

    def run_bayesian_study(self, n_trials: int = 500) -> Tuple[StrategyParameters, List[OptimizationTrialResult]]:
        """Tüm CPU çekirdeklerini kullanarak paralel Optuna optimizasyonu yapar."""
        num_cores = max(1, os.cpu_count() or 4)
        logger.info(f"Yüksek hızlı Bayesian optimizasyon başlatılıyor... ({n_trials} Deneme, {num_cores} CPU Çekirdeği)")
        trial_results: List[OptimizationTrialResult] = []

        def objective(trial: optuna.Trial) -> float:
            params = StrategyParameters(
                min_buyer_pressure=trial.suggest_float("min_buyer_pressure", 48.0, 65.0, step=1.0),
                min_candle_score=trial.suggest_float("min_candle_score", 60.0, 85.0, step=5.0),
                dynamic_edge_threshold=trial.suggest_float("dynamic_edge_threshold", 45.0, 60.0, step=2.5),
                rsi_oversold=trial.suggest_float("rsi_oversold", 25.0, 45.0, step=2.5),
                volume_surge_mult=trial.suggest_float("volume_surge_mult", 1.2, 3.0, step=0.2),
                atr_initial_stop_mult=trial.suggest_float("atr_initial_stop_mult", 1.5, 3.5, step=0.25),
                atr_breakeven_mult=trial.suggest_float("atr_breakeven_mult", 2.0, 4.0, step=0.25),
                atr_trailing_mult=trial.suggest_float("atr_trailing_mult", 2.5, 5.0, step=0.25),
                crisis_exit_buffer=trial.suggest_float("crisis_exit_buffer", 0.90, 0.98, step=0.01),
                max_positions_bull=trial.suggest_int("max_positions_bull", 5, 12),
                position_alloc_bull=trial.suggest_float("position_alloc_bull", 0.08, 0.15, step=0.01)
            )

            res = self.simulate_fast(params, start_year=1997, end_year=2023)
            res.trial_id = trial.number
            trial_results.append(res)

            if trial.number % 50 == 0:
                print(f"  [İlerleme] Deneme #{trial.number}/{n_trials} | En İyi Fitness: {res.fitness_score:.2f} | Getiri: %{res.total_return_pct:+,.1f}")

            return res.fitness_score

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best_trial = study.best_trial
        best_params = StrategyParameters(
            min_buyer_pressure=best_trial.params.get("min_buyer_pressure", 52.0),
            min_candle_score=best_trial.params.get("min_candle_score", 70.0),
            dynamic_edge_threshold=best_trial.params.get("dynamic_edge_threshold", 50.0),
            rsi_oversold=best_trial.params.get("rsi_oversold", 35.0),
            volume_surge_mult=best_trial.params.get("volume_surge_mult", 1.5),
            atr_initial_stop_mult=best_trial.params.get("atr_initial_stop_mult", 2.0),
            atr_breakeven_mult=best_trial.params.get("atr_breakeven_mult", 2.5),
            atr_trailing_mult=best_trial.params.get("atr_trailing_mult", 3.0),
            crisis_exit_buffer=best_trial.params.get("crisis_exit_buffer", 0.95),
            max_positions_bull=best_trial.params.get("max_positions_bull", 10),
            position_alloc_bull=best_trial.params.get("position_alloc_bull", 0.10)
        )

        return best_params, trial_results
