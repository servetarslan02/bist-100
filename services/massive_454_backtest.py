import structlog

logger = structlog.get_logger(__name__)
import gc
from typing import Any

from services.core.alpha_engine import AlphaEngine


def run_massive() -> Any:
    """Tüm BIST hisse evreni üzerinde 5 yıllık walk-forward alfa motoru backtestini çalıştırır."""
    logger.info("--- 454 HISSE 5 YILLIK DEV OTONOM BACKTEST ---")
    engine = AlphaEngine()
    engine.params["n_estimators"] = 50  # slightly faster

    start_date = "2019-01-01"
    end_date = "2024-01-01"

    logger.info(f"1. Veri indiriliyor: {start_date} -> {end_date}")
    market_data, bm_df, sector_map = engine.fetch_data(start_date, end_date)
    logger.info(f"Basarili! Toplam indirilen hisse: {len(market_data)}")

    common_dates = list(sorted([d for d in bm_df.index]))

    # Walk-forward setup
    # Egitim periyodu: 252 gun (1 yil)
    # Test (Yatirim) periyodu: 63 gun (1 ceyrek)

    train_size = 252
    step_size = 63

    portfolio = 1000000.0
    equity_curve = []

    # Sadece Optuna'yi kisalim ki 30 dk surmesin, 3 trial yeterli hizli sonuc icin
    from services.ml.hyper_optimizer import HyperOptimizer

    optimizer = HyperOptimizer(n_trials=3)

    # Start iterating
    current_idx = train_size

    while current_idx < len(common_dates) - step_size:
        t_start = common_dates[current_idx - train_size]
        t_end = common_dates[current_idx]
        t_test_end = common_dates[current_idx + step_size]

        logger.info(f"\n>> PERIYOT: Train({t_start.date()} to {t_end.date()}) | Test({t_end.date()} to {t_test_end.date()})")

        # 1. Egitim verisi olustur
        try:
            X, y, feature_names = engine.generate_training_samples(market_data, bm_df, sector_map, t_start, t_end)
        except Exception as e:
            logger.info(f"Data generation failed: {e}")
            break

        if len(X) == 0:
            logger.info("Uyari: Yeterli egitim verisi yok, atlaniyor.")
            current_idx += step_size
            continue

        # 2. Optuna ile egit
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
            preds = engine.predict(market_data, bm_df, sector_map, t_end.strftime("%Y-%m-%d"))
        except Exception as e:
            logger.info(f"Tahmin hatasi: {e}")
            break

        # 4. Portfoy yonetimi
        top_10 = preds[:10]
        selected_tickers = [p["ticker"] for p in top_10]
        logger.info(f"Secilen Hisseler: {selected_tickers}")

        # 5. Gercek Getiriyi Hesapla (63 gun sonrasi)
        period_return = 0.0
        valid_picks = 0
        for tick in selected_tickers:
            if tick in market_data:
                df = market_data[tick]
                try:
                    p_buy = df.loc[df.index <= t_end]["Close"].iloc[-1]
                    p_sell = df.loc[df.index <= t_test_end]["Close"].iloc[-1]
                    ret = (p_sell - p_buy) / p_buy
                    period_return += ret
                    valid_picks += 1
                except Exception:
                    logger.error("Exception caught", exc_info=True)

        if valid_picks > 0:
            avg_return = period_return / valid_picks
        else:
            avg_return = 0.0

        # BIST 100 getirisini hesapla
        try:
            bm_buy = bm_df.loc[bm_df.index <= t_end]["Close"].iloc[-1]
            bm_sell = bm_df.loc[bm_df.index <= t_test_end]["Close"].iloc[-1]
            bm_ret = (bm_sell - bm_buy) / bm_buy
        except Exception:
            bm_ret = 0.0

        logger.info(f"-> Portfoy Getirisi: %{avg_return * 100:.2f} | BIST100 Getirisi: %{bm_ret * 100:.2f}")

        portfolio = portfolio * (1 + avg_return)
        equity_curve.append(portfolio)
        logger.info(f"-> Guncel Kasa: {portfolio:,.2f} TL")

        # Bellek temizligi
        del X
        del y
        gc.collect()

        current_idx += step_size

    logger.info("\n========================================================")
    logger.info("BASLANGIC KASASI: 1,000,000.00 TL")
    logger.info(f"FINAL KASA: {portfolio:,.2f} TL")
    total_ret = (portfolio / 1000000.0) - 1
    years = 5.0
    cagr = ((1 + total_ret) ** (1 / years) - 1) * 100
    logger.info(f"5 YILLIK CAGR (Bilesik Getiri): %{cagr:.2f}")
    logger.info("========================================================")


if __name__ == "__main__":
    run_massive()
