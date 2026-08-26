"""
ALPHA BIST — Kurumsal Risk Parity & 3 Günlük Kriz Teyidi + Boğa Breakout Motoru
==============================================================================
1. 3 Günlük Kriz Teyit Filtresi (3-Day Consecutive Crisis Confirmation - Whipsaw Önleyici)
2. Boğada 20 Günlük Zirve Breakout Girişi (Bull Momentum Participation - Nakit Kalan Sermayeyi Çalıştırma)
3. Fixed Fractional ATR Risk Sizing (%1.0 Risk / Trade, Max %10 Hisse Tavanı, Max %5 Portföy Isısı)
"""

from typing import Dict, List, Any
from dataclasses import dataclass
import numpy as np
import polars as pl
import structlog

logger = structlog.get_logger()


@dataclass
class RiskParityParameters:
    # Risk Yönetimi
    risk_per_trade_pct: float = 0.010       # Her işlemde portföyün en fazla %1.0'ı riske atılır
    max_position_size_pct: float = 0.10     # Tek bir hisseye asla portföyün %10'undan fazlası bağlanmaz
    max_portfolio_heat_pct: float = 0.05    # Portföy açık risk tavanı: %5.0
    max_sector_concentration_pct: float = 0.30  # Tek sektörde max %30 yoğunlaşma
    
    # Teknik Eşikler
    min_buyer_pressure: float = 50.0
    min_candle_score: float = 65.0
    rsi_oversold: float = 30.0
    volume_surge_mult: float = 1.20
    
    # ATR Stop & Trailing
    atr_initial_stop_mult: float = 2.20     # İlk stop mesafesi
    atr_breakeven_mult: float = 2.20        # Kâra geçince stopu maliyete çekme eşiği
    atr_trailing_bull_mult: float = 6.00    # Boğada trendi sağma mesafesi
    atr_trailing_bear_mult: float = 2.00    # Ayıda sıkı koruma mesafesi
    
    # Rejim & Kriz Teyidi
    regime_sma_fast: int = 50
    regime_sma_slow: int = 200
    crisis_exit_buffer: float = 0.96
    crisis_confirm_days: int = 3            # Kriz çıkışı için 3 ardışık gün teyit şartı
    max_positions_bull: int = 8
    max_positions_bear: int = 3


@dataclass
class RiskAuditResult:
    total_return_pct: float = 0.0
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 1.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    equity_curve: List[float] = None
    trade_logs: List[Dict[str, Any]] = None


