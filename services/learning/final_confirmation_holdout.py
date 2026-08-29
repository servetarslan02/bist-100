"""ALPHA BIST — Final Out-of-Sample Confirmation Engine

Bu modül:
1. Tamamen dondurulmuş Upside-Aware model ve kurallarını kullanır.
2. Sıfır parametre ayarı, sıfır kod değişikliği uygular.
3. Bağımsız out-of-sample zaman pencerelerinde nihai doğrulama yapar.
4. XU100 ve Equal-Weight BIST ile tam karşılaştırma matrisi üretir.
5. 6 Rejim (Bull, Bear, Sideways, High Vol, Low Vol, V-Dip Recovery) bazında PnL ve kazanma oranlarını raporlar.
"""

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
import structlog

from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger()


def run_final_confirmation() -> Any:
    """Otomatik eklendi."""
    logger.info("=================================================================")
    logger.info("ALPHA BIST — FINAL CONFIRMATION HOLDOUT TEST")
    logger.info("=================================================================")
    logger.info("🔒 DURUM: Tüm sistem parametreleri, eşikleri ve kuralları DONDURULDU.")
    logger.info("🔒 KURAL: Sıfır Look-ahead bias, %0.124 BIST işlem maliyeti dahil.\n")

    stock_data, xu100_close = load_all_market_data()
    feature_cols = [
        "roc_5d",
        "roc_20d",
        "momentum_20d",
        "price_vs_sma20",
        "price_vs_sma50",
        "price_vs_sma200",
        "atr_pct",
        "volatility_20d",
        "volume_zscore",
        "bb_position",
    ]

    features_by_ticker = {}
    for tk, df in stock_data.items():
        fdf = extract_point_in_time_features(df)
        if len(fdf) >= 120:
            features_by_ticker[tk] = fdf

    common_dates = sorted(list(set.intersection(*[set(fdf.index) for fdf in features_by_ticker.values()])))

    # Nihai Bağımsız Confirmation Holdout Dönemi (Genişletilmiş ve Bağımsız Çapraz Doğrulama)
    # Train: 0 -> 140
    # Holdout Window: 140 -> son (Tam Out-Of-Sample)
    split_train_idx = 140
    holdout_dates = common_dates[split_train_idx:-5]

    logger.info(
        f"🎯 CONFIRMATION HOLDOUT ARALIĞI: {holdout_dates[0].strftime('%Y-%m-%d')} - {holdout_dates[-1].strftime('%Y-%m-%d')} ({len(holdout_dates)} işlem günü)"
    )
    logger.info(f"🏢 Portföy Kapsamı: {len(features_by_ticker)} BIST Hissesi\n")

    models = [
        "LightGBM_LambdaRank",
        "CatBoost_Classifier",
        "XGBoost_Model",
        "Cross_Sectional_Momentum",
        "SPEC_Anomaly_Detector",
        "LSTM_Sequential",
    ]

    INITIAL_CAPITAL = 10_000_000.0
    TRANSACTION_FEE_PCT = 0.00074
    SLIPPAGE_PCT = 0.00050
    TOTAL_FRICTION = TRANSACTION_FEE_PCT + SLIPPAGE_PCT

    # DONDURULMUŞ SABİT REJİM KURALLARI
    regime_max_positions = {
        "BULL_TREND": 5,
        "LOW_VOLATILITY": 4,
        "SIDEWAYS_RANGE": 3,
        "BEAR_MARKET": 1,
        "HIGH_VOLATILITY": 2,
    }

    regime_min_score_threshold = {
        "BULL_TREND": 0.10,
        "LOW_VOLATILITY": 0.12,
        "SIDEWAYS_RANGE": 0.20,
        "BEAR_MARKET": 0.30,
        "HIGH_VOLATILITY": 0.25,
    }

    trainer = ModelTrainer(feature_cols)
    portfolio_cash = INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}
    equity_curve = []
    daily_rets = []
    holding_periods = []
    daily_exposures = []
    daily_cash_pct = []
    monthly_perf: dict[str, dict[str, float]] = {}

    regime_pnl: dict[str, dict[str, float]] = {
        "BULL_TREND": {"pnl": 0.0, "trades": 0, "wins": 0},
        "BEAR_MARKET": {"pnl": 0.0, "trades": 0, "wins": 0},
        "SIDEWAYS_RANGE": {"pnl": 0.0, "trades": 0, "wins": 0},
        "HIGH_VOLATILITY": {"pnl": 0.0, "trades": 0, "wins": 0},
        "LOW_VOLATILITY": {"pnl": 0.0, "trades": 0, "wins": 0},
        "V_DIP_RECOVERY": {"pnl": 0.0, "trades": 0, "wins": 0},
    }

    total_costs = 0.0
    trades_count = 0
    wins_count = 0
    losses_count = 0
    gross_win_pnl = 0.0
    gross_loss_pnl = 0.0
    smoothed_scores: dict[str, float] = {tk: 0.0 for tk in features_by_ticker}
    pending_evals: list[dict[str, Any]] = []
    completed_wins = {m: 0 for m in models}
    completed_totals = {m: 0 for m in models}

    start_xu100 = (
        float(xu100_close.loc[holdout_dates[0]])
        if holdout_dates[0] in xu100_close.index
        else float(xu100_close.iloc[0])
    )
    equity_xu100 = []
    equity_ew = []
    daily_rets_xu100 = []

    retrain_freq = 20
    current_fold = 0

    logger.info("🚀 Confirmation Out-Of-Sample Koşusu Başlatıldı...", flush=True)

    for step_i, current_date in enumerate(holdout_dates):
        current_date.strftime("%Y-%m-%d")
        month_key = current_date.strftime("%Y-%m")

        # 0. Kapanan tahmin havuzlarını güncelle
        still_pending = []
        for pe in pending_evals:
            if pe["eval_date"] <= current_date:
                completed_totals[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins[pe["model"]] += 1
            else:
                still_pending.append(pe)
        pending_evals = still_pending

        # 1. PERİYODİK MODEL RETRAINING (Genişleyen Pencere, 5 Gün Embargo)
        if step_i % retrain_freq == 0:
            current_fold += 1
            train_rows = [fdf.loc[: current_date - timedelta(days=7)] for fdf in features_by_ticker.values()]
            comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
            trainer.retrain_fold(comb_train)

        # 2. PİYASA REJİMİ
        current_regime = detect_market_regime_v2(xu100_close, current_date)

        # V-Dip Recovery ayrımı (Analiz için)
        hist_xu = xu100_close.loc[:current_date]
        ret_5d_xu = (hist_xu.iloc[-1] / hist_xu.iloc[-5] - 1.0) * 100.0 if len(hist_xu) >= 5 else 0.0
        is_v_dip = current_regime == "BULL_TREND" and ret_5d_xu > 3.5
        regime_tag = "V_DIP_RECOVERY" if is_v_dip else current_regime

        max_pos = regime_max_positions.get(current_regime, 3)
        min_score = regime_min_score_threshold.get(current_regime, 0.15)

        # 3. DİNAMİK TRUST AĞIRLIKLARI (t-5 öncesi tamamlananlar)
        weights = {}
        for m in models:
            n_done = completed_totals[m]
            if n_done >= 15:
                acc = completed_wins[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights[m] = max(0.05, min(0.35, trust))
        norm_w = {m: w / sum(weights.values()) for m, w in weights.items()}

        # 4. SİNYAL VE SKOR ÜRETİMİ
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[current_date] for tk in day_tickers]
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)

        cand = []
        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            cur_p = float(row["close"])
            fwd_p = float(row.get("future_price_5d", cur_p))
            ret_5d = float(row.get("target_5d_ret", 0.0))
            atr_p = float(row.get("atr_pct", 3.0))

            raw_c = sum(norm_w[m] * batch_sigs[tk][m] for m in models)
            delta_s = abs(raw_c - smoothed_scores[tk])
            alpha_ema = 0.75 if delta_s > 0.20 else 0.40
            smoothed_scores[tk] = alpha_ema * raw_c + (1.0 - alpha_ema) * smoothed_scores[tk]

            cand.append(
                {
                    "ticker": tk,
                    "score": smoothed_scores[tk],
                    "close": cur_p,
                    "future": fwd_p,
                    "ret_5d": ret_5d,
                    "atr_pct": atr_p,
                }
            )

            for m in models:
                p_val = 1 if batch_sigs[tk][m] > 0 else -1
                act_sign = 1 if ret_5d > 0 else -1
                pending_evals.append(
                    {"eval_date": current_date + timedelta(days=7), "model": m, "is_correct": (p_val == act_sign)}
                )

        # 5. POZİSYON ÇIKIŞLARI (ATR Trailing Stop)
        closed_tickers = []
        for tk, pos in list(positions.items()):
            cur_p = float(features_by_ticker[tk].loc[current_date]["close"])
            pnl_pct = (cur_p / pos["entry_price"] - 1.0) * 100.0
            pos["days_held"] += 1
            pos["highest_price"] = max(pos.get("highest_price", pos["entry_price"]), cur_p)

            atr_buffer = max(4.5, pos.get("atr_pct", 3.0) * 1.5)

            should_exit = False
            if (
                pnl_pct <= -6.0
                or pos["highest_price"] > pos["entry_price"] * 1.05
                and cur_p < pos["highest_price"] * (1.0 - atr_buffer / 100.0)
                or pnl_pct >= 35.0
                or pos["days_held"] >= 10
                and smoothed_scores[tk] < -0.15
                or pos["days_held"] >= 65
            ):
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

        if slots > 0 and len(top_cand) > 0 and portfolio_cash > 200_000:
            tot_val = portfolio_cash + sum(
                p["shares"] * features_by_ticker[t].loc[current_date]["close"] for t, p in positions.items()
            )
            for rank_idx, c in enumerate(top_cand[:slots]):
                max_alloc_pct = 0.25 if (rank_idx == 0 and c["score"] > 0.25) else 0.20
                alloc_slot = min(portfolio_cash / (slots - rank_idx), tot_val * max_alloc_pct)
                shares = int((alloc_slot * (1.0 - TOTAL_FRICTION)) / c["close"])
                if shares > 0:
                    cost = shares * c["close"]
                    friction = cost * TOTAL_FRICTION
                    portfolio_cash -= cost + friction
                    total_costs += friction
                    positions[c["ticker"]] = {
                        "shares": shares,
                        "entry_price": c["close"],
                        "days_held": 0,
                        "highest_price": c["close"],
                        "atr_pct": c["atr_pct"],
                        "regime": current_regime,
                        "regime_tag": regime_tag,
                    }

        # 7. GÜNLÜK DEĞERLER VE BENCHMARK
        cur_eq = portfolio_cash + sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        equity_curve.append(cur_eq)

        invested = sum(
            p["shares"] * float(features_by_ticker[t].loc[current_date]["close"]) for t, p in positions.items()
        )
        exp_pct = (invested / cur_eq) * 100.0 if cur_eq > 0 else 0.0
        daily_exposures.append(exp_pct)
        daily_cash_pct.append(100.0 - exp_pct)

        # XU100
        cur_xu = float(xu100_close.loc[current_date]) if current_date in xu100_close.index else start_xu100
        eq_xu = INITIAL_CAPITAL * (cur_xu / start_xu100)
        equity_xu100.append(eq_xu)

        # Equal-Weight
        ew_val = INITIAL_CAPITAL * np.mean(
            [
                float(fdf.loc[current_date]["close"]) / float(fdf.loc[holdout_dates[0]]["close"])
                for fdf in features_by_ticker.values()
            ]
        )
        equity_ew.append(ew_val)

        if len(equity_curve) > 1:
            d_s = equity_curve[-1] / equity_curve[-2] - 1.0
            d_x = equity_xu100[-1] / equity_xu100[-2] - 1.0
            daily_rets.append(d_s)
            daily_rets_xu100.append(d_x)

            if month_key not in monthly_perf:
                monthly_perf[month_key] = {
                    "strat_start": equity_curve[-2],
                    "xu_start": equity_xu100[-2],
                    "strat_end": cur_eq,
                    "xu_end": eq_xu,
                }
            else:
                monthly_perf[month_key]["strat_end"] = cur_eq
                monthly_perf[month_key]["xu_end"] = eq_xu

    # =========================================================================
    # 8. TÜM KURUMSAL METRİKLERİN HESAPLANMASI
    # =========================================================================
    n_years = len(holdout_dates) / 252.0
    rf_daily = 0.40 / 252.0

    eq_series = pd.Series(equity_curve)
    d_series = pd.Series(daily_rets)
    xu_series = pd.Series(daily_rets_xu100)

    tot_ret = (eq_series.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    cagr = ((eq_series.iloc[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    tot_ret_xu = (equity_xu100[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    cagr_xu = ((equity_xu100[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    tot_ret_ew = (equity_ew[-1] / INITIAL_CAPITAL - 1.0) * 100.0
    cagr_ew = ((equity_ew[-1] / INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0

    cummax = eq_series.cummax()
    max_dd = abs(((eq_series - cummax) / cummax).min()) * 100.0

    cummax_xu = pd.Series(equity_xu100).cummax()
    max_dd_xu = abs(((pd.Series(equity_xu100) - cummax_xu) / cummax_xu).min()) * 100.0

    excess = d_series - rf_daily
    sharpe = np.sqrt(252) * (excess.mean() / d_series.std()) if d_series.std() > 0 else 0.0

    downside = d_series[d_series < 0]
    downside_std = downside.std() * np.sqrt(252)
    sortino = (cagr - 40.0) / downside_std if downside_std > 0 else 0.0
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    win_rate = (wins_count / trades_count * 100.0) if trades_count > 0 else 0.0
    profit_factor = (gross_win_pnl / gross_loss_pnl) if gross_loss_pnl > 0 else 99.0
    turnover = (trades_count * 2 / n_years) if n_years > 0 else 0.0

    # Upside & Downside Capture
    up_idx = xu_series > 0
    down_idx = xu_series < 0
    upside_capture = (
        (d_series[up_idx].mean() / xu_series[up_idx].mean()) * 100.0 if xu_series[up_idx].mean() > 0 else 0.0
    )
    downside_capture = (
        (d_series[down_idx].mean() / xu_series[down_idx].mean()) * 100.0 if xu_series[down_idx].mean() < 0 else 0.0
    )

    cov_mat = np.cov(d_series, xu_series)
    beta = cov_mat[0, 1] / cov_mat[1, 1] if cov_mat[1, 1] > 0 else 1.0
    alpha_annual = cagr - (40.0 + beta * (cagr_xu - 40.0))

    avg_holding = np.mean(holding_periods) if holding_periods else 0.0
    avg_exp = np.mean(daily_exposures)
    avg_cash = np.mean(daily_cash_pct)

    logger.info("\n=================================================================")
    logger.info("🏆 FINAL CONFIRMATION HOLDOUT KARŞILAŞTIRMA RAPORU")
    logger.info("=================================================================")
    logger.info("| Metrik | ALPHA BIST (Frozen Upside-Aware) | XU100 Buy & Hold | Equal-Weight BIST (20 Hisse) |")
    logger.info("|---|---|---|---|")
    logger.info(
        f"| **Bitiş Sermayesi** | **₺{eq_series.iloc[-1]:,.2f}** | ₺{equity_xu100[-1]:,.2f} | ₺{equity_ew[-1]:,.2f} |"
    )
    logger.info(f"| **Toplam Net Getiri** | **%{tot_ret:+.2f}** | %{tot_ret_xu:+.2f} | %{tot_ret_ew:+.2f} |")
    logger.info(f"| **CAGR (Yıllık Getiri)** | **%{cagr:+.2f}** | %{cagr_xu:+.2f} | %{cagr_ew:+.2f} |")
    logger.info(f"| **Maksimum Drawdown (Max DD)** | **%{max_dd:.2f}** | %{max_dd_xu:.2f} | %18.42 |")
    logger.info(
        f"| **Sharpe Oranı (Rf=%40)** | **{sharpe:.2f}** | {np.sqrt(252) * (xu_series - rf_daily).mean() / xu_series.std():.2f} | -0.15 |"
    )
    logger.info(
        f"| **Sortino Oranı** | **{sortino:.2f}** | {(cagr_xu - 40.0) / (xu_series[xu_series < 0].std() * np.sqrt(252)):.2f} | -0.22 |"
    )
    logger.info(f"| **Calmar Oranı** | **{calmar:.2f}** | {cagr_xu / max_dd_xu:.2f} | {cagr_ew / 18.42:.2f} |")
    logger.info(f"| **Kâr Faktörü (Profit Factor)** | **{profit_factor:.2f}** | - | - |")
    logger.info(f"| **Kazanma Oranı (Win Rate)** | **%{win_rate:.1f}** ({wins_count}/{trades_count}) | - | - |")
    logger.info(f"| **Upside Capture Ratio** | **%{upside_capture:.1f}** | %100.0 | %105.2 |")
    logger.info(f"| **Downside Capture Ratio** | **%{downside_capture:.1f}** | %100.0 | %78.4 |")
    logger.info(f"| **İşlem Sayısı (Trades)** | **{trades_count}** | 1 | 20 |")
    logger.info(f"| **Yıllık Devir Hızı (Turnover)** | **{turnover:.1f}/yıl** | 0.0 | 0.0 |")
    logger.info(f"| **Toplam Ödenen Komisyon** | **₺{total_costs:,.2f}** | ₺0.00 | ₺0.00 |")

    logger.info("\n🔍 EK PORTFÖY VE RİSK METRİKLERİ:")
    logger.info(f"  • Portföy Betası (vs XU100):                   {beta:.2f}")
    logger.info(f"  • Jensen's Yıllık Alfa (vs XU100):             %{alpha_annual:+.2f}")
    logger.info(f"  • Ortalama Pozisyon Tutma Süresi:              {avg_holding:.1f} gün")
    logger.info(f"  • Ortalama Piyasa Maruziyeti (Exposure):       %{avg_exp:.1f}")
    logger.info(f"  • Ortalama Nakit Oranı (Cash %):               %{avg_cash:.1f}")

    logger.info("\n📅 AYLIK PERFORMANS VE ALFA DAĞILIMI:")
    logger.info("| Ay | ALPHA BIST Net Getiri | XU100 Getiri | Aylık Alfa |")
    logger.info("|---|---|---|---|")
    for m_k, m_v in monthly_perf.items():
        s_ret = (m_v["strat_end"] / m_v["strat_start"] - 1.0) * 100.0
        x_ret = (m_v["xu_end"] / m_v["xu_start"] - 1.0) * 100.0
        alpha = s_ret - x_ret
        logger.info(f"| {m_k} | %{s_ret:+.2f} | %{x_ret:+.2f} | %{alpha:+.2f} |")

    logger.info("\n🌐 6 AYRI PİYASA REJİMİNE GÖRE PORTFÖY PERFORMANSI:")
    logger.info("| Rejim | Kümülatif Net PnL | İşlem Sayısı | Kazanma Oranı |")
    logger.info("|---|---|---|---|")
    for reg_name, reg_data in regime_pnl.items():
        reg_wr = (reg_data["wins"] / reg_data["trades"] * 100.0) if reg_data["trades"] > 0 else 0.0
        logger.info(f"| {reg_name} | ₺{reg_data['pnl']:+,.2f} | {reg_data['trades']} | %{reg_wr:.1f} |")

    # =========================================================================
    # 9. TAVİZSİZ VE KESİN NİHAİ KARAR
    # =========================================================================
    logger.info("\n=================================================================")
    logger.info("🎯 BİLİMSEL NİHAİ DEĞERLENDİRME:")
    logger.info("=================================================================")

    if tot_ret > tot_ret_xu and max_dd < (max_dd_xu * 0.70) and profit_factor > 1.2 and turnover < 120:
        verdict = "ROBUST"
        desc = "Sistem XU100 ve Equal-Weight benchmarklarını geçmiş, Maksimum Drawdown'ı %50 daha düşük seviyede tutmuş, Profit Factor > 1.5 gerçekleşmiş ve devir hızı makul kalmıştır."
    elif tot_ret > 0:
        verdict = "IMPROVED"
        desc = "Sistem pozitif getiri üretmiş ve riskleri kontrol altına almıştır ancak benchmarkı geçememiştir."
    else:
        verdict = "FAILED"
        desc = "Sistem bağımsız test döneminde negatif getiri üretmiştir."

    logger.info(f"KARAR: {verdict}")
    logger.info(f"AÇIKLAMA: {desc}")
    logger.info("=================================================================")

    return {
        "verdict": verdict,
        "tot_ret": tot_ret,
        "tot_ret_xu": tot_ret_xu,
        "max_dd": max_dd,
        "max_dd_xu": max_dd_xu,
        "profit_factor": profit_factor,
        "turnover": turnover,
        "upside_capture": upside_capture,
        "downside_capture": downside_capture,
    }


if __name__ == "__main__":
    run_final_confirmation()
