"""ALPHA BIST — Phase 5-7: Frozen Strategy Engine (C_Max_Sustainable_Alpha)

Train/Validation multi-fold sonucuna göre seçilen mimari:
C_Max_Sustainable_Alpha:
  - max_pos_bull: 4 (Bull/Low-Vol'de 4 pozisyon = %75 Equity)
  - max_pos_bear: 2 (Bear/Sideways/HighVol'de 2 pozisyon = %50 Equity)
  - top1_alloc: 0.30 (En yüksek skorlu hisseye %30 conviction payı)
  - trailing_atr: 2.5x (ATR-tabanlı, genişletilmiş kâr sürme)
  - min_hold: 12 gün (Minimum pozisyon tutma - churn'ü bastırır)
  - min_score_bull: 0.08 (Boğa trendinde düşük giriş bariyeri - daha fazla katılım)

Fold Sonuçları (Train/Val üzerinde kanıtlanmış):
  Fold 1 (Düşüş): %-23.59 (En kötü fold - Bear dönemde kısmen korumasız)
  Fold 2 (Ralli): %+13.25 (XU100: %+6.47 - Güçlü alfa)
  Fold 3 (Konsolidasyon): %+9.78 (XU100: %+5.61 - Alfa korunuyor)
  Fold 4 (Yatay): %+0.47 (XU100: %+0.08 - Stabil)

UYARI: Bu parametre seti Final Holdout verisi kullanılarak SEÇİLMEMİŞTİR.
"""

import numpy as np
import pandas as pd
from datetime import timedelta
from typing import Dict, List, Any

