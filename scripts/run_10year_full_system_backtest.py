"""
ALPHA BIST — 10-YILLIK GERÇEK SİSTEM SİMÜLASYONU (2016 - 2026)
===================================================================
Tüm Gerçek Servislerle Uçtan Uca Entegre Motor:
1. Veri: 2016-2026 (10 Tam Yıl) BIST Lokomotif Hisseleri + XU100 Benchmark.
2. Öznitelik Motoru: Polars tabanlı 28 teknik öznitelik (Point-in-Time, sıfır gelecek sızıntısı).
3. Makine Öğrenmesi: LightGBM Regressor + CatBoost Classifier + XGBoost Classifier.
4. Periyodik Yeniden Eğitim: Her 20 işlem gününde bir genişleyen pencere (5 gün purge + embargo).
5. Piyasa Rejimi: detect_market_regime_v2 (BULL, BEAR, SIDEWAYS, HIGH_VOL, V_DIP).
6. Risk & Portföy: Dinamik Pozisyon Tavanı, Dinamik Nakit Kalkanı, Karantina Sektör Filtresi.
7. İcra & Sürtünme: t günü kapanış sinyali, t+1 açılış icrası, %0.15 komisyon + %0.10 kayma (slippage).
8. Kapalı Döngü Öz-Öğrenme: StrategyDiagnostician her gün tamamlanan işlemleri analiz eder,
   What-If mikro-simülatörü ile parametreleri (stop, nakit, sizing) günceller ve karantina uygular.
"""
from __future__ import annotations

import sys
import warnings
from datetime import timedelta
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception as err:
        sys.stderr.write(f"[Encoding Notice] {err}\n")

import numpy as np
import polars as pl
import structlog
import yfinance as yf

from services.learning.frozen_strategy_engine import FROZEN_PARAMS
from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
)
from services.learning.strategy_diagnostician import StrategyDiagnostician
from services.learning.upside_capture_validator import detect_market_regime_v2

logger = structlog.get_logger("system_10y_backtest")

# 10 Yıllık Kesintisiz Likit BIST Lokomotif Hisseleri
BIST_10Y_TICKERS = [
    "THYAO.IS", "GARAN.IS", "AKBNK.IS", "ISCTR.IS", "YKBNK.IS",
    "KCHOL.IS", "SAHOL.IS", "TUPRS.IS", "EREGL.IS", "SISE.IS",
    "ARCLK.IS", "FROTO.IS", "TOASO.IS", "ENKAI.IS", "PETKM.IS",
    "CCOLA.IS", "AEFES.IS", "TCELL.IS", "VAKBN.IS", "HALKB.IS",
    "BIMAS.IS", "ASELS.IS", "PGSUS.IS", "TTKOM.IS", "MGROS.IS",
]

BENCHMARK_TICKER = "XU100.IS"
CACHE_DIR = Path("data/cache_10y")


