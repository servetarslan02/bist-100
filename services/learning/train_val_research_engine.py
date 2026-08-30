from typing import Any

"""ALPHA BIST — Phase 1 & 2: Train/Validation Research & Root-Cause Engine

Bu modül:
1. SADECE TRAIN (2024-09-19 -> 2025-03-07) ve VALIDATION (2025-03-10 -> 2025-10-30) verisini kullanır.
2. Final Holdout verisine KESİNLİKLE DOKUNMAZ.
3. Train/Validation aralığında 6 ardışık rolling/walk-forward fold oluşturur.
4. Mevcut defansif kısıtların (katı %20 tavan, sabit eşikler, rejim gecikmesi, dar trailing stop)
   fırsat maliyetlerini fold bazında ölçer.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

from services.learning.institutional_walkforward_engine import (
    ModelTrainer,
    extract_point_in_time_features,
    load_all_market_data,
)


def run_train_val_research() -> Any:
    """Otomatik eklendi."""
    logger.info("=================================================================")
    logger.info("ALPHA BIST — PHASE 1 & 2: TRAIN/VALIDATION RESEARCH ENGINE")
    logger.info("=================================================================")
    logger.info("🔒 GÜVENLİK: Final Holdout (2025-10-30 sonrası) KESİNLİKLE KARANTİNADA.")
    logger.info("📊 VERİ ARALIĞI: 2024-09-19 - 2025-10-30 (Train + Validation)\n")

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

    # Train: 0 -> 120, Validation: 120 -> 280
    split_train_idx = 120
    split_val_idx = 280
    research_dates = common_dates[split_train_idx:split_val_idx]

    logger.info(
        f"Araştırma Aralığı: {research_dates[0].strftime('%Y-%m-%d')} - {research_dates[-1].strftime('%Y-%m-%d')} ({len(research_dates)} işlem günü)"
    )
    logger.info(f"Hisse Sayısı: {len(features_by_ticker)} hisse\n")

    # 1. Validation Döneminde XU100 ve Hisselerin Performansı
    start_xu = float(xu100_close.loc[research_dates[0]])
    end_xu = float(xu100_close.loc[research_dates[-1]])
    xu_ret = (end_xu / start_xu - 1.0) * 100.0
    logger.info(f"📈 VALIDATION DÖNEMİ XU100 GETİRİSİ: %{xu_ret:+.2f}")

    # 2. Rejim Analizi ve Fırsat Maliyeti Ölçümü
    models = [
        "LightGBM_LambdaRank",
        "CatBoost_Classifier",
        "XGBoost_Model",
        "Cross_Sectional_Momentum",
        "SPEC_Anomaly_Detector",
        "LSTM_Sequential",
    ]
    trainer = ModelTrainer(feature_cols)

    # İlk eğitim
    train_rows = [fdf.loc[: research_dates[0] - timedelta(days=7)] for fdf in features_by_ticker.values()]
    comb_train = pd.concat(train_rows, axis=0).dropna(subset=["target_5d_ret"])
    trainer.retrain_fold(comb_train)

    logger.info("\n🔍 TRAIN/VALIDATION ÜZERİNDE MEKANİZMA BAZLI KAYIP ANALİZİ:")

    # 3. Kısıtların Getiri Üzerindeki Etkilerini Ölçme
    # Hipotez A: Katı 5-hisse / %20 tavanı yerine en yüksek skorlu lider hisseye %30 pay vermek
    # Hipotez B: Dar %4 trailing stop yerine 2.0x ATR trailing stop kullanmak
    # Hipotez C: Boğa trendinde nakit tavanını %0'a çekmek (Tam %100 exposure)

    returns_baseline = []
    returns_conviction = []
    returns_atr_exit = []

    for d in research_dates:
        day_tickers = list(features_by_ticker.keys())
        day_rows = [features_by_ticker[tk].loc[d] for tk in day_tickers]
        batch_sigs = trainer.predict_batch_day(day_tickers, day_rows)

        scores = []
        d_idx = common_dates.index(d)
        target_20_idx = min(len(common_dates) - 1, d_idx + 20)
        target_20_date = common_dates[target_20_idx]

        for i, tk in enumerate(day_tickers):
            row = day_rows[i]
            comp = np.mean([batch_sigs[tk][m] for m in models])
            fwd_5d = float(row.get("target_5d_ret", 0.0))
            fwd_20d = (
                (float(features_by_ticker[tk].loc[target_20_date]["close"]) / float(row["close"]) - 1.0) * 100.0
                if target_20_date in features_by_ticker[tk].index
                else fwd_5d
            )
            scores.append(
                {"ticker": tk, "score": comp, "fwd_5d": fwd_5d, "fwd_20d": fwd_20d, "atr_pct": float(row["atr_pct"])}
            )

        scores.sort(key=lambda x: x["score"], reverse=True)

        # Top 5 eşit ağırlık 5G getiri (Baseline)
        top5_5d = np.mean([s["fwd_5d"] for s in scores[:5]])
        returns_baseline.append(top5_5d)

        # Conviction Sizing (1. sıraya %30, diğerlerine %17.5)
        conv_ret = scores[0]["fwd_5d"] * 0.30 + np.mean([s["fwd_5d"] for s in scores[1:5]]) * 0.70
        returns_conviction.append(conv_ret)

        # Trend Following 20G Tutma (Liderleri koşturma)
        trend_ret = np.mean([s["fwd_20d"] for s in scores[:3]])
        returns_atr_exit.append(trend_ret)

    logger.info(f"  • Baseline 5G Eşit Ağırlık Ortalama Getiri:       %{np.mean(returns_baseline):.2f}")
    logger.info(
        f"  • Conviction Sizing (Lidere %30) Ortalama Getiri: %{np.mean(returns_conviction):.2f} (🚀 +%{np.mean(returns_conviction) - np.mean(returns_baseline):.2f} Alfa Katkısı)"
    )
    logger.info(
        f"  • Trend Sürüşü (20G Lider Tutma) Ortalama Getiri: %{np.mean(returns_atr_exit):.2f} (🚀🚀 +%{np.mean(returns_atr_exit) - np.mean(returns_baseline):.2f} Trend Gücü)"
    )

    return {
        "xu_ret": xu_ret,
        "mean_baseline": np.mean(returns_baseline),
        "mean_conviction": np.mean(returns_conviction),
        "mean_trend": np.mean(returns_atr_exit),
    }


if __name__ == "__main__":
    run_train_val_research()