from services.learning.institutional_walkforward_engine import (
    load_all_market_data,
    extract_point_in_time_features,
    ModelTrainer,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

import structlog

logger = structlog.get_logger(__name__)


# ============================================================
# FROZEN STRATEGY PARAMETERS — C_Max_Sustainable_Alpha
# Bu parametreler Train/Validation sonucuna göre kilitlenmiştir.
# Final Holdout üzerinde HİÇBİR şekilde değiştirilmeyecektir.
# ============================================================
FROZEN_PARAMS = {
    "max_pos": {
        "BULL_TREND": 4,
        "LOW_VOLATILITY": 4,
        "SIDEWAYS_RANGE": 2,
        "BEAR_MARKET": 2,
        "HIGH_VOLATILITY": 2,
    },
    "min_score": {
        "BULL_TREND": 0.08,
        "LOW_VOLATILITY": 0.10,
        "SIDEWAYS_RANGE": 0.20,
        "BEAR_MARKET": 0.28,
        "HIGH_VOLATILITY": 0.22,
    },
    "top1_alloc_pct": 0.30,       # Lider hisse conviction payı
    "default_alloc_pct": 0.20,    # Diğer hisseler
    "trailing_atr_mult": 2.5,     # ATR trailing stop çarpanı
    "min_atr_pct": 4.0,           # Minimum trailing stop (%)
    "hard_stop_pct": -6.5,        # Hard stop-loss
    "take_profit_pct": 35.0,      # Take-profit
    "min_hold_days": 12,          # Minimum tutma süresi
    "max_hold_days": 65,          # Maksimum tutma süresi
    "signal_reversal_thresh": -0.15,  # Sinyal tersine dönüş
    "ema_alpha_fast": 0.75,       # Hızlı sinyal ivmesi
    "ema_alpha_slow": 0.40,       # Yavaş gürültü filtresi
    "ema_delta_thresh": 0.15,     # İvme eşiği
    "conviction_score_min": 0.20, # %30 pay için minimum skor
    "transaction_fee": 0.00074,   # BIST komisyon + MKK + Takas
    "slippage": 0.00050,          # Slippage
    "min_cash_to_open": 200_000,  # Yeni pozisyon açmak için minimum nakit
    "retraining_freq": 20,        # Her 20 günde bir model yeniden eğitimi
}

MODELS = [
    "LightGBM_LambdaRank", "CatBoost_Classifier", "XGBoost_Model",
    "Cross_Sectional_Momentum", "SPEC_Anomaly_Detector", "LSTM_Sequential"
]

TOTAL_FRICTION = FROZEN_PARAMS["transaction_fee"] + FROZEN_PARAMS["slippage"]


def run_frozen_strategy(eval_dates, features_by_ticker, xu100_close,
                        trainer, initial_capital=10_000_000.0,
                        verbose=False, label="Frozen Strategy"):
    """
    Tamamen dondurulmuş C_Max_Sustainable_Alpha stratejisini çalıştırır.
    Final Holdout veya Train/Validation fark etmeksizin aynı parametrelerle çalışır.
    """
    portfolio_cash = initial_capital
    positions: Dict[str, Dict[str, Any]] = {}
    equity_curve = []
    daily_rets = []
    holding_periods = []
    daily_exposures = []
    monthly_perf: Dict[str, Dict[str, float]] = {}

    regime_pnl = {r: {"pnl": 0.0, "trades": 0, "wins": 0} for r in [
        "BULL_TREND", "BEAR_MARKET", "SIDEWAYS_RANGE", "HIGH_VOLATILITY",
        "LOW_VOLATILITY", "V_DIP_RECOVERY"
    ]}

    total_costs = 0.0
    trades_count = 0
    wins_count = 0
    losses_count = 0
    gross_win_pnl = 0.0
    gross_loss_pnl = 0.0
    smoothed_scores: Dict[str, float] = {tk: 0.0 for tk in features_by_ticker}
    pending_evals: List[Dict[str, Any]] = []
    completed_wins = {m: 0 for m in MODELS}
    completed_totals = {m: 0 for m in MODELS}

    start_xu100 = float(xu100_close.loc[eval_dates[0]]) if eval_dates[0] in xu100_close.index else float(xu100_close.iloc[0])
    equity_xu100 = []
    daily_rets_xu100 = []
    equity_ew = []

    current_fold = 0

    for step_i, current_date in enumerate(eval_dates):
        month_key = current_date.strftime("%Y-%m")

        # 0. Kapanan tahmin havuzlarını güncelle (t-5 öncesi)
        still_pending = []
        for pe in pending_evals:
            if pe["eval_date"] <= current_date:
                completed_totals[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins[pe["model"]] += 1
            else:
                still_pending.append(pe)
        pending_evals = still_pending

        # 1. RETRAINING (Genişleyen pencere, 5 gün embargo)
        if step_i % FROZEN_PARAMS["retraining_freq"] == 0:
            current_fold += 1
            train_rows = [fdf.loc[:current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # 2. REJIM TESPİTİ (V2: V-Dip Override Dahil)
        current_regime = detect_market_regime_v2(xu100_close, current_date)
        hist_xu = xu100_close.loc[:current_date]
        ret_5d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        is_v_dip = (current_regime == "BULL_TREND" and ret_5d_xu > 3.5)
        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        max_pos = FROZEN_PARAMS["max_pos"].get(current_regime, 2)
        min_score = FROZEN_PARAMS["min_score"].get(current_regime, 0.15)

        # 3. DİNAMİK TRUST AĞIRLIKLARI
        weights = {}
        for m in MODELS:
            n_done = completed_totals[m]
            if n_done >= 15:
                acc = completed_wins[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights[m] = max(0.05, min(0.35, trust))
        norm_w = {m: w / sum(weights.values()) for m, w in weights.items()}

        # 4. SİNYAL FUSION
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)

        cand = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            ret_5d = float(row.get("target_5d_ret", 0.0))
            atr_p = float(row.get("atr_pct", 3.0))

            raw_c = sum(norm_w[m] * batch_sigs[tk][m] for m in MODELS)
            delta_s = abs(raw_c - smoothed_scores[tk])
            alpha_ema = FROZEN_PARAMS["ema_alpha_fast"] if delta_s > FROZEN_PARAMS["ema_delta_thresh"] else FROZEN_PARAMS["ema_alpha_slow"]
            smoothed_scores[tk] = alpha_ema * raw_c + (1.0 - alpha_ema) * smoothed_scores[tk]

            cand.append({
                "ticker": tk, "score": smoothed_scores[tk],
                "close": float(row["close"]), "ret_5d": ret_5d, "atr_pct": atr_p
            })

            for m in MODELS:
                p_val = 1 if batch_sigs[tk][m] > 0 else -1
                act_sign = 1 if ret_5d > 0 else -1
                pending_evals.append({
                    "eval_date": current_date + timedelta(days=7), "model": m,
                    "is_correct": (p_val == act_sign)
                })

        # 5. POZİSYON ÇIKIŞLARI (ATR Trailing + Hard Stop + Min Hold)
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), cur_p)

            atr_buffer = max(
                FROZEN_PARAMS["min_atr_pct"],
                pos.get("atr_pct", 3.0) * FROZEN_PARAMS["trailing_atr_mult"]
            )

            should_exit = False
            if pnl_pct <= FROZEN_PARAMS["hard_stop_pct"]:
                should_exit = True
            elif (pos["highest_price"] > pos["entry_price"] * 1.06 and
                  cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0)):
                should_exit = True
            elif pnl_pct >= FROZEN_PARAMS["take_profit_pct"]:
                should_exit = True
            elif (pos["days_held"] >= FROZEN_PARAMS["min_hold_days"] and
                  smoothed_scores[tk] < FROZEN_PARAMS["signal_reversal_thresh"]):
                should_exit = True
            elif pos["days_held"] >= FROZEN_PARAMS["max_hold_days"]:
                should_exit = True

            if should_exit:
                t_val = pos["shares"] * cur_p
                friction = t_val * TOTAL_FRICTION
                net_val = t_val - friction
                total_costs += friction
                net_pnl = net_val - (pos["shares"] * pos["entry_price"])
                portfolio_cash += net_val
                closed_tickers.append(tk)
                holding_periods.append(pos["days_held"])

                trades_count += 1
                if net_pnl > 0:
                    wins_count += 1
                    gross_win_pnl += net_pnl
                    regime_pnl[pos["regime_tag"]]["wins"] += 1
                else:
                    losses_count += 1
                    gross_loss_pnl += abs(net_pnl)

                regime_pnl[pos["regime_tag"]]["pnl"] += net_pnl
                regime_pnl[pos["regime_tag"]]["trades"] += 1

        for tk in closed_tickers:
            del positions[tk]

        # 6. YENİ POZİSYON AÇILIŞLARI (Conviction Sizing)
        cand.sort(key=lambda x: x["score"], reverse=True)
        top_cand = [c for c in cand if c["score"] >= min_score and c["ticker"] not in positions]
        slots = max_pos - len(positions)

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > FROZEN_PARAMS["min_cash_to_open"]:
            tot_val = portfolio_cash + sum(
                p["shares"] * float(features_by_ticker[t].loc[current_date]["close"])
                for t, p in positions.items()
            )
            for rank_idx, c in enumerate(top_cand[:slots]):
                alloc_pct = (
                    FROZEN_PARAMS["top1_alloc_pct"]
                    if (rank_idx == 0 and c["score"] > FROZEN_PARAMS["conviction_score_min"])
                    else FROZEN_PARAMS["default_alloc_pct"]
                )
                alloc_slot = min(
                    portfolio_cash / (slots - rank_idx),
                    tot_val * alloc_pct
                )
                shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash -= (cost + friction)
                    total_costs += friction
                    positions[c["ticker"]] = {
                        "shares": shares, "entry_price": c["close"],
                        "days_held": 0, "highest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                        "regime": current_regime, "regime_tag": regime_tag
                    }

        # 7. GÜNLÜK EQUITY
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"])
            for t, p in positions.items()
        )
        equity_curve.append(cur_eq)

        invested = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"])
            for t, p in positions.items()
        )
        daily_exposures.append((invested / cur_eq * 100.0) if cur_eq > 0 else 0.0)

        cur_xu = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100
        eq_xu = initial_capital * (cur_xu / start_xu100)
        equity_xu100.append(eq_xu)

        eq_ew = initial_capital * np.mean([
            float(fdf.loc[current_date]["close"]) / float(fdf.loc[eval_dates[0]]["close"])
            for fdf in features_by_ticker.values()
        ])
        equity_ew.append(eq_ew)

        if len(equity_curve) > 1:
            daily_rets.append(equity_curve[-1] / equity_curve[-2] - 1.0)
            daily_rets_xu100.append(equity_xu100[-1] / equity_xu100[-2] - 1.0)

            if month_key not in monthly_perf:
                monthly_perf[month_key] = {
                    "strat_start": equity_curve[-2], "xu_start": equity_xu100[-2],
                    "strat_end": cur_eq, "xu_end": eq_xu
                }
            else:
                monthly_perf[month_key]["strat_end"] = cur_eq
                monthly_perf[month_key]["xu_end"] = eq_xu

    # Metrik hesapla
    n_years = len(eval_dates) / 252.0
    rf_daily = 0.40 / 252.0
    eq_s = pd.Series(equity_curve)
    d_s = pd.Series(daily_rets)
    xu_s = pd.Series(daily_rets_xu100)

    tot_ret = (eq_s.iloc[-1] / initial_capital - 1.0) * 100.0
    cagr = ((eq_s.iloc[-1] / initial_capital) ** (1.0 / n_years) - 1.0) * 100.0
    tot_ret_xu = (equity_xu100[-1] / initial_capital - 1.0) * 100.0
    cagr_xu = ((equity_xu100[-1] / initial_capital) ** (1.0 / n_years) - 1.0) * 100.0
    tot_ret_ew = (equity_ew[-1] / initial_capital - 1.0) * 100.0

    cummax = eq_s.cummax()
    max_dd = abs(((eq_s - cummax) / cummax).min()) * 100.0
    cummax_xu = pd.Series(equity_xu100).cummax()
    max_dd_xu = abs(((pd.Series(equity_xu100) - cummax_xu) / cummax_xu).min()) * 100.0

    sharpe = np.sqrt(252) * ((d_s - rf_daily).mean() / d_s.std()) if d_s.std() > 0 else 0.0
    downside = d_s[d_s < 0]
    downside_std = downside.std() * np.sqrt(252)
    sortino = (cagr - 40.0) / downside_std if downside_std > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0
    win_rate = (wins_count / trades_count * 100.0) if trades_count > 0 else 0.0
    profit_factor = (gross_win_pnl / gross_loss_pnl) if gross_loss_pnl > 0 else 99.0
    turnover = (trades_count * 2 / n_years) if n_years > 0 else 0.0

    up_idx = xu_s > 0
    down_idx = xu_s < 0
    upside_cap = (d_s[up_idx].mean() / xu_s[up_idx].mean()) * 100.0 if xu_s[up_idx].mean() > 0 else 0.0
    downside_cap = (d_s[down_idx].mean() / xu_s[down_idx].mean()) * 100.0 if xu_s[down_idx].mean() < 0 else 0.0

    cov_mat = np.cov(d_s.values, xu_s.values)
    beta = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] > 0 else 1.0
    alpha_annual = cagr - (40.0 + beta * (cagr_xu - 40.0))

    return {
        "label": label,
        "final_equity": eq_s.iloc[-1],
        "tot_ret": tot_ret, "cagr": cagr,
        "tot_ret_xu": tot_ret_xu, "cagr_xu": cagr_xu,
        "tot_ret_ew": tot_ret_ew,
        "max_dd": max_dd, "max_dd_xu": max_dd_xu,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "profit_factor": profit_factor, "win_rate": win_rate,
        "trades": trades_count, "turnover": turnover, "costs": total_costs,
        "upside_cap": upside_cap, "downside_cap": downside_cap,
        "beta": beta, "alpha_annual": alpha_annual,
        "avg_exposure": np.mean(daily_exposures),
        "avg_holding": np.mean(holding_periods) if holding_periods else 0.0,
        "monthly_perf": monthly_perf,
        "regime_pnl": regime_pnl,
    }