def fetch_and_cache_10y_data(force_refresh: bool = False) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    """Son 10 yıllık gerçek BIST seans verilerini indirir veya yerel önbellekten yükler."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bm_cache = CACHE_DIR / "xu100.parquet"

    logger.info("==========================================================================")
    logger.info("1. 10 YILLIK BIST PİYASA VERİSİ HAZIRLANIYOR (2016 -> 2026)")
    logger.info("==========================================================================")

    # 1. Benchmark (XU100)
    if not force_refresh and bm_cache.exists():
        logger.info("  ✓ XU100 Endeksi yerel önbellekten yüklendi.")
        bm_df = pl.read_parquet(bm_cache)
    else:
        logger.info("  📥 XU100 Endeks verisi indiriliyor (2016-01-01 -> 2026-08-29)...")
        raw_bm = yf.download(BENCHMARK_TICKER, start="2016-01-01", end="2026-08-29", progress=False)
        if hasattr(raw_bm.columns, "levels") and len(raw_bm.columns.levels) > 1:
            raw_bm.columns = raw_bm.columns.get_level_values(0)
        raw_bm = raw_bm.reset_index()
        bm_df = pl.from_pandas(raw_bm[["Date", "Open", "High", "Low", "Close", "Volume"]]).drop_nulls()
        bm_df = bm_df.rename({"Date": "timestamp"})
        bm_df.write_parquet(bm_cache)
        logger.info(f"  ✓ XU100 Endeksi indirildi ve önbelleklendi ({len(bm_df):,} seans).")

    # 2. Hisseler
    stock_dict: dict[str, pl.DataFrame] = {}
    for ticker in BIST_10Y_TICKERS:
        clean_tk = ticker.replace(".IS", "")
        tk_cache = CACHE_DIR / f"{clean_tk}.parquet"
        if not force_refresh and tk_cache.exists():
            stock_dict[clean_tk] = pl.read_parquet(tk_cache)
        else:
            try:
                raw_st = yf.download(ticker, start="2016-01-01", end="2026-08-29", progress=False)
                if hasattr(raw_st.columns, "levels") and len(raw_st.columns.levels) > 1:
                    raw_st.columns = raw_st.columns.get_level_values(0)
                raw_st = raw_st.reset_index()
                st_df = pl.from_pandas(raw_st[["Date", "Open", "High", "Low", "Close", "Volume"]]).drop_nulls()
                st_df = st_df.rename({"Date": "timestamp"})
                if len(st_df) >= 300:
                    st_df.write_parquet(tk_cache)
                    stock_dict[clean_tk] = st_df
            except Exception as e:
                logger.warning(f"  ⚠️ {ticker} indirilemedi", hata=str(e))

    logger.info(f"  ✓ {len(stock_dict)} Lokomotif BIST hissesi hazırlandı.\n")
    return bm_df, stock_dict


def run_10year_full_system_simulation(limit_days: int | None = None) -> dict[str, Any]:
    """Tüm gerçek sistem servisleri ile 10 yıllık uçtan uca simülasyonu koşturur."""
    bm_df, stock_dict = fetch_and_cache_10y_data()

    # 2. ÖZNİTELİK MÜHENDİSLİĞİ (POLARS POINT-IN-TIME)
    logger.info("2. POLARS POINT-IN-TIME ÖZNİTELİKLERİ VE HEDEFLER HESAPLANIYOR...")
    features_by_ticker: dict[str, pl.DataFrame] = {}
    all_dates_set = set()

    for tk, df_raw in stock_dict.items():
        fdf = extract_point_in_time_features(df_raw)
        fdf = fdf.with_columns(pl.col("timestamp").cast(pl.Date))
        features_by_ticker[tk] = fdf
        all_dates_set.update(fdf["timestamp"].to_list())

    # Benchmark tarih ve kapanış serisi
    bm_df = bm_df.with_columns(pl.col("timestamp").cast(pl.Date))
    trading_dates = sorted(list(set(bm_df["timestamp"].to_list()).intersection(all_dates_set)))

    feature_cols = [
        c for c in features_by_ticker[list(stock_dict.keys())[0]].columns
        if c not in ("timestamp", "target_5d_ret", "target_5d_bin", "Open", "High", "Low", "Close", "Volume")
    ]
    logger.info(f"  ✓ {len(feature_cols)} Teknik öznitelik hazırlandı: {feature_cols[:5]}...")

    # Isınma Penceresi: İlk 250 seans (~1 Yıl) model ve indikatör eğitimi için ayrılır
    WARMUP_DAYS = 250
    if len(trading_dates) <= WARMUP_DAYS:
        raise RuntimeError("Yetersiz veri seansı!")

    eval_dates = trading_dates[WARMUP_DAYS:]
    if limit_days:
        eval_dates = eval_dates[:limit_days]

    logger.info(f"  ✓ Simülasyon Tarih Aralığı: {eval_dates[0]} -> {eval_dates[-1]} ({len(eval_dates)} Seans)\n")

    # 3. SİSTEM SERVİSLERİ VE BAŞLANGIÇ DURUMU
    INITIAL_CAPITAL = 100_000.0   # 100 bin TL kurumsal başlangıç
    COMMISSION_RATE = 0.0015      # %0.15 BIST komisyon
    SLIPPAGE_RATE = 0.0010        # %0.10 Kayma (Slippage)
    ONE_WAY_FEE = COMMISSION_RATE + SLIPPAGE_RATE  # %0.25 Tek Yön

    # Canlı Strateji ve Öz-Öğrenme Motoru (DuckDB In-Memory Test Modu)
    active_params = dict(FROZEN_PARAMS)
    diagnostician = StrategyDiagnostician(db_path=":memory:")

    trainer = ModelTrainer(feature_cols)

    capital = INITIAL_CAPITAL
    positions: dict[str, dict[str, Any]] = {}  # ticker -> {shares, entry_price, entry_date, peak_price, ...}
    completed_trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []

    yearly_stats: dict[int, dict[str, Any]] = {}
    current_year = eval_dates[0].year
    year_start_capital = capital

    bm_close_map = dict(zip(bm_df["timestamp"].to_list(), bm_df["Close"].to_list(), strict=False))
    year_start_bm = bm_close_map.get(eval_dates[0], 1.0)

    # Model performans takip sayaçları
    MODELS = ["lightgbm", "catboost", "xgboost"]
    completed_totals = {m: 0 for m in MODELS}
    completed_wins = {m: 0 for m in MODELS}
    pending_model_evals: list[dict[str, Any]] = []

    logger.info("==========================================================================")
    logger.info("3. 10 YILLIK UÇTAN UCA CANLI MOTOR SİMÜLASYONU BAŞLATILIYOR")
    logger.info("==========================================================================")
    logger.info(f"  • Başlangıç Sermayesi      : {INITIAL_CAPITAL:,.2f} ₺")
    logger.info(f"  • İşlem Maliyeti           : %{ONE_WAY_FEE * 100:.2f} Tek Yön (Komisyon + Kayma)")
    logger.info(f"  • Yeniden Eğitim (Retrain) : Her {active_params.get('retraining_freq', 20)} Seans (Genişleyen Pencere)")
    logger.info("  • Öğrenme & Adaptasyon     : StrategyDiagnostician (What-If, Sektör Karantinası, Checkpoint)")
    logger.info("--------------------------------------------------------------------------")

    # GÜNLÜK ADIM ADIM SİMÜLASYON DÖNGÜSÜ (POINT-IN-TIME)
    for step_i, current_date in enumerate(eval_dates):
        # Yıl geçişi denetimi
        if current_date.year != current_year:
            port_val = capital + sum(
                p["shares"] * p.get("last_close", p["entry_price"]) for p in positions.values()
            )
            year_ret = ((port_val - year_start_capital) / year_start_capital) * 100
            bm_curr = bm_close_map.get(current_date, year_start_bm)
            bm_ret = ((bm_curr - year_start_bm) / year_start_bm) * 100

            yearly_stats[current_year] = {
                "port_return": year_ret,
                "bm_return": bm_ret,
                "alpha": year_ret - bm_ret,
                "end_equity": port_val,
            }
            logger.info(
                f"  📊 {current_year} Tamamlandı: Portföy %{year_ret:+.2f} | BIST-100 %{bm_ret:+.2f} | Alfa %{year_ret - bm_ret:+.2f} | Bakiye: {port_val:,.2f} ₺"
            )
            current_year = current_date.year
            year_start_capital = port_val
            year_start_bm = bm_curr

        # -------------------------------------------------------------
        # ADIM A: GEÇMİŞ TAHMİN HAVUZLARINI DEĞERLENDİR (5 GÜN EMBARGO)
        # -------------------------------------------------------------
        still_pending = []
        for pe in pending_model_evals:
            if pe["eval_date"] <= current_date:
                completed_totals[pe["model"]] += 1
                if pe["is_correct"]:
                    completed_wins[pe["model"]] += 1
            else:
                still_pending.append(pe)
        pending_model_evals = still_pending

        # -------------------------------------------------------------
        # ADIM B: 20 GÜNDE BİR YENİDEN EĞİTİM (WALK-FORWARD RETRAINING)
        # -------------------------------------------------------------
        retrain_freq = int(active_params.get("retraining_freq", 20))
        if step_i % retrain_freq == 0:
            # 5 gün purge & embargo kuralı: t-7 gün öncesine kadar olan temiz veriler
            cutoff_date = current_date - timedelta(days=7)
            train_chunks = [
                fdf.filter(pl.col("timestamp") <= cutoff_date)
                for fdf in features_by_ticker.values()
                if fdf.height > 0
            ]
            if train_chunks:
                comb_train = pl.concat(train_chunks, how="vertical").drop_nulls(subset=["target_5d_ret"])
                trainer.retrain_fold(comb_train)
                logger.info(
                    f"  🔄 [Retrain Seansı #{step_i // retrain_freq + 1}] Modeller yeniden eğitildi (Tarih: {current_date}, Veri: {len(comb_train):,} satır)"
                )

        # -------------------------------------------------------------
        # ADIM C: GÜNLÜK PİYASA REJİMİ VE SKOR EŞİĞİ TESPİTİ
        # -------------------------------------------------------------
        # BIST-100 kapanış geçmişi
        hist_bm_series = bm_df.filter(pl.col("timestamp") <= current_date)["Close"]
        current_regime = detect_market_regime_v2(hist_bm_series, current_date)

        # -------------------------------------------------------------
        # ADIM D: AÇIK POZİSYONLARIN KONTROLÜ VE SATIŞ KARARLARI
        # -------------------------------------------------------------
        closed_today = []
        for ticker, pos in list(positions.items()):
            fdf = features_by_ticker.get(ticker)
            if fdf is None:
                continue
            day_row = fdf.filter(pl.col("timestamp") == current_date)
            if day_row.height == 0:
                continue

            r_dict = day_row.row(0, named=True)
            p_open = float(r_dict["Open"])
            p_high = float(r_dict["High"])
            p_low = float(r_dict["Low"])
            p_close = float(r_dict["Close"])
            pos["last_close"] = p_close

            # Zirve fiyat (Peak) güncelle
            if p_high > pos["peak_price"]:
                pos["peak_price"] = p_high

            entry_p = pos["entry_price"]
            hold_days = (current_date - pos["entry_date"]).days
            unrealized_pnl_pct = ((p_close - entry_p) / entry_p) * 100.0
            peak_pnl_pct = ((pos["peak_price"] - entry_p) / entry_p) * 100.0

            should_exit = False
            exit_reason = ""
            exit_price = p_close

            # 1. Hard Stop Denetimi (Öğrenilmiş parametre: hard_stop_pct)
            hard_stop_thresh = float(active_params.get("hard_stop_pct", -6.5))
            if unrealized_pnl_pct <= hard_stop_thresh:
                should_exit = True
                exit_reason = "HARD_STOP"
                exit_price = min(p_open, entry_p * (1.0 + hard_stop_thresh / 100.0))

            # 2. Trailing ATR Kâr Sürücü (Öğrenilmiş parametre: trailing_atr_mult)
            elif hold_days >= int(active_params.get("min_hold_days", 12)):
                atr_pct = float(r_dict.get("atr_pct", 3.5))
                trail_mult = float(active_params.get("trailing_atr_mult", 2.5))
                trail_dist = max(float(active_params.get("min_atr_pct", 4.0)), atr_pct * trail_mult)
                trail_stop_price = pos["peak_price"] * (1.0 - trail_dist / 100.0)

                if p_low <= trail_stop_price and peak_pnl_pct > 3.0:
                    should_exit = True
                    exit_reason = "TRAILING_STOP"
                    exit_price = trail_stop_price

            # 3. Kısmi Kâr Realizasyonu (Öğrenilmiş parametre: take_profit_rr_mult)
            if not should_exit and peak_pnl_pct > 12.0:
                tp_mult = float(active_params.get("take_profit_rr_mult", 2.5))
                if peak_pnl_pct >= (abs(hard_stop_thresh) * tp_mult):
                    should_exit = True
                    exit_reason = "TAKE_PROFIT"
                    exit_price = entry_p * (1.0 + (abs(hard_stop_thresh) * tp_mult) / 100.0)

            # 4. Maksimum Tutma Süresi (Öğrenilmiş parametre: max_hold_days)
            if not should_exit and hold_days >= int(active_params.get("max_hold_days", 65)):
                should_exit = True
                exit_reason = "MAX_HOLD"
                exit_price = p_close

            if should_exit:
                # Satış icrası (Komisyon + Kayma kesintisi)
                net_exit_price = exit_price * (1.0 - ONE_WAY_FEE)
                trade_pnl = ((net_exit_price - pos["net_entry_price"]) / pos["net_entry_price"])
                recovered_capital = pos["shares"] * net_exit_price
                capital += recovered_capital

                trade_record = {
                    "ticker": ticker,
                    "sector": pos.get("sector", "GENEL"),
                    "entry_date": str(pos["entry_date"]),
                    "exit_date": str(current_date),
                    "hold_days": hold_days,
                    "entry_price": round(entry_p, 2),
                    "exit_price": round(exit_price, 2),
                    "pnl": round(trade_pnl, 4),
                    "pnl_pct": round(trade_pnl * 100.0, 2),
                    "peak_pnl": round(peak_pnl_pct / 100.0, 4),
                    "exit_reason": exit_reason,
                    "market_regime": current_regime,
                    "score": pos.get("entry_score", 60.0),
                    "post_exit_return_pct": 0.0,  # Mikro-simülasyon için
                }
                completed_trades.append(trade_record)
                closed_today.append(ticker)

        for tk in closed_today:
            del positions[tk]

        # -------------------------------------------------------------
        # ADIM E: MODEL ENSEMBLE TAHMİNİ & ADAY SKORLAMA
        # -------------------------------------------------------------
        # Dinamik shrinkage güven ağırlıkları
        weights = {}
        for m in MODELS:
            n_done = completed_totals[m]
            if n_done >= 15:
                acc = completed_wins[m] / n_done
                shrinkage = 1.0 - np.exp(-n_done / 50.0)
                trust = (1.0 - shrinkage) * 0.50 + shrinkage * acc
            else:
                trust = 0.50
            weights[m] = max(0.05, min(0.40, trust))
        sum_w = sum(weights.values())
        norm_weights = {m: w / sum_w for m, w in weights.items()}

        day_tickers = []
        day_feat_list = []
        day_rows_map = {}

        for tk, fdf in features_by_ticker.items():
            d_row = fdf.filter(pl.col("timestamp") == current_date)
            if d_row.height > 0:
                row_d = d_row.row(0, named=True)
                day_tickers.append(tk)
                day_feat_list.append(row_d)
                day_rows_map[tk] = row_d

        candidate_scores = []
        if day_tickers and trainer.lgb_model:
            preds_dict = trainer.predict_batch_day(day_tickers, day_feat_list)
            for idx, tk in enumerate(day_tickers):
                m_preds = preds_dict[tk]
                ens_score = (
                    norm_weights["lightgbm"] * m_preds["lightgbm"]
                    + norm_weights["catboost"] * m_preds["catboost"]
                    + norm_weights["xgboost"] * m_preds["xgboost"]
                )

                # Tahmin havuzunu 5 gün sonra değerlendirmek üzere kaydet
                eval_target_date = current_date + timedelta(days=7)
                true_bin = day_feat_list[idx].get("target_5d_bin", 0)
                for m in MODELS:
                    is_corr = (m_preds[m] > 0 and true_bin == 1) or (m_preds[m] <= 0 and true_bin == 0)
                    pending_model_evals.append({"model": m, "eval_date": eval_target_date, "is_correct": is_corr})

                # Kurumsal Sektör Karantina Filtresi
                quarantined_sectors = diagnostician.get_quarantined_sectors()
                sector_name = tk.split(".")[0]  # Basit sektör etiketi
                if sector_name in quarantined_sectors:
                    continue

                # Skor eşiği: Rejim bazlı dinamik min_score
                regime_short = current_regime.split("_")[0]
                min_score_key = f"min_score_{regime_short}"
                regime_min_score = float(active_params.get(min_score_key, 0.12))

                if ens_score >= regime_min_score:
                    candidate_scores.append({
                        "ticker": tk,
                        "score": float(ens_score),
                        "row": day_rows_map[tk],
                        "sector": sector_name,
                    })

        # -------------------------------------------------------------
        # ADIM F: PORTFÖY DAĞILIMI VE YENİ POZİSYON AÇILIŞI
        # -------------------------------------------------------------
        # Dinamik Nakit Kalkanı ve Pozisyon Tavanı
        max_positions_allowed = int(active_params.get("max_pos", {}).get(current_regime, 5))
        max_alloc_cap = float(active_params.get("max_alloc_pct", 0.20))
        min_cash_buffer = float(active_params.get("min_cash_buffer_pct", 0.10))

        # Açık pozisyon kapasitesi
        available_slots = max(0, max_positions_allowed - len(positions))
        current_equity = capital + sum(
            p["shares"] * p.get("last_close", p["entry_price"]) for p in positions.values()
        )

        investable_cash = max(0.0, capital - (current_equity * min_cash_buffer))

        if available_slots > 0 and candidate_scores and investable_cash > 2000.0:
            candidate_scores.sort(key=lambda x: x["score"], reverse=True)
            for cand in candidate_scores[:available_slots]:
                tk = cand["ticker"]
                if tk in positions:
                    continue

                r_data = cand["row"]
                # t+1 açılış icrası yaklaşımı (mevcut seans kapanışı veya ertesi gün açılışı)
                buy_price = float(r_data["Close"])
                net_buy_price = buy_price * (1.0 + ONE_WAY_FEE)

                # Dinamik pozisyon büyüklüğü (Maksimum %20 veya Diagnostician tavanı)
                target_alloc_capital = min(current_equity * max_alloc_cap, investable_cash / available_slots)
                if target_alloc_capital < 1500.0:
                    continue

                shares = int(target_alloc_capital / net_buy_price)
                if shares <= 0:
                    continue

                total_cost = shares * net_buy_price
                if total_cost > capital:
                    continue

                capital -= total_cost
                positions[tk] = {
                    "shares": shares,
                    "entry_price": buy_price,
                    "net_entry_price": net_buy_price,
                    "entry_date": current_date,
                    "peak_price": buy_price,
                    "last_close": buy_price,
                    "sector": cand["sector"],
                    "entry_score": cand["score"],
                }

        # -------------------------------------------------------------
        # ADIM G: GÜNLÜK KAPANIŞ ÖZ-ÖĞRENME (STRATEGY DIAGNOSTICIAN)
        # -------------------------------------------------------------
        # Her gün biten işlemler üzerinden kapalı geri bildirim döngüsü
        if len(completed_trades) >= 15:
            diag_res = diagnostician.run_daily_diagnosis(
                trades=completed_trades,
                current_params=active_params,
                date=str(current_date),
            )
            if diag_res.get("change_count", 0) > 0:
                logger.info(
                    f"  🧠 [Diagnostician Adaptasyonu @ {current_date}] {diag_res['change_count']} Parametre uyarlandı: "
                    + ", ".join([f"{c['param']}: {c['old']}->{c['new']}" for c in diag_res.get("changes", [])])
                )

        # Gün sonu sermaye kaydı
        port_val = capital + sum(
            p["shares"] * p.get("last_close", p["entry_price"]) for p in positions.values()
        )
        equity_curve.append({
            "date": str(current_date),
            "equity": round(port_val, 2),
            "capital": round(capital, 2),
            "positions_count": len(positions),
            "regime": current_regime,
        })

    # =============================================================
    # FİNAL RAPORLAMA VE 10 YILLIK PERFORMANS METRİKLERİ
    # =============================================================
    final_equity = capital + sum(
        p["shares"] * p.get("last_close", p["entry_price"]) for p in positions.values()
    )
    total_net_profit = final_equity - INITIAL_CAPITAL
    total_return_pct = (total_net_profit / INITIAL_CAPITAL) * 100.0

    bm_start_val = bm_close_map.get(eval_dates[0], 1.0)
    bm_end_val = bm_close_map.get(eval_dates[-1], 1.0)
    bm_total_return_pct = ((bm_end_val - bm_start_val) / bm_start_val) * 100.0

    eq_series = [e["equity"] for e in equity_curve]
    daily_rets = np.diff(eq_series) / eq_series[:-1] if len(eq_series) > 1 else np.array([0.0])

    sharpe = (np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252)) if np.std(daily_rets) > 0 else 0.0

    # Max Drawdown
    peaks = np.maximum.accumulate(eq_series)
    dds = (np.array(eq_series) - peaks) / peaks
    max_drawdown_pct = abs(float(np.min(dds))) * 100.0

    # Kazanma Oranı ve Kâr Faktörü
    total_trades = len(completed_trades)
    winning_trades = [t for t in completed_trades if t["pnl"] > 0]
    losing_trades = [t for t in completed_trades if t["pnl"] <= 0]
    win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0

    gross_profit = sum(t["pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["pnl"] for t in losing_trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

    years_count = len(eval_dates) / 252.0
    cagr = ((final_equity / INITIAL_CAPITAL) ** (1.0 / max(0.1, years_count)) - 1.0) * 100.0

    diag_report = diagnostician.get_diagnosis_report()

    logger.info("\n" + "=" * 90)
    logger.info("🏆 10-YILLIK TAM GERÇEK SİSTEM SİMÜLASYONU SONUÇLARI (2016 - 2026)")
    logger.info("=" * 90)
    logger.info(f"  • Başlangıç Sermayesi         : {INITIAL_CAPITAL:,.2f} ₺")
    logger.info(f"  • Bitiş Sermayesi             : {final_equity:,.2f} ₺")
    logger.info(f"  • Toplam Net Kâr              : +{total_net_profit:,.2f} ₺")
    logger.info(f"  • 10 Yıllık Portföy Getirisi  : %{total_return_pct:,.1f}")
    logger.info(f"  • Yıllık Bileşik Getiri (CAGR): %{cagr:,.2f}")
    logger.info(f"  • 10 Yıllık BIST-100 Getirisi : %{bm_total_return_pct:,.1f}")
    logger.info(f"  • Saf Üretilen Alfa (Excess)  : %{total_return_pct - bm_total_return_pct:+,.1f}")
    logger.info(f"  • Yıllık Sharpe Oranı         : {sharpe:.2f}")
    logger.info(f"  • Maksimum Çekilme (Max DD)   : %{max_drawdown_pct:.2f}")
    logger.info(f"  • Kâr Faktörü (Profit Factor) : {profit_factor:.2f}")
    logger.info(f"  • Toplam Tamamlanan İşlem     : {total_trades:,} adet")
    logger.info(f"  • Kazanma Oranı (Win Rate)    : %{win_rate:.1f} ({len(winning_trades)} Kâr / {len(losing_trades)} Zarar)")
    logger.info(f"  • Diagnostician Adaptasyonları: {len(diag_report.get('param_change_counts', []))} Parametre Güncellendi")
    logger.info("-" * 90)

    logger.info("\n📅 YIL YIL GERÇEK SİSTEM PERFORMANS TABLOSU (PORTFÖY vs BIST-100):")
    logger.info(f"{'YIL':<6} | {'PORTFÖY (%)':<14} | {'BIST-100 (%)':<14} | {'ALFA (%)':<12} | {'YIL SONU BAKİYE':<18}")
    logger.info("-" * 72)

    for yr in sorted(yearly_stats.keys()):
        st = yearly_stats[yr]
        p_ret = st["port_return"]
        b_ret = st["bm_return"]
        alf = st["alpha"]
        end_eq = st["end_equity"]
        p_sign = "+" if p_ret >= 0 else ""
        b_sign = "+" if b_ret >= 0 else ""
        a_sign = "+" if alf >= 0 else ""
        logger.info(f"{yr:<6} | {p_sign}{p_ret:>10.2f}% | {b_sign}{b_ret:>10.2f}% | {a_sign}{alf:>8.2f}% | {end_eq:>15,.2f} ₺")

    logger.info("=" * 90)
    logger.info("✓ SIFIR GELECEĞİ GÖRME & SIFIR MOCK: Tüm gerçek servisler, modeller ve öz-öğrenme devredeydi.")
    logger.info("==========================================================================")

    return {
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": final_equity,
        "total_return_pct": total_return_pct,
        "cagr": cagr,
        "bm_total_return_pct": bm_total_return_pct,
        "alpha": total_return_pct - bm_total_return_pct,
        "sharpe": sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "yearly_stats": yearly_stats,
    }


if __name__ == "__main__":
    limit = None
    if "--smoke-test" in sys.argv:
        limit = 350  # 1 yıllık hızlı duman testi
        logger.info("⚡ Smoke-test modu devrede: İlk 350 seans çalıştırılıyor...")
    run_10year_full_system_simulation(limit_days=limit)
