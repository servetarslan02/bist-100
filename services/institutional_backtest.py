import structlog

logger = structlog.get_logger(__name__)
import gc
from typing import Any

from services.core.alpha_engine import AlphaEngine
from services.ml.hyper_optimizer import HyperOptimizer


def run_institutional() -> Any:
    """Tüm BIST hisse evreni üzerinde kurumsal seviye slippage ve likidite filtreli backtest çalıştırır."""
    logger.info("--- INSTITUTIONAL-GRADE BACKTEST (454 HISSE) ---")
    engine = AlphaEngine()
    engine.params["n_estimators"] = 50

    start_date = "2019-01-01"
    end_date = "2024-01-01"

    logger.info(f"1. Veri indiriliyor: {start_date} -> {end_date}")
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
    logger.info(f"Basarili! Toplam hisse: {len(market_data)}")

    common_dates = list(sorted([d for d in bm_df.index]))

    train_size = 252
    step_size = 63

    portfolio = 1000000.0

    # 20 trial gercek optimizasyon
    optimizer = HyperOptimizer(n_trials=20)

    # RISK KURALLARI:
    # 1. Slippage: Her islem basina (Al/Sat) %0.5 kayma maliyeti (Toplam %1 gidis donus)
    SLIPPAGE_RATE = 0.005

    # 2. Likidite Filtresi: Testin yapildigi gun, son 20 gunluk ortalama hacmi (Volume * Close)
    # 10 Milyon TL altinda olan hisseler ISLEME ALINMAZ.
    MIN_LIQUIDITY_TL = 10_000_000

    current_idx = train_size

    while current_idx < len(common_dates) - step_size:
        t_start = common_dates[current_idx - train_size]
        t_end = common_dates[current_idx]
        t_test_end = common_dates[current_idx + step_size]

        logger.info(f"\n>> PERIYOT: Train({t_start.date()} to {t_end.date()}) | Test({t_end.date()} to {t_test_end.date()})")

        try:
            X, y, feature_names = engine.generate_training_samples(market_data, bm_df, sector_map, t_start, t_end)
        except Exception as e:
            logger.info(f"Data generation failed: {e}")
            break

        if len(X) == 0:
            current_idx += step_size
            continue

        logger.info(f"Egitiliyor... Orneklem: {len(X)}")
        try:
            best_params = optimizer.optimize(X, y, feature_names)
            engine.params.update(best_params)

            import lightgbm as lgb

            train_data = lgb.Dataset(X, label=y, feature_name=feature_names)
            engine.model = lgb.train(engine.params, train_data, num_boost_round=100)
            engine.features = feature_names
        except Exception as e:
            logger.info(f"Egitim hatasi: {e}")
            break

        # 3. Test gunu icin tahmin yap
        try:
            preds = engine.predict(market_data, bm_df, sector_map, t_end)
        except Exception as e:
            logger.info(f"Tahmin hatasi: {e}")
            break

        # LIKIDITE FILTRESI (Point-in-Time)
        valid_preds = []
        for p in preds:
            tick = p["ticker"]
            if tick in market_data:
                df = market_data[tick]
                # Test gununden onceki 20 gunluk veri
                df_past = df.loc[df.index <= t_end]
                if len(df_past) >= 20:
                    avg_vol = df_past["Volume"].tail(20).mean()
                    avg_close = df_past["Close"].tail(20).mean()
                    liquidity_tl = avg_vol * avg_close
                    if liquidity_tl >= MIN_LIQUIDITY_TL:
                        valid_preds.append(p)

        top_10 = valid_preds[:10]
        selected_tickers = [p["ticker"] for p in top_10]
        logger.info(f"Filtreden Gecen Top 10: {selected_tickers}")

        # 5. Gercek Getiriyi Hesapla (Slippage Dahil)
        period_return = 0.0
        valid_picks = 0
        for tick in selected_tickers:
            if tick in market_data:
                df = market_data[tick]
                try:
                    p_buy = df.loc[df.index <= t_end]["Close"].iloc[-1]
                    p_sell = df.loc[df.index <= t_test_end]["Close"].iloc[-1]

                    # Alirken yukaridan, satarken asagidan (Slippage)
                    p_buy_real = p_buy * (1 + SLIPPAGE_RATE)
                    p_sell_real = p_sell * (1 - SLIPPAGE_RATE)

                    ret = (p_sell_real - p_buy_real) / p_buy_real
                    period_return += ret
                    valid_picks += 1
                except Exception:
                    logger.error("Exception caught", exc_info=True)

        if valid_picks > 0:
            avg_return = period_return / valid_picks
        else:
            avg_return = 0.0

        try:
            bm_buy = bm_df.loc[bm_df.index <= t_end]["Close"].iloc[-1]
            bm_sell = bm_df.loc[bm_df.index <= t_test_end]["Close"].iloc[-1]
            bm_ret = (bm_sell - bm_buy) / bm_buy
        except Exception:
            bm_ret = 0.0

        logger.info(f"-> Portfoy Getirisi: %{avg_return * 100:.2f} | BIST100 Getirisi: %{bm_ret * 100:.2f}")
        portfolio = portfolio * (1 + avg_return)
        logger.info(f"-> Guncel Kasa: {portfolio:,.2f} TL")

        del X
        del y
        gc.collect()

        current_idx += step_size

    logger.info("\n========================================================")
    logger.info(f"FINAL KASA: {portfolio:,.2f} TL")
    total_ret = (portfolio / 1000000.0) - 1
    cagr = ((1 + total_ret) ** (1 / 5.0) - 1) * 100
    logger.info(f"5 YILLIK CAGR (Kurumsal Seviye): %{cagr:.2f}")
    logger.info("========================================================")


if __name__ == "__main__":
    run_institutional()