class RiskParityEngine:
    """Kurumsal Risk Parity ve Teyitli Kriz Kontrol Motoru."""

    def __init__(self, bm_df: pl.DataFrame, stock_dict: Dict[str, pl.DataFrame], sector_map: Dict[str, str] = None):
        self.bm_df = bm_df
        self.stock_dict = stock_dict
        self.sector_map = sector_map or {}  # {ticker: sector_name}
        self._precompute_technicals()

    def _precompute_technicals(self):
        """Teknik göstergeleri RAM'e önbellekler."""
        self.tech_cache = {}
        for ticker, df in self.stock_dict.items():
            if len(df) < 50:
                continue
            closes = df["Close"].to_numpy().astype(np.float64)
            opens = df["Open"].to_numpy().astype(np.float64)
            highs = df["High"].to_numpy().astype(np.float64)
            lows = df["Low"].to_numpy().astype(np.float64)
            volumes = df["Volume"].to_numpy().astype(np.float64)

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

            # 20 günlük ortalama hacim ve 20 günlük en yüksek zirve
            vol_avg20 = np.zeros(len(df), dtype=np.float64)
            high_20d = np.zeros(len(df), dtype=np.float64)
            for i in range(20, len(df)):
                vol_avg20[i] = np.mean(volumes[max(0, i-20):i])
                high_20d[i] = np.max(highs[max(0, i-20):i])

            canonical_ticker = ticker if ticker.endswith(".IS") else f"{ticker}.IS"
            self.tech_cache[canonical_ticker] = {
                "atr14": atr14,
                "rsi14": rsi14,
                "closes": closes,
                "opens": opens,
                "highs": highs,
                "lows": lows,
                "volumes": volumes,
                "vol_avg20": vol_avg20,
                "high_20d": high_20d,
                "dates": df.index
            }

    def _get_sector_exposure(self, positions: Dict, total_equity: float) -> Dict[str, float]:
        """Mevcut pozisyonların sektör bazlı yoğunlaşmasını hesapla."""
        sector_values: Dict[str, float] = {}
        for ticker, pos in positions.items():
            sector = self.sector_map.get(ticker.split(".")[0], "unknown")
            pos_value = pos["shares"] * pos["entry_price"]
            sector_values[sector] = sector_values.get(sector, 0.0) + pos_value
        return {s: v / max(total_equity, 1.0) for s, v in sector_values.items()}

    COMMISSION_RATE = 0.0015
    SLIPPAGE_RATE = 0.0010

    def simulate(self, params: RiskParityParameters, start_year: int = 1997, end_year: int = 2026, initial_capital: float = 100000.0) -> RiskAuditResult:
        """Risk Parity & 3 Günlük Kriz Teyidi + Breakout Destekli Simülasyon."""
        trading_dates = [d for d in self.bm_df.index if start_year <= d.year <= end_year]
        if len(trading_dates) < 30:
            return RiskAuditResult()

        capital = initial_capital
        positions = {}
        pending_buy_orders = []
        pending_sell_orders = []
        trade_logs = []
        equity_curve = []
        consecutive_crisis_days = 0

        bm_closes = self.bm_df["Close"].to_numpy()
        bm_dates = self.bm_df.index

        for day_idx in range(len(trading_dates)):
            current_date = trading_dates[day_idx]
            global_idx = bm_dates.get_loc(current_date)

            # Güncel portföy değeri (Tatil günlerinde son işlem fiyatını kullanır)
            curr_pos_val = 0.0
            for t, p in positions.items():
                cdata = self.tech_cache.get(t)
                if cdata:
                    valid_dates = cdata["dates"][cdata["dates"] <= current_date]
                    if len(valid_dates) > 0:
                        last_idx = len(valid_dates) - 1
                        curr_pos_val += p["shares"] * cdata["closes"][last_idx]
            total_equity = capital + curr_pos_val

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
                        trade_logs.append({
                            "ticker": t, "entry_date": pos["entry_date"], "exit_date": current_date,
                            "pnl": net_pnl, "ret_pct": ret_pct, "reason": sell_ord.get("reason", "STOP")
                        })
                        positions.pop(t, None)
            pending_sell_orders = []

            # 2. Bekleyen Alışlar ($t+1$ Open / Risk Parity Sizing)
            for buy_ord in pending_buy_orders:
                t = buy_ord["ticker"]
                if t not in positions:
                    cdata = self.tech_cache.get(t)
                    if cdata and current_date in cdata["dates"]:
                        d_idx = cdata["dates"].get_loc(current_date)
                        open_p = cdata["opens"][d_idx]
                        entry_p = open_p * (1 + SLIPPAGE_RATE)
                        cost_with_fee = entry_p * (1 + COMMISSION_RATE)
                        atr_val = max(cdata["atr14"][d_idx], entry_p * 0.015)

                        # Risk Parity: Stop mesafesi kadar risk al (%1.0)
                        stop_dist = atr_val * params.atr_initial_stop_mult
                        dollar_risk = total_equity * params.risk_per_trade_pct
                        
                        shares_by_risk = int(dollar_risk / stop_dist)
                        max_pos_val = total_equity * params.max_position_size_pct
                        shares_by_cap = int(max_pos_val / cost_with_fee)
                        
                        shares = min(shares_by_risk, shares_by_cap)
                        total_cost = shares * cost_with_fee

                        if shares > 0 and capital >= total_cost:
                            capital -= total_cost
                            positions[t] = {
                                "shares": shares,
                                "entry_price": entry_p,
                                "entry_date": current_date,
                                "peak_price": entry_p,
                                "stop_loss": entry_p - stop_dist,
                                "breakeven_hit": False,
                                "initial_stop_dist": stop_dist
                            }
            pending_buy_orders = []

            # 3. Rejim & Kriz Teyidi (3 Günlük Teyit Filtresi)
            bm_now = bm_closes[global_idx]
            bm_sma50 = np.mean(bm_closes[max(0, global_idx-params.regime_sma_fast):global_idx+1])
            bm_sma200 = np.mean(bm_closes[max(0, global_idx-params.regime_sma_slow):global_idx+1])
            is_bull = bm_now >= bm_sma50

            # Kriz eşiği kontrolü
            if bm_now < (bm_sma200 * params.crisis_exit_buffer):
                consecutive_crisis_days += 1
            else:
                consecutive_crisis_days = 0

            # 3 gün üst üste kriz teyit edilirse acil çıkış devreye girer
            is_confirmed_crisis = consecutive_crisis_days >= params.crisis_confirm_days

            # 4. Trend Rider & Portföy Isı Kontrolü
            trailing_mult = params.atr_trailing_bull_mult if is_bull else params.atr_trailing_bear_mult
            total_open_risk = 0.0

            for ticker, pos in list(positions.items()):
                cdata = self.tech_cache.get(ticker)
                if not cdata or current_date not in cdata["dates"]:
                    continue
                d_idx = cdata["dates"].get_loc(current_date)
                close_p = cdata["closes"][d_idx]
                high_p = cdata["highs"][d_idx]
                atr_val = max(cdata["atr14"][d_idx], close_p * 0.01)

                if high_p > pos["peak_price"]:
                    pos = pos.with_columns(pl.lit(high_p).alias('peak_price'))

                # Breakeven kontrolü
                if close_p >= pos["entry_price"] + (atr_val * params.atr_breakeven_mult):
                    pos = pos.with_columns(pl.lit(True).alias('breakeven_hit'))

                if pos["breakeven_hit"]:
                    new_stop = pos["peak_price"] - (atr_val * trailing_mult)
                    pos = pos.with_columns(pl.lit(max(pos["stop_loss"], new_stop, pos["entry_price"])).alias('stop_loss'))

                # Kalan açık risk hesabı
                if not pos["breakeven_hit"]:
                    curr_risk = max(0.0, (pos["entry_price"] - pos["stop_loss"]) * pos["shares"])
                    total_open_risk += curr_risk

                # Satış Tetiklenmesi
                if close_p <= pos["stop_loss"]:
                    pending_sell_orders.append({"ticker": ticker, "reason": "TRAILING_STOP" if pos["breakeven_hit"] else "STOP_LOSS"})
                elif is_confirmed_crisis:
                    pending_sell_orders.append({"ticker": ticker, "reason": "CRISIS_EXIT"})

            # 5. Giriş Taraması (Dip Girişi + Boğada 20 Günlük Breakout)
            max_pos = params.max_positions_bull if is_bull else params.max_positions_bear
            active_cnt = len(positions) + len(pending_buy_orders) - len(pending_sell_orders)
            portfolio_heat_ratio = total_open_risk / max(total_equity, 1.0)

            if active_cnt < max_pos and portfolio_heat_ratio < params.max_portfolio_heat_pct and not is_confirmed_crisis:
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
                    high_20 = cdata["high_20d"][d_idx]
                    close_p = cdata["closes"][d_idx]
                    open_p = cdata["opens"][d_idx]
                    low_p = cdata["lows"][d_idx]
                    high_p = cdata["highs"][d_idx]

                    # Alıcı Baskısı
                    total_range = max(high_p - low_p, 1e-4)
                    lower_wick = min(open_p, close_p) - low_p
                    body = abs(close_p - open_p) if close_p >= open_p else 0
                    buyer_press = ((lower_wick + body) / total_range) * 100.0

                    # 1. Kural: Klasik Dip Dönüşü (Oversold + Alıcı Baskısı)
                    is_dip_setup = (buyer_press >= params.min_buyer_pressure and (vol_v >= vol_avg * params.volume_surge_mult or rsi_v <= params.rsi_oversold))

                    # 2. Kural: Boğa Rejiminde 20 Günlük Zirve Breakout (Momentum Katılımı)
                    is_breakout_setup = (is_bull and close_p >= high_20 and vol_v >= vol_avg * 1.10 and rsi_v >= 55.0)

                    if is_dip_setup or is_breakout_setup:
                        score = buyer_press + (15.0 if is_breakout_setup else 0.0)
                        candidates.append({"ticker": ticker, "score": score})

                candidates.sort(key=lambda x: x["score"], reverse=True)
                available = max_pos - active_cnt

                # Sektör yoğunlaşma kontrolü
                sector_exposure = self._get_sector_exposure(positions, total_equity)

                for cand in candidates[:available * 2]:  # Fazla aday al, filtrele
                    if len(pending_buy_orders) >= available:
                        break
                    ticker = cand["ticker"]
                    sector = self.sector_map.get(ticker.split(".")[0], "unknown")
                    sector_pct = sector_exposure.get(sector, 0.0)

                    # Sektör yoğunlaşma limiti kontrolü
                    if sector_pct >= params.max_sector_concentration_pct:
                        logger.debug("Sektör yoğunlaşma limiti", ticker=ticker,
                                   sector=sector, pct=f"{sector_pct:.1%}")
                        continue

                    pending_buy_orders.append({"ticker": ticker})
                    # Sektör exposure güncelle
                    sector_exposure[sector] = sector_pct + (1.0 / max(total_equity, 1.0))

            equity_curve.append(total_equity)

        return self._compute_sim_result(equity_curve, trade_logs, initial_capital, trading_dates)

    def _compute_sim_result(self, equity_curve, trade_logs, initial_capital, trading_dates) -> RiskAuditResult:
        """Simülasyon metriklerini hesapla."""
        final_eq = equity_curve[-1] if equity_curve else initial_capital
        total_ret = ((final_eq - initial_capital) / initial_capital) * 100.0

        df_eq = pl.Series(equity_curve)
        peak = df_eq.cummax()
        dd = (df_eq - peak) / peak * 100.0
        max_dd = float(dd.min()) if len(dd) > 0 else 0.0

        df_t = pl.DataFrame(trade_logs)
        t_cnt = len(df_t)
        w_cnt = len(df_t.filter(pl.col('df_t') pnl >)) if t_cnt > 0 else 0
        w_rate = (w_cnt / t_cnt * 100.0) if t_cnt > 0 else 0.0
        w_sum = df_t.filter(pl.col('df_t') pnl >)["pnl"].sum() if t_cnt > 0 else 0.0
        l_sum = abs(df_t.filter(pl.col('df_t') pnl <)["pnl"].sum()) if t_cnt > 0 else 1e-9
        pf = round(float(w_sum / max(l_sum, 1e-9)), 2)

        returns = df_eq.pct_change().dropna()
        sharpe = float(np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)) if len(returns) > 10 else 0.0
        downside_returns = returns[returns < 0]
        sortino = float(np.mean(returns) / (np.std(downside_returns) + 1e-9) * np.sqrt(252)) if len(downside_returns) > 5 else sharpe

        years = len(trading_dates) / 252.0
        cagr = ((final_eq / initial_capital) ** (1.0 / max(years, 0.1)) - 1.0) * 100.0

        return RiskAuditResult(
            total_return_pct=round(total_ret, 1),
            cagr=round(cagr, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            profit_factor=pf,
            win_rate=round(w_rate, 1),
            max_drawdown=round(max_dd, 2),
            total_trades=t_cnt,
            equity_curve=equity_curve,
            trade_logs=trade_logs
        )
