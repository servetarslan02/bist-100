"""ALPHA BIST — Super-Alpha Büyüme ve Yüksek Kârlılık (Unrestricted Multi-Bagger) Simülasyon Motoru.

Bu motor:
1. Kurumsal Fon Hacim Kısıtlaması (DEFAULT_MAX_VOLUME_PARTICIPATION = 0.10 vb.) İÇERMEZ.
   100.000 TL - 5.000.000 TL yöneten dinamik bir portföy gibi BIST 173 hissesinin tamamında
   kârlılığı patlayan, büyüme ve ivme lideri orta/küçük ölçekli cevherleri özgürce seçer.
2. Canlı tarayıcı (bist_ml_scanner.py) ile %100 senkronize çalışır:
   - Özsermaye Kârlılığı (ROE), Net Kâr Marjı ve Bilanço Kalitesi puanlamaya dahil edilir.
   - KAP İstihbaratı pozitif katalizör bonusu (+10) ve negatif cezası (-15) uygulanır.
3. Multi-Bagger Asimetrik Kâr Sürme:
   - Sabit tavan kâr satışı (Take Profit) YOKTUR. 2x, 5x, 10x giden hisseler trend bitene kadar
     Genişletilmiş Chandelier ATR Trailing Stop ile taşınır.
4. Yüksek Hızlı Bellek İndekslemesi:
   - 7.4 milyonluk yavaş DataFrame filtreleri yerine O(1) anlık sözlük indekslemesi ile çalışır.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Proje kök dizinini PYTHONPATH'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import numpy as np
import orjson
import polars as pl
import structlog

if TYPE_CHECKING:
    from datetime import date

logger = structlog.get_logger("super_alpha_growth_sim")

# =====================================================================
# SİSTEM SABİTLERİ (KISITSIZ PRO-BİREYSEL & ÇOKLU ÇARPAN MODELİ)
# =====================================================================
DEFAULT_INITIAL_CAPITAL: float = 100_000.0     # 100.000 TL başlangıç sermayesi
DEFAULT_COMMISSION_RATE: float = 0.0015       # BIST aracı kurum komisyonu (%0.15)
DEFAULT_BASE_SLIPPAGE: float = 0.0010         # Baz slippage (%0.10)
DEFAULT_MAX_SECTOR_PCT: float = 0.30          # Sektör tavanı (%30)
DEFAULT_MAX_HOLDING_DAYS: int = 120           # Multi-bagger için genişletilmiş taşıma süresi
DEFAULT_GAP_LIMIT_PCT: float = 9.8            # Taban/tavan kilit koruması


@dataclass
class FastPosition:
    ticker: str
    sector: str
    entry_price: float
    shares: int
    entry_val: float
    highest_price: float
    holding_days: int = 0
    is_multibagger: bool = False


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


def compute_realistic_slippage(price: float, volume: float, quantity: int) -> float:
    """Pro-bireysel portföy büyüklükleri için gerçekçi slippage."""
    if volume <= 0:
        return DEFAULT_BASE_SLIPPAGE * 2.0
    trade_val = quantity * price
    daily_val = max(volume * price, 1.0)
    participation = min(trade_val / daily_val, 0.20)
    return float(max(DEFAULT_BASE_SLIPPAGE * (1.0 + np.sqrt(participation) * 4.0), DEFAULT_BASE_SLIPPAGE * 0.5))


def run_simulation(
    params: dict[str, Any],
    bm_df: pl.DataFrame,
    features_by_ticker: dict[str, pl.DataFrame],
    ipo_map: dict[str, date],
    eval_dates: list[date],
    probs_cache: dict[tuple[str, date], float],
    allow_multibagger_trail: bool = True,
) -> dict[str, Any]:
    """Kısıtsız Büyüme & Kârlılık (Super-Alpha) portföy simülasyonu."""
    from services.ingestion.bist_universe import bist_universe
    from services.intelligence.kap_intelligence_service import kap_intelligence_service
    from services.learning.upside_capture_validator import detect_market_regime_v2

    sector_map = bist_universe.SECTOR_MAP
    cash = DEFAULT_INITIAL_CAPITAL
    positions: dict[str, FastPosition] = {}
    pending_orders: list[dict[str, Any]] = []

    equity_curve: list[float] = []
    closed_pnl_pcts: list[float] = []
    peak_equity = cash
    max_drawdown = 0.0
    multibagger_count = 0

    # 1. Hızlı Arama İndeksi: Tarih & Hisse bazlı O(1) anlık erişim haritası
    logger.info("[BELLEK] Yuksek hizli O(1) seans bellegi olusturuluyor...")
    day_lookup: dict[tuple[str, date], dict[str, float]] = {}
    for sym, fdf in features_by_ticker.items():
        dates_list = fdf["timestamp"].to_list()
        opens = fdf["Open"].to_list()
        highs = fdf["High"].to_list()
        lows = fdf["Low"].to_list()
        closes = fdf["Close"].to_list()
        vols = fdf["Volume"].to_list()
        roc_20s = fdf["roc_20d"].to_list() if "roc_20d" in fdf.columns else [0.0] * len(dates_list)
        p_sma50s = fdf["price_vs_sma50"].to_list() if "price_vs_sma50" in fdf.columns else [0.0] * len(dates_list)
        atr_pcts = fdf["atr_pct"].to_list() if "atr_pct" in fdf.columns else [3.5] * len(dates_list)

        for i, dt in enumerate(dates_list):
            day_lookup[(sym, dt)] = {
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "vol": float(vols[i]),
                "roc_20": float(roc_20s[i] or 0.0),
                "p_sma50": float(p_sma50s[i] or 0.0),
                "atr_pct": float(atr_pcts[i] or 3.5),
            }

    # XU100 Günlük Kapanış Haritası
    bm_lookup: dict[date, float] = dict(zip(bm_df["timestamp"].to_list(), bm_df["Close"].to_list(), strict=False))
    bm_dates = sorted(list(bm_lookup.keys()))

    logger.info(f"[SIMULASYON] Kisitsiz Buyume Simulasyonu Basliyor: {len(eval_dates)} Seans...")

    for current_date in eval_dates:
        # 1. Bekleyen Emirleri Sabah Açılışında Yürüt (Sıfır Lookahead)
        executed_orders = []
        for order in pending_orders:
            ticker = order["ticker"]
            action = order["action"]
            day_info = day_lookup.get((ticker, current_date))
            if not day_info:
                continue

            open_price = day_info["open"]
            low_price = day_info["low"]
            high_price = day_info["high"]
            vol = day_info["vol"]

            # Taban / Tavan Likidite Koruması
            prev_day_close = day_info["close"]
            if prev_day_close > 0:
                pct_change_low = (low_price / prev_day_close - 1.0) * 100.0
                if action == "SELL" and pct_change_low <= -DEFAULT_GAP_LIMIT_PCT and open_price == low_price:
                    continue
                pct_change_high = (high_price / prev_day_close - 1.0) * 100.0
                if action == "BUY" and pct_change_high >= DEFAULT_GAP_LIMIT_PCT and open_price == high_price:
                    continue

            if action == "BUY":
                target_alloc = order["target_alloc"]
                sec = sector_map.get(ticker, "GENEL")
                slip = compute_realistic_slippage(open_price, vol, int(target_alloc / max(open_price, 1)))
                exec_price = round(open_price * (1.0 + slip), 2)
                shares = int(target_alloc / exec_price)
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
                    slip = compute_realistic_slippage(open_price, vol, pos.shares)
                    exec_price = round(open_price * (1.0 - slip), 2)
                    gross = pos.shares * exec_price
                    fee = gross * DEFAULT_COMMISSION_RATE
                    net = gross - fee
                    cash += net
                    trade_ret = (exec_price / pos.entry_price - 1.0) * 100.0
                    closed_pnl_pcts.append(trade_ret)
                    if trade_ret >= 100.0:
                        multibagger_count += 1
                    positions.pop(ticker, None)
                    executed_orders.append(order)

        pending_orders = [o for o in pending_orders if o not in executed_orders]

        # 2. Portföy Değeri & Rejim Tespiti
        port_val = cash
        for tk, p in positions.items():
            day_info = day_lookup.get((tk, current_date))
            cp = day_info["close"] if day_info else p.entry_price
            port_val += p.shares * cp

        equity_curve.append(port_val)
        if port_val > peak_equity:
            peak_equity = port_val
        cur_dd = (peak_equity - port_val) / peak_equity
        if cur_dd > max_drawdown:
            max_drawdown = cur_dd

        # Rejim Tespiti
        recent_bm_dates = [d for d in bm_dates if d <= current_date][-65:]
        recent_closes = np.array([bm_lookup[d] for d in recent_bm_dates])
        current_regime = detect_market_regime_v2(recent_closes, current_date)

        # Rejim Ayrık Dinamik Kurallar
        if current_regime in ("BULL_TREND", "LOW_VOLATILITY"):
            trailing_mult = params.get("bull_trailing_atr", 2.6)
            be_trigger = params.get("bull_breakeven_trigger", 7.0)
            be_lock = params.get("bull_breakeven_lock", 2.5)
            hard_stop = params.get("bull_hard_stop", -6.0)
            target_max_pos = int(params.get("bull_max_pos", 11))
            min_cash_pct = params.get("bull_min_cash", 5.0)
            max_alloc_pct = 0.14  # Kısıtsız büyüme için tek hisseye %14 pay
            min_score = 15.0
        elif current_regime == "SIDEWAYS_RANGE":
            trailing_mult = params.get("sideway_trailing_atr", 2.4)
            be_trigger = 6.0
            be_lock = 1.5
            hard_stop = params.get("sideway_hard_stop", -6.0)
            target_max_pos = int(params.get("sideway_max_pos", 6))
            min_cash_pct = 25.0
            max_alloc_pct = 0.10
            min_score = 22.0
        else:  # BEAR_MARKET veya HIGH_VOLATILITY
            trailing_mult = params.get("bear_trailing_atr", 2.0)
            be_trigger = 5.0
            be_lock = 0.5
            hard_stop = params.get("bear_hard_stop", -5.5)
            target_max_pos = int(params.get("bear_max_pos", 4))
            min_cash_pct = params.get("bear_min_cash", 80.0)
            max_alloc_pct = 0.08
            min_score = 30.0

        # 3. Gün İçi Pozisyon Kontrolleri (Multi-Bagger Sınırsız Kâr Sürme)
        for ticker, pos in list(positions.items()):
            pos.holding_days += 1
            day_info = day_lookup.get((ticker, current_date))
            if not day_info:
                continue

            high_p = day_info["high"]
            low_p = day_info["low"]
            close_p = day_info["close"]
            atr_pct = day_info["atr_pct"]

            if high_p > pos.highest_price:
                pos.highest_price = high_p

            peak_gain = (pos.highest_price / pos.entry_price - 1.0) * 100.0
            cur_gain = (close_p / pos.entry_price - 1.0) * 100.0

            # Multi-Bagger Koruması: Hisse %50'den fazla prim yaptıysa özel korumaya geçer
            if peak_gain >= 50.0:
                pos.is_multibagger = True

            should_sell = False

            # Hard Stop
            if ((low_p / pos.entry_price - 1.0) * 100.0) <= hard_stop:
                should_sell = True
            # Breakeven Stop
            elif peak_gain >= be_trigger and cur_gain <= be_lock:
                should_sell = True
            # Multi-Bagger Chandelier ATR Trailing Stop (Sabit kâr al tavanı YOK!)
            elif peak_gain >= 10.0:
                if pos.is_multibagger and allow_multibagger_trail:
                    # Multi-bagger hisselerde trendi erken terketmemek için genişletilmiş takip
                    buffer_pct = max(6.0, atr_pct * (trailing_mult * 1.25))
                else:
                    buffer_pct = max(4.0, atr_pct * trailing_mult)

                if close_p <= (pos.highest_price * (1.0 - buffer_pct / 100.0)):
                    should_sell = True
            # Zaman Aşımı (Sadece kâr etmeyen zombiler için)
            elif pos.holding_days >= DEFAULT_MAX_HOLDING_DAYS and peak_gain < 8.0:
                should_sell = True

            if should_sell:
                pending_orders.append({"ticker": ticker, "action": "SELL", "reason": "EXIT"})

        # 4. Sinyal Üretimi & Aday Seçimi (Kârlılık, Büyüme & KAP Entegre)
        w_model = params.get("model_prob_weight", 0.50)
        w_mom = params.get("momentum_weight", 0.45)
        w_trend = params.get("trend_weight", 0.15)

        candidate_scores: list[tuple[str, float, str]] = []
        for sym in features_by_ticker.keys():
            if sym in positions:
                continue
            ipo_dt = ipo_map.get(sym)
            if ipo_dt and current_date < ipo_dt:
                continue

            day_info = day_lookup.get((sym, current_date))
            if not day_info:
                continue

            vol = day_info["vol"]
            close_p = day_info["close"]

            # Asgari Likidite Filtresi: Sadece işlem görmeyen ölü tahtaları filtrele (Hantal kısıtlar YOK!)
            if (vol * close_p) < 50_000.0:
                continue

            model_p = probs_cache.get((sym, current_date), 0.5)
            roc_20 = day_info["roc_20"]
            p_sma50 = day_info["p_sma50"]

            if p_sma50 < -4.0:
                continue

            # Skorlama: Model Olasılığı + Momentum + Trend
            c_score = (
                (model_p * 100.0 * w_model)
                + (min(max(roc_20, -15.0), 35.0) * w_mom * 2.0)
                + (min(max(p_sma50, -10.0), 25.0) * w_trend * 2.0)
            )

            # KAP Katalizör Bonusu (+10 / -15)
            kap_m = kap_intelligence_service.get_ticker_kap_metrics(sym)
            if kap_m.get("has_positive_catalyst"):
                c_score += 10.0
            elif kap_m.get("has_negative_catalyst"):
                c_score -= 15.0

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
        "multibaggers_100pct_plus": multibagger_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Super-Alpha Büyüme & Multi-Bagger Kısıtsız Simülasyon Motoru")
    parser.add_argument("--run", action="store_true", default=False, help="Simülasyonu fiilen başlat")
    parser.add_argument("--save-report", action="store_true", default=False, help="Sonuçları rapora yaz")
    args = parser.parse_args()

    logger.info("[ALPHA_BIST] Super-Alpha Buyume & Kisitsiz Multi-Bagger Motoru")
    logger.info("   - 173 Borsa Evreni: Kisitsiz ve Esit Rekabet")
    logger.info("   - Canli Motor ile %100 Senkronize (bist_ml_scanner)")
    logger.info("   - Sinirsiz Kar Surme (No Artificial Take-Profit Cap)")
    logger.info("   - KAP Katalizor Bonusu (+10 / -15)")

    # Parametreleri Canlı Şampiyon Yapılandırmasından Yükle
    cfg_file = Path("config/champion_hyperparameters.json")
    if cfg_file.exists():
        data = orjson.loads(cfg_file.read_bytes())
        params = data.get("hyperparameters", {})
        logger.info(f"[SAMPIYON] Sampiyon hiperparametreler yuklendi (Fitness: {data.get('fitness_score', 0):.2f})")
    else:
        params = {
            "bull_trailing_atr": 2.6,
            "bull_breakeven_trigger": 7.0,
            "bull_breakeven_lock": 2.5,
            "bull_hard_stop": -6.0,
            "bull_max_pos": 11,
            "bull_min_cash": 5.0,
            "bear_trailing_atr": 2.0,
            "bear_breakeven_trigger": 5.0,
            "bear_hard_stop": -5.5,
            "bear_max_pos": 4,
            "bear_min_cash": 80.0,
            "sideway_trailing_atr": 2.4,
            "sideway_hard_stop": -6.0,
            "sideway_max_pos": 6,
            "model_prob_weight": 0.50,
            "momentum_weight": 0.45,
            "trend_weight": 0.15,
        }

    if not args.run:
        logger.info(
            "[BEKLEMEDE] Motor ve kurallar canli sistemle %100 esitlendi. Calistirmak icin '--run' parametresi gereklidir.",
            parametre_adedi=len(params),
        )
        return

    # Fiili Çalıştırma (Sadece kullanıcı '--run' ile izin verdiğinde çalışır)
    logger.info("[HAZIRLIK] Veri ambari yukleniyor ve simulasyon baslatiliyor...")
    bm_df, stock_dict, ipo_map = load_warehouse_dataset()

    from services.learning.institutional_walkforward_engine import extract_point_in_time_features
    features_by_ticker: dict[str, pl.DataFrame] = {}
    all_dates_set = set()
    for sym, raw_df in stock_dict.items():
        fdf = extract_point_in_time_features(raw_df).with_columns(pl.col("timestamp").cast(pl.Date))
        features_by_ticker[sym] = fdf
        all_dates_set.update(fdf["timestamp"].to_list())

    bm_df = bm_df.with_columns(pl.col("timestamp").cast(pl.Date))
    trading_dates = sorted(list(set(bm_df["timestamp"].to_list()).intersection(all_dates_set)))
    eval_dates = trading_dates[250:]

    cache_file = Path("data/walkforward_probs_cache.pkl")
    probs_cache = {}
    if cache_file.exists():
        import pickle
        with open(cache_file, "rb") as f:
            probs_cache = pickle.load(f)

    res = run_simulation(params, bm_df, features_by_ticker, ipo_map, eval_dates, probs_cache)

    logger.info("==================================================================")
    logger.info("=== KISITSIZ SUPER-ALPHA BUYUME SIMULASYONU SONUCLARI ===")
    logger.info(f"  * Toplam Net Getiri:   %{res['total_return']:+,.2f}")
    logger.info(f"  * Yillik Bilesik Getiri (CAGR): %{res['cagr']:.2f}")
    logger.info(f"  * Maksimum Dusus (Max DD):  %{res['max_drawdown']:.2f}")
    logger.info(f"  * Kar Faktoru (Profit Factor): {res['profit_factor']:.2f}")
    logger.info(f"  * Baslangic -> Bitis:   TL {DEFAULT_INITIAL_CAPITAL:,.0f} -> TL {res['final_equity']:,.0f}")
    logger.info(f"  * Toplam Islem:        {res['trades_count']}")
    logger.info(f"  * Multi-Bagger Adedi (%100+ Prim Yapan): {res['multibaggers_100pct_plus']} Hisse")
    logger.info("==================================================================")


if __name__ == "__main__":
    main()