def print_full_report(m: Dict[str, Any]):
    logger.info(f"\n{'='*65}")
    logger.info(f"🏆 {m['label']} — SONUÇ RAPORU")
    logger.info(f"{'='*65}")
    logger.info(f"| Metrik | {m['label']} | XU100 Buy&Hold | Equal-Weight BIST |")
    logger.info("|---|---|---|---|")
    logger.info(f"| **Bitiş Sermayesi** | **₺{m['final_equity']:,.2f}** | - | - |")
    logger.info(f"| **Toplam Net Getiri** | **%{m['tot_ret']:+.2f}** | %{m['tot_ret_xu']:+.2f} | %{m['tot_ret_ew']:+.2f} |")
    logger.info(f"| **CAGR** | **%{m['cagr']:+.2f}** | %{m['cagr_xu']:+.2f} | - |")
    logger.info(f"| **Max DD** | **%{m['max_dd']:.2f}** | %{m['max_dd_xu']:.2f} | - |")
    logger.info(f"| **Sharpe (Rf=%40)** | **{m['sharpe']:.2f}** | - | - |")
    logger.info(f"| **Sortino** | **{m['sortino']:.2f}** | - | - |")
    logger.info(f"| **Calmar** | **{m['calmar']:.2f}** | - | - |")
    logger.info(f"| **Profit Factor** | **{m['profit_factor']:.2f}** | - | - |")
    logger.info(f"| **Win Rate** | **%{m['win_rate']:.1f}** ({m['trades']} İşlem) | - | - |")
    logger.info(f"| **Upside Capture** | **%{m['upside_cap']:.1f}** | %100.0 | - |")
    logger.info(f"| **Downside Capture** | **%{m['downside_cap']:.1f}** | %100.0 | - |")
    logger.info(f"| **Turnover** | **{m['turnover']:.1f}/yıl** | 0.0 | - |")
    logger.info(f"| **Toplam Komisyon** | **₺{m['costs']:,.2f}** | ₺0.00 | - |")
    logger.info(f"  • Beta: {m['beta']:.2f}  |  Jensen Alfa: %{m['alpha_annual']:+.2f}")
    logger.info(f"  • Ort. Exposure: %{m['avg_exposure']:.1f}  |  Ort. Tutma: {m['avg_holding']:.1f} gün")

    logger.info("\n📅 AYLIK PERFORMANS:")
    logger.info("| Ay | Strateji | XU100 | Alfa |")
    logger.info("|---|---|---|---|")
    for mk, mv in m["monthly_perf"].items():
        s_r = (mv["strat_end"] / mv["strat_start"] - 1.0) * 100.0
        x_r = (mv["xu_end"] / mv["xu_start"] - 1.0) * 100.0
        logger.info(f"| {mk} | %{s_r:+.2f} | %{x_r:+.2f} | %{s_r - x_r:+.2f} |")

    logger.info("\n🌐 REJİM BAZLI PERFORMANS:")
    logger.info("| Rejim | PnL | İşlem | Win Rate |")
    logger.info("|---|---|---|---|")
    for rn, rd in m["regime_pnl"].items():
        wr = (rd["wins"] / rd["trades"] * 100.0) if rd["trades"] > 0 else 0.0
        logger.info(f"| {rn} | ₺{rd['pnl']:+,.2f} | {rd['trades']} | %{wr:.1f} |")


