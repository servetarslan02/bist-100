"""ALPHA BIST — 10 Yıllık Tam Borsa (173 Hisse) Otonom Sistem Backtest Motoru.

Bu test:
1. NEMA / REPO / FAİZ İÇERMEZ: Saf borsa sermaye kazancı/kaybı (Pure Stock Equity Return).
2. TÜM BORSA EVRENİ: 20-25 hisse kısıtı YOK. 'data/bist_all_10y_warehouse.duckdb' içindeki 173 BIST hissesi (362,877 bar).
3. SİSTEMİN GERÇEK MOTOR KURALLARI:
   - T+1 Takas Yürütümü: T günü kapanışında EOD sinyal üretilir, T+1 sabah açılış fiyatından gerçekleşir (Sıfır Lookahead).
   - Dinamik Slippage (Karekök Pazar Etki Modeli).
   - Likidite Kısıtı (Azami %10 Günlük Hacim Katılımı).
   - BIST %10 Taban/Tavan Marj Kilidi (Taban yemiş hissede satış ertelenir).
   - Sektör Maruziyet Kuralı (Tek sektöre maksimum %25 ağırlık).
   - StrategyDiagnostician Öz-Öğrenme: Sektör körlüğü karantinası, What-If simülasyonu, dinamik stop/tp, auto-rollback.
   - Walk-Forward Retraining: Her 20 günde bir 5 gün Purge + Embargo ile sıfırdan eğitilen ML modeli.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# Proje kök dizinini PYTHONPATH'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import lightgbm as lgb
import numpy as np
import polars as pl
import structlog

from services.ingestion.bist_universe import bist_universe
from services.learning.frozen_strategy_engine import FROZEN_PARAMS
from services.learning.institutional_walkforward_engine import (
    detect_market_regime as detect_market_regime_v2,
)
from services.learning.institutional_walkforward_engine import (
    extract_point_in_time_features,
)
from services.learning.strategy_diagnostician import StrategyDiagnostician

logger = structlog.get_logger("all_bist_10y_backtest")


# =====================================================================
# GERÇEK MOTOR KURALLARI VE SABİTLER
# =====================================================================
DEFAULT_INITIAL_CAPITAL: float = 1_000_000.0   # 1 Milyon TL kurumsal portföy
DEFAULT_COMMISSION_RATE: float = 0.0015       # %0.15 BIST aracı kurum komisyonu
DEFAULT_BASE_SLIPPAGE: float = 0.0010         # %0.10 Baz slippage
DEFAULT_MAX_SECTOR_PCT: float = 0.25          # Tek bir sektöre maksimum %25 ağırlık
DEFAULT_MAX_VOLUME_PARTICIPATION: float = 0.10 # Günlük hacmin maksimum %10'u
DEFAULT_MAX_HOLDING_DAYS: int = 63            # Maksimum taşıma süresi (~1 çeyrek)
DEFAULT_GAP_LIMIT_PCT: float = 9.8            # BIST %10 Taban/Tavan likidite kısıtı


@dataclass
class Position:
    """Açık pozisyon veri sınıfı."""
    ticker: str
    sector: str
    entry_date: date
    entry_price: float
    shares: int
    entry_val: float
    highest_price: float
    holding_days: int = 0
    pending_exit: bool = False
    exit_reason: str = ""


@dataclass
class TradeRecord:
    """Gerçekleşen işlem kaydı."""
    ticker: str
    sector: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    holding_days: int
    exit_reason: str
    total_fees: float


def load_all_bist_warehouse_data() -> tuple[pl.DataFrame, dict[str, pl.DataFrame], dict[str, date]]:
    """DuckDB 10 yıllık ambarından 173 BIST hissesi, XU100 benchmark ve resmi IPO tarihlerini çeker."""
    logger.info("📦 1. DuckDB 10 Yıllık BIST Ambarından Veriler Yükleniyor...")
    conn = duckdb.connect("data/bist_all_10y_warehouse.duckdb", read_only=True)

    # Benchmark XU100
    bm_df = conn.execute("""
        SELECT date as timestamp, open as Open, high as High, low as Low, close as Close, volume as Volume
        FROM benchmark_xu100_10y
        ORDER BY date
    """).pl()

    # 173 Hisse
    raw_stocks_df = conn.execute("""
        SELECT date as timestamp, symbol, open as Open, high as High, low as Low, close as Close, volume as Volume
        FROM stock_candles_10y
        ORDER BY symbol, date
    """).pl()

    # Resmi IPO / İlk İşlem Tarihleri (Hayatta kalma yanlılığı önleme - Survival Bias Prevention)
    ipo_rows = conn.execute("SELECT symbol, first_traded_date FROM ipo_dates").fetchall()
    ipo_map: dict[str, date] = {r[0]: r[1] for r in ipo_rows}
    conn.close()

    stock_dict: dict[str, pl.DataFrame] = {}
    for sym in raw_stocks_df["symbol"].unique().to_list():
        sym_df = raw_stocks_df.filter(pl.col("symbol") == sym).sort("timestamp")
        # En az 25 seanslık geçmişi olan TÜM hisseler (yeni halka arzlar dahil) evrene girer
        if sym_df.height >= 25:
            stock_dict[sym] = sym_df

    logger.info(f"  ✓ {len(stock_dict)} BIST hissesi başarıyla yüklendi. Toplam bar: {raw_stocks_df.height:,}")
    return bm_df, stock_dict, ipo_map


def compute_dynamic_slippage(price: float, volume: float, quantity: int, base_slippage: float = DEFAULT_BASE_SLIPPAGE) -> float:
    """Bizim gerçek motorun karekök pazar etkisi (square-root impact) slippage modeli."""
    if volume <= 0:
        return base_slippage * 3.0
    trade_val = quantity * price
    daily_val = max(volume * price, 1.0)
    participation = trade_val / daily_val
    impact = base_slippage * (1.0 + np.sqrt(participation) * 10.0)
    return float(max(impact, base_slippage * 0.5))


def run_full_bist_10y_simulation(limit_days: int | None = None) -> dict[str, Any]:
    """173 hisse üzerinde saf borsa getirili kurumsal 10 yıllık otonom sistem simülasyonu."""
    bm_df, stock_dict, ipo_map = load_all_bist_warehouse_data()
    sector_map = bist_universe.SECTOR_MAP

    # 2. POLARS POINT-IN-TIME ÖZNİTELİK MÜHENDİSLİĞİ
    logger.info("⚙️ 2. Polars Point-in-Time Öznitelikleri Hesaplanıyor (Sıfır Lookahead)...")
    features_by_ticker: dict[str, pl.DataFrame] = {}
    all_dates_set = set()

    for sym, raw_df in stock_dict.items():
        fdf = extract_point_in_time_features(raw_df)
        fdf = fdf.with_columns(pl.col("timestamp").cast(pl.Date))
        features_by_ticker[sym] = fdf
        all_dates_set.update(fdf["timestamp"].to_list())

    bm_df = bm_df.with_columns(pl.col("timestamp").cast(pl.Date))
    trading_dates = sorted(list(set(bm_df["timestamp"].to_list()).intersection(all_dates_set)))

    sample_fdf = next(iter(features_by_ticker.values()))
    feature_cols = [
        c for c in sample_fdf.columns
        if c not in ("timestamp", "Date", "target_5d_ret", "target_5d_bin", "Open", "High", "Low", "Close", "Volume", "close")
    ]
    logger.info(f"  ✓ {len(feature_cols)} Teknik öznitelik hazırlandı ({len(features_by_ticker)} hisse üzerinde).")

    # Isınma Penceresi: İlk 250 seans (~1 Yıl) model ve indikatör eğitimi için ayrılır
    WARMUP_DAYS = 250
    if len(trading_dates) <= WARMUP_DAYS:
        raise RuntimeError("Yetersiz simülasyon seansı!")

    eval_dates = trading_dates[WARMUP_DAYS:]
    if limit_days:
        eval_dates = eval_dates[:limit_days]

    logger.info(f"  ✓ Simülasyon Tarih Aralığı: {eval_dates[0]} -> {eval_dates[-1]} ({len(eval_dates)} İşlem Günü)\n")

    # 3. BAŞLANGIÇ DURUMU VE GERÇEK SİSTEM SERVİSLERİ
    cash = DEFAULT_INITIAL_CAPITAL
    positions: dict[str, Position] = {}
    pending_orders: list[dict[str, Any]] = [] # T+1 Yürütümü için bekleyen emirler
    closed_trades: list[TradeRecord] = []

    active_params = dict(FROZEN_PARAMS)
    diagnostician = StrategyDiagnostician(db_path=":memory:")

    # Yıllık ve toplam metrikler
    equity_curve: list[dict[str, Any]] = []
    current_year = eval_dates[0].year
    year_start_capital = cash
    year_start_bm = float(bm_df.filter(pl.col("timestamp") == eval_dates[0])["Close"][0])
    yearly_reports: list[dict[str, Any]] = []

    # Model durumu
    trained_model: lgb.Booster | None = None

    logger.info("🚀 3. 10 YILLIK TAM BORSA OTONOM SİMÜLASYONU BAŞLIYOR (NEMA YOK, SAF BORSA)...")

    for step_i, current_date in enumerate(eval_dates):
        # Benchmark o günkü kapanışı
        bm_curr_row = bm_df.filter(pl.col("timestamp") == current_date)
        bm_curr = float(bm_curr_row["Close"][0]) if bm_curr_row.height > 0 else year_start_bm

        # -------------------------------------------------------------
        # 1. SEANS AÇILIŞI (09:55 - 10:05): T+1 BEKLEYEN EMİRLERİ YÜRÜT
        # -------------------------------------------------------------
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

            # BIST %10 Taban/Tavan Likidite Kilidi Kontrolü:
            # 1. Taban Kilidi: Eğer gün taban açmış veya tabana kilitlenmişse satış gerçekleşemez!
            prev_close = float(day_row["close"][0]) if "close" in day_row.columns else open_price
            if prev_close > 0:
                pct_change_low = (low_price / prev_close - 1.0) * 100.0
                if action == "SELL" and pct_change_low <= -DEFAULT_GAP_LIMIT_PCT and open_price == low_price:
                    logger.debug(f"  ⚠️ [Taban Kilidi] {ticker} tabana kilitlendiği için satış ertesi güne ertelendi.")
                    continue

                # 2. Tavan Kilidi: Eğer hisse tavan açmışsa ve tavana kilitliyse (alış yapılamaz):
                pct_change_high = (high_price / prev_close - 1.0) * 100.0
                if action == "BUY" and pct_change_high >= DEFAULT_GAP_LIMIT_PCT and open_price == high_price:
                    logger.debug(f"  ⚠️ [Tavan Kilidi] {ticker} tavana kilitlendiği için alış kuyrukta kaldı.")
                    continue

            # Dinamik Slippage & Yürütme Fiyatı (Açılış Fiyatı + Kuruş Yuvarlama)
            if action == "BUY":
                target_alloc = order["target_alloc"]
                sec = sector_map.get(ticker, "GENEL")
                # Likidite katılım kontrolü
                slip = compute_dynamic_slippage(open_price, vol, int(target_alloc / max(open_price, 1)))
                exec_price = round(open_price * (1.0 + slip), 2)

                max_shares_allowed = int(vol * DEFAULT_MAX_VOLUME_PARTICIPATION) if vol > 0 else 999_999
                shares = min(int(target_alloc / exec_price), max_shares_allowed)
                cost = shares * exec_price
                fee = cost * DEFAULT_COMMISSION_RATE

                if shares > 0 and cash >= (cost + fee):
                    cash -= (cost + fee)
                    positions[ticker] = Position(
                        ticker=ticker,
                        sector=sec,
                        entry_date=current_date,
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
                    slip = compute_dynamic_slippage(open_price, vol, pos.shares)
                    exec_price = round(open_price * (1.0 - slip), 2)
                    gross_val = pos.shares * exec_price
                    fee = gross_val * DEFAULT_COMMISSION_RATE
                    net_val = gross_val - fee
                    cash += net_val

                    pnl = net_val - pos.entry_val
                    pnl_pct = (exec_price / pos.entry_price - 1.0) * 100.0

                    tr = TradeRecord(
                        ticker=ticker,
                        sector=pos.sector,
                        entry_date=pos.entry_date,
                        exit_date=current_date,
                        entry_price=pos.entry_price,
                        exit_price=exec_price,
                        shares=pos.shares,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        holding_days=pos.holding_days,
                        exit_reason=order.get("reason", "SIGNAL_EXIT"),
                        total_fees=fee + (pos.entry_val * DEFAULT_COMMISSION_RATE),
                    )
                    closed_trades.append(tr)
                    positions.pop(ticker, None)
                    executed_orders.append(order)

        # Yürütülenleri kuyruktan temizle
        pending_orders = [o for o in pending_orders if o not in executed_orders]

        # -------------------------------------------------------------
        # 2. GÜN İÇİ / GÜN SONU POZİSYON KONTROLLERİ (ASİMETRİK TREND TAKİBİ)
        # Kural: Kârı asla %10'da kesme! Let Profits Run to +1000%!
        # Kâr koruması: Breakeven Stop + ATR Chandelier Trailing Stop
        # -------------------------------------------------------------
        hard_stop_pct = float(active_params.get("hard_stop_pct", -6.5))
        trailing_atr_mult = float(active_params.get("trailing_atr_mult", 2.5))

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
            atr_pct = float(day_row["atr_pct"][0]) if "atr_pct" in day_row.columns else 3.5

            if high_p > pos.highest_price:
                pos.highest_price = high_p

            peak_gain_pct = (pos.highest_price / pos.entry_price - 1.0) * 100.0
            cur_gain_pct = (close_p / pos.entry_price - 1.0) * 100.0

            should_sell = False
            exit_reason = ""

            # 1. Sabit Hard Stop-Loss (Giriş seviyesinden maksimum zarar koruması)
            if ((low_p / pos.entry_price - 1.0) * 100.0) <= hard_stop_pct:
                should_sell = True
                exit_reason = "HARD_STOP_LOSS"

            # 2. Breakeven Stop: Hisse %8 prim yapınca stop maliyetin üstüne (+%1) çekilir (Sıfır risk!)
            elif peak_gain_pct >= 8.0 and cur_gain_pct <= 1.0:
                should_sell = True
                exit_reason = "BREAKEVEN_PROTECTION"

            # 3. Chandelier ATR Trailing Stop (Kârı Sürme / Let Profits Run):
            # Hisse %12'den fazla kazanç sağladıysa, zirvesinden 2.5x ATR gerilediğinde kârı realize et!
            # Sabit bir kâr tavanı yoktur; ralli %300 sürerse pozisyon %270'e kadar taşınır!
            elif peak_gain_pct >= 12.0:
                atr_buffer_pct = max(4.5, atr_pct * trailing_atr_mult)
                trailing_stop_price = pos.highest_price * (1.0 - atr_buffer_pct / 100.0)
                if close_p <= trailing_stop_price:
                    should_sell = True
                    exit_reason = "ATR_TRAILING_PROFIT"

            # 4. Maksimum Taşıma Süresi (Sadece yatayda kalmış hisseler için)
            elif pos.holding_days >= DEFAULT_MAX_HOLDING_DAYS and peak_gain_pct < 8.0:
                should_sell = True
                exit_reason = "MAX_HOLDING_PERIOD"

            if should_sell and not pos.pending_exit:
                pos.pending_exit = True
                pending_orders.append({"ticker": ticker, "action": "SELL", "reason": exit_reason})

        # -------------------------------------------------------------
        # 3. YIL DÖNÜMÜ RAPORLAMASI
        # -------------------------------------------------------------
        port_val = cash
        for tk, p in positions.items():
            fdf = features_by_ticker.get(tk)
            if fdf is not None:
                drow = fdf.filter(pl.col("timestamp") == current_date)
                cp = float(drow["Close"][0]) if drow.height > 0 else p.entry_price
                port_val += p.shares * cp

        equity_curve.append({"date": current_date, "equity": port_val, "benchmark": bm_curr})

        if current_date.year != current_year or step_i == len(eval_dates) - 1:
            year_ret = (port_val / year_start_capital - 1.0) * 100.0
            bm_ret = (bm_curr / year_start_bm - 1.0) * 100.0
            yearly_reports.append({
                "year": current_year,
                "port_return": year_ret,
                "bm_return": bm_ret,
                "alpha": year_ret - bm_ret,
                "end_equity": port_val,
                "positions_count": len(positions),
            })
            logger.info(
                f"  📊 {current_year} Yılı Sonu: Portföy: %{year_ret:+.2f} | BIST-100: %{bm_ret:+.2f} | Alfa: %{year_ret - bm_ret:+.2f} | Bakiye: ₺{port_val:,.2f}"
            )
            current_year = current_date.year
            year_start_capital = port_val
            year_start_bm = bm_curr

        # -------------------------------------------------------------
        # 4. HER 20 GÜNDE BİR WALK-FORWARD YENİDEN EĞİTİM & ÖZ-ÖĞRENME
        # -------------------------------------------------------------
        retrain_freq = int(active_params.get("retraining_freq", 20))
        if step_i % retrain_freq == 0:
            # 5 Gün Purge & Embargo: t-7 gün öncesine kadar olan temiz veriler
            cutoff_date = current_date - timedelta(days=7)
            train_chunks = []
            for fdf in features_by_ticker.values():
                cfdf = fdf.filter(pl.col("timestamp") <= cutoff_date).drop_nulls(subset=["target_5d_ret"])
                if cfdf.height > 0:
                    train_chunks.append(cfdf)

            if train_chunks:
                comb_train = pl.concat(train_chunks, how="vertical")
                X_train = comb_train.select(feature_cols).to_numpy()
                y_train = comb_train["target_5d_bin"].to_numpy()
                trn_data = lgb.Dataset(X_train, label=y_train)
                lgb_params = {
                    "objective": "binary",
                    "metric": "binary_logloss",
                    "learning_rate": 0.05,
                    "num_leaves": 20,
                    "max_depth": 4,
                    "verbose": -1,
                    "n_jobs": -1,
                    "random_state": 42,
                }
                trained_model = lgb.train(lgb_params, trn_data, num_boost_round=60)
                logger.info(
                    f"  🔄 [Retrain Seansı #{step_i // retrain_freq + 1}] LightGBM eğitildi (Tarih: {current_date}, Veri: {len(comb_train):,} satır)"
                )

            # StrategyDiagnostician Öz-Öğrenme Döngüsü
            recent_trades_dicts = [
                {
                    "trade_id": f"TR_{idx}",
                    "ticker": tr.ticker,
                    "sector": tr.sector,
                    "entry_time": tr.entry_date.isoformat(),
                    "exit_time": tr.exit_date.isoformat(),
                    "pnl": tr.pnl,
                    "pnl_pct": tr.pnl_pct,
                    "holding_period_bars": tr.holding_days,
                    "exit_reason": tr.exit_reason,
                    "mae": -abs(tr.pnl_pct * 0.5) if tr.pnl_pct < 0 else -1.0,
                    "mfe": max(tr.pnl_pct, 2.0),
                    "model_confidence": 0.65,
                }
                for idx, tr in enumerate(closed_trades[-30:])
            ]
            if len(recent_trades_dicts) >= 5:
                diag_res = diagnostician.run_daily_diagnosis(
                    trades=recent_trades_dicts,
                    current_params=active_params,
                    date=str(current_date),
                )
                if diag_res.get("changes"):
                    logger.info(f"  🧠 [Diagnostician] Parametreler revize edildi ({len(diag_res['changes'])} adet): {[c['param'] for c in diag_res['changes']]}")

        # -------------------------------------------------------------
        # 5. EOD SİNYAL ÜRETİMİ (18:15): CROSS-SECTIONAL MOMENTUM & MODEL SIRALAMASI
        # -------------------------------------------------------------
        if trained_model is None:
            continue

        # Rejim tespiti
        hist_bm_series = bm_df.filter(pl.col("timestamp") <= current_date)["Close"]
        current_regime = detect_market_regime_v2(hist_bm_series, current_date)

        # Rejime Göre Sermaye Yangını ve Pozisyon Tavanı:
        # Boğa piyasasında sermayenin %85-%95'i sahada olmalı (Compounding Firepower)!
        # Ayı piyasasında %80 nakitte kalarak sermaye korunmalı!
        if current_regime in ("BULL_TREND", "LOW_VOLATILITY"):
            target_max_pos = 12
            min_cash_buffer_pct = 5.0
            max_alloc_pct = 0.12
            min_rank_score = 15.0
        elif current_regime == "SIDEWAYS_RANGE":
            target_max_pos = 8
            min_cash_buffer_pct = 25.0
            max_alloc_pct = 0.10
            min_rank_score = 25.0
        else: # BEAR_MARKET veya HIGH_VOLATILITY
            target_max_pos = 3
            min_cash_buffer_pct = 75.0
            max_alloc_pct = 0.08
            min_rank_score = 35.0

        quarantined_sectors = diagnostician.get_quarantined_sectors()

        # Tüm BIST hisse havuzunu tara ve Kompozit Alfa Skoru hesapla
        candidate_scores: list[tuple[str, float, str]] = []

        for sym, fdf in features_by_ticker.items():
            if sym in positions:
                continue

            # Tarihsel BIST IPO Kontrolü (Hisse halka arz edilmeden önce sisteme giremez)
            ipo_date = ipo_map.get(sym)
            if ipo_date and current_date < ipo_date:
                continue

            sec = sector_map.get(sym, "GENEL")
            if sec in quarantined_sectors:
                continue

            day_row = fdf.filter(pl.col("timestamp") == current_date)
            if day_row.height == 0:
                continue

            vol = float(day_row["Volume"][0])
            close_p = float(day_row["Close"][0])
            # BIST Likidite Filtresi: Günlük işlem hacmi 250 bin TL altındaki sığ tahtalara kurumsal emir girilemez
            if (vol * close_p) < 250_000.0:
                continue

            X_curr = day_row.select(feature_cols).to_numpy()
            if np.isnan(X_curr).any():
                continue

            model_prob = float(trained_model.predict(X_curr)[0]) # 0.0 - 1.0
            roc_20d = float(day_row["roc_20d"][0]) if "roc_20d" in day_row.columns else 0.0
            price_vs_sma50 = float(day_row["price_vs_sma50"][0]) if "price_vs_sma50" in day_row.columns else 0.0

            # Yükselen trend filtresi: Hisse kendi 50 günlük ortalamasının üzerinde olmalı
            if price_vs_sma50 < -3.0:
                continue

            # Kompozit Alfa Skoru: Model Olasılığı (%40) + Momentum (%40) + Trend Gücü (%20)
            composite_score = (
                (model_prob * 40.0)
                + (min(max(roc_20d, -15.0), 35.0) * 0.80)
                + (min(max(price_vs_sma50, -10.0), 25.0) * 0.50)
            )

            if composite_score >= min_rank_score:
                candidate_scores.append((sym, composite_score, sec))

        # Büyükten küçüğe sırala (Top Pick)
        candidate_scores.sort(key=lambda x: x[1], reverse=True)

        # Portföy Dağılımı ve Sektör Tavanı
        avail_cash = max(0.0, cash - (port_val * (min_cash_buffer_pct / 100.0)))
        max_pos_val = port_val * max_alloc_pct

        current_sector_exposure: dict[str, float] = {}
        for p in positions.values():
            current_sector_exposure[p.sector] = current_sector_exposure.get(p.sector, 0.0) + p.entry_val

        # Hedef pozisyon sayısına kadar yeni alım emirleri üret
        open_slots = max(0, target_max_pos - len(positions))
        for cand_sym, cand_score, cand_sec in candidate_scores[:open_slots]:
            if avail_cash < (port_val * 0.02):
                break

            sec_val = current_sector_exposure.get(cand_sec, 0.0)
            if (sec_val + max_pos_val) / max(port_val, 1.0) > DEFAULT_MAX_SECTOR_PCT:
                continue

            target_alloc = min(max_pos_val, avail_cash)
            pending_orders.append({
                "ticker": cand_sym,
                "action": "BUY",
                "target_alloc": target_alloc,
                "score": cand_score,
                "sector": cand_sec,
            })
            avail_cash -= target_alloc
            current_sector_exposure[cand_sec] = sec_val + target_alloc

    # -----------------------------------------------------------------
    # 6. NİHAİ PERFORMANS VE İSTATİSTİK RAPORU
    # -----------------------------------------------------------------
    final_equity = equity_curve[-1]["equity"]
    total_return_port = (final_equity / DEFAULT_INITIAL_CAPITAL - 1.0) * 100.0

    bm_start_val = float(bm_df.filter(pl.col("timestamp") == eval_dates[0])["Close"][0])
    bm_end_val = float(bm_df.filter(pl.col("timestamp") == eval_dates[-1])["Close"][0])
    total_return_bm = (bm_end_val / bm_start_val - 1.0) * 100.0

    n_years = len(eval_dates) / 252.0
    cagr_port = ((final_equity / DEFAULT_INITIAL_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0
    cagr_bm = ((bm_end_val / bm_start_val) ** (1.0 / n_years) - 1.0) * 100.0

    # Drawdown hesabı
    eq_vals = np.array([pt["equity"] for pt in equity_curve])
    cummax = np.maximum.accumulate(eq_vals)
    drawdowns = (eq_vals - cummax) / cummax
    max_dd = abs(float(np.min(drawdowns))) * 100.0

    # Sharpe ve Günlük Getiriler (Nema yok, saf getiri!)
    daily_rets = np.diff(eq_vals) / eq_vals[:-1]
    sharpe = float(np.sqrt(252) * (np.mean(daily_rets) / np.std(daily_rets))) if np.std(daily_rets) > 0 else 0.0

    # İşlem İstatistikleri
    total_trades_count = len(closed_trades)
    winning_trades = [t for t in closed_trades if t.pnl > 0]
    win_rate = (len(winning_trades) / total_trades_count * 100.0) if total_trades_count > 0 else 0.0
    gross_profits = sum(t.pnl for t in winning_trades)
    gross_losses = abs(sum(t.pnl for t in closed_trades if t.pnl <= 0))
    profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else 99.0
    total_commission_paid = sum(t.total_fees for t in closed_trades)

    print("\n" + "=" * 70)
    print("🏆 10 YILLIK TAM BORSA (173 HİSSE) OTONOM SİSTEM SONUÇ RAPORU")
    print("=" * 70)
    print(f"💰 Başlangıç Sermayesi:     ₺{DEFAULT_INITIAL_CAPITAL:,.2f}")
    print(f"💎 Bitiş Sermayesi:         ₺{final_equity:,.2f} (Net: ₺{final_equity - DEFAULT_INITIAL_CAPITAL:+,.2f})")
    print(f"📈 Portföy Toplam Getirisi: %{total_return_port:,.2f} (XU100 Benchmark: %{total_return_bm:,.2f})")
    print(f"🚀 Alfa (Excess Return):    %{total_return_port - total_return_bm:+,.2f}")
    print(f"🎯 Portföy CAGR:            %{cagr_port:.2f} (XU100 CAGR: %{cagr_bm:.2f})")
    print(f"⚡ Sharpe Oranı (Saf):      {sharpe:.2f}")
    print(f"🛡️ Maksimum Drawdown (DD):  %{max_dd:.2f}")
    print(f"🎯 Kazanma Oranı (Win Rate):%{win_rate:.1f} ({len(winning_trades)} / {total_trades_count} işlem)")
    print(f"⚖️ Profit Factor (Kâr Fak): {profit_factor:.2f}")
    print(f"💸 Ödenen BIST Komisyonu:   ₺{total_commission_paid:,.2f}")
    print("🔒 Nema / Repo Durumu:      %0 (Kesinlikle nema yok, saf borsa sermaye getirisi)")
    print("=" * 70)

    print("\n📅 YILLIK BAZDA GETİRİ VE ALFA TABLOSU:")
    print(f"{'Yıl':<6} | {'Portföy (%)':<14} | {'BIST-100 (%)':<14} | {'Alfa (%)':<12} | {'Yıl Sonu Portföy Değeri':<24}")
    print("-" * 75)
    for yr in yearly_reports:
        print(
            f"{yr['year']:<6} | %{yr['port_return']:<12.2f} | %{yr['bm_return']:<12.2f} | %{yr['alpha']:<10.2f} | ₺{yr['end_equity']:>18,.2f}"
        )
    print("-" * 75)

    return {
        "final_equity": final_equity,
        "total_return_port": total_return_port,
        "total_return_bm": total_return_bm,
        "alpha": total_return_port - total_return_bm,
        "cagr_port": cagr_port,
        "cagr_bm": cagr_bm,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": total_trades_count,
        "yearly_reports": yearly_reports,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="10 Yıllık Tam BIST Otonom Sistem Backtest")
    parser.add_argument("--limit-days", type=int, default=None, help="Hızlı doğrulama için seans limiti")
    args = parser.parse_args()

    run_full_bist_10y_simulation(limit_days=args.limit_days)
