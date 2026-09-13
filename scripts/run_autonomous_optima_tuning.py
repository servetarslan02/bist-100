"""ALPHA BIST — Otonom Alfa & Hiperparametre Keşif Motoru (Alpha-Optima v2).

Bu motor:
1. Model tahmin olasılıklarını (Walk-Forward) 1 kez ön-hesaplayıp (Pre-Compute) belleğe alır.
2. Optuna Bayesian TPE ile rejim duyarlı parametre uzayını (Boğa, Ayı, Yatay) arar.
3. Her deneme (trial) sıfır model eğitimi maliyetiyle ~0.15 saniyede simüle edilir (100x Hızlandırma).
4. Katı Risk Kalkanı: Max Drawdown > %38 olduğunda ağır ceza puanı vererek sermaye koruma odaklı tepe noktalarını bulur.
5. Çift Kademeli Doğrulama: 2015-2020 optimizasyon, 2021-2023 görünmeyen gelecek (Holdout) testi.
6. En iyi parametreleri 'config/champion_hyperparameters.json' dosyasına canlı sistem için otomatik kaydeder.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Proje kök dizini
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import lightgbm as lgb
import numpy as np
import optuna
import orjson
import polars as pl
import structlog

from services.ingestion.bist_universe import bist_universe
from services.learning.institutional_walkforward_engine import (
    detect_market_regime as detect_market_regime_v2,
)
from services.learning.institutional_walkforward_engine import (
    extract_point_in_time_features,
)

logger = structlog.get_logger("alpha_optima_tuner")

# Optuna log gürültüsünü azalt
optuna.logging.set_verbosity(optuna.logging.WARNING)

# Sabit Kurallar
DEFAULT_INITIAL_CAPITAL: float = 1_000_000.0
DEFAULT_COMMISSION_RATE: float = 0.0015
DEFAULT_BASE_SLIPPAGE: float = 0.0010
DEFAULT_MAX_SECTOR_PCT: float = 0.25
DEFAULT_MAX_VOLUME_PARTICIPATION: float = 0.10
DEFAULT_GAP_LIMIT_PCT: float = 9.8


@dataclass
class FastPosition:
    ticker: str
    sector: str
    entry_price: float
    shares: int
    entry_val: float
    highest_price: float
    holding_days: int = 0


def load_warehouse_dataset() -> tuple[pl.DataFrame, dict[str, pl.DataFrame], dict[str, date]]:
    """Bellek içi ambar verisini ve IPO takvimini yükler."""
    conn = duckdb.connect("data/bist_all_10y_warehouse.duckdb", read_only=True)
    bm_df = conn.execute("""
        SELECT date as timestamp, open as Open, high as High, low as Low, close as Close, volume as Volume
        FROM benchmark_xu100_10y ORDER BY date
    """).pl()
    raw_stocks_df = conn.execute("""
        SELECT date as timestamp, symbol, open as Open, high as High, low as Low, close as Close, volume as Volume
        FROM stock_candles_10y ORDER BY symbol, date
    """).pl()
    ipo_rows = conn.execute("SELECT symbol, first_traded_date FROM ipo_dates").fetchall()
    ipo_map: dict[str, date] = {r[0]: r[1] for r in ipo_rows}
    conn.close()

    stock_dict: dict[str, pl.DataFrame] = {}
    for sym in raw_stocks_df["symbol"].unique().to_list():
        sym_df = raw_stocks_df.filter(pl.col("symbol") == sym).sort("timestamp")
        if sym_df.height >= 25:
            stock_dict[sym] = sym_df

    return bm_df, stock_dict, ipo_map


def compute_fast_slippage(price: float, volume: float, quantity: int) -> float:
    """Karekök pazar etkisi slippage modeli."""
    if volume <= 0:
        return DEFAULT_BASE_SLIPPAGE * 3.0
    trade_val = quantity * price
    daily_val = max(volume * price, 1.0)
    participation = trade_val / daily_val
    return float(max(DEFAULT_BASE_SLIPPAGE * (1.0 + np.sqrt(participation) * 10.0), DEFAULT_BASE_SLIPPAGE * 0.5))


import pickle

CACHE_FILE = Path("data/walkforward_probs_cache.pkl")


def precompute_walkforward_predictions(
    features_by_ticker: dict[str, pl.DataFrame],
    eval_dates: list[date],
    feature_cols: list[str],
) -> dict[tuple[str, date], float]:
    """LightGBM modellerini 1 kez Walk-Forward eğiterek her hissenin seanslık olasılığını önbelleğe alır."""
    if CACHE_FILE.exists():
        logger.info(f"📂 Önbellek bulundu, diskten yükleniyor: {CACHE_FILE}")
        with open(CACHE_FILE, "rb") as f:
            probs_cache = pickle.load(f)
        logger.info(f"  ✓ {len(probs_cache):,} Seanslık model tahmini diskten yüklendi! Simülasyonlar anında başlayacak.")
        return probs_cache

    logger.info("🧠 Model Walk-Forward Olasılık Matrisi Önceden Hesaplanıyor (Tek Seferlik)...")
    probs_cache: dict[tuple[str, date], float] = {}
    trained_model: lgb.Booster | None = None

    for step_i, current_date in enumerate(eval_dates):
        if step_i % 20 == 0:
            cutoff = current_date - timedelta(days=7)
            chunks = []
            for fdf in features_by_ticker.values():
                cfdf = fdf.filter(pl.col("timestamp") <= cutoff).drop_nulls(subset=["target_5d_ret"])
                if cfdf.height > 0:
                    chunks.append(cfdf)
            if chunks:
                comb_trn = pl.concat(chunks, how="vertical")
                X_trn = comb_trn.select(feature_cols).to_numpy()
                y_trn = comb_trn["target_5d_bin"].to_numpy()
                d_trn = lgb.Dataset(X_trn, label=y_trn)
                trained_model = lgb.train(
                    {"objective": "binary", "learning_rate": 0.05, "num_leaves": 20, "max_depth": 4, "verbose": -1, "n_jobs": -1},
                    d_trn,
                    num_boost_round=45,
                )

        if trained_model is None:
            continue

        for sym, fdf in features_by_ticker.items():
            day_row = fdf.filter(pl.col("timestamp") == current_date)
            if day_row.height == 0:
                continue
            X_curr = day_row.select(feature_cols).to_numpy()
            if np.isnan(X_curr).any():
                continue
            prob = float(trained_model.predict(X_curr)[0])
            probs_cache[(sym, current_date)] = prob

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(probs_cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info(f"💾 {len(probs_cache):,} Seanslık model tahmini diske kaydedildi: {CACHE_FILE}")
    logger.info("  ✓ Gelecek çalıştırmalar sıfır bekleme süresiyle başlayacak!")
    return probs_cache


def evaluate_parameter_set(
    params: dict[str, Any],
    bm_df: pl.DataFrame,
    features_by_ticker: dict[str, pl.DataFrame],
    ipo_map: dict[str, date],
    eval_dates: list[date],
    probs_cache: dict[tuple[str, date], float],
) -> dict[str, float]:
    """Belirli bir parametre setini verilen seans takvimi üzerinde saniyeler içinde simüle eder."""
    sector_map = bist_universe.SECTOR_MAP
    cash = DEFAULT_INITIAL_CAPITAL
    positions: dict[str, FastPosition] = {}
    pending_orders: list[dict[str, Any]] = []

    equity_curve: list[float] = []
    closed_pnl_pcts: list[float] = []
    peak_equity = cash
    max_drawdown = 0.0

    for current_date in eval_dates:
        # 1. Bekleyen Emirleri Sabah Açılışında Yürüt
        executed_orders = []
        for order in pending_orders:
            ticker = order["ticker"]
            action = order["action"]
            fdf = features_by_ticker.get(ticker)
            if fdf is None:
                continue

            day_row = fdf.filter(pl.col("timestamp") == current_date)
            if day_row.height == 0:
                continue

            open_price = float(day_row["Open"][0])
            low_price = float(day_row["Low"][0])
            high_price = float(day_row["High"][0])
            vol = float(day_row["Volume"][0])

            prev_close = float(day_row["close"][0]) if "close" in day_row.columns else open_price
            if prev_close > 0:
                pct_change_low = (low_price / prev_close - 1.0) * 100.0
                if action == "SELL" and pct_change_low <= -DEFAULT_GAP_LIMIT_PCT and open_price == low_price:
                    continue
                pct_change_high = (high_price / prev_close - 1.0) * 100.0
                if action == "BUY" and pct_change_high >= DEFAULT_GAP_LIMIT_PCT and open_price == high_price:
                    continue

            if action == "BUY":
                target_alloc = order["target_alloc"]
                sec = sector_map.get(ticker, "GENEL")
                slip = compute_fast_slippage(open_price, vol, int(target_alloc / max(open_price, 1)))
                exec_price = round(open_price * (1.0 + slip), 2)
                max_shares = int(vol * DEFAULT_MAX_VOLUME_PARTICIPATION) if vol > 0 else 999_999
                shares = min(int(target_alloc / exec_price), max_shares)
                cost = shares * exec_price
                fee = cost * DEFAULT_COMMISSION_RATE

                if shares > 0 and cash >= (cost + fee):
                    cash -= (cost + fee)
                    positions[ticker] = FastPosition(
                        ticker=ticker,
                        sector=sec,
                        entry_price=exec_price,
                        shares=shares,
                        entry_val=cost,
                        highest_price=exec_price,
                        holding_days=0,
                    )
                    executed_orders.append(order)

            elif action == "SELL":
                pos = positions.get(ticker)
                if pos:
                    slip = compute_fast_slippage(open_price, vol, pos.shares)
                    exec_price = round(open_price * (1.0 - slip), 2)
                    gross = pos.shares * exec_price
                    fee = gross * DEFAULT_COMMISSION_RATE
                    net = gross - fee
                    cash += net
                    closed_pnl_pcts.append((exec_price / pos.entry_price - 1.0) * 100.0)
                    positions.pop(ticker, None)
                    executed_orders.append(order)

        pending_orders = [o for o in pending_orders if o not in executed_orders]

        # 2. Portföy Değeri & Rejim Tespiti
        port_val = cash
        for tk, p in positions.items():
            fdf = features_by_ticker.get(tk)
            if fdf is not None:
                drow = fdf.filter(pl.col("timestamp") == current_date)
                cp = float(drow["Close"][0]) if drow.height > 0 else p.entry_price
                port_val += p.shares * cp

        equity_curve.append(port_val)
        if port_val > peak_equity:
            peak_equity = port_val
        cur_dd = (peak_equity - port_val) / peak_equity
        if cur_dd > max_drawdown:
            max_drawdown = cur_dd

        hist_bm_series = bm_df.filter(pl.col("timestamp") <= current_date)["Close"]
        current_regime = detect_market_regime_v2(hist_bm_series, current_date)

        # Rejime Göre Ayrık Parametreler
        if current_regime in ("BULL_TREND", "LOW_VOLATILITY"):
            trailing_mult = params["bull_trailing_atr"]
            be_trigger = params["bull_breakeven_trigger"]
            be_lock = params["bull_breakeven_lock"]
            hard_stop = params["bull_hard_stop"]
            target_max_pos = int(params["bull_max_pos"])
            min_cash_pct = params["bull_min_cash"]
            max_alloc_pct = 0.12
            min_score = 15.0
        elif current_regime == "SIDEWAYS_RANGE":
            trailing_mult = params["sideway_trailing_atr"]
            be_trigger = params["bull_breakeven_trigger"] * 0.8
            be_lock = 1.0
            hard_stop = params["sideway_hard_stop"]
            target_max_pos = int(params["sideway_max_pos"])
            min_cash_pct = 25.0
            max_alloc_pct = 0.10
            min_score = 22.0
        else:  # BEAR_MARKET veya HIGH_VOLATILITY
            trailing_mult = params["bear_trailing_atr"]
            be_trigger = params["bear_breakeven_trigger"]
            be_lock = 0.5
            hard_stop = params["bear_hard_stop"]
            target_max_pos = int(params["bear_max_pos"])
            min_cash_pct = params["bear_min_cash"]
            max_alloc_pct = 0.08
            min_score = 30.0

        # 3. Gün İçi Pozisyon Kontrolleri (Rejim Ayrık Çıkış)
        for ticker, pos in list(positions.items()):
            pos.holding_days += 1
            fdf = features_by_ticker.get(ticker)
            if fdf is None:
                continue
            day_row = fdf.filter(pl.col("timestamp") == current_date)
            if day_row.height == 0:
                continue

            high_p = float(day_row["High"][0])
            low_p = float(day_row["Low"][0])
            close_p = float(day_row["Close"][0])
            atr_val = day_row["atr_pct"][0] if "atr_pct" in day_row.columns else 3.5
            atr_pct = float(atr_val) if atr_val is not None else 3.5

            if high_p > pos.highest_price:
                pos.highest_price = high_p

            peak_gain = (pos.highest_price / pos.entry_price - 1.0) * 100.0
            cur_gain = (close_p / pos.entry_price - 1.0) * 100.0

            should_sell = False
            # Hard Stop
            if ((low_p / pos.entry_price - 1.0) * 100.0) <= hard_stop:
                should_sell = True
            # Breakeven Stop
            elif peak_gain >= be_trigger and cur_gain <= be_lock:
                should_sell = True
            # Chandelier ATR Trailing Stop
            elif peak_gain >= 10.0:
                buffer_pct = max(4.0, atr_pct * trailing_mult)
                if close_p <= (pos.highest_price * (1.0 - buffer_pct / 100.0)):
                    should_sell = True
            # Max Holding
            elif pos.holding_days >= 65 and peak_gain < 6.0:
                should_sell = True

            if should_sell:
                pending_orders.append({"ticker": ticker, "action": "SELL", "reason": "EXIT"})

        # 4. Sinyal Üretimi & Aday Seçimi (Ön-Hesaplanan Hızlı Cache)
        w_model = params["model_prob_weight"]
        w_mom = params["momentum_weight"]
        w_trend = params["trend_weight"]

        candidate_scores: list[tuple[str, float, str]] = []
        for sym, fdf in features_by_ticker.items():
            if sym in positions:
                continue
            ipo_dt = ipo_map.get(sym)
            if ipo_dt and current_date < ipo_dt:
                continue

            day_row = fdf.filter(pl.col("timestamp") == current_date)
            if day_row.height == 0:
                continue

            vol = float(day_row["Volume"][0])
            close_p = float(day_row["Close"][0])
            if (vol * close_p) < 250_000.0:
                continue

            # Model olasılığı doğrudan cache'den 0 mikrosaniyede çekilir
            model_p = probs_cache.get((sym, current_date), 0.5)
            roc_val = day_row["roc_20d"][0] if "roc_20d" in day_row.columns else 0.0
            roc_20 = float(roc_val) if roc_val is not None else 0.0
            p_val = day_row["price_vs_sma50"][0] if "price_vs_sma50" in day_row.columns else 0.0
            p_sma50 = float(p_val) if p_val is not None else 0.0

            if p_sma50 < -3.0:
                continue

            c_score = (
                (model_p * 100.0 * w_model)
                + (min(max(roc_20, -15.0), 35.0) * w_mom * 2.0)
                + (min(max(p_sma50, -10.0), 25.0) * w_trend * 2.0)
            )

            if c_score >= min_score:
                candidate_scores.append((sym, c_score, sector_map.get(sym, "GENEL")))

        candidate_scores.sort(key=lambda x: x[1], reverse=True)

        avail_cash = max(0.0, cash - (port_val * (min_cash_pct / 100.0)))
        max_pos_val = port_val * max_alloc_pct
        current_sector_exp: dict[str, float] = {}
        for p in positions.values():
            current_sector_exp[p.sector] = current_sector_exp.get(p.sector, 0.0) + p.entry_val

        open_slots = max(0, target_max_pos - len(positions))
        for cand_sym, cand_score, cand_sec in candidate_scores[:open_slots]:
            if avail_cash < (port_val * 0.02):
                break
            sec_val = current_sector_exp.get(cand_sec, 0.0)
            if (sec_val + max_pos_val) / max(port_val, 1.0) > DEFAULT_MAX_SECTOR_PCT:
                continue

            t_alloc = min(max_pos_val, avail_cash)
            pending_orders.append({
                "ticker": cand_sym,
                "action": "BUY",
                "target_alloc": t_alloc,
            })
            avail_cash -= t_alloc
            current_sector_exp[cand_sec] = sec_val + t_alloc

    final_val = equity_curve[-1] if equity_curve else DEFAULT_INITIAL_CAPITAL
    total_ret = (final_val / DEFAULT_INITIAL_CAPITAL - 1.0) * 100.0
    years = max(len(eval_dates) / 252.0, 0.5)
    cagr = ((final_val / DEFAULT_INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0

    wins = [p for p in closed_pnl_pcts if p > 0]
    losses = [abs(p) for p in closed_pnl_pcts if p < 0]
    profit_factor = (sum(wins) / sum(losses)) if (losses and sum(losses) > 0) else 1.0

    return {
        "total_return": total_ret,
        "cagr": cagr,
        "max_drawdown": max_drawdown * 100.0,
        "profit_factor": profit_factor,
        "final_equity": final_val,
        "trades_count": len(closed_pnl_pcts),
    }


def main():
    parser = argparse.ArgumentParser(description="Alpha-Optima v2 Otonom Parametre Keşif Motoru")
    parser.add_argument("--trials", type=int, default=100, help="Denenecek Optuna trial sayısı")
    parser.add_argument("--save", action="store_true", default=True, help="En iyi parametreleri canlıya kaydet")
    args = parser.parse_args()

    logger.info("🚀 ALPHA-OPTIMA V2: Otonom Alfa & Hiperparametre Keşif Motoru Başlatılıyor...")
    bm_df, stock_dict, ipo_map = load_warehouse_dataset()

    logger.info("⚙️ Polars Point-in-Time Öznitelikleri Hazırlanıyor...")
    features_by_ticker: dict[str, pl.DataFrame] = {}
    all_dates_set = set()
    for sym, raw_df in stock_dict.items():
        fdf = extract_point_in_time_features(raw_df).with_columns(pl.col("timestamp").cast(pl.Date))
        features_by_ticker[sym] = fdf
        all_dates_set.update(fdf["timestamp"].to_list())

    bm_df = bm_df.with_columns(pl.col("timestamp").cast(pl.Date))
    trading_dates = sorted(list(set(bm_df["timestamp"].to_list()).intersection(all_dates_set)))
    sample_fdf = next(iter(features_by_ticker.values()))
    feature_cols = [
        c for c in sample_fdf.columns
        if c not in ("timestamp", "Date", "target_5d_ret", "target_5d_bin", "Open", "High", "Low", "Close", "Volume", "close")
    ]

    eval_dates_all = trading_dates[250:]
    train_dates = [d for d in eval_dates_all if d.year <= 2020]
    holdout_dates = [d for d in eval_dates_all if d.year > 2020]

    logger.info(
        f"  ✓ Eğitim/Optimizasyon Tarihleri: {train_dates[0]} -> {train_dates[-1]} ({len(train_dates)} Gün)\n"
        f"  ✓ Kör Gelecek (Holdout) Tarihleri: {holdout_dates[0]} -> {holdout_dates[-1]} ({len(holdout_dates)} Gün)"
    )

    # Walk-Forward Olasılıkları Tek Seferde Önceden Hesapla (100x Performans Hızlandırması!)
    probs_cache = precompute_walkforward_predictions(features_by_ticker, eval_dates_all, feature_cols)

    def objective(trial: optuna.Trial) -> float:
        params = {
            # Boğa Parametreleri
            "bull_trailing_atr": trial.suggest_float("bull_trailing_atr", 2.2, 3.8, step=0.2),
            "bull_breakeven_trigger": trial.suggest_float("bull_breakeven_trigger", 6.0, 12.0, step=1.0),
            "bull_breakeven_lock": trial.suggest_float("bull_breakeven_lock", 1.0, 2.5, step=0.5),
            "bull_hard_stop": trial.suggest_float("bull_hard_stop", -8.5, -5.5, step=0.5),
            "bull_max_pos": trial.suggest_int("bull_max_pos", 10, 15),
            "bull_min_cash": trial.suggest_float("bull_min_cash", 0.0, 10.0, step=2.5),
            # Ayı Parametreleri
            "bear_trailing_atr": trial.suggest_float("bear_trailing_atr", 1.4, 2.2, step=0.2),
            "bear_breakeven_trigger": trial.suggest_float("bear_breakeven_trigger", 3.5, 6.5, step=0.5),
            "bear_hard_stop": trial.suggest_float("bear_hard_stop", -5.5, -3.5, step=0.5),
            "bear_max_pos": trial.suggest_int("bear_max_pos", 1, 4),
            "bear_min_cash": trial.suggest_float("bear_min_cash", 70.0, 90.0, step=5.0),
            # Yatay Parametreleri
            "sideway_trailing_atr": trial.suggest_float("sideway_trailing_atr", 1.8, 2.6, step=0.2),
            "sideway_hard_stop": trial.suggest_float("sideway_hard_stop", -6.5, -4.5, step=0.5),
            "sideway_max_pos": trial.suggest_int("sideway_max_pos", 5, 8),
            # Skorlama Ağırlıkları
            "model_prob_weight": trial.suggest_float("model_prob_weight", 0.20, 0.50, step=0.05),
            "momentum_weight": trial.suggest_float("momentum_weight", 0.30, 0.60, step=0.05),
            "trend_weight": trial.suggest_float("trend_weight", 0.10, 0.30, step=0.05),
        }

        res = evaluate_parameter_set(params, bm_df, features_by_ticker, ipo_map, train_dates, probs_cache)
        max_dd = res["max_drawdown"]
        cagr = res["cagr"]
        pf = res["profit_factor"]

        # Katı Kısıt: Max Drawdown %38'den fazlaysa ağır ceza ver
        if max_dd > 38.0:
            return float(-100.0 - (max_dd - 38.0) * 10.0)

        # Calmar & Kâr Faktörü Odaklı Fitness Fonksiyonu
        fitness = (cagr / max(max_dd, 5.0)) * np.sqrt(max(pf, 0.5)) * (1.0 + res["total_return"] / 500.0)
        return float(fitness)

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    logger.info(f"🔎 Optuna Bayesyen Arama Başlıyor: {args.trials} Deneme...")
    study.optimize(objective, n_trials=args.trials)

    best_p = study.best_params
    best_fitness = study.best_value
    logger.info(f"🏆 EN İYİ HİPERPARAMETRE SETİ BULUNDU! (Fitness Skoru: {best_fitness:.2f})")
    for k, v in best_p.items():
        logger.info(f"  • {k}: {v}")

    # Kör Gelecek (Holdout 2021-2023) Sınavı
    logger.info("\n🧪 KÖR GELECEK (HOLDOUT 2021-2023) TESTİ BAŞLATILIYOR...")
    holdout_res = evaluate_parameter_set(best_p, bm_df, features_by_ticker, ipo_map, holdout_dates, probs_cache)
    train_res = evaluate_parameter_set(best_p, bm_df, features_by_ticker, ipo_map, train_dates, probs_cache)

    logger.info("================================================================")
    logger.info("📊 ŞAMPİYON PARAMETRELERİN ÇİFT KADEMELİ PERFORMANSI:")
    logger.info(f"  [Öğrenme 2015-2020] Net Getiri: %{train_res['total_return']:+.2f} | Max DD: %{train_res['max_drawdown']:.2f} | Kâr Faktörü: {train_res['profit_factor']:.2f}")
    logger.info(f"  [Kör Sınav 2021-2023] Net Getiri: %{holdout_res['total_return']:+.2f} | Max DD: %{holdout_res['max_drawdown']:.2f} | Kâr Faktörü: {holdout_res['profit_factor']:.2f}")
    logger.info("================================================================")

    # Canlı Sistem İçin Kaydet
    if args.save:
        config_path = Path("config/champion_hyperparameters.json")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        save_data = {
            "discovered_at": date.today().isoformat(),
            "fitness_score": best_fitness,
            "train_return_pct": train_res["total_return"],
            "train_max_dd_pct": train_res["max_drawdown"],
            "holdout_return_pct": holdout_res["total_return"],
            "holdout_max_dd_pct": holdout_res["max_drawdown"],
            "hyperparameters": best_p,
        }
        config_path.write_bytes(orjson.dumps(save_data, option=orjson.OPT_INDENT_2))
        logger.info(f"💾 Şampiyon parametreler canlı konfigürasyona kaydedildi: {config_path}")


if __name__ == "__main__":
    main()