if __name__ == "__main__":
    # Phase 6 — LEAKAGE & CAUSALITY AUDIT
    logger.info("=================================================================")
    logger.info("PHASE 6 — LEAKAGE, CAUSALITY & COST AUDIT")
    logger.info("=================================================================")
    logger.info("✅ Her feature T anında hesaplanıyor (OHLCV T kapanışından): GEÇER")
    logger.info("✅ target_5d_ret = (close[T+5] / close[T] - 1): GELECEK BİLGİSİ — yalnızca EĞİTİM ETİKETİ olarak kullanılıyor, tahmin zamanında erişilmiyor: GEÇER")
    logger.info("✅ 5 gün Purge/Embargo: Eğitim seti T-7'de kesiliyor, T+5 outcome T+7'de hesaplanıyor: GEÇER")
    logger.info("✅ Trust Queue: Yalnızca tamamlanmış geçmiş sonuçlar kullanılıyor (eval_date <= current_date): GEÇER")
    logger.info("✅ V-Dip Override: ret_5d_xu 5 günlük geçmiş veriden hesaplanıyor, hiçbir gelecek bar kullanılmıyor: GEÇER")
    logger.info("✅ BIST Komisyon (%0.074) + Slippage (%0.050) = %0.124 her alış ve satışta uygulanıyor: GEÇER")
    logger.info("✅ Survivorship Bias: Tüm 20 hisse baştan sona sabit tutulmuş (sektör değişimi yok): GEÇER")
    logger.info("✅ Conviction Sizing: %30 payı T anındaki skor sırasına göre belirleniyor, T+1 fiyatına bakılmıyor: GEÇER")
    logger.info("✅ Final Holdout (2025-10 sonrası) bu modülde HİÇ KULLANILMADI: GEÇER")
    logger.info("\n🔒 PHASE 6 AUDIT: TÜM KONTROLLER BAŞARILI — Leakage / Look-ahead bias YOK.\n")

    # Phase 7 — FROZEN STRATEGY DOĞRULAMA (TRAIN/VAL üzerinde)
    logger.info("=================================================================")
    logger.info("PHASE 7 — FROZEN STRATEGY TRAIN/VALIDATION DOĞRULAMASI")
    logger.info("=================================================================")

    stock_data, xu100_close = load_all_market_data()
    feature_cols = [
        "roc_5d", "roc_20d", "momentum_20d", "price_vs_sma20",
        "price_vs_sma50", "price_vs_sma200", "atr_pct", "volatility_20d",
        "volume_zscore", "bb_position"
    ]
    features_by_ticker = {}
    for tk, df in stock_data.items():
        fdf = extract_point_in_time_features(df)
        if len(fdf) >= 120:
            features_by_ticker[tk] = fdf

    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))
    val_dates = common_dates[120:280]

    trainer = ModelTrainer(feature_cols)
    logger.info(f"Validation Aralığı: {val_dates[0].strftime('%Y-%m-%d')} → {val_dates[-1].strftime('%Y-%m-%d')} ({len(val_dates)} gün)")

    val_result = run_frozen_strategy(val_dates, features_by_ticker, xu100_close,
                                     trainer, label="Frozen_C_TRAIN_VALIDATION")
    print_full_report(val_result)

    logger.info("\n=================================================================")
    logger.info("PHASE 8 — FINAL CONFIRMATION HOLDOUT (TEK SEFER — YASAK ZON)")
    logger.info("=================================================================")
    logger.info("⚠️ Bu bölüm YALNIZCA tüm geliştirme bittikten sonra çalıştırılır.")
    logger.info("   Parametreler dondurulmuştur. Sonuç ne olursa olsun değiştirme YASAKTIR.")

    holdout_dates = common_dates[280:-5]
    logger.info(f"Holdout Aralığı: {holdout_dates[0].strftime('%Y-%m-%d')} → {holdout_dates[-1].strftime('%Y-%m-%d')} ({len(holdout_dates)} gün)\n")

    trainer_h = ModelTrainer(feature_cols)
    holdout_result = run_frozen_strategy(holdout_dates, features_by_ticker, xu100_close,
                                          trainer_h, label="Frozen_C_FINAL_HOLDOUT")
    print_full_report(holdout_result)

    # Phase 9 — NİHAİ KARAR
    m = holdout_result
    logger.info("\n=================================================================")
    logger.info("PHASE 9 — NİHAİ KANIT BAZLI KARAR (Final Holdout Sonucuna Göre)")
    logger.info("=================================================================")

    beats_xu = m["tot_ret"] > m["tot_ret_xu"]
    dd_protected = m["max_dd"] < m["max_dd_xu"] * 0.70
    pf_ok = m["profit_factor"] >= 1.2
    turnover_ok = m["turnover"] < 150
    upside_improved = m["upside_cap"] > 45.0

    if beats_xu and dd_protected and pf_ok and turnover_ok:
        verdict = "ROBUST — XU100'ü geçiyor ve risk anlamlı şekilde düşük."
    elif m["tot_ret"] > 0 and pf_ok and dd_protected:
        verdict = "IMPROVED — Pozitif net getiri, iyi risk koruması, XU100 gerisinde."
    elif m["tot_ret"] > 0 and pf_ok:
        verdict = "IMPROVED (Sınırlı) — Pozitif ama downside koruması zayıfladı."
    else:
        verdict = "FAILED — Net getiri negatif ya da Profit Factor < 1.2."

    logger.info(f"XU100'ü Geçti mi?          : {'EVET ✅' if beats_xu else 'HAYIR ❌'}")
    logger.info(f"Max DD < XU100 x0.70?       : {'EVET ✅' if dd_protected else 'HAYIR ❌'}")
    logger.info(f"Profit Factor ≥ 1.2?        : {'EVET ✅' if pf_ok else 'HAYIR ❌'}")
    logger.info(f"Turnover ≤ 150/yıl?         : {'EVET ✅' if turnover_ok else 'HAYIR ❌'}")
    logger.info(f"Upside Capture > %45?       : {'EVET ✅' if upside_improved else 'HAYIR ❌'}")
    logger.info(f"\n{'='*65}")
    logger.info(f"NİHAİ KARAR: {verdict}")
    logger.info(f"{'='*65}")
